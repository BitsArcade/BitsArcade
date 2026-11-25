"""
Endpoints de MOD-05 Transacciones (HU-36).
"""
from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.core.base_datos import get_db
from app.core.seguridad import UsuarioAutenticado, obtener_usuario_autenticado
from app.domain.transacciones import (
    DatosPagoEnProceso,
    RespuestaIniciarPago,
    SolicitudIniciarPago,
)
from app.repositories.repositorio_transacciones import RepositorioTransacciones
from app.services.servicio_transacciones import (
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
    return ServicioTransacciones(
        repositorio=repositorio,
        adaptador_ordenes=adaptador_ordenes,
        cliente_pasarela=cliente_pasarela,
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