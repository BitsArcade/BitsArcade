"""
MOD-06: Despacho de licencias y biblioteca del cliente (HU-41 a HU-50).

MOD-06 guarda su propio registro de compra (precio, moneda, tasa, transaccionId, correo) para
HU-46 a HU-50: no consulta a MOD-04 ni a MOD-05.
"""
import re
from typing import Optional

from pydantic import BaseModel
from sqlalchemy import Boolean, Column, DateTime, Float, Integer, String, Text, event

from app.core.base_datos import Base
from app.domain.parametros import porcentajeADecimal
from app.core.fechas import ahoraUtc

# ===== COMÚN MOD-06: entidades de asignación y registro de compra =====

ESTADO_ASIGNACION_ENTREGADA = "ENTREGADA"
DESPACHO_ENTREGADO = "ENTREGADO"
DESPACHO_PENDIENTE_REINTENTO = "PENDIENTE_REINTENTO"


class AsignacionLicencia(Base):
    """Licencia entregada a un usuario. Inmutable (RN-10): solo se permite marcar el revelado (HU-43)."""
    __tablename__ = "asignaciones_licencia"

    id = Column(Integer, primary_key=True, index=True)
    licenciaId = Column(String(20), nullable=False, unique=True, index=True)
    ordenId = Column(Integer, nullable=False, index=True)
    usuarioId = Column(Integer, nullable=False, index=True)
    juegoId = Column(Integer, nullable=False)
    titulo = Column(String(150), nullable=True)
    plataforma = Column(String(20), nullable=True)
    reservaId = Column(String(40), nullable=False, unique=True)   # RN-10: una entrega por reserva
    claveCifrada = Column(Text, nullable=False)
    claveHash = Column(String(64), nullable=False, unique=True)       # RN-10: una entrega por clave
    precioUnitarioFinal = Column(Float, nullable=False, default=0.0)
    estado = Column(String(20), nullable=False, default=ESTADO_ASIGNACION_ENTREGADA)
    entregadaEn = Column(DateTime, nullable=False, default=ahoraUtc)
    revelada = Column(Boolean, nullable=False, default=False)
    reveladaEn = Column(DateTime, nullable=True)


class RegistroCompra(Base):
    """Registro propio de la compra en MOD-06 (fuente de HU-46 a HU-50)."""
    __tablename__ = "registros_compra"

    id = Column(Integer, primary_key=True, index=True)
    ordenId = Column(Integer, nullable=False, unique=True, index=True)
    usuarioId = Column(Integer, nullable=False, index=True)
    correo = Column(String(150), nullable=True)
    nombre = Column(String(80), nullable=True)
    transaccionId = Column(String(40), nullable=False)
    moneda = Column(String(3), nullable=False)
    tasaCambio = Column(Float, nullable=False, default=1.0)
    total = Column(Float, nullable=False)
    baseGravable = Column(Float, nullable=False, default=0.0)
    iva = Column(Float, nullable=False, default=0.0)
    fecha = Column(DateTime, nullable=False, default=ahoraUtc)
    estadoOrden = Column(String(20), nullable=False, default="PAGADA")
    estadoDespacho = Column(String(30), nullable=False, default=DESPACHO_PENDIENTE_REINTENTO)
    entregadaEn = Column(DateTime, nullable=True)


def enmascararClave(clave: str) -> str:
    """'AAAAA-BBBBB-CCCCC' → '*****-*****-*****' (conserva solo los separadores)."""
    return re.sub(r"[A-Za-z0-9]", "*", clave)


# ===== HU-41: Asignar clave digital al perfil del usuario =====

class ItemDespachoEntrada(BaseModel):
    juegoId: int
    titulo: Optional[str] = None
    reservaId: str
    precioUnitario: Optional[float] = 0.0


class DespachoEntrada(BaseModel):
    """COM-10 ampliado."""
    ordenId: int
    usuarioId: int
    transaccionId: str
    moneda: str
    tasaCambio: float = 1.0
    total: float
    items: list[ItemDespachoEntrada] = []

    model_config = {
        "json_schema_extra": {
            "examples": [{
                "ordenId": 5001, "usuarioId": 77, "transaccionId": "TX-9001", "moneda": "COP", "tasaCambio": 1,
                "total": 238000, "items": [{"juegoId": 101, "titulo": "Aurora Quest",
                                            "reservaId": "res-9f1", "precioUnitario": 238000}],
            }]
        }
    }


class LicenciaAsignadaSalida(BaseModel):
    licenciaId: str
    juegoId: int


