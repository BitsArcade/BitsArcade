"""
Validación de tokens JWT para endpoints protegidos (consumidor de MOD-01).

La emisión del token corresponde a HU-07 (MOD-01). Aquí solo se valida la firma HS256 con
SECRET_KEY y se extrae el usuario: el userId sale SIEMPRE del JWT (claim `sub`), sin consultar
el perfil (HU-08).
"""
from dataclasses import dataclass
from typing import Optional

import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.configuracion import settings
from app.core.respuestas import ErrorAplicacion

ALGORITMO_JWT = "HS256"
MENSAJE_TOKEN_INVALIDO = "Token inválido, expirado o ausente"

esquema_bearer = HTTPBearer(auto_error=False, description="Bearer JWT emitido por MOD-01 (HU-07)")


@dataclass(frozen=True)
class UsuarioAutenticado:
    id: int
    rol: Optional[str] = None


def decodificar_token(token: str) -> UsuarioAutenticado:
    """Valida firma y expiración del JWT y retorna el usuario; lanza 401 si no es válido."""
    try:
        carga = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITMO_JWT])
        identificador = carga.get("sub", carga.get("userId"))
        if identificador is None:
            raise ErrorAplicacion(401, MENSAJE_TOKEN_INVALIDO)
        return UsuarioAutenticado(id=int(identificador), rol=carga.get("rol", carga.get("role")))
    except (jwt.PyJWTError, ValueError, TypeError) as error:
        raise ErrorAplicacion(401, MENSAJE_TOKEN_INVALIDO) from error


def obtener_usuario_autenticado(
    credenciales: Optional[HTTPAuthorizationCredentials] = Depends(esquema_bearer),
) -> UsuarioAutenticado:
    """Dependencia FastAPI: exige un Bearer JWT válido (401 si falta, es inválido o expiró)."""
    if credenciales is None or credenciales.scheme.lower() != "bearer" or not credenciales.credentials:
        raise ErrorAplicacion(401, MENSAJE_TOKEN_INVALIDO)
    return decodificar_token(credenciales.credentials)
