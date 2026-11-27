"""
MOD-04: Órdenes de compra (HU-31 a HU-35) y contratos COM-08 / COM-09.

- La orden congela precioUnitario, tasaIva y tasaCambio al crearse (RN-09); nadie los recalcula.
- Los montos se guardan en COP (moneda base). Si la moneda de cobro es otra, el total y los precios
  se convierten con la tasa congelada: monto en moneda = monto COP / tasaCambio.
- Redondeo: COP sin decimales, otras monedas con 2 decimales; baseGravable + valorIva = total.
- La orden guarda los reservaIds de sus claves (COM-06) para liberarlos (COM-13) al cancelar.
"""
from typing import Optional

from pydantic import BaseModel
from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import relationship

from app.core.base_datos import Base
from app.core.fechas import ahoraUtc
from app.core.respuestas import ErrorAplicacion
from app.domain.parametros import MONEDA_BASE, porcentajeADecimal

ESTADO_ORDEN_PENDIENTE = "PENDIENTE"
ESTADO_ORDEN_PROCESANDO = "PROCESANDO"
ESTADO_ORDEN_PAGADA = "PAGADA"
ESTADO_ORDEN_CANCELADA = "CANCELADA"
ESTADO_ORDEN_ENTREGADA = "ENTREGADA"
ESTADOS_ORDEN = (
    ESTADO_ORDEN_PENDIENTE,
    ESTADO_ORDEN_PROCESANDO,
    ESTADO_ORDEN_PAGADA,
    ESTADO_ORDEN_CANCELADA,
    ESTADO_ORDEN_ENTREGADA,
)

# HU-35: máquina de estados de la orden (COM-09). CANCELADA y ENTREGADA son terminales.
TRANSICIONES_PERMITIDAS = {
    ESTADO_ORDEN_PENDIENTE: {ESTADO_ORDEN_PROCESANDO, ESTADO_ORDEN_CANCELADA},
    ESTADO_ORDEN_PROCESANDO: {ESTADO_ORDEN_PAGADA, ESTADO_ORDEN_CANCELADA},
    ESTADO_ORDEN_PAGADA: {ESTADO_ORDEN_ENTREGADA},
    ESTADO_ORDEN_CANCELADA: set(),
    ESTADO_ORDEN_ENTREGADA: set(),
}
# Solicitantes autorizados de COM-09 por estado destino (HU-35, HU-40, HU-42).
SOLICITANTES_POR_ESTADO = {
    ESTADO_ORDEN_PROCESANDO: {"MOD-05"},
    ESTADO_ORDEN_PAGADA: {"MOD-05"},
    ESTADO_ORDEN_CANCELADA: {"MOD-05", "MOD-04"},
    ESTADO_ORDEN_ENTREGADA: {"MOD-06"},
}

MINUTOS_EXPIRACION_ORDEN = 15
MOTIVO_EXPIRACION = "Orden expirada (15 minutos sin pago)"

MENSAJE_ORDEN_NO_EXISTE = "La orden indicada no existe"
MENSAJE_TRANSICION_NO_PERMITIDA = "Transición de estado no permitida"
MENSAJE_ORDEN_EXPIRADA = "La orden expiró"
MENSAJE_CARRITO_VACIO = "No es posible generar una orden con el carrito vacío"
MENSAJE_MONEDA_NO_HABILITADA = "La moneda indicada no está habilitada"
MENSAJE_STOCK_INSUFICIENTE_ORDEN = "Stock insuficiente para generar la orden"
MENSAJE_CUENTA_NO_CONFIRMADA = "Debe confirmar su cuenta para realizar compras"
MENSAJE_SOLO_PENDIENTE = "Solo se pueden cancelar órdenes en estado PENDIENTE"
MENSAJE_ESTADO_INVALIDO = "El estado indicado no es válido"
MENSAJE_IDEMPOTENCIA_OBLIGATORIA = "El encabezado Idempotency-Key es obligatorio"


# =====================================================================
# Entidades
# =====================================================================

class Orden(Base):
    """Orden de compra con valores congelados (RN-09)."""
    __tablename__ = "ordenes"
    __table_args__ = (UniqueConstraint("usuarioId", "claveIdempotencia", name="uq_orden_idempotencia"),)

    id = Column(Integer, primary_key=True, index=True)
    usuarioId = Column(Integer, nullable=False, index=True)
    estado = Column(String(20), nullable=False, default=ESTADO_ORDEN_PENDIENTE, index=True)
    moneda = Column(String(3), nullable=False, default=MONEDA_BASE)
    tasaCambio = Column(Float, nullable=False, default=1.0)
    tasaIva = Column(Float, nullable=False)
    subtotalCop = Column(Float, nullable=False)
    descuentosCop = Column(Float, nullable=False, default=0.0)
    totalCop = Column(Float, nullable=False)
    claveIdempotencia = Column(String(80), nullable=True)
    transaccionId = Column(String(40), nullable=True)
    motivoCancelacion = Column(String(200), nullable=True)
    expiraEn = Column(DateTime, nullable=False)
    creadaEn = Column(DateTime, nullable=False, default=ahoraUtc)
    actualizadaEn = Column(DateTime, nullable=False, default=ahoraUtc)
    entregadaEn = Column(DateTime, nullable=True)

    lineas = relationship("LineaOrden", back_populates="orden", cascade="all, delete-orphan", order_by="LineaOrden.id")
    reservas = relationship("ReservaOrden", back_populates="orden", cascade="all, delete-orphan", order_by="ReservaOrden.id")


