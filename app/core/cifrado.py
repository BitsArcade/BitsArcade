"""
Cifrado simétrico y hash de claves de licencia (MOD-03 / MOD-06).

- La clave se almacena cifrada (Fernet, AES-128-CBC + HMAC) con una llave derivada de CLAVE_SECRETA.
- El hash SHA-256 de la clave normalizada solo se usa para la unicidad RN-03.
Nunca se registran valores de claves en logs.
"""
import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.core.configuracion import configuracion


def _obtenerFernet() -> Fernet:
    llave = hashlib.sha256(f"vault-keys::{configuracion.CLAVE_SECRETA}".encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(llave))


def cifrarClave(valor: str) -> str:
    return _obtenerFernet().encrypt(valor.encode("utf-8")).decode("utf-8")


def descifrarClave(valorCifrado: str) -> str:
    try:
        return _obtenerFernet().decrypt(valorCifrado.encode("utf-8")).decode("utf-8")
    except InvalidToken as error:
        raise ValueError("No fue posible descifrar la clave") from error


def hashClave(valorNormalizado: str) -> str:
    return hashlib.sha256(valorNormalizado.encode("utf-8")).hexdigest()
