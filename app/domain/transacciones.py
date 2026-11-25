"""
Dominio, modelos ORM, esquemas Pydantic y reglas de negocio de MOD-05 Transacciones.
"""
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
# MODELO ORM (Base de Datos)
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