"""
Utilidades transversales para el contrato de respuesta estándar de BitArcade:

    {"message": str, "data": <objeto | lista | null>, "success": bool}

Se usan en todos los módulos (MOD-00, MOD-02, MOD-04).
"""
from contextlib import contextmanager
from typing import Any, Generic, Optional, TypeVar

from fastapi import FastAPI, HTTPException, Request
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


async def _manejar_error_validacion(_: Request, error: RequestValidationError) -> JSONResponse:
    """Estandariza errores de validación Pydantic/FastAPI a HTTP 400 (eliminando 422)."""
    errores = error.errors()
    detalle = errores[0].get("msg", "Datos de entrada inválidos") if errores else "Datos de entrada inválidos"
    return JSONResponse(
        status_code=400,
        content=respuesta(detalle, None, False),
    )


async def _manejar_http_exception(_: Request, error: HTTPException) -> JSONResponse:
    """Asegura el formato estándar cuando se lanza HTTPException."""
    mensaje = error.detail if isinstance(error.detail, str) else "Error en la solicitud"
    return JSONResponse(
        status_code=error.status_code,
        content=respuesta(mensaje, None, False),
    )


def registrar_manejadores_errores(app: FastAPI) -> None:
    """Registra los manejadores del contrato de error estándar en la aplicación."""
    app.add_exception_handler(ErrorAplicacion, _manejar_error_aplicacion)
    app.add_exception_handler(RequestValidationError, _manejar_error_validacion)
    app.add_exception_handler(HTTPException, _manejar_http_exception)