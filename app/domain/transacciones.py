"""
Dominio, modelos ORM, esquemas Pydantic y reglas de negocio de MOD-05 Transacciones (HU-36 a HU-40).
"""
import hashlib
import hmac
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field
from sqlalchemy import Column, DateTime, Float, Integer, String

from app.core.base_datos import Base
from app.core.respuestas import ErrorAplicacion


class EstadoTransaccion(str, Enum):
    EN_PROCESO = "EN_PROCESO"
    APROBADA = "APROBADA"
    FALLIDA = "FALLIDA"
    EXPIRADA = "EXPIRADA"
    REQUIERE_REVISION = "REQUIERE_REVISION"


# ==============================================================================
# MODELOS ORM (Base de Datos)
# ==============================================================================
class TransaccionORM(Base):
    __tablename__ = "transacciones"

    id = Column(Integer, primary_key=True, autoincrement=True)
    transaccion_id = Column(String(32), unique=True, nullable=False, index=True)
    orden_id = Column(Integer, unique=True, nullable=False, index=True)
    usuario_id = Column(Integer, nullable=False, index=True)
    metodo_pago_id = Column(Integer, nullable=False)
    monto = Column(Float, nullable=False)
    moneda = Column(String(3), nullable=False)
    tasa_cambio = Column(Float, nullable=False)
    estado = Column(String(30), nullable=False, default=EstadoTransaccion.EN_PROCESO.value)
    referencia_pasarela = Column(String(64), nullable=True)
    mensaje_usuario = Column(String(255), nullable=True)
    creado_en = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    actualizado_en = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class ComprobanteORM(Base):
    __tablename__ = "comprobantes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    comprobante_id = Column(String(32), unique=True, nullable=False, index=True)
    transaccion_id = Column(String(32), unique=True, nullable=False, index=True)
    orden_id = Column(Integer, nullable=False, index=True)
    usuario_id = Column(Integer, nullable=False, index=True)
    fecha = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    monto = Column(Float, nullable=False)
    moneda = Column(String(3), nullable=False)
    tasa_cambio = Column(Float, nullable=False)
    referencia_pasarela = Column(String(64), nullable=True)


# ==============================================================================
# ENTIDADES Y REGLAS DE DOMINIO
# ==============================================================================
@dataclass(frozen=True)
class OrdenParaCobro:
    orden_id: int
    usuario_id: int
    estado: str
    total: float
    moneda: str
    tasa_cambio: float
    expira_en: datetime
    items: list[dict[str, Any]]


@dataclass
class Transaccion:
    transaccion_id: str
    orden_id: int
    usuario_id: int
    metodo_pago_id: int
    monto: float
    moneda: str
    tasa_cambio: float
    estado: EstadoTransaccion = EstadoTransaccion.EN_PROCESO
    referencia_pasarela: Optional[str] = None
    mensaje_usuario: Optional[str] = None
    creado_en: Optional[datetime] = None
    actualizado_en: Optional[datetime] = None


@dataclass
class Comprobante:
    comprobante_id: str
    transaccion_id: str
    orden_id: int
    usuario_id: int
    fecha: datetime
    monto: float
    moneda: str
    tasa_cambio: float
    referencia_pasarela: Optional[str] = None


