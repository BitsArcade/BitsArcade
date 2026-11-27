from datetime import datetime, timedelta
from typing import Optional
from pydantic import BaseModel, Field
from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from app.core.base_datos import Base
from app.core.respuestas import ErrorAplicacion

# =====================================================================
# 1. CONSTANTES Y REGLAS DE DOMINIO (MOD-04 / SUB-04.2: Órdenes)
# =====================================================================

ESTADO_ORDEN_PENDIENTE = "PENDIENTE"
ESTADO_ORDEN_PROCESANDO = "PROCESANDO"
ESTADO_ORDEN_PAGADA = "PAGADA"
ESTADO_ORDEN_CANCELADA = "CANCELADA"
ESTADO_ORDEN_ENTREGADA = "ENTREGADA"

MINUTOS_EXPIRACION_RESERVA = 15  # RN-04: Reserva temporal estricta de 15 minutos


def validarOrdenPendiente(estadoActual: str, accion: str) -> None:
    """Valida que una orden solo pueda liquidarse, cancelarse o bloquearse si está PENDIENTE."""
    if estadoActual != ESTADO_ORDEN_PENDIENTE:
        raise ErrorAplicacion(
            409,
            f"No es posible {accion} la orden porque su estado actual es '{estadoActual}' (se requiere PENDIENTE)."
        )


def validarTransicionEstadoCom09(estadoActual: str, nuevoEstado: str) -> None:
    """Valida transiciones permitidas desde el módulo de pagos (COM-09 / RN-06)."""
    estadosPermitidos = (ESTADO_ORDEN_PAGADA, ESTADO_ORDEN_CANCELADA)
    if nuevoEstado not in estadosPermitidos:
        raise ErrorAplicacion(
            400,
            f"Estado destino inválido '{nuevoEstado}'. Solo se admite PAGADA o CANCELADA."
        )
    if estadoActual not in (ESTADO_ORDEN_PENDIENTE, ESTADO_ORDEN_PROCESANDO):
        raise ErrorAplicacion(
            409,
            f"La orden ya se encuentra en estado terminal '{estadoActual}' y no puede modificarse."
        )


def calcularLiquidacionOrden(itemsCalculados: list[dict], tasaIvaDecimal: float) -> dict:
    """
    HU-32 (FUN-04.2.2 / PRO-04.2.2): Liquidación financiera de la orden.
    Los precios unitarios ya vienen calculados con RN-01 desde Catálogo (COM-11)
    y descuentos por volumen (RN-08) desde Carrito. Aquí se consolida el desglose fiscal.
    """
    totalConIva = round(sum(item["subtotal"] for item in itemsCalculados), 2)
    descuentoTotal = round(sum(item["descuentoVolumen"] for item in itemsCalculados), 2)
    baseGravable = round(totalConIva / (1 + tasaIvaDecimal), 2) if tasaIvaDecimal >= 0 else totalConIva
    montoIva = round(totalConIva - baseGravable, 2)

    return {
        "subtotalBase": baseGravable,
        "descuentoAplicado": descuentoTotal,
        "montoIva": montoIva,
        "totalPagar": totalConIva,
    }


# =====================================================================
# 2. ENTIDADES DE DOMINIO (Tablas ORM en SQLite)
# =====================================================================

