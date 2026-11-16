from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.base_datos import get_db
from app.core.respuestas import Respuesta
from app.core.seguridad import UsuarioAutenticado, obtener_usuario_autenticado
from app.domain.carrito import AgregarItemEntrada, CarritoSalida
from app.services.servicio_carrito import ServicioCarrito

enrutador_carrito = APIRouter(
    prefix="/api/v1/carrito",
    tags=["MOD-04: Carrito de Compras (HU-26 a HU-29)"],
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
    """
    HU-26: Agregar juego al carrito de compras.

    Obtiene existencia, estado y precio del juego vía COM-11, verifica stock vía COM-12
    (solo consulta; la reserva ocurre en HU-31) y aplica RN-05 en PREVENTA (máximo 1 licencia).
    Si el juego ya estaba en el carrito acumula la cantidad. El userId sale del JWT.
    """
    return servicio_carrito.agregar_item(sesion, usuario, datos)
