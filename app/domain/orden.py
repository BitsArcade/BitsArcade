from datetime import datetime, timezone

from pydantic import BaseModel, Field
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

ESTADOS_ORDEN_VALIDOS = (
    ESTADO_ORDEN_PENDIENTE,
    ESTADO_ORDEN_PROCESANDO,
    ESTADO_ORDEN_PAGADA,
    ESTADO_ORDEN_CANCELADA,
)

ESTADOS_ORDEN_ACTIVAS_PREVENTA = (
    ESTADO_ORDEN_PENDIENTE,
    ESTADO_ORDEN_PROCESANDO,
    ESTADO_ORDEN_PAGADA,
)

MENSAJE_CARRITO_VACIO = "No es posible generar una orden con el carrito vacío"
MENSAJE_ORDEN_NO_EXISTE = "La orden indicada no existe"
MENSAJE_ORDEN_YA_CANCELADA = "La orden ya se encuentra cancelada"
MENSAJE_ORDEN_NO_CANCELABLE = "Solo se pueden cancelar órdenes en estado PENDIENTE"
MENSAJE_ORDEN_BLOQUEADA = "La orden se encuentra bloqueada en estado PROCESANDO y no admite esta transición"
MENSAJE_TRANSICION_INVALIDA = "Transición de estado de orden no permitida"


def validar_estado_consulta(estado: str | None) -> str | None:
    if estado is None:
        return None
    valor = estado.strip().upper()
    if valor not in ESTADOS_ORDEN_VALIDOS:
        raise ErrorAplicacion(400, f"Estado no válido. Use: {', '.join(ESTADOS_ORDEN_VALIDOS)}")
    return valor


def validar_cancelacion_orden(estado_actual: str) -> None:
    """HU-34: Solo se pueden cancelar órdenes en estado PENDIENTE."""
    if estado_actual == ESTADO_ORDEN_CANCELADA:
        raise ErrorAplicacion(409, MENSAJE_ORDEN_YA_CANCELADA)
    if estado_actual != ESTADO_ORDEN_PENDIENTE:
        raise ErrorAplicacion(409, MENSAJE_ORDEN_NO_CANCELABLE)


def validar_transicion_estado_interno(estado_actual: str, nuevo_estado: str) -> str:
    """
    HU-35: Bloqueo de orden al pasar a PROCESANDO (contrato interno para MOD-05 Pagos).
    - PENDIENTE -> PROCESANDO (bloquea la orden frente a cancelaciones o modificaciones).
    - PROCESANDO -> PAGADA o CANCELADA (resolución del pago).
    - Cualquier otro intento sobre PROCESANDO (ej. volver a PENDIENTE o repetir PROCESANDO) responde 409.
    """
    destino = (nuevo_estado or "").strip().upper()
    if destino not in ESTADOS_ORDEN_VALIDOS:
        raise ErrorAplicacion(400, f"Estado destino no válido. Use: {', '.join(ESTADOS_ORDEN_VALIDOS)}")

    if estado_actual == ESTADO_ORDEN_PROCESANDO:
        if destino in (ESTADO_ORDEN_PAGADA, ESTADO_ORDEN_CANCELADA):
            return destino
        raise ErrorAplicacion(409, MENSAJE_ORDEN_BLOQUEADA)

    if estado_actual == ESTADO_ORDEN_PENDIENTE and destino == ESTADO_ORDEN_PROCESANDO:
        return destino

    raise ErrorAplicacion(409, f"{MENSAJE_TRANSICION_INVALIDA}: {estado_actual} -> {destino}")


# =====================================================================
# 2. ENTIDADES DE DOMINIO (Mapeo de tablas SQLite)
# =====================================================================

class Orden(Base):
    """Orden de compra consolidada desde el carrito activo (HU-31 a HU-35)."""
    __tablename__ = "ordenes"

    id = Column(Integer, primary_key=True, index=True)
    usuario_id = Column(Integer, nullable=False, index=True)
    estado = Column(String(20), nullable=False, default=ESTADO_ORDEN_PENDIENTE, index=True)
    moneda = Column(String(3), nullable=False, default="COP")
    tasa_iva = Column(Float, nullable=False, default=0.19)
    subtotal_bruto = Column(Float, nullable=False, default=0.0)
    descuento_total = Column(Float, nullable=False, default=0.0)
    subtotal_neto = Column(Float, nullable=False, default=0.0)
    valor_iva = Column(Float, nullable=False, default=0.0)
    total = Column(Float, nullable=False, default=0.0)
    fecha_creacion = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    items = relationship(
        "ItemOrden",
        back_populates="orden",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="ItemOrden.id",
    )


class ItemOrden(Base):
    """Detalle congelado de cada juego adquirido en una orden."""
    __tablename__ = "orden_items"

    id = Column(Integer, primary_key=True, index=True)
    orden_id = Column(Integer, ForeignKey("ordenes.id"), nullable=False, index=True)
    juego_id = Column(Integer, nullable=False, index=True)
    titulo_juego = Column(String(150), nullable=False)
    cantidad = Column(Integer, nullable=False)
    precio_unitario = Column(Float, nullable=False)
    descuento_volumen = Column(Float, nullable=False, default=0.0)
    subtotal = Column(Float, nullable=False)

    orden = relationship("Orden", back_populates="items")


# =====================================================================
# 3. ESQUEMAS DE ENTRADA / SALIDA (Pydantic DTOs - camelCase)
# =====================================================================

class ItemOrdenSalida(BaseModel):
    itemOrdenId: int
    juegoId: int
    titulo: str
    cantidad: int
    precioUnitario: float
    descuentoVolumen: float
    subtotal: float


class OrdenSalida(BaseModel):
    ordenId: int
    usuarioId: int
    estado: str
    moneda: str
    subtotalBruto: float
    descuentoTotal: float
    subtotalNeto: float
    valorIva: float
    total: float
    fechaCreacion: datetime
    items: list[ItemOrdenSalida]


class LiquidacionOrdenSalida(BaseModel):
    """Contrato de salida para HU-32: desglose financiero de la orden."""
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
    """Contrato de salida para HU-34: confirmación de cancelación y liberación de stock."""
    ordenId: int
    estado: str
    licenciasLiberadas: int


class ActualizarEstadoOrdenEntrada(BaseModel):
    """Contrato de entrada para HU-35 (PATCH /interno/v1/ordenes/{ordenId}/estado)."""
    estado: str = Field(..., examples=["PROCESANDO"])


class EstadoOrdenInternoSalida(BaseModel):
    """Contrato de salida para HU-35."""
    ordenId: int
    estadoAnterior: str
    estadoActual: str
    bloqueada: bool