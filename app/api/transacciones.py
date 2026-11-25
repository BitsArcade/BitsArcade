"""
Endpoints de MOD-05 Transacciones (HU-36, HU-37 y HU-38).
"""
import json
from typing import Optional, Union

from fastapi import APIRouter, Depends, Header, Request, status
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.base_datos import get_db
from app.core.respuestas import ErrorAplicacion
from app.core.seguridad import UsuarioAutenticado, obtener_usuario_autenticado
from app.domain.transacciones import (
    DatosEstadoPago,
    DatosPagoEnProceso,
    ReglasTransaccion,
    RespuestaEstadoPago,
    RespuestaIniciarPago,
    RespuestaPagoAprobado,
    RespuestaPagoRechazado,
    SolicitudIniciarPago,
    SolicitudNotificacionPasarela,
)
from app.repositories.repositorio_transacciones import RepositorioTransacciones
from app.services.servicio_transacciones import (
    AdaptadorDespachoLocal,
    AdaptadorOrdenesLocal,
    ClientePasarelaSimulada,
    ServicioTransacciones,
)

enrutador_transacciones = APIRouter(prefix="/api/v1/pagos", tags=["MOD-05 Transacciones"])


def obtener_servicio_transacciones(
    db: Session = Depends(get_db),
) -> ServicioTransacciones:
    repositorio = RepositorioTransacciones(db)
    adaptador_ordenes = AdaptadorOrdenesLocal(db)
    cliente_pasarela = ClientePasarelaSimulada()
    adaptador_despacho = AdaptadorDespachoLocal()
    return ServicioTransacciones(
        repositorio=repositorio,
        adaptador_ordenes=adaptador_ordenes,
        cliente_pasarela=cliente_pasarela,
        adaptador_despacho=adaptador_despacho,
    )


@enrutador_transacciones.post(
    "",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=RespuestaIniciarPago,
    summary="Transmitir cobro a la pasarela de pago simulada (HU-36)",
    description=(
        "Inicia el cobro de una orden PENDIENTE usando la tasa de cambio congelada (RN-09), "
        "cambia la orden a PROCESANDO (COM-09) y transmite la solicitud a la pasarela con "
        "Idempotency-Key = ordenId. Nota P-03: validación de método de pago ACTIVO pendiente."
    ),
)
async def iniciar_pago(
    cuerpo: SolicitudIniciarPago,
    usuario: UsuarioAutenticado = Depends(obtener_usuario_autenticado),
    servicio: ServicioTransacciones = Depends(obtener_servicio_transacciones),
):
    transaccion = await servicio.iniciar_cobro(
        orden_id=cuerpo.ordenId,
        metodo_pago_id=cuerpo.metodoPagoId,
        usuario_id=usuario.id,
    )
    datos = DatosPagoEnProceso(
        transaccionId=transaccion.transaccion_id,
        ordenId=transaccion.orden_id,
        estado=transaccion.estado.value,
    )
    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content={
            "message": "Pago en proceso",
            "data": datos.model_dump(),
            "success": True,
        },
    )


@enrutador_transacciones.post(
    "/notificacion-pasarela",
    status_code=status.HTTP_200_OK,
    response_model=Union[RespuestaPagoAprobado, RespuestaPagoRechazado],
    summary="Recibir y procesar notificación de la pasarela de pagos (HU-37 y HU-38)",
    description=(
        "Webhook firmado con HMAC-SHA256 en el header X-Signature. Procesa tanto "
        "aprobaciones (APROBADO -> HU-37) como rechazos, fallos y expiraciones "
        "(RECHAZADO, FALLIDO, EXPIRADO -> HU-38), delegando el estado final de la orden "
        "a COM-09 (HU-40)."
    ),
)
async def notificacion_pasarela(
    request: Request,
    x_signature: Optional[str] = Header(default=None, alias="X-Signature"),
    servicio: ServicioTransacciones = Depends(obtener_servicio_transacciones),
):
    cuerpo_crudo = await request.body()

    # Validamos firma HMAC antes de confiar en el cuerpo del webhook (401 prioritario)
    ReglasTransaccion.verificar_firma_hmac(
        cuerpo_crudo=cuerpo_crudo,
        firma_recibida=x_signature,
        secreto=servicio.secreto_webhook,
    )

    try:
        datos_json = json.loads(cuerpo_crudo.decode("utf-8")) if cuerpo_crudo else {}
        notificacion = SolicitudNotificacionPasarela(**datos_json)
    except (json.JSONDecodeError, UnicodeDecodeError, ValidationError) as error:
        raise ErrorAplicacion(400, "Cuerpo de notificación inválido") from error

    mensaje, datos = await servicio.procesar_notificacion_pasarela(
        cuerpo_crudo=cuerpo_crudo,
        firma_hmac=x_signature,
        notificacion=notificacion,
    )
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={
            "message": mensaje,
            "data": datos,
            "success": True,
        },
    )


@enrutador_transacciones.get(
    "/{transaccionId}/estado",
    status_code=status.HTTP_200_OK,
    response_model=RespuestaEstadoPago,
    summary="Consultar el estado de una transacción de pago (HU-38)",
    description=(
        "Permite al cliente autenticado consultar el resultado actual de su transacción "
        "(EN_PROCESO, APROBADA, FALLIDA, EXPIRADA o REQUIERE_REVISION) con un mensaje claro."
    ),
)
def consultar_estado_pago(
    transaccionId: str,
    usuario: UsuarioAutenticado = Depends(obtener_usuario_autenticado),
    servicio: ServicioTransacciones = Depends(obtener_servicio_transacciones),
):
    resultado = servicio.consultar_estado_transaccion(
        transaccion_id=transaccionId,
        usuario_id=usuario.id,
    )
    datos = DatosEstadoPago(**resultado)
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={
            "message": "Consulta de estado de pago exitosa",
            "data": datos.model_dump(),
            "success": True,
        },
    )