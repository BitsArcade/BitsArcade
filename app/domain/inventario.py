import re
from typing import Optional

from pydantic import BaseModel
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import synonym

from app.core.base_datos import Base
from app.core.fechas import ahoraUtc
from app.core.respuestas import ErrorAplicacion

ESTADO_CLAVE_DISPONIBLE = "DISPONIBLE"
ESTADO_CLAVE_RESERVADA = "RESERVADA"
ESTADO_CLAVE_VENDIDA = "VENDIDA"
ESTADOS_CLAVE = (ESTADO_CLAVE_DISPONIBLE, ESTADO_CLAVE_RESERVADA, ESTADO_CLAVE_VENDIDA)


class ClaveLicencia(Base):
    """Licencia digital de un juego con su estado de inventario (DISPONIBLE, RESERVADA, VENDIDA)."""
    __tablename__ = "claves_licencia"
    # ===== HU-11: Unicidad RN-03 sobre (juegoId, plataforma, hash de la clave) =====
    __table_args__ = (UniqueConstraint("juegoId", "plataforma", "claveHash", name="uq_clave_juego_plataforma_hash"),)

    id = Column(Integer, primary_key=True, index=True)
    juegoId = Column(Integer, ForeignKey("juegos.id"), nullable=False, index=True)
    plataforma = Column(String(20), nullable=True)
    estado = Column(String(20), nullable=False, default=ESTADO_CLAVE_DISPONIBLE)
    # ===== HU-11: Columnas del vault =====
    claveCifrada = Column(Text, nullable=True)        # Fernet (reversible solo dentro de MOD-03/MOD-06)
    claveHash = Column(String(64), nullable=True)     # SHA-256 de la clave normalizada (solo unicidad)
    creadaEn = Column(DateTime, nullable=True, default=ahoraUtc)

    # Compatibilidad temporal: nombre de atributo anterior usado por las órdenes (HU-31 a HU-33).
    juego_id = synonym("juegoId")


# ===== HU-11: Carga masiva de claves al vault =====

PATRON_CLAVE = re.compile(r"^[A-Z0-9]+(-[A-Z0-9]+)*$")
LONGITUD_MINIMA_CLAVE_LICENCIA = 5
LONGITUD_MAXIMA_CLAVE_LICENCIA = 64
MOTIVO_DUPLICADA = "DUPLICADA"
MOTIVO_FORMATO_INVALIDO = "FORMATO_INVALIDO"


def normalizarClave(valor) -> str:
    """trim, mayúsculas y sin espacios internos."""
    return re.sub(r"\s+", "", str(valor or "")).upper()


def claveConFormatoValido(valor: str) -> bool:
    return LONGITUD_MINIMA_CLAVE_LICENCIA <= len(valor) <= LONGITUD_MAXIMA_CLAVE_LICENCIA and bool(PATRON_CLAVE.match(valor))


def validarLote(juegoId, plataforma, claves) -> None:
    if juegoId is None or not str(plataforma or "").strip():
        raise ErrorAplicacion(400, "juegoId y plataforma son obligatorios")
    if not claves:
        raise ErrorAplicacion(400, "El lote no contiene claves")


class CargaLoteEntrada(BaseModel):
    juegoId: Optional[int] = None
    plataforma: Optional[str] = None
    claves: Optional[list[str]] = None

    model_config = {
        "json_schema_extra": {
            "examples": [{"juegoId": 101, "plataforma": "PC",
                          "claves": ["AAAAA-BBBBB-CCCCC", "DDDDD-EEEEE-FFFFF", "AAAAA-BBBBB-CCCCC"]}]
        }
    }


class ClaveRechazadaSalida(BaseModel):
    indice: int
    motivo: str


class CargaLoteSalida(BaseModel):
    juegoId: int
    plataforma: str
    recibidas: int
    cargadas: int
    rechazadas: list[ClaveRechazadaSalida]


# ===== HU-12: Consultar y auditar inventario de claves =====

