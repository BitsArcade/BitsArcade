"""
MOD-00: Parametrización (HU-01 a HU-05) y contratos COM-01 / COM-02 / COM-03.

Reglas generales:
- La moneda base es COP (TT-02). La entidad Moneda NO guarda tasas de cambio: la tasa se consulta
  en tiempo real a la API externa de Divisas (COM-03) solo cuando la moneda de cobro no es COP.
- tasaIva y margenGanancia se guardan como porcentaje de 0 a 100 (19 = 19 %). La conversión a
  decimal se hace únicamente con `porcentajeADecimal` (dominio), sin crear otro nombre de campo.
- Estados en MAYÚSCULAS: ACTIVO / INACTIVO.
"""
import re
from typing import Any, Optional

from pydantic import BaseModel
from sqlalchemy import Column, DateTime, Float, Integer, String

from app.core.base_datos import Base
from app.core.fechas import ahoraUtc
from app.core.respuestas import ErrorAplicacion

ESTADO_ACTIVO = "ACTIVO"
ESTADO_INACTIVO = "INACTIVO"
ESTADOS_VALIDOS = (ESTADO_ACTIVO, ESTADO_INACTIVO)
MONEDA_BASE = "COP"
NOMBRE_IMPUESTO_IVA = "IVA"
PARAMETRO_MARGEN_GANANCIA = "MARGEN_GANANCIA"
PATRON_CODIGO_ISO = re.compile(r"^[A-Z]{3}$")

MENSAJE_CODIGO_ISO_INVALIDO = "Código ISO inválido. Debe tener 3 letras mayúsculas (ISO 4217)"
MENSAJE_NOMBRE_OBLIGATORIO = "El nombre de la moneda es obligatorio"
MENSAJE_FILTRO_ESTADO_INVALIDO = "El valor del filtro estado no es válido. Use ACTIVO o INACTIVO"
MENSAJE_TASA_IVA_INVALIDA = "La tasa de IVA debe estar entre 0 y 100"
MENSAJE_MARGEN_INVALIDO = "El margen de ganancia debe ser mayor a 0"


# =====================================================================
# Entidades
# =====================================================================

class Moneda(Base):
    """HU-01 / HU-02: moneda ISO 4217 habilitada (sin campos de tasa de cambio)."""
    __tablename__ = "monedas"

    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String(80), nullable=False)
    codigoIso = Column(String(3), unique=True, index=True, nullable=False)
    estado = Column(String(20), nullable=False, default=ESTADO_ACTIVO)


class Impuesto(Base):
    """HU-03: impuesto global (IVA) expresado como porcentaje 0-100."""
    __tablename__ = "impuestos"

    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String(30), unique=True, nullable=False)
    tasaIva = Column(Float, nullable=False)
    actualizadoEn = Column(DateTime, nullable=False, default=ahoraUtc)


class ParametroFinanciero(Base):
    """HU-04: parámetros financieros globales (MARGEN_GANANCIA) expresados como porcentaje."""
    __tablename__ = "parametros_financieros"

    id = Column(Integer, primary_key=True, index=True)
    parametro = Column(String(40), unique=True, nullable=False)
    margenGanancia = Column(Float, nullable=False)
    actualizadoEn = Column(DateTime, nullable=False, default=ahoraUtc)


class MetodoPago(Base):
    """HU-05: método de pago (dato semilla TT-02); se inactiva con borrado lógico."""
    __tablename__ = "metodos_pago"

    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String(60), unique=True, nullable=False)
    estado = Column(String(20), nullable=False, default=ESTADO_ACTIVO)


# =====================================================================
# Contratos de entrada / salida (camelCase en español)
# =====================================================================

class CrearMonedaEntrada(BaseModel):
    nombre: Optional[Any] = None
    codigoIso: Optional[Any] = None


class MonedaSalida(BaseModel):
    monedaId: int
    nombre: str
    codigoIso: str
    estado: str


class MonedaResumenSalida(BaseModel):
    codigoIso: str
    nombre: str


class ActualizarIvaEntrada(BaseModel):
    tasaIva: Optional[Any] = None


class ImpuestoSalida(BaseModel):
    impuestoId: int
    nombre: str
    tasaIva: float
    actualizadoEn: str


class ActualizarMargenEntrada(BaseModel):
    margenGanancia: Optional[Any] = None


class MargenSalida(BaseModel):
    parametro: str
    margenGanancia: float
    actualizadoEn: str


class MetodoPagoSalida(BaseModel):
    metodoPagoId: int
    nombre: str
    estado: str


class ParametrosFinancierosSalida(BaseModel):
    tasaIva: float
    margenGanancia: float
    monedaBase: str


class TasaCambioSalida(BaseModel):
    codigoIso: str
    tasaCambio: float
    consultadaEn: str


# =====================================================================
# Reglas de dominio
# =====================================================================

def porcentajeADecimal(porcentaje: float) -> float:
    """Convierte un porcentaje (19) a decimal (0.19). Único punto de conversión (HU-03 / HU-04)."""
    return float(porcentaje) / 100.0


def validarMoneda(nombre: Any, codigoIso: Any) -> tuple[str, str]:
    """HU-01: codigoIso ^[A-Z]{3}$ y nombre no vacío."""
    if not isinstance(codigoIso, str) or not PATRON_CODIGO_ISO.match(codigoIso):
        raise ErrorAplicacion(400, MENSAJE_CODIGO_ISO_INVALIDO)
    if not isinstance(nombre, str) or not nombre.strip():
        raise ErrorAplicacion(400, MENSAJE_NOMBRE_OBLIGATORIO)
    return nombre.strip(), codigoIso


def validarFiltroEstado(estado: Optional[str]) -> str:
    """HU-02: el filtro estado solo admite ACTIVO o INACTIVO (por defecto ACTIVO)."""
    valor = ESTADO_ACTIVO if estado is None else estado
    if valor not in ESTADOS_VALIDOS:
        raise ErrorAplicacion(400, MENSAJE_FILTRO_ESTADO_INVALIDO)
    return valor


def _numero(valor: Any) -> Optional[float]:
    if isinstance(valor, bool) or not isinstance(valor, (int, float)):
        return None
    return float(valor)


def validarTasaIva(tasaIva: Any) -> float:
    """HU-03: 0 <= tasaIva <= 100."""
    numero = _numero(tasaIva)
    if numero is None or not 0 <= numero <= 100:
        raise ErrorAplicacion(400, MENSAJE_TASA_IVA_INVALIDA)
    return numero


def validarMargenGanancia(margenGanancia: Any) -> float:
    """HU-04: margenGanancia > 0 (porcentaje)."""
    numero = _numero(margenGanancia)
    if numero is None or numero <= 0:
        raise ErrorAplicacion(400, MENSAJE_MARGEN_INVALIDO)
    return numero
