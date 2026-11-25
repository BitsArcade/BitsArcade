"""
Endpoints de MOD-06 Despacho (HU-41).
"""
from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.core.base_datos import get_db
from app.domain.despacho import (
    DatosDespachoCOM10,
    RespuestaDespachoCOM10,
    SolicitudDespachoCOM10,
)
from app.repositories.repositorio_despacho import RepositorioDespacho
from app.services.servicio_despacho import (
    AdaptadorOrdenYInventarioLocal,
    ServicioDespacho,
)

enrutador_despacho_interno = APIRouter(
    prefix="/interno/v1/despacho",
    tags=["MOD-06 Despacho (Interno COM-10)"],
)


def obtener_servicio_despacho(
    db: Session = Depends(get_db),
) -> ServicioDespacho:
    repositorio = RepositorioDespacho(db)
    adaptador_inventario = AdaptadorOrdenYInventarioLocal(db)
    return ServicioDespacho(
        repositorio=repositorio,
        adaptador_inventario=adaptador_inventario,
    )


@enrutador_despacho_interno.post(
    "/ordenes",
    status_code=status.HTTP_200_OK,
    response_model=RespuestaDespachoCOM10,
    summary="Asignar claves digitales al perfil del usuario tras pago aprobado (COM-10 / HU-41)",
    description=(
        "Endpoint interno invocado por MOD-05 (COM-10) al aprobarse un pago. Valida que "
        "la orden esté PAGADA, confirma las licencias reservadas en inventario (VENDIDA) "
        "y asigna de forma idempotente e inmutable cada licencia al perfil del usuario."
    ),
)
def despachar_orden_com10(
    cuerpo: SolicitudDespachoCOM10,
    servicio: ServicioDespacho = Depends(obtener_servicio_despacho),
):
    resultado = servicio.ejecutar_despacho_com10(cuerpo)
    datos = DatosDespachoCOM10(**resultado)
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={
            "message": "Licencias digitales asignadas al usuario",
            "data": datos.model_dump(),
            "success": True,
        },
    )