from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.base_datos import obtenerSesionBd
from app.core.respuestas import Respuesta
from app.core.seguridad import UsuarioAutenticado, obtenerUsuarioAutenticado
from app.domain.carrito import (
    ActualizarCantidadEntrada,
    AgregarItemEntrada,
    CarritoSalida,
    DesgloseItemSalida,
)
from app.services.servicio_carrito import ServicioCarrito

enrutadorCarrito = APIRouter(
    prefix="/api/v1/carrito",
    tags=["MOD-04: Carrito de Compras (HU-26 a HU-30)"],
)

servicioCarrito = ServicioCarrito()

ERROR_401 = {"description": "Token inválido, expirado o ausente"}


@enrutadorCarrito.post(
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
def agregarJuegoAlCarrito(
    datos: AgregarItemEntrada,
    usuario: UsuarioAutenticado = Depends(obtenerUsuarioAutenticado),
    sesion: Session = Depends(obtenerSesionBd),
):
    """
    HU-26: Agregar juego al carrito de compras.

    Obtiene existencia, estado y precio del juego vía COM-11, verifica stock vía COM-12
    (solo consulta; la reserva ocurre en HU-31) y aplica RN-05 en PREVENTA (máximo 1 licencia).
    Si el juego ya estaba en el carrito acumula la cantidad. El usuarioId sale del JWT.
    """
    return servicioCarrito.agregarItem(sesion, usuario, datos)


@enrutadorCarrito.get(
    "",
    response_model=Respuesta[CarritoSalida],
    responses={
        401: ERROR_401,
        503: {"description": "No fue posible obtener los precios vigentes (COM-11) / consultar el carrito (BD)"},
    },
)
def consultarCarritoActivo(
    usuario: UsuarioAutenticado = Depends(obtenerUsuarioAutenticado),
    sesion: Session = Depends(obtenerSesionBd),
):
    """
    HU-27: Consultar ítems del carrito activo.

    Retorna los ítems del carrito del usuario del JWT con precios vigentes obtenidos del
    Catálogo (COM-11; MOD-04 no recalcula RN-01) y el subtotal preliminar SIN descuentos
    (los descuentos los aplica HU-29). Si el carrito está vacío responde 200 con `success=false`.
    """
    return servicioCarrito.consultarCarrito(sesion, usuario)


@enrutadorCarrito.delete(
    "/items/{itemId}",
    response_model=Respuesta[CarritoSalida],
    responses={
        401: ERROR_401,
        404: {"description": "El ítem no existe en tu carrito"},
        503: {"description": "No fue posible eliminar el ítem"},
    },
)
def eliminarItemDelCarrito(
    itemId: int,
    usuario: UsuarioAutenticado = Depends(obtenerUsuarioAutenticado),
    sesion: Session = Depends(obtenerSesionBd),
):
    """
    HU-28: Eliminar ítem del carrito.

    Remueve el ítem del carrito del usuario autenticado (solo del propio carrito; un ítem de
    otro usuario responde 404), recalcula los totales y retorna el carrito.
    """
    return servicioCarrito.eliminarItem(sesion, usuario, itemId)


@enrutadorCarrito.patch(
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
def recalcularSubtotalesItem(
    itemId: int,
    datos: ActualizarCantidadEntrada,
    usuario: UsuarioAutenticado = Depends(obtenerUsuarioAutenticado),
    sesion: Session = Depends(obtenerSesionBd),
):
    """
    HU-29: Recalcular subtotales con promociones y volumen.

    Cambia la cantidad del ítem y retorna el desglose. Estado y precios vía COM-11.
    RN-07: PREVENTA/ESTRENO sin descuentos. RN-05: máximo 1 licencia en preventa.
    RN-08: juego ACTIVO con cantidad >= 3 recibe 10 % de descuento por unidad.
    RN-02: ningún precio unitario con descuento baja de precioMinimo.
    """
    return servicioCarrito.actualizarCantidad(sesion, usuario, itemId, datos)


@enrutadorCarrito.delete(
    "",
    response_model=Respuesta[CarritoSalida],
    responses={
        401: ERROR_401,
        503: {"description": "No fue posible vaciar el carrito de compras"},
    },
)
def vaciarCarritoDeCompras(
    usuario: UsuarioAutenticado = Depends(obtenerUsuarioAutenticado),
    sesion: Session = Depends(obtenerSesionBd),
):
    """
    HU-30 (FUN-04.1.5 / PRO-04.1.5): Vaciar carrito de compras.

    Elimina todos los ítems asociados al carrito activo del usuario autenticado (JWT)
    y retorna el carrito vacío con subtotal en 0.0.
    """
    return servicioCarrito.vaciarCarrito(sesion, usuario)
