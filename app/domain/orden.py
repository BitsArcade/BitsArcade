from typing import Optional
from datetime import datetime

from pydantic import BaseModel
from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import relationship
from app.core.base_datos import Base
from app.core.respuestas import ErrorAplicacion

# =====================================================================
# 1. CONSTANTES Y REGLAS DE DOMINIO (MOD-04: Órdenes de Compra)
# =====================================================================

ESTADO_ORDEN_PENDIENTE = "PENDIENTE"
ESTADO_ORDEN_PROCESANDO = "PROCESANDO"
ESTADO_ORDEN_PAGADA = "PAGADA"
ESTADO_ORDEN_CANCELADA = "CANCELADA"
ESTADO_ORDEN_ENTREGADA = "ENTREGADA"

ESTADOS_ORDEN_VALIDOS = (
    ESTADO_ORDEN_PENDIENTE,
    ESTADO_ORDEN_PROCESANDO,
    ESTADO_ORDEN_PAGADA,
    ESTADO_ORDEN_CANCELADA,
    ESTADO_ORDEN_ENTREGADA,
)

# Órdenes que cuentan para el límite de 1 licencia en preventa (RN-05)
ESTADOS_ORDEN_ACTIVAS_PREVENTA = (
    ESTADO_ORDEN_PENDIENTE,
    ESTADO_ORDEN_PROCESANDO,
    ESTADO_ORDEN_PAGADA,
    ESTADO_ORDEN_ENTREGADA,
)

ESTADOS_DESTINO_INTERNO_PERMITIDOS = (
    ESTADO_ORDEN_PROCESANDO,
    ESTADO_ORDEN_PAGADA,
    ESTADO_ORDEN_CANCELADA,
    ESTADO_ORDEN_ENTREGADA,
)

MENSAJE_ORDEN_NO_EXISTE = "La orden indicada no existe"
MENSAJE_CARRITO_VACIO_ORDEN = "No es posible generar una orden con el carrito vacío"
MENSAJE_TRANSICION_NO_PERMITIDA = "Transición de estado no permitida"


def validar_estado_consulta_orden(estado: Optional[str]) -> Optional[str]:
    """HU-33: valida que el filtro opcional de estado pertenezca al dominio."""
    if estado is None:
        return None
    estado_limpio = estado.strip().upper()
    if estado_limpio not in ESTADOS_ORDEN_VALIDOS:
        raise ErrorAplicacion(400, f"Estado inválido. Valores permitidos: {', '.join(ESTADOS_ORDEN_VALIDOS)}")
    return estado_limpio


def validar_cancelacion_orden(estado_actual: str) -> None:
    """HU-34: solo se pueden cancelar órdenes en estado PENDIENTE."""
    if estado_actual == ESTADO_ORDEN_CANCELADA:
        raise ErrorAplicacion(409, "La orden ya se encuentra cancelada")
    if estado_actual != ESTADO_ORDEN_PENDIENTE:
        raise ErrorAplicacion(409, "Solo se pueden cancelar órdenes en estado PENDIENTE")


def validar_transicion_estado_interno(
    estado_actual: str,
    nuevo_estado: str,
    entregada_en: Optional[datetime] = None,
) -> str:
    """
    HU-35 y HU-42: valida transiciones internas invocadas por MOD-05 (Transacciones)
    y MOD-06 (Despacho) vía COM-09:
    - PENDIENTE -> PROCESANDO (bloquea la orden durante el pago)
    - PROCESANDO -> PAGADA | CANCELADA (resuelve el pago)
    - PAGADA -> ENTREGADA (cierra la orden tras asignar licencias, HU-42)
    """
    destino = (nuevo_estado or "").strip().upper()
    if destino not in ESTADOS_ORDEN_VALIDOS:
        raise ErrorAplicacion(
            400,
            f"Estado destino inválido. Valores permitidos: {', '.join(ESTADOS_DESTINO_INTERNO_PERMITIDOS)}",
        )

    transiciones_validas = {
        ESTADO_ORDEN_PENDIENTE: (ESTADO_ORDEN_PROCESANDO,),
        ESTADO_ORDEN_PROCESANDO: (ESTADO_ORDEN_PAGADA, ESTADO_ORDEN_CANCELADA),
        ESTADO_ORDEN_PAGADA: (ESTADO_ORDEN_ENTREGADA,),
    }

    permitidos = transiciones_validas.get(estado_actual, ())
    if destino not in permitidos:
        if destino == ESTADO_ORDEN_ENTREGADA or estado_actual == ESTADO_ORDEN_ENTREGADA:
            raise ErrorAplicacion(409, MENSAJE_TRANSICION_NO_PERMITIDA)
        raise ErrorAplicacion(
            409,
            f"No es posible transicionar una orden de {estado_actual} a {destino}",
        )

    if destino == ESTADO_ORDEN_ENTREGADA and entregada_en is None:
        raise ErrorAplicacion(
            400,
            "La marca temporal entregadaEn es obligatoria para marcar la orden como ENTREGADA",
        )

    return destino