class DespachoSalida(BaseModel):
    ordenId: int
    estadoDespacho: str
    licencias: list[LicenciaAsignadaSalida]


def calcularDesgloseIva(total: float, tasaIva: float, decimales: int = 2) -> tuple[float, float]:
    """Separa base gravable e IVA de un total con IVA incluido. tasaIva en porcentaje (19)."""
    base = round(total / (1 + porcentajeADecimal(tasaIva)), decimales) if tasaIva > -100 else total
    return base, round(total - base, decimales)


# ===== HU-43: Formateo y visualización segura de la clave =====

def formatearClave(clave: str) -> str:
    """Mayúsculas; si la clave no trae separadores se agrupa en bloques de 5 con guiones."""
    valor = clave.strip().upper()
    if "-" not in valor and len(valor) > 5:
        valor = "-".join(valor[i:i + 5] for i in range(0, len(valor), 5))
    return valor


class ClaveReveladaSalida(BaseModel):
    licenciaId: str
    juegoId: int
    claveLicencia: str
    reveladaEn: str
    reembolsable: bool


# ===== HU-44: Notificación automática de despacho =====

MAXIMO_REINTENTOS_NOTIFICACION = 3
PLANTILLA_DESPACHO = "DESPACHO_CONFIRMADO"


class NotificacionDespacho(Base):
    """Resultado del envío del correo de despacho (una falla no revierte la entrega)."""
    __tablename__ = "notificaciones_despacho"

    id = Column(Integer, primary_key=True, index=True)
    ordenId = Column(Integer, nullable=False, unique=True, index=True)
    notificacionId = Column(String(20), nullable=True)
    estado = Column(String(20), nullable=False)
    intentos = Column(Integer, nullable=False, default=0)
    creadaEn = Column(DateTime, nullable=False, default=ahoraUtc)


# ===== HU-45: Validar unicidad e inmutabilidad de entrega =====

class EntregaInmutableError(Exception):
    """RN-10: las asignaciones no admiten UPDATE (salvo revelado) ni DELETE."""


CAMPOS_MUTABLES_ASIGNACION = {"revelada", "reveladaEn"}


@event.listens_for(AsignacionLicencia, "before_update")
def _impedirModificacion(_mapper, _conexion, asignacion):
    from sqlalchemy import inspect

    estado = inspect(asignacion)
    for atributo in estado.mapper.column_attrs:
        if atributo.key in CAMPOS_MUTABLES_ASIGNACION:
            continue
        if estado.attrs[atributo.key].history.has_changes():
            raise EntregaInmutableError("La licencia ya fue entregada y no puede modificarse")


@event.listens_for(AsignacionLicencia, "before_delete")
def _impedirBorrado(_mapper, _conexion, _asignacion):
    raise EntregaInmutableError("La licencia ya fue entregada y no puede eliminarse")


class ItemElegibilidadSalida(BaseModel):
    reservaId: str
    entregada: bool


class ElegibilidadSalida(BaseModel):
    ordenId: int
    autorizado: bool
    items: list[ItemElegibilidadSalida]


# ===== HU-46: Consultar biblioteca personal de juegos =====

class LicenciaBibliotecaSalida(BaseModel):
    licenciaId: str
    juegoId: int
    titulo: Optional[str] = None
    plataforma: Optional[str] = None
    entregadaEn: str
    claveLicencia: str
    revelada: bool


# ===== HU-47: Consultar detalle de compra pasada =====

class ItemCompraSalida(BaseModel):
    juegoId: int
    titulo: Optional[str] = None
    precioUnitario: float
    claveLicencia: str


class DetalleCompraSalida(BaseModel):
    ordenId: int
    fecha: str
    moneda: str
    total: float
    tasaCambio: float
    transaccionId: str
    estadoOrden: str
    items: list[ItemCompraSalida]


# ===== HU-48: Descargar comprobante digital de compra =====

EMISOR_COMPROBANTE = "BitArcade"


# ===== HU-49: Consultar estado de licencias =====

class EstadoLicenciaSalida(BaseModel):
    licenciaId: str
    juegoId: int
    estado: str
    revelada: bool
    reveladaEn: Optional[str] = None
    reembolsable: bool


# ===== HU-50: Filtrar historial por fechas =====

MENSAJE_FECHA_INVALIDA = "Formato de fecha no válido. Debe ser YYYY-MM-DD"
MENSAJE_RANGO_INVALIDO = "La fecha 'desde' no puede ser posterior a 'hasta'"


class CompraHistorialSalida(BaseModel):
    ordenId: int
    fecha: str
    total: float
    moneda: str
