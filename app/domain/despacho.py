"""
Dominio, modelos ORM, esquemas Pydantic y reglas de negocio de MOD-06 Despacho (HU-41 a HU-46).
"""
import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field
from sqlalchemy import Boolean, Column, DateTime, Float, Integer, String

from app.core.base_datos import Base
from app.core.respuestas import ErrorAplicacion


class EstadoDespacho(str, Enum):
    ACTIVADO = "ACTIVADO"
    ENTREGADO = "ENTREGADO"
    REQUIERE_REVISION = "REQUIERE_REVISION"


# ==============================================================================
# MODELOS ORM (Base de Datos)
# ==============================================================================
class DespachoOrdenORM(Base):
    """Registro maestro del despacho ejecutado para una orden pagada (COM-10 / HU-41)."""

    __tablename__ = "despachos_ordenes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    despacho_id = Column(String(32), unique=True, nullable=False, index=True)
    orden_id = Column(Integer, unique=True, nullable=False, index=True)
    usuario_id = Column(Integer, nullable=False, index=True)
    transaccion_id = Column(String(32), unique=True, nullable=False, index=True)
    estado = Column(String(30), nullable=False, default=EstadoDespacho.ACTIVADO.value)
    notificado_externo = Column(Boolean, nullable=False, default=False)
    creado_en = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    actualizado_en = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class LicenciaUsuarioORM(Base):
    """Licencia digital asignada de forma única e inmutable al perfil del usuario (HU-41)."""

    __tablename__ = "licencias_usuario"

    id = Column(Integer, primary_key=True, autoincrement=True)
    licencia_id = Column(String(32), unique=True, nullable=False, index=True)
    despacho_id = Column(String(32), nullable=False, index=True)
    orden_id = Column(Integer, nullable=False, index=True)
    usuario_id = Column(Integer, nullable=False, index=True)
    juego_id = Column(Integer, nullable=False, index=True)
    titulo_juego = Column(String(180), nullable=False)
    plataforma = Column(String(60), nullable=False, default="PC")
    reserva_id = Column(String(64), nullable=True)
    key_inventario_id = Column(Integer, unique=True, nullable=True, index=True)
    clave_digital = Column(String(64), unique=True, nullable=False)
    clave_enmascarada = Column(String(32), nullable=False)
    huella_clave = Column(String(64), unique=True, nullable=False)
    revelada = Column(Boolean, nullable=False, default=False)
    revelada_en = Column(DateTime(timezone=True), nullable=True)
    asignada_en = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


# ==============================================================================
# ENTIDADES Y REGLAS DE DOMINIO
# ==============================================================================
@dataclass(frozen=True)
class LicenciaUsuario:
    """Entidad inmutable de licencia digital asignada al usuario (HU-41)."""

    licencia_id: str
    despacho_id: str
    orden_id: int
    usuario_id: int
    juego_id: int
    titulo_juego: str
    plataforma: str
    reserva_id: Optional[str]
    key_inventario_id: Optional[int]
    clave_digital: str
    clave_enmascarada: str
    revelada: bool
    revelada_en: Optional[datetime]
    asignada_en: datetime


@dataclass(frozen=True)
class DespachoOrden:
    """Entidad de despacho de una orden con sus licencias asignadas."""

    despacho_id: str
    orden_id: int
    usuario_id: int
    transaccion_id: str
    estado: EstadoDespacho
    notificado_externo: bool
    creado_en: datetime
    licencias: list[LicenciaUsuario]


class ReglasDespacho:
    @staticmethod
    def validar_orden_elegible_despacho(estado_orden: str) -> None:
        """Solo una orden en estado PAGADA puede recibir asignación de licencias (HU-41)."""
        if estado_orden.strip().upper() != "PAGADA":
            raise ErrorAplicacion(
                409, "La orden no está en estado PAGADA y no es elegible para despacho"
            )

    @staticmethod
    def generar_clave_digital(orden_id: int, juego_id: int, indice: int) -> tuple[str, str, str]:
        """
        Genera una clave digital única de 16 caracteres (XXXX-XXXX-XXXX-XXXX),
        su versión enmascarada (XXXX-XXXX-XXXX-****) y su huella SHA-256.
        """
        alfabeto = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
        bloques = [
            "".join(secrets.choice(alfabeto) for _ in range(4))
            for _ in range(4)
        ]
        clave_plana = "-".join(bloques)
        clave_enmascarada = f"{bloques[0]}-{bloques[1]}-{bloques[2]}-****"
        semilla = f"{orden_id}:{juego_id}:{indice}:{clave_plana}".encode("utf-8")
        huella = hashlib.sha256(semilla).hexdigest()
        return clave_plana, clave_enmascarada, huella


# ==============================================================================
# ESQUEMAS PYDANTIC (Contratos COM-10 y API español camelCase)
# ==============================================================================
class ItemDespachoCOM10(BaseModel):
    juegoId: int = Field(..., gt=0)
    titulo: str = Field(..., min_length=1)
    reservaId: Optional[str] = None
    precioUnitario: float = Field(..., ge=0)


class SolicitudDespachoCOM10(BaseModel):
    ordenId: int = Field(..., gt=0)
    usuarioId: int = Field(..., gt=0)
    transaccionId: str = Field(..., min_length=1)
    moneda: str = Field(..., min_length=3, max_length=3)
    tasaCambio: float = Field(..., gt=0)
    total: float = Field(..., ge=0)
    items: list[ItemDespachoCOM10] = Field(..., min_length=1)


class LicenciaAsignadaSalida(BaseModel):
    licenciaId: str
    juegoId: int
    titulo: str
    plataforma: str
    claveEnmascarada: str
    revelada: bool
    asignadaEn: str


class DatosDespachoCOM10(BaseModel):
    despachoId: str
    ordenId: int
    usuarioId: int
    transaccionId: str
    estadoDespacho: str
    licenciasAsignadas: list[LicenciaAsignadaSalida]


class RespuestaDespachoCOM10(BaseModel):
    message: str
    data: Optional[DatosDespachoCOM10] = None
    success: bool