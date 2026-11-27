"""
Utilidades transversales para el contrato de respuesta estándar de BitArcade:

    {"message": str, "data": <objeto | lista | null>, "success": bool}

Se usan en los módulos MOD-02 (Catálogo) y MOD-04 (Carrito).
"""
from contextlib import contextmanager
from typing import Any, Generic, Optional, TypeVar

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError

T = TypeVar("T")


class Respuesta(BaseModel, Generic[T]):
    """Envoltura estándar de respuesta documentada en Swagger."""
    message: str
    data: Optional[T] = None
    success: bool


class ErrorAplicacion(Exception):
    """Error de validación, regla de negocio o infraestructura con su código HTTP."""

    def __init__(self, codigoHttp: int, mensaje: str):
        super().__init__(mensaje)
        self.codigoHttp = codigoHttp
        self.mensaje = mensaje


def respuesta(message: str, data: Any, success: bool = True) -> dict:
    """Construye el cuerpo estándar de respuesta."""
    return {"message": message, "data": data, "success": success}


@contextmanager
def manejarErroresBd(mensaje: str):
    """Traduce cualquier fallo de base de datos en un 503 con mensaje amigable."""
    try:
        yield
    except SQLAlchemyError as error:
        raise ErrorAplicacion(503, mensaje) from error


async def _manejarErrorAplicacion(_: Request, error: ErrorAplicacion) -> JSONResponse:
    return JSONResponse(
        status_code=error.codigoHttp,
        content=respuesta(error.mensaje, None, False),
    )


def mensajeValidacion(errores: list[dict]) -> str:
    """Traduce el primer error de validación de FastAPI/Pydantic a un mensaje en español."""
    if not errores:
        return "Los datos enviados no son válidos"
    error = errores[0]
    ubicacion = [str(parte) for parte in error.get("loc", ()) if parte not in ("body", "query", "path", "header")]
    campo = ".".join(ubicacion) or "cuerpo"
    tipo = error.get("type", "")
    if tipo == "missing":
        return f"El campo {campo} es obligatorio"
    if tipo in ("json_invalid", "model_attributes_type", "dict_type"):
        return "El cuerpo de la petición no es un JSON válido"
    return f"El campo {campo} tiene un valor inválido"


async def _manejarErrorValidacion(_: Request, error: RequestValidationError) -> JSONResponse:
    """Las validaciones de entrada responden 400 con el sobre estándar y mensaje en español."""
    return JSONResponse(status_code=400, content=respuesta(mensajeValidacion(error.errors()), None, False))


def registrarManejadoresErrores(app: FastAPI) -> None:
    """Registra el manejador del contrato de error estándar en la aplicación."""
    app.add_exception_handler(ErrorAplicacion, _manejarErrorAplicacion)
    app.add_exception_handler(RequestValidationError, _manejarErrorValidacion)
