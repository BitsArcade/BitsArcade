"""
Endpoints internos y públicos de MOD-06 Despacho y Biblioteca (HU-41 a HU-50).
"""
from typing import Optional

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.core.base_datos import get_db
from app.core.seguridad import UsuarioAutenticado, obtener_usuario_autenticado
from app.domain.despacho import (
    ClaveReveladaSalida,
    DatosDespachoCOM10,
    DatosElegibilidadEntrega,
    LicenciaBibliotecaSalida,
    RespuestaBibliotecaLicencias,
    RespuestaDespachoCOM10,
    RespuestaElegibilidadEntrega,
    RespuestaRevelarClave,
    SolicitudDespachoCOM10,
)
from app.repositories.repositorio_despacho import RepositorioDespacho
from app.services.servicio_despacho import (
    AdaptadorOrdenYInventarioLocal,
    ServicioDespacho,
)

enrutador_despacho_interno = APIRouter(
    prefix="/interno/v1/despacho",
    tags=["MOD-06 Despacho (Interno COM-10 / HU-45)"],
)

enrutador_biblioteca = APIRouter(
    prefix="/api/v1/biblioteca",
    tags=["MOD-06 Despacho y Biblioteca (HU-43 a HU-50)"],
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


@enrutador_despacho_interno.get(
    "/ordenes/{ordenId}/elegibilidad",
    status_code=status.HTTP_200_OK,
    response_model=RespuestaElegibilidadEntrega,
    summary="Validar unicidad e inmutabilidad de entrega para una orden (HU-45)",
    description=(
        "Verifica en Despacho.Dominio que ninguna clave o reserva de la orden haya sido "
        "entregada previamente a otra orden/usuario (RN-10). Es idempotente si la misma "
        "orden ya fue despachada."
    ),
    responses={
        409: {"description": "La licencia ya fue entregada y no puede reasignarse"},
        503: {"description": "No fue posible validar la entrega"},
    },
)
def validar_elegibilidad_entrega_orden(
    ordenId: int,
    reservaId: Optional[list[str]] = Query(default=None),
    servicio: ServicioDespacho = Depends(obtener_servicio_despacho),
):
    resultado = servicio.validar_unicidad_entrega_orden(
        orden_id=ordenId,
        reserva_ids_explicitas=reservaId,
    )
    datos = DatosElegibilidadEntrega(**resultado)
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={
            "message": "Entrega autorizada",
            "data": datos.model_dump(),
            "success": True,
        },
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


@enrutador_biblioteca.get(
    "",
    status_code=status.HTTP_200_OK,
    response_model=RespuestaBibliotecaLicencias,
    summary="Consultar biblioteca digital del usuario autenticado (HU-46)",
    description=(
        "Despliega la biblioteca digital del usuario autenticado con sus licencias "
        "enmascaradas por seguridad y filtros opcionales por título y plataforma."
    ),
    responses={
        401: {"description": "Token inválido, expirado o ausente"},
        503: {"description": "No fue posible consultar la biblioteca de licencias"},
    },
)
def consultar_biblioteca_usuario(
    titulo: Optional[str] = Query(default=None),
    plataforma: Optional[str] = Query(default=None),
    usuario: UsuarioAutenticado = Depends(obtener_usuario_autenticado),
    servicio: ServicioDespacho = Depends(obtener_servicio_despacho),
):
    licencias = servicio.listar_biblioteca_usuario(
        usuario_id=usuario.id,
        titulo=titulo,
        plataforma=plataforma,
    )
    datos = [LicenciaBibliotecaSalida(**item).model_dump() for item in licencias]
    if not datos:
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "message": "El usuario aún no tiene licencias digitales en su biblioteca",
                "data": [],
                "success": False,
            },
        )
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={
            "message": "Biblioteca de licencias obtenida exitosamente",
            "data": datos,
            "success": True,
        },
    )


@enrutador_biblioteca.get(
    "/licencias",
    status_code=status.HTTP_200_OK,
    response_model=RespuestaBibliotecaLicencias,
    summary="Desplegar biblioteca y listado de licencias digitales del usuario",
    description=(
        "Consulta el listado de licencias digitales adquiridas por el usuario autenticado "
        "con sus claves en formato enmascarado por seguridad."
    ),
    responses={
        401: {"description": "Token inválido, expirado o ausente"},
        503: {"description": "No fue posible consultar la biblioteca de licencias"},
    },
)
def listar_licencias_biblioteca(
    usuario: UsuarioAutenticado = Depends(obtener_usuario_autenticado),
    servicio: ServicioDespacho = Depends(obtener_servicio_despacho),
):
    licencias = servicio.listar_biblioteca_usuario(usuario_id=usuario.id)
    datos = [LicenciaBibliotecaSalida(**item).model_dump() for item in licencias]
    if not datos:
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "message": "El usuario aún no tiene licencias digitales en su biblioteca",
                "data": [],
                "success": False,
            },
        )
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={
            "message": "Biblioteca de licencias obtenida exitosamente",
            "data": datos,
            "success": True,
        },
    )


@enrutador_biblioteca.post(
    "/licencias/{licenciaId}/revelar",
    status_code=status.HTTP_200_OK,
    response_model=RespuestaRevelarClave,
    summary="Revelar clave digital de forma segura con formato legible (HU-43)",
    description=(
        "Permite al usuario autenticado propietario revelar su clave digital en grupos "
        "de 4 caracteres separados por guiones junto con la instrucción de activación, "
        "registrando auditoría de visualización."
    ),
    responses={
        401: {"description": "Token inválido, expirado o ausente"},
        404: {"description": "La licencia indicada no existe"},
        503: {"description": "No fue posible revelar la clave digital"},
    },
)
def revelar_clave_licencia(
    licenciaId: str,
    usuario: UsuarioAutenticado = Depends(obtener_usuario_autenticado),
    servicio: ServicioDespacho = Depends(obtener_servicio_despacho),
):
    resultado = servicio.revelar_clave_licencia(
        licencia_id=licenciaId,
        usuario_id=usuario.id,
    )
    datos = ClaveReveladaSalida(**resultado)
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={
            "message": "Clave digital revelada",
            "data": datos.model_dump(),
            "success": True,
        },
    )