# =====================================================================
# 2. ENTIDADES DE DOMINIO (SQLite)
# =====================================================================

class Orden(Base):
    """Orden de compra consolidada a partir del carrito (HU-31)."""
    __tablename__ = "ordenes"

    id = Column(Integer, primary_key=True, index=True)
    usuario_id = Column(Integer, nullable=False, index=True)
    estado = Column(String(20), nullable=False, default=ESTADO_ORDEN_PENDIENTE)
    moneda = Column(String(10), nullable=False, default="COP")
    subtotal_bruto = Column(Float, nullable=False, default=0.0)
    descuento_total = Column(Float, nullable=False, default=0.0)
    total = Column(Float, nullable=False, default=0.0)
    entregada_en = Column(DateTime(timezone=True), nullable=True)

    items = relationship(
        "ItemOrden",
        back_populates="orden",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="ItemOrden.id",
    )


class ItemOrden(Base):
    """Detalle congelado de cada título incluido en la orden."""
    __tablename__ = "orden_items"

    id = Column(Integer, primary_key=True, index=True)
    orden_id = Column(Integer, ForeignKey("ordenes.id"), nullable=False, index=True)
    juego_id = Column(Integer, nullable=False, index=True)
    titulo = Column(String(200), nullable=False)
    cantidad = Column(Integer, nullable=False)
    precio_unitario = Column(Float, nullable=False)
    descuento_volumen = Column(Float, nullable=False, default=0.0)
    subtotal = Column(Float, nullable=False)

    orden = relationship("Orden", back_populates="items")


# =====================================================================
# 3. ESQUEMAS DE ENTRADA / SALIDA (Pydantic DTOs - camelCase en español)
# =====================================================================

class ItemOrdenSalida(BaseModel):
    juegoId: int
    titulo: str
    cantidad: int
    precioUnitario: float
    descuentoVolumen: float
    subtotal: float


class OrdenSalida(BaseModel):
    ordenId: int
    estado: str
    moneda: str
    subtotalBruto: float
    descuentoTotal: float
    total: float
    items: list[ItemOrdenSalida]


class LiquidacionOrdenSalida(BaseModel):
    ordenId: int
    estado: str
    moneda: str
    tasaIvaPorcentaje: float
    subtotalBruto: float
    descuentoVolumenTotal: float
    baseGravable: float
    valorIva: float
    totalPagar: float


class CancelacionOrdenSalida(BaseModel):
    ordenId: int
    estado: str
    licenciasLiberadas: int


class ActualizarEstadoOrdenEntrada(BaseModel):
    """Contrato interno COM-09 de entrada (HU-35 y HU-42)."""
    estado: str
    transaccionId: Optional[str] = None
    entregadaEn: Optional[datetime] = None

    model_config = {
        "json_schema_extra": {
            "examples": [
                {"estado": "PROCESANDO"},
                {"estado": "ENTREGADA", "entregadaEn": "2026-10-25T10:03:05Z"},
            ]
        }
    }


class EstadoOrdenInternoSalida(BaseModel):
    """Contrato interno de salida de HU-35."""
    ordenId: int
    estadoAnterior: str
    estadoActual: str
    bloqueada: bool


class CierreOrdenEntregadaSalida(BaseModel):
    """Datos de salida de HU-42 al cerrar una orden como ENTREGADA."""
    ordenId: int
    estado: str
    confirmado: bool