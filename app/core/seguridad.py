"""
Validación de tokens JWT para endpoints protegidos (consumidor de MOD-01).

La emisión del token corresponde a HU-07 (MOD-01). Aquí solo se valida la firma HS256 con
CLAVE_SECRETA y se extrae el usuario: el usuarioId sale SIEMPRE del JWT (claim `sub`), sin consultar
el perfil (HU-08).
"""
from dataclasses import dataclass
from typing import Optional

import jwt
import hmac

from fastapi import Depends, Header
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.configuracion import configuracion
from app.core.respuestas import ErrorAplicacion

ALGORITMO_JWT = "HS256"
MENSAJE_TOKEN_INVALIDO = "Token inválido, expirado o ausente"

esquemaBearer = HTTPBearer(auto_error=False, description="Bearer JWT emitido por MOD-01 (HU-07)")


@dataclass(frozen=True)
class UsuarioAutenticado:
    id: int
    rol: Optional[str] = None


def decodificarToken(token: str) -> UsuarioAutenticado:
    """Valida firma y expiración del JWT y retorna el usuario; lanza 401 si no es válido."""
    try:
        carga = jwt.decode(token, configuracion.CLAVE_SECRETA, algorithms=[ALGORITMO_JWT])
        identificador = carga.get("sub", carga.get("usuarioId"))
        if identificador is None:
            raise ErrorAplicacion(401, MENSAJE_TOKEN_INVALIDO)
        return UsuarioAutenticado(id=int(identificador), rol=carga.get("rol", carga.get("role")))
    except (jwt.PyJWTError, ValueError, TypeError) as error:
        raise ErrorAplicacion(401, MENSAJE_TOKEN_INVALIDO) from error


def obtenerUsuarioAutenticado(
    credenciales: Optional[HTTPAuthorizationCredentials] = Depends(esquemaBearer),
) -> UsuarioAutenticado:
    """Dependencia FastAPI: exige un Bearer JWT válido (401 si falta, es inválido o expiró)."""
    if credenciales is None or credenciales.scheme.lower() != "bearer" or not credenciales.credentials:
        raise ErrorAplicacion(401, MENSAJE_TOKEN_INVALIDO)
    return decodificarToken(credenciales.credentials)


# ===== HU-07: Emisión del JWT (MOD-01) =====

def emitirToken(usuarioId: int, rol: str, cuentaConfirmada: bool) -> tuple[str, int]:
    """
    HU-07: genera el JWT HS256 con claims sub, rol, cuentaConfirmada, iat y exp.
    Retorna (token, segundos de vigencia). Los demás módulos lo validan localmente con
    `decodificarToken`, sin llamar a MOD-01.
    """
    from datetime import datetime, timedelta, timezone

    segundos = int(configuracion.MINUTOS_EXPIRACION_TOKEN) * 60
    emitido = datetime.now(timezone.utc)
    carga = {
        "sub": str(usuarioId),
        "rol": rol,
        "cuentaConfirmada": bool(cuentaConfirmada),
        "iat": emitido,
        "exp": emitido + timedelta(seconds=segundos),
    }
    return jwt.encode(carga, configuracion.CLAVE_SECRETA, algorithm=ALGORITMO_JWT), segundos


# ===== HU-11: Autorización por rol ADMIN (MOD-03) =====

ROL_ADMIN = "ADMIN"
MENSAJE_SIN_PERMISOS = "No cuenta con permisos para realizar esta operación"


def obtenerUsuarioAdmin(
    usuario: UsuarioAutenticado = Depends(obtenerUsuarioAutenticado),
) -> UsuarioAutenticado:
    """Dependencia FastAPI: exige JWT válido (401) y rol ADMIN (403)."""
    if (usuario.rol or "").upper() != ROL_ADMIN:
        raise ErrorAplicacion(403, MENSAJE_SIN_PERMISOS)
    return usuario


# ===== Token de servicio para contratos internos (/interno/v1) =====

ENCABEZADO_TOKEN_SERVICIO = "X-Token-Servicio"
ENCABEZADO_MODULO_SOLICITANTE = "X-Modulo-Solicitante"
MENSAJE_TOKEN_SERVICIO_INVALIDO = "Token de servicio inválido o ausente"


@dataclass(frozen=True)
class ServicioAutenticado:
    modulo: Optional[str] = None


def validarTokenServicio(
    tokenServicio: Optional[str] = Header(default=None, alias=ENCABEZADO_TOKEN_SERVICIO),
    moduloSolicitante: Optional[str] = Header(default=None, alias=ENCABEZADO_MODULO_SOLICITANTE),
) -> ServicioAutenticado:
    """
    Dependencia FastAPI para las rutas /interno/v1: exige el token de servicio compartido entre
    módulos (401 si falta o no coincide). La comparación es en tiempo constante.
    """
    esperado = configuracion.TOKEN_SERVICIO
    if not tokenServicio or not hmac.compare_digest(tokenServicio.encode(), esperado.encode()):
        raise ErrorAplicacion(401, MENSAJE_TOKEN_SERVICIO_INVALIDO)
    return ServicioAutenticado(modulo=moduloSolicitante)


def encabezadosServicio(modulo: str) -> dict:
    """Encabezados que un módulo envía al invocar un contrato interno de otro módulo."""
    return {ENCABEZADO_TOKEN_SERVICIO: configuracion.TOKEN_SERVICIO, ENCABEZADO_MODULO_SOLICITANTE: modulo}


# ===== Compatibilidad temporal con los módulos que aún usan los nombres anteriores =====
esquema_bearer = esquemaBearer
decodificar_token = decodificarToken
obtener_usuario_autenticado = obtenerUsuarioAutenticado