def validarJuegoIdConsulta(juegoId: Optional[str]) -> Optional[int]:
    if juegoId is None or juegoId == "":
        return None
    if not str(juegoId).strip().isdigit():
        raise ErrorAplicacion(400, "juegoId debe ser numérico")
    return int(juegoId)


# HU-12: nombre del contador de métricas por estado de la clave
CONTADORES_POR_ESTADO = {
    ESTADO_CLAVE_DISPONIBLE: "disponibles",
    ESTADO_CLAVE_RESERVADA: "reservadas",
    ESTADO_CLAVE_VENDIDA: "vendidas",
}


def totalesVacios() -> dict:
    return {contador: 0 for contador in CONTADORES_POR_ESTADO.values()}


# ===== HU-13: Reservar clave temporalmente =====

MINUTOS_RESERVA = 15  # RN-04
ESTADO_RESERVA_ACTIVA = "ACTIVA"
ESTADO_RESERVA_LIBERADA = "LIBERADA"
ESTADO_RESERVA_EXPIRADA = "EXPIRADA"
ESTADO_RESERVA_VENDIDA = "VENDIDA"


class ReservaClave(Base):
    """Reserva temporal de una clave para una orden (RN-04: 15 minutos)."""
    __tablename__ = "reservas_clave"

    id = Column(Integer, primary_key=True, index=True)
    reservaId = Column(String(40), nullable=False, unique=True, index=True)
    claveId = Column(Integer, ForeignKey("claves_licencia.id"), nullable=False, index=True)
    ordenId = Column(Integer, nullable=False, index=True)
    juegoId = Column(Integer, nullable=False)
    estado = Column(String(20), nullable=False, default=ESTADO_RESERVA_ACTIVA)
    expiraEn = Column(DateTime, nullable=False)
    creadaEn = Column(DateTime, nullable=False, default=ahoraUtc)
    vendidaEn = Column(DateTime, nullable=True)


def validarCantidadReserva(cantidad) -> int:
    if cantidad is None or int(cantidad) < 1:
        raise ErrorAplicacion(400, "cantidad debe ser mayor o igual a 1")
    return int(cantidad)


class ReservarClavesEntrada(BaseModel):
    ordenId: Optional[int] = None
    juegoId: Optional[int] = None
    cantidad: Optional[int] = None

    model_config = {"json_schema_extra": {"examples": [{"ordenId": 5001, "juegoId": 101, "cantidad": 2}]}}


class ReservaSalida(BaseModel):
    reservaIds: list[str]
    expiraEn: str


class LiberarReservasEntrada(BaseModel):
    reservaIds: list[str] = []


class LiberacionSalida(BaseModel):
    liberadas: int


class StockSalida(BaseModel):
    juegoId: int
    cantidadDisponible: int


# ===== HU-14: Actualizar estado de clave a vendida =====

class VentaClaveSalida(BaseModel):
    reservaId: str
    estado: str
    claveLicencia: str


# ===== HU-15: Reportar y alertar llaves agotadas =====

class AlertaStock(Base):
    """Alerta interna de stock agotado: una abierta por (juego, plataforma)."""
    __tablename__ = "alertas_stock"

    id = Column(Integer, primary_key=True, index=True)
    juegoId = Column(Integer, nullable=False, index=True)
    plataforma = Column(String(20), nullable=True)
    alertaDesde = Column(DateTime, nullable=False, default=ahoraUtc)
    activa = Column(Boolean, nullable=False, default=True)
    cerradaEn = Column(DateTime, nullable=True)


class AlertaAgotadaSalida(BaseModel):
    juegoId: int
    plataforma: Optional[str] = None
    alertaDesde: str


# ===== Compatibilidad temporal =====
# Nombres anteriores ("key") que aún usa el módulo de órdenes fusionado (HU-31 a HU-33).
# Se retiran cuando ese módulo migre a la convención actualizada.
ESTADO_KEY_DISPONIBLE = ESTADO_CLAVE_DISPONIBLE
ESTADO_KEY_RESERVADA = ESTADO_CLAVE_RESERVADA
ESTADO_KEY_VENDIDA = ESTADO_CLAVE_VENDIDA
KeyLicencia = ClaveLicencia
