from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.base_datos import get_db
from app.core.respuestas import Respuesta
from app.core.seguridad import UsuarioAutenticado, obtener_usuario_autenticado
from app.domain.orden import (
    ActualizarEstadoOrdenEntrada,
    CancelacionOrdenSalida,
    EstadoOrdenInternoSalida,
    LiquidacionOrdenSalida,
    OrdenSalida,
)
from app.services.servicio_orden import ServicioOrden

enrutador_ordenes = APIRouter(
    prefix="/api/v1/ordenes",
    tags=["MOD-04: Órdenes de Compra (HU-31 a HU-34)"],
)

enrutador_ordenes_interno = APIRouter(
    prefix="/interno/v1/ordenes",
    tags=["Contratos Internos MOD-04 (HU-35)"],
)

servicio_orden = ServicioOrden()

ERROR_401 = {"description": "Token inválido, expirado o ausente"}


@enrutador_ordenes.post(
    "",
    response_model=Respuesta[OrdenSalida],
    status_code=status.HTTP_201_CREATED,
    responses={
        400: {"description": "El carrito está vacío"},
        401: ERROR_401,
        404: {"description": "El juego indicado no existe"},
        409: {"description": "Stock insuficiente / Límite de preventa"},
        503: {"description": "No fue posible consolidar la orden"},
    },
)
def consolidar_orden_compra(
    usuario: UsuarioAutenticado = Depends(obtener_usuario_autenticado),
    sesion: Session = Depends(get_db),
):
    """HU-31: Consolidar orden de compra pendiente desde el carrito activo."""
    return servicio_orden.consolidar_orden(sesion, usuario)


@enrutador_ordenes.get(
    "/{ordenId}/liquidacion",
    response_model=Respuesta[LiquidacionOrdenSalida],
    responses={
        401: ERROR_401,
        404: {"description": "La orden indicada no existe"},
        503: {"description": "No fue posible consultar la liquidación"},
    },
)
def consultar_liquidacion_orden(
    ordenId: int,
    usuario: UsuarioAutenticado = Depends(obtener_usuario_autenticado),
    sesion: Session = Depends(get_db),
):
    """HU-32: Liquidación financiera de la orden."""
    return servicio_orden.consultar_liquidacion(sesion, usuario, ordenId)


@enrutador_ordenes.get(
    "",
    response_model=Respuesta[list[OrdenSalida]],
    responses={
        400: {"description": "Estado de orden no válido"},
        401: ERROR_401,
        503: {"description": "No fue posible consultar las órdenes"},
    },
)
def consultar_ordenes_usuario(
    estado: str | None = Query(None, description="Filtrar por estado (ej. PENDIENTE)"),
    usuario: UsuarioAutenticado = Depends(obtener_usuario_autenticado),
    sesion: Session = Depends(get_db),
):
    """HU-33: Consultar órdenes pendientes (o filtradas por estado)."""
    return servicio_orden.listar_ordenes(sesion, usuario, estado)


@enrutador_ordenes.post(
    "/{ordenId}/cancelacion",
    response_model=Respuesta[CancelacionOrdenSalida],
    responses={
        401: ERROR_401,
        404: {"description": "La orden indicada no existe"},
        409: {"description": "La orden ya está cancelada o no está en estado PENDIENTE"},
        503: {"description": "No fue posible cancelar la orden o liberar el stock"},
    },
)
def cancelar_orden_compra(
    ordenId: int,
    usuario: UsuarioAutenticado = Depends(obtener_usuario_autenticado),
    sesion: Session = Depends(get_db),
):
    """HU-34: Cancelar orden de compra y liberar stock reservado."""
    return servicio_orden.cancelar_orden(sesion, usuario, ordenId)


@enrutador_ordenes_interno.patch(
    "/{ordenId}/estado",
    response_model=EstadoOrdenInternoSalida,
    responses={
        400: {"description": "Estado destino no válido"},
        404: {"description": "La orden indicada no existe"},
        409: {"description": "La orden está bloqueada en PROCESANDO o la transición no es válida"},
        503: {"description": "No fue posible actualizar el estado de la orden"},
    },
)
def actualizar_estado_orden_interno(
    ordenId: int,
    datos: ActualizarEstadoOrdenEntrada,
    sesion: Session = Depends(get_db),
):
    """HU-35: Bloquear orden al pasar a PROCESANDO (contrato interno para MOD-05 Pagos)."""
    return servicio_orden.actualizar_estado_interno(sesion, ordenId, datos.estado)