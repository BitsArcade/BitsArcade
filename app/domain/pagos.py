"""
MOD-05: Transacciones y pagos (HU-36 a HU-40).
"""
import hashlib
import hmac
from typing import Optional

from pydantic import BaseModel
from sqlalchemy import Boolean, Column, DateTime, Float, Integer, String, Text

from app.core.base_datos import Base
from app.core.fechas import ahoraUtc

# ===== COMÚN MOD-05: estados y entidad Transacción =====

ESTADO_TX_EN_PROCESO = "EN_PROCESO"
ESTADO_TX_APROBADA = "APROBADA"
ESTADO_TX_FALLIDA = "FALLIDA"
ESTADO_TX_EXPIRADA = "EXPIRADA"
ESTADO_TX_REQUIERE_REVISION = "REQUIERE_REVISION"


class Transaccion(Base):
    """Intento de cobro de una orden (uno vigente por orden, idempotente por ordenId)."""
    __tablename__ = "transacciones"

    id = Column(Integer, primary_key=True, index=True)
    transaccionId = Column(String(40), nullable=False, unique=True, index=True)
    ordenId = Column(Integer, nullable=False, index=True)
    usuarioId = Column(Integer, nullable=False, index=True)
    metodoPagoId = Column(Integer, nullable=True)
    monto = Column(Float, nullable=False)
    moneda = Column(String(3), nullable=False)
    tasaCambio = Column(Float, nullable=False, default=1.0)   # Congelada en la orden (RN-09)
    itemsJson = Column(Text, nullable=True)
    estado = Column(String(20), nullable=False, default=ESTADO_TX_EN_PROCESO)
    referenciaPasarela = Column(String(60), nullable=True)
    motivo = Column(String(60), nullable=True)
    ordenEstado = Column(String(20), nullable=True)
    estadoDespacho = Column(String(30), nullable=True)
    creadaEn = Column(DateTime, nullable=False, default=ahoraUtc)
    resueltaEn = Column(DateTime, nullable=True)


# ===== HU-36: Transmitir cobro a la pasarela de pago simulada =====

MINUTOS_MINIMOS_VIGENCIA = 2


class IniciarPagoEntrada(BaseModel):
    ordenId: int
    metodoPagoId: Optional[int] = None

    model_config = {"json_schema_extra": {"examples": [{"ordenId": 5001, "metodoPagoId": 2}]}}


class PagoEnProcesoSalida(BaseModel):
    transaccionId: str
    ordenId: int
    estado: str


# ===== HU-37: Recibir y procesar aprobación de pago =====

ESTADO_PASARELA_APROBADO = "APROBADO"
ESTADOS_PASARELA_RECHAZO = {"RECHAZADO": ESTADO_TX_FALLIDA, "FALLIDO": ESTADO_TX_FALLIDA, "EXPIRADO": ESTADO_TX_EXPIRADA}


def calcularFirma(cuerpo: bytes, secreto: str) -> str:
    return hmac.new(secreto.encode("utf-8"), cuerpo, hashlib.sha256).hexdigest()


def firmaValida(cuerpo: bytes, firma: Optional[str], secreto: str) -> bool:
    return bool(secreto) and bool(firma) and hmac.compare_digest(calcularFirma(cuerpo, secreto), firma.strip().lower())


def montosCoinciden(monto, moneda, totalOrden: float, monedaOrden: str) -> bool:
    try:
        return abs(float(monto) - float(totalOrden)) < 0.01 and str(moneda or "").upper() == monedaOrden.upper()
    except (TypeError, ValueError):
        return False


class NotificacionPasarelaEntrada(BaseModel):
    transaccionId: Optional[str] = None
    ordenId: Optional[int] = None
    estado: Optional[str] = None
    referenciaPasarela: Optional[str] = None
    monto: Optional[float] = None
    moneda: Optional[str] = None
    motivo: Optional[str] = None


class PagoAprobadoSalida(BaseModel):
    transaccionId: str
    estado: str
    estadoOrden: Optional[str] = None
    estadoDespacho: Optional[str] = None


# ===== HU-38: Gestionar rechazo de pago y cancelación de orden =====

MENSAJES_USUARIO = {
    "RECHAZADO": "El pago fue rechazado. Genera una nueva orden para reintentar.",
    "FALLIDO": "Ocurrió un error al procesar el pago. Genera una nueva orden para reintentar.",
    "EXPIRADO": "El tiempo para completar el pago expiró. Genera una nueva orden para reintentar.",
}
MENSAJES_USUARIO_POR_ESTADO = {
    ESTADO_TX_EN_PROCESO: "Tu pago está en proceso.",
    ESTADO_TX_APROBADA: "Tu pago fue aprobado.",
    ESTADO_TX_REQUIERE_REVISION: "Tu pago fue aprobado y está en revisión.",
}


class PagoRechazadoSalida(BaseModel):
    transaccionId: str
    estado: str
    estadoOrden: Optional[str] = None
    mensajeUsuario: str


class EstadoPagoSalida(BaseModel):
    transaccionId: str
    ordenId: int
    estado: str
    estadoOrden: Optional[str] = None
    mensajeUsuario: Optional[str] = None


# ===== HU-39: Registrar comprobante digital de transacción =====

class Comprobante(Base):
    """Recibo digital: uno por transacción y solo para transacciones APROBADA."""
    __tablename__ = "comprobantes_pago"

    id = Column(Integer, primary_key=True, index=True)
    comprobanteId = Column(String(40), nullable=False, unique=True)
    transaccionId = Column(String(40), nullable=False, unique=True, index=True)
    ordenId = Column(Integer, nullable=False)
    usuarioId = Column(Integer, nullable=False, index=True)
    fecha = Column(DateTime, nullable=False, default=ahoraUtc)
    monto = Column(Float, nullable=False)
    moneda = Column(String(3), nullable=False)
    tasaCambio = Column(Float, nullable=False)
    referenciaPasarela = Column(String(60), nullable=True)


class ComprobanteSalida(BaseModel):
    comprobanteId: str
    transaccionId: str
    ordenId: int
    fecha: str
    monto: float
    moneda: str
    tasaCambio: float
    referenciaPasarela: Optional[str] = None


# ===== HU-40: Notificar resultado del cobro a Órdenes =====

MAXIMO_REINTENTOS_COM09 = 3


class NotificacionOrden(Base):
    """Registro de cada notificación COM-09 emitida por MOD-05 (idempotente por transaccionId)."""
    __tablename__ = "notificaciones_orden"

    id = Column(Integer, primary_key=True, index=True)
    transaccionId = Column(String(40), nullable=False, unique=True, index=True)
    ordenId = Column(Integer, nullable=False)
    estado = Column(String(20), nullable=False)
    confirmado = Column(Boolean, nullable=False, default=False)
    intentos = Column(Integer, nullable=False, default=0)
    detalle = Column(String(120), nullable=True)
    actualizadaEn = Column(DateTime, nullable=False, default=ahoraUtc)
