from typing import Optional

from fastapi import APIRouter, Depends, Header, Request, status
from sqlalchemy.orm import Session

from app.core.base_datos import obtenerSesionBd
from app.core.respuestas import Respuesta
from app.core.seguridad import UsuarioAutenticado, obtenerUsuarioAutenticado
from app.domain.pagos import (
    ComprobanteSalida,
    EstadoPagoSalida,
    IniciarPagoEntrada,
    PagoEnProcesoSalida,
)
from app.services.servicio_pagos import ServicioPagos

enrutadorPagos = APIRouter(
    prefix="/api/v1/pagos",
    tags=["MOD-05: Transacciones y Pagos (HU-36 a HU-40)"],
)

servicioPagos = ServicioPagos()

ERROR_401 = {"description": "Token inválido, expirado o ausente"}


# ===== HU-36: Transmitir cobro a la pasarela de pago simulada =====

@enrutadorPagos.post(
    "",
    response_model=Respuesta[PagoEnProcesoSalida],
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        401: ERROR_401,
        404: {"description": "La orden indicada no existe"},
        409: {"description": "La orden no está disponible para pago / La orden está por expirar"},
        503: {"description": "No fue posible iniciar el pago"},
        504: {"description": "La pasarela de pagos no respondió"},
    },
)
def iniciarCobro(
    datos: IniciarPagoEntrada,
    usuario: UsuarioAutenticado = Depends(obtenerUsuarioAutenticado),
    sesion: Session = Depends(obtenerSesionBd),
):
    """HU-36: envía el cobro a la pasarela simulada con la tasa congelada de la orden (RN-09)."""
    return servicioPagos.iniciarPago(sesion, usuario, datos)


# ===== HU-37: Recibir y procesar aprobación de pago =====

@enrutadorPagos.post(
    "/notificacion-pasarela",
    response_model=Respuesta[dict],
    responses={
        400: {"description": "El monto o la moneda no coinciden con la orden"},
        401: {"description": "Firma de la notificación de la pasarela inválida"},
        404: {"description": "La transacción indicada no existe"},
        409: {"description": "La transacción ya fue resuelta con otro estado"},
        503: {"description": "No fue posible procesar el pago"},
    },
)
async def recibirNotificacionPasarela(
    request: Request,
    firmaPasarela: Optional[str] = Header(default=None, alias="X-Signature"),
    sesion: Session = Depends(obtenerSesionBd),
):
    """
    HU-37 (APROBADO) y HU-38 (RECHAZADO, FALLIDO, EXPIRADO): notificación de la pasarela firmado con HMAC-SHA256 del
    cuerpo en el header X-Signature.
    """
    cuerpo = await request.body()
    return servicioPagos.procesarNotificacion(sesion, cuerpo, firmaPasarela)


# ===== HU-38: Gestionar rechazo de pago y cancelación de orden =====

@enrutadorPagos.get(
    "/{transaccionId}/estado",
    response_model=Respuesta[EstadoPagoSalida],
    responses={401: ERROR_401, 404: {"description": "La transacción indicada no existe"}},
)
def consultarEstadoPago(
    transaccionId: str,
    usuario: UsuarioAutenticado = Depends(obtenerUsuarioAutenticado),
    sesion: Session = Depends(obtenerSesionBd),
):
    """HU-38: estado del pago y mensaje claro para el usuario."""
    return servicioPagos.consultarEstado(sesion, usuario, transaccionId)


# ===== HU-39: Registrar comprobante digital de transacción =====

@enrutadorPagos.get(
    "/{transaccionId}/comprobante",
    response_model=Respuesta[ComprobanteSalida],
    responses={
        401: ERROR_401,
        404: {"description": "No existe comprobante para la transacción indicada"},
        503: {"description": "No fue posible consultar el comprobante"},
    },
)
def consultarComprobante(
    transaccionId: str,
    usuario: UsuarioAutenticado = Depends(obtenerUsuarioAutenticado),
    sesion: Session = Depends(obtenerSesionBd),
):
    """HU-39: comprobante digital de una transacción APROBADA del usuario."""
    return servicioPagos.consultarComprobante(sesion, usuario, transaccionId)
