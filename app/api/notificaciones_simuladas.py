"""
PLACEHOLDER – API externa Notificaciones (simulada) expuesta para pruebas manuales.

Representa el destino de la interfaz saliente de HU-44: POST /external/notificaciones/despacho.
"""
from typing import Optional

from fastapi import APIRouter, status
from pydantic import BaseModel

from app.core.respuestas import ErrorAplicacion, Respuesta, respuesta
from app.services.cliente_notificaciones import ClienteNotificaciones, NotificacionesNoDisponible

enrutadorNotificacionesExternas = APIRouter(
    prefix="/externo/v1/notificaciones",
    tags=["API externa Notificaciones (simulada)"],
)


# ===== HU-44: Notificación automática de despacho =====

class NotificacionDespachoEntrada(BaseModel):
    destinatario: Optional[str] = None
    plantilla: str = "DESPACHO_CONFIRMADO"
    datos: dict = {}


class NotificacionDespachoSalida(BaseModel):
    notificacionId: str
    estado: str


@enrutadorNotificacionesExternas.post(
    "/despacho",
    response_model=Respuesta[NotificacionDespachoSalida],
    status_code=status.HTTP_202_ACCEPTED,
    responses={503: {"description": "El servicio de notificaciones no está disponible"}},
)
def enviarNotificacionDespacho(datos: NotificacionDespachoEntrada):
    """HU-44: recibe la plantilla DESPACHO_CONFIRMADO (sin la clave) y simula el envío del correo."""
    try:
        resultado = ClienteNotificaciones().enviar(datos.destinatario, datos.plantilla, datos.datos)
    except NotificacionesNoDisponible as error:
        raise ErrorAplicacion(503, "El servicio de notificaciones no está disponible") from error
    return respuesta("Notificación de despacho enviada", resultado)