class ReglasTransaccion:
    MARGEN_MINIMO_EXPIRACION = timedelta(minutes=2)

    @classmethod
    def validar_orden_cobrable(
        cls,
        orden: OrdenParaCobro,
        usuario_autenticado_id: int,
        ahora: Optional[datetime] = None,
    ) -> None:
        if orden.usuario_id != usuario_autenticado_id:
            raise ErrorAplicacion(404, "La orden indicada no existe")

        if orden.estado != "PENDIENTE":
            raise ErrorAplicacion(409, "La orden no está disponible para pago")

        referencia_actual = ahora or datetime.now(timezone.utc)
        expira_utc = (
            orden.expira_en.replace(tzinfo=timezone.utc)
            if orden.expira_en.tzinfo is None
            else orden.expira_en
        )

        if (expira_utc - referencia_actual) < cls.MARGEN_MINIMO_EXPIRACION:
            raise ErrorAplicacion(409, "La orden está por expirar. Genera una nueva orden")

    @staticmethod
    def construir_payload_pasarela(
        transaccion_id: str,
        orden: OrdenParaCobro,
        metodo_pago_id: int,
    ) -> dict[str, Any]:
        """
        RN-09: Usa el total y la tasaCambio ya congelados en la orden (COM-08),
        sin consultar la API de Divisas ni COM-03.
        """
        return {
            "transaccionId": transaccion_id,
            "ordenId": orden.orden_id,
            "metodoPagoId": metodo_pago_id,
            "monto": orden.total,
            "moneda": orden.moneda,
            "tasaCambio": orden.tasa_cambio,
        }

    @staticmethod
    def calcular_firma_hmac(cuerpo_crudo: bytes, secreto: str) -> str:
        return hmac.new(
            secreto.encode("utf-8"),
            cuerpo_crudo,
            hashlib.sha256,
        ).hexdigest()

    @classmethod
    def verificar_firma_hmac(
        cls,
        cuerpo_crudo: bytes,
        firma_recibida: Optional[str],
        secreto: str,
    ) -> None:
        if not firma_recibida or not firma_recibida.strip():
            raise ErrorAplicacion(401, "Firma de la notificación de la pasarela inválida")

        firma_limpia = firma_recibida.strip()
        if firma_limpia.lower().startswith("sha256="):
            firma_limpia = firma_limpia.split("=", 1)[1]

        esperada = cls.calcular_firma_hmac(cuerpo_crudo, secreto)
        if not hmac.compare_digest(esperada, firma_limpia):
            raise ErrorAplicacion(401, "Firma de la notificación de la pasarela inválida")

    @staticmethod
    def validar_aprobacion_pasarela(
        transaccion: Transaccion,
        monto_notificado: Optional[float],
        moneda_notificada: Optional[str],
    ) -> None:
        if transaccion.estado in (EstadoTransaccion.FALLIDA, EstadoTransaccion.EXPIRADA):
            raise ErrorAplicacion(409, "La transacción ya fue resuelta con otro estado")

        if monto_notificado is None or not moneda_notificada:
            raise ErrorAplicacion(409, "El monto o la moneda no coinciden con la orden")

        if (
            round(float(transaccion.monto), 2) != round(float(monto_notificado), 2)
            or transaccion.moneda.upper() != moneda_notificada.strip().upper()
        ):
            raise ErrorAplicacion(409, "El monto o la moneda no coinciden con la orden")

    @staticmethod
    def construir_payload_com10(
        transaccion: Transaccion,
        orden: OrdenParaCobro,
    ) -> dict[str, Any]:
        """Contrato COM-10 ampliado hacia MOD-06 Despacho."""
        items_com10 = [
            {
                "juegoId": item.get("juegoId"),
                "titulo": item.get("titulo", f"Juego #{item.get('juegoId')}"),
                "reservaId": item.get("reservaId"),
                "precioUnitario": float(item.get("precioUnitario", 0.0)),
            }
            for item in orden.items
        ]
        return {
            "ordenId": transaccion.orden_id,
            "usuarioId": transaccion.usuario_id,
            "transaccionId": transaccion.transaccion_id,
            "moneda": transaccion.moneda,
            "tasaCambio": transaccion.tasa_cambio,
            "total": transaccion.monto,
            "items": items_com10,
        }


# ==============================================================================
# ESQUEMAS PYDANTIC (Contratos API español camelCase)
# ==============================================================================
class SolicitudIniciarPago(BaseModel):
    ordenId: int = Field(..., gt=0, description="Identificador de la orden PENDIENTE")
    metodoPagoId: int = Field(..., gt=0, description="Identificador del método de pago (P-03)")


class DatosPagoEnProceso(BaseModel):
    transaccionId: str
    ordenId: int
    estado: str


class RespuestaIniciarPago(BaseModel):
    message: str
    data: Optional[DatosPagoEnProceso] = None
    success: bool


class SolicitudNotificacionPasarela(BaseModel):
    transaccionId: str = Field(..., min_length=1)
    ordenId: int = Field(..., gt=0)
    estado: str = Field(..., min_length=1)
    referenciaPasarela: Optional[str] = None
    monto: Optional[float] = None
    moneda: Optional[str] = None
    motivo: Optional[str] = None


class DatosPagoAprobado(BaseModel):
    transaccionId: str
    estado: str
    estadoOrden: str
    estadoDespacho: str


class RespuestaPagoAprobado(BaseModel):
    message: str
    data: Optional[DatosPagoAprobado] = None
    success: bool