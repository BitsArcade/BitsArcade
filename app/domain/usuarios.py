"""
MOD-01: Usuarios y autenticación (HU-06 a HU-10).

Entidades, reglas de validación y contratos de entrada/salida del módulo.
"""
import re
from typing import Optional

from pydantic import BaseModel
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String

from app.core.base_datos import Base
from app.core.fechas import ahoraUtc
from app.core.respuestas import ErrorAplicacion

# ===== COMÚN MOD-01: constantes, entidades y reglas compartidas =====

ROL_CLIENTE = "CLIENTE"
ESTADO_PENDIENTE_CONFIRMACION = "PENDIENTE_CONFIRMACION"
ESTADO_CONFIRMADA = "CONFIRMADA"

TIPO_CODIGO_CONFIRMACION = "CONFIRMACION"
TIPO_CODIGO_RECUPERACION = "RECUPERACION"
MINUTOS_VIGENCIA_CODIGO = 15
MAXIMO_INTENTOS_CODIGO = 5
LONGITUD_MINIMA_CONTRASENA = 8

PATRON_CORREO = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")

MENSAJE_CORREO_INVALIDO = "Formato de correo inválido"
MENSAJE_CONTRASENA_CORTA = "La contraseña debe tener mínimo 8 caracteres"


class Usuario(Base):
    """Cuenta de comprador. La contraseña solo se guarda como hash bcrypt."""
    __tablename__ = "usuarios"

    id = Column(Integer, primary_key=True, index=True)
    correo = Column(String(150), nullable=False, unique=True, index=True)  # siempre en minúsculas
    nombre = Column(String(80), nullable=False)
    telefono = Column(String(15), nullable=True)
    rol = Column(String(20), nullable=False, default=ROL_CLIENTE)
    estado = Column(String(30), nullable=False, default=ESTADO_PENDIENTE_CONFIRMACION)
    contrasenaHash = Column(String(100), nullable=False)
    creadoEn = Column(DateTime, nullable=False, default=ahoraUtc)


class CodigoVerificacion(Base):
    """Código temporal (confirmación de cuenta o recuperación de contraseña), guardado con hash."""
    __tablename__ = "codigos_verificacion"

    id = Column(Integer, primary_key=True, index=True)
    usuarioId = Column(Integer, ForeignKey("usuarios.id"), nullable=False, index=True)
    tipo = Column(String(20), nullable=False)
    codigoHash = Column(String(64), nullable=False)
    expiraEn = Column(DateTime, nullable=False)
    usado = Column(Boolean, nullable=False, default=False)
    intentos = Column(Integer, nullable=False, default=0)


def normalizarCorreo(correo: Optional[str]) -> str:
    """El correo es único sin distinguir mayúsculas/minúsculas."""
    return (correo or "").strip().lower()


def validarCorreo(correo: Optional[str]) -> str:
    valor = normalizarCorreo(correo)
    if not PATRON_CORREO.match(valor):
        raise ErrorAplicacion(400, MENSAJE_CORREO_INVALIDO)
    return valor


def validarContrasena(contrasena: Optional[str]) -> str:
    if contrasena is None or len(contrasena) < LONGITUD_MINIMA_CONTRASENA:
        raise ErrorAplicacion(400, MENSAJE_CONTRASENA_CORTA)
    return contrasena


def codigoVigente(codigo: CodigoVerificacion | None, ahora) -> bool:
    return (
        codigo is not None
        and not codigo.usado
        and codigo.intentos < MAXIMO_INTENTOS_CODIGO
        and codigo.expiraEn >= ahora
    )


# ===== HU-06: Registro de nuevos clientes =====

def validarNombreRegistro(nombre: Optional[str]) -> str:
    valor = (nombre or "").strip()
    if not valor:
        raise ErrorAplicacion(400, "El nombre es obligatorio")
    return valor


class RegistroEntrada(BaseModel):
    """Contrato de entrada de HU-06 (los formatos se validan en el dominio para responder 400)."""
    correo: Optional[str] = None
    contrasena: Optional[str] = None
    nombre: Optional[str] = None

    model_config = {
        "json_schema_extra": {
            "examples": [{"correo": "jugador@correo.com", "contrasena": "Clave#2026", "nombre": "Ana Pérez"}]
        }
    }


class RegistroSalida(BaseModel):
    usuarioId: int
    correo: str
    nombre: str
    rol: str
    cuentaConfirmada: bool


class ConfirmarRegistroEntrada(BaseModel):
    correo: Optional[str] = None
    codigo: Optional[str] = None


class ConfirmacionSalida(BaseModel):
    usuarioId: int
    cuentaConfirmada: bool


# ===== HU-07: Iniciar sesión y generación de JWT =====

class InicioSesionEntrada(BaseModel):
    correo: Optional[str] = None
    contrasena: Optional[str] = None

    model_config = {"json_schema_extra": {"examples": [{"correo": "jugador@correo.com", "contrasena": "Clave#2026"}]}}


class InicioSesionSalida(BaseModel):
    token: str
    tipo: str
    expiraEn: int
    cuentaConfirmada: bool


# ===== HU-08: Consultar perfil autenticado =====

class PerfilSalida(BaseModel):
    usuarioId: int
    correo: str
    nombre: str
    telefono: Optional[str] = None
    rol: str
    creadoEn: str


# ===== HU-09: Actualizar datos personales =====

PATRON_TELEFONO = re.compile(r"^\d{7,15}$")


def validarNombrePerfil(nombre: Optional[str]) -> str:
    valor = (nombre or "").strip()
    if not 2 <= len(valor) <= 80:
        raise ErrorAplicacion(400, "El nombre debe tener entre 2 y 80 caracteres")
    return valor


def validarTelefono(telefono: Optional[str]) -> Optional[str]:
    """Teléfono opcional: si se envía debe tener entre 7 y 15 dígitos."""
    if telefono is None or str(telefono).strip() == "":
        return None
    valor = str(telefono).strip()
    if not PATRON_TELEFONO.match(valor):
        raise ErrorAplicacion(400, "El teléfono debe contener entre 7 y 15 dígitos")
    return valor


class ActualizarPerfilEntrada(BaseModel):
    """Solo nombre y teléfono son editables; correo y rol se ignoran si se envían."""
    nombre: Optional[str] = None
    telefono: Optional[str] = None

    model_config = {"json_schema_extra": {"examples": [{"nombre": "Ana María Pérez", "telefono": "3001234567"}]}}


class PerfilActualizadoSalida(BaseModel):
    usuarioId: int
    nombre: str
    telefono: Optional[str] = None


# ===== HU-10: Restablecer contraseña mediante código =====

MENSAJE_CODIGO_INVALIDO = "El código es inválido o expiró"


class SolicitarRecuperacionEntrada(BaseModel):
    correo: Optional[str] = None


class EstadoEnvioSalida(BaseModel):
    estadoEnvio: str


class ConfirmarRecuperacionEntrada(BaseModel):
    correo: Optional[str] = None
    codigo: Optional[str] = None
    nuevaContrasena: Optional[str] = None

    model_config = {
        "json_schema_extra": {
            "examples": [{"correo": "jugador@correo.com", "codigo": "482915", "nuevaContrasena": "NuevaClave#2026"}]
        }
    }
