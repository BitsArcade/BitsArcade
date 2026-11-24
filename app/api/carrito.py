from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.base_datos import get_db
from app.core.respuestas import Respuesta
from app.core.seguridad import UsuarioAutenticado, obtener_usuario_autenticado
from app.domain.carrito import (
    ActualizarCantidadEntrada,
    AgregarItemEntrada,
    CarritoSalida,
    DesgloseItemSalida,
)
from app.services.servicio_carrito import ServicioCarrito

enrutador_carrito = APIRouter(
    prefix="/api/v1/carrito",
    tags=["MOD-04: Carrito de Compras (HU-26 a HU-30)"],
)

servicio_carrito = ServicioCarrito()

ERROR_401 = {"description": "Token inválido, expirado o ausente"}


@enrutador_carrito.post(
    "/items",
    response_model=Respuesta[CarritoSalida],
    status_code=status.HTTP_201_CREATED,
    responses={
        400: {"description": "cantidad debe ser mayor o igual a 1"},
        401: ERROR_401,
        404: {"description": "El juego indicado no existe"},
        409: {"description": "Stock insuficiente / Solo se permite una licencia por título en preventa"},
        503: {"description": "No fue posible agregar el juego al carrito"},
    },
)
def agregar_juego_al_carrito(
    datos: AgregarItemEntrada,
    usuario: UsuarioAutenticado = Depends(obtener_usuario_autenticado),
    sesion: Session = Depends(get_db),
):
    """HU-26: Agregar juego al carrito de compras."""
    return servicio_carrito.agregar_item(sesion, usuario, datos)


@enrutador_carrito.get(
    "",
    response_model=Respuesta[CarritoSalida],
    responses={
        401: ERROR_401,
        503: {"description": "No fue posible obtener los precios vigentes (COM-11) / consultar el carrito (BD)"},
    },
)
def consultar_carrito_activo(
    usuario: UsuarioAutenticado = Depends(obtener_usuario_autenticado),
    sesion: Session = Depends(get_db),
):
    """HU-27: Consultar ítems del carrito activo."""
    return servicio_carrito.consultar_carrito(sesion, usuario)


@enrutador_carrito.delete(
    "",
    response_model=Respuesta[CarritoSalida],
    responses={
        401: ERROR_401,
        503: {"description": "No fue posible vaciar el carrito"},
    },
)
def vaciar_carrito_activo(
    usuario: UsuarioAutenticado = Depends(obtener_usuario_autenticado),
    sesion: Session = Depends(get_db),
):
    """HU-30: Vaciar carrito de compras."""
    return servicio_carrito.vaciar_carrito(sesion, usuario)


@enrutador_carrito.delete(
    "/items/{itemId}",
    response_model=Respuesta[CarritoSalida],
    responses={
        401: ERROR_401,
        404: {"description": "El ítem no existe en tu carrito"},
        503: {"description": "No fue posible eliminar el ítem"},
    },
)
def eliminar_item_del_carrito(
    itemId: int,
    usuario: UsuarioAutenticado = Depends(obtener_usuario_autenticado),
    sesion: Session = Depends(get_db),
):
    """HU-28: Eliminar ítem del carrito."""
    return servicio_carrito.eliminar_item(sesion, usuario, itemId)


@enrutador_carrito.patch(
    "/items/{itemId}",
    response_model=Respuesta[DesgloseItemSalida],
    responses={
        400: {"description": "cantidad debe ser mayor o igual a 1. Use DELETE para retirar el ítem"},
        401: ERROR_401,
        404: {"description": "El ítem no existe en tu carrito"},
        409: {"description": "Stock insuficiente / Solo se permite una licencia por título en preventa"},
        503: {"description": "No fue posible recalcular los subtotales"},
    },
)
def recalcular_subtotales_item(
    itemId: int,
    datos: ActualizarCantidadEntrada,
    usuario: UsuarioAutenticado = Depends(obtener_usuario_autenticado),
    sesion: Session = Depends(get_db),
):
    """HU-29: Recalcular subtotales con promociones y volumen."""
    return servicio_carrito.actualizar_cantidad(sesion, usuario, itemId, datos)