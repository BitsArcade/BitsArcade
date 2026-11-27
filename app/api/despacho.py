from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.base_datos import obtenerSesionBd
from app.core.seguridad import validarTokenServicio
from app.core.respuestas import Respuesta
from app.domain.despacho import DespachoEntrada, DespachoSalida, ElegibilidadSalida
from app.services.servicio_despacho import ServicioDespacho

enrutadorDespachoInterno = APIRouter(
    prefix="/interno/v1/despacho",
    tags=["Contratos Internos MOD-06 Despacho (COM-10, HU-41 y HU-45)"],
    dependencies=[Depends(validarTokenServicio)],
)

servicioDespacho = ServicioDespacho()


# ===== HU-41: Asignar clave digital al perfil del usuario =====

@enrutadorDespachoInterno.post(
    "/ordenes",
    response_model=Respuesta[DespachoSalida],
    status_code=status.HTTP_201_CREATED,
    responses={
        404: {"description": "El comprador no existe"},
        409: {"description": "La licencia ya fue entregada y no puede reasignarse"},
        503: {"description": "No fue posible obtener la clave del inventario / No fue posible asignar la licencia"},
    },
)
def asignarLicenciasCom10(datos: DespachoEntrada, sesion: Session = Depends(obtenerSesionBd)):
    """HU-41 / COM-10 ampliado: vincula las claves compradas al perfil del comprador."""
    return servicioDespacho.asignarLicencias(sesion, datos)


# ===== HU-45: Validar unicidad e inmutabilidad de entrega =====

@enrutadorDespachoInterno.get(
    "/ordenes/{ordenId}/elegibilidad",
    response_model=Respuesta[ElegibilidadSalida],
    responses={
        409: {"description": "La licencia ya fue entregada y no puede reasignarse"},
        503: {"description": "No fue posible validar la entrega"},
    },
)
def validarElegibilidadEntrega(
    ordenId: int,
    reservaIds: list[str] = Query(default=[], description="Reservas de la orden a validar"),
    sesion: Session = Depends(obtenerSesionBd),
):
    """HU-45 (RN-10): verifica que ninguna reserva de la orden haya sido entregada a otra orden."""
    return servicioDespacho.validarElegibilidad(sesion, ordenId, reservaIds)