class OrdenCompra(Base):
    """Entidad principal de Órdenes de Compra (HU-31 a HU-35)."""
    __tablename__ = "ordenes_compra"

    id = Column(Integer, primary_key=True, index=True)
    usuarioId = Column("usuario_id", Integer, index=True, nullable=False)
    estado = Column(String(20), nullable=False, default=ESTADO_ORDEN_PENDIENTE)
    moneda = Column(String(3), nullable=False, default="COP")
    tasaCambioCongelada = Column("tasa_cambio_congelada", Float, nullable=False, default=1.0)
    subtotalBase = Column("subtotal_base", Float, nullable=False, default=0.0)
    descuentoAplicado = Column("descuento_aplicado", Float, nullable=False, default=0.0)
    montoIva = Column("monto_iva", Float, nullable=False, default=0.0)
    totalPagar = Column("total_pagar", Float, nullable=False, default=0.0)
    motivoCancelacion = Column("motivo_cancelacion", String(200), nullable=True)
    fechaCreacion = Column("fecha_creacion", DateTime, default=datetime.utcnow)
    fechaExpiracionReserva = Column(
        "fecha_expiracion_reserva",
        DateTime,
        default=lambda: datetime.utcnow() + timedelta(minutes=MINUTOS_EXPIRACION_RESERVA)
    )

    detalles = relationship("DetalleOrden", back_populates="orden", cascade="all, delete-orphan", lazy="selectin")
    reservas = relationship("ReservaOrdenKey", back_populates="orden", cascade="all, delete-orphan", lazy="selectin")


class DetalleOrden(Base):
    """Ítems congelados dentro de una OrdenCompra (HU-31)."""
    __tablename__ = "detalles_orden"

    id = Column(Integer, primary_key=True, index=True)
    ordenId = Column("orden_id", Integer, ForeignKey("ordenes_compra.id"), nullable=False)
    juegoId = Column("juego_id", Integer, nullable=False)
    tituloJuego = Column("titulo_juego", String(100), nullable=False)
    cantidad = Column(Integer, nullable=False)
    precioUnitario = Column("precio_unitario", Float, nullable=False)
    descuentoVolumen = Column("descuento_volumen", Float, nullable=False, default=0.0)
    subtotal = Column(Float, nullable=False)

    orden = relationship("OrdenCompra", back_populates="detalles")


class ReservaOrdenKey(Base):
    """
    Vincula cada orden con las keys reservadas en inventario (RN-04)
    para poder liberarlas si la orden se cancela (HU-34 / RN-06) o venderlas al pagar.
    """
    __tablename__ = "reservas_orden_keys"

    id = Column(Integer, primary_key=True, index=True)
    ordenId = Column("orden_id", Integer, ForeignKey("ordenes_compra.id"), nullable=False)
    keyId = Column("key_id", Integer, ForeignKey("claves_licencia.id"), nullable=False)

    orden = relationship("OrdenCompra", back_populates="reservas")


# =====================================================================
# 3. ESQUEMAS DE ENTRADA / SALIDA (Pydantic DTOs en Español + camelCase)
# =====================================================================

class DetalleOrdenSalida(BaseModel):
    juegoId: int
    tituloJuego: str
    cantidad: int
    precioUnitario: float
    descuentoVolumen: float
    subtotal: float

    model_config = {"from_attributes": True}


class OrdenCompraSalida(BaseModel):
    id: int
    usuarioId: int
    estado: str
    moneda: str
    tasaCambioCongelada: float
    subtotalBase: float
    descuentoAplicado: float
    montoIva: float
    totalPagar: float
    motivoCancelacion: Optional[str] = None
    fechaCreacion: datetime
    fechaExpiracionReserva: Optional[datetime] = None
    detalles: list[DetalleOrdenSalida] = []

    model_config = {"from_attributes": True}


class LiquidacionOrdenSalida(BaseModel):
    """Contrato de salida para HU-32 (Liquidación financiera detallada)."""
    ordenId: int
    estado: str
    moneda: str
    tasaCambioAplicada: float
    subtotalBase: float
    descuentoAplicado: float
    montoIva: float
    totalPagar: float
    items: list[DetalleOrdenSalida]


class CancelarOrdenEntrada(BaseModel):
    """Contrato de entrada para HU-34 (Cancelar orden de compra)."""
    motivo: str = Field(..., min_length=5, max_length=200, examples=["Decidí cambiar los juegos del pedido"])


class ActualizarEstadoOrdenEntrada(BaseModel):
    """Contrato interno COM-09: actualización de estado desde Transacciones (MOD-05)."""
    ordenId: int
    estado: str = Field(..., examples=["PAGADA"])