class LineaOrden(Base):
    """Línea de la orden: juego, cantidad, precio unitario congelado (COP, IVA incluido) y descuento."""
    __tablename__ = "lineas_orden"

    id = Column(Integer, primary_key=True, index=True)
    ordenId = Column(Integer, ForeignKey("ordenes.id"), nullable=False, index=True)
    juegoId = Column(Integer, nullable=False)
    titulo = Column(String(150), nullable=True)
    cantidad = Column(Integer, nullable=False)
    precioUnitarioCop = Column(Float, nullable=False)
    descuentoCop = Column(Float, nullable=False, default=0.0)

    orden = relationship("Orden", back_populates="lineas")


class ReservaOrden(Base):
    """Reserva de clave asociada a la orden (COM-06): una por unidad comprada."""
    __tablename__ = "reservas_orden"

    id = Column(Integer, primary_key=True, index=True)
    ordenId = Column(Integer, ForeignKey("ordenes.id"), nullable=False, index=True)
    juegoId = Column(Integer, nullable=False)
    titulo = Column(String(150), nullable=True)
    reservaId = Column(String(40), nullable=False, unique=True)
    precioUnitarioCop = Column(Float, nullable=False)

    orden = relationship("Orden", back_populates="reservas")


# =====================================================================
# Contratos de entrada / salida
# =====================================================================

class CrearOrdenEntrada(BaseModel):
    moneda: Optional[str] = MONEDA_BASE


class OrdenSalida(BaseModel):
    ordenId: int
    estado: str
    moneda: str
    tasaCambio: float
    total: float
    expiraEn: str


class DesgloseSalida(BaseModel):
    subtotal: float
    descuentos: float
    baseGravable: float
    valorIva: float
    total: float


class LineaLiquidacionSalida(BaseModel):
    juegoId: int
    cantidad: int
    precioUnitario: float


class LiquidacionSalida(BaseModel):
    ordenId: int
    moneda: str
    tasaCambio: float
    desglose: DesgloseSalida
    lineas: list[LineaLiquidacionSalida]


class OrdenPendienteSalida(BaseModel):
    ordenId: int
    total: float
    moneda: str
    expiraEn: str


class CancelarOrdenEntrada(BaseModel):
    motivo: Optional[str] = None


class OrdenCanceladaSalida(BaseModel):
    ordenId: int
    estado: str


class ActualizarEstadoOrdenEntrada(BaseModel):
    estado: str
    transaccionId: Optional[str] = None
    entregadaEn: Optional[str] = None


class EstadoOrdenSalida(BaseModel):
    ordenId: int
    estado: str
    confirmado: bool


class ItemContratoCom08(BaseModel):
    juegoId: int
    titulo: Optional[str] = None
    reservaId: str
    precioUnitario: float


class ContratoCom08Salida(BaseModel):
    ordenId: int
    usuarioId: int
    estado: str
    moneda: str
    tasaCambio: float
    total: float
    expiraEn: str
    items: list[ItemContratoCom08]


# =====================================================================
# Reglas de dominio
# =====================================================================

def decimalesMoneda(moneda: str) -> int:
    """COP sin decimales; otras monedas con 2 decimales."""
    return 0 if moneda == MONEDA_BASE else 2


def redondear(valor: float, moneda: str) -> float:
    decimales = decimalesMoneda(moneda)
    resultado = round(float(valor) + 0.0, decimales)
    return float(int(resultado)) if decimales == 0 else resultado


def convertirDesdeCop(montoCop: float, tasaCambio: float, moneda: str) -> float:
    """Monto en moneda de cobro = monto COP / tasaCambio (tasa = COP por 1 unidad)."""
    return redondear(montoCop / (tasaCambio or 1.0), moneda)


def calcularLiquidacion(subtotalCop: float, descuentosCop: float, tasaIva: float, tasaCambio: float, moneda: str) -> dict:
    """
    HU-32: el precio unitario ya incluye IVA (RN-01): se extrae la base gravable sin volver a aplicar IVA.
    baseGravable = total / (1 + tasaIva/100); valorIva = total - baseGravable.
    """
    subtotal = convertirDesdeCop(subtotalCop, tasaCambio, moneda)
    descuentos = convertirDesdeCop(descuentosCop, tasaCambio, moneda)
    total = redondear(subtotal - descuentos, moneda)
    baseGravable = redondear(total / (1 + porcentajeADecimal(tasaIva)), moneda)
    valorIva = redondear(total - baseGravable, moneda)
    return {
        "subtotal": subtotal,
        "descuentos": descuentos,
        "baseGravable": baseGravable,
        "valorIva": valorIva,
        "total": total,
    }


def validarEstadoConsulta(estado: Optional[str]) -> str:
    """HU-33: filtro de estado (por defecto PENDIENTE)."""
    valor = ESTADO_ORDEN_PENDIENTE if estado is None else str(estado).upper()
    if valor not in ESTADOS_ORDEN:
        raise ErrorAplicacion(400, MENSAJE_ESTADO_INVALIDO)
    return valor


def validarTransicion(estadoActual: str, estadoNuevo: str) -> None:
    """HU-35 (COM-09): solo se permiten las transiciones de la máquina de estados."""
    if estadoNuevo not in TRANSICIONES_PERMITIDAS.get(estadoActual, set()):
        raise ErrorAplicacion(409, MENSAJE_TRANSICION_NO_PERMITIDA)


def validarSolicitante(estadoNuevo: str, solicitante: Optional[str]) -> None:
    """COM-09 ampliado: cada estado destino solo lo puede pedir su módulo autorizado (si se informa)."""
    if solicitante and solicitante not in SOLICITANTES_POR_ESTADO.get(estadoNuevo, set()):
        raise ErrorAplicacion(409, MENSAJE_TRANSICION_NO_PERMITIDA)
