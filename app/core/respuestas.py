"""
Utilidades transversales para el contrato de respuesta estándar de BitArcade:

    {"message": str, "data": <objeto | lista | null>, "success": bool}

Se usan en los módulos MOD-02 (Catálogo) y MOD-04 (Carrito).
"""
from contextlib import contextmanager
from typing import Any, Generic, Optional, TypeVar

from fastapi import FastAPI, Request
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

    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def respuesta(message: str, data: Any, success: bool = True) -> dict:
    """Construye el cuerpo estándar de respuesta."""
    return {"message": message, "data": data, "success": success}


@contextmanager
def manejar_errores_bd(mensaje: str):
    """Traduce cualquier fallo de base de datos en un 503 con mensaje amigable."""
    try:
        yield
    except SQLAlchemyError as error:
        raise ErrorAplicacion(503, mensaje) from error


async def _manejar_error_aplicacion(_: Request, error: ErrorAplicacion) -> JSONResponse:
    return JSONResponse(
        status_code=error.status_code,
        content=respuesta(error.message, None, False),
    )


def registrar_manejadores_errores(app: FastAPI) -> None:
    """Registra el manejador del contrato de error estándar en la aplicación."""
    app.add_exception_handler(ErrorAplicacion, _manejar_error_aplicacion)
