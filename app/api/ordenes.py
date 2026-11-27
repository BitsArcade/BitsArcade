from typing import Optional

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy.orm import Session

from app.core.base_datos import obtenerSesionBd
from app.core.respuestas import ErrorAplicacion, Respuesta, manejarErroresBd, respuesta
from app.core.seguridad import ServicioAutenticado, UsuarioAutenticado, obtenerUsuarioAutenticado, validarTokenServicio
from app.domain.ordenes import (
    MENSAJE_ORDEN_NO_EXISTE,
    ActualizarEstadoOrdenEntrada,
    CancelarOrdenEntrada,
    ContratoCom08Salida,
    CrearOrdenEntrada,
    EstadoOrdenSalida,
    LiquidacionSalida,
    OrdenCanceladaSalida,
    OrdenPendienteSalida,
    OrdenSalida,
)
from app.core.fechas import aIsoZ
from app.services.servicio_ordenes import ServicioOrdenes

enrutadorOrdenes = APIRouter(prefix="/api/v1/ordenes", tags=["MOD-04: Órdenes de compra (HU-31 a HU-34)"])
enrutadorOrdenesInterno = APIRouter(
    prefix="/interno/v1/ordenes",
    tags=["MOD-04: Contratos internos (COM-08, COM-09 / HU-35)"],
    dependencies=[Depends(validarTokenServicio)],
)
servicioOrdenes = ServicioOrdenes()

ERROR_401 = {"description": "Token inválido, expirado o ausente"}


@enrutadorOrdenes.post(
    "",
    status_code=201,
    response_model=Respuesta[OrdenSalida],
    responses={
        401: ERROR_401,
        403: {"description": "Debe confirmar su cuenta para realizar compras"},
        409: {"description": "Carrito vacío / moneda no habilitada / stock insuficiente"},
        503: {"description": "Tasa de cambio no disponible / base de datos no disponible"},
    },
)
def consolidarOrden(
    datos: CrearOrdenEntrada,
    claveIdempotencia: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    usuario: UsuarioAutenticado = Depends(obtenerUsuarioAutenticado),
    sesion: Session = Depends(obtenerSesionBd),
):
    """HU-31: transforma el carrito en una orden PENDIENTE con precios, IVA, tasa y claves congelados."""
    return servicioOrdenes.crearOrden(sesion, usuario, datos, claveIdempotencia)


@enrutadorOrdenes.get("", response_model=Respuesta[list[OrdenPendienteSalida]], responses={401: ERROR_401})
def consultarOrdenes(
    estado: Optional[str] = Query(default="PENDIENTE", description="Estado de la orden (por defecto PENDIENTE)"),
    usuario: UsuarioAutenticado = Depends(obtenerUsuarioAutenticado),
    sesion: Session = Depends(obtenerSesionBd),
):
    """HU-33: órdenes del usuario autenticado en el estado indicado (PENDIENTE)."""
    return servicioOrdenes.consultarOrdenes(sesion, usuario, estado)


@enrutadorOrdenes.get("/{ordenId}/liquidacion", response_model=Respuesta[LiquidacionSalida], responses={401: ERROR_401})
def consultarLiquidacion(
    ordenId: int,
    usuario: UsuarioAutenticado = Depends(obtenerUsuarioAutenticado),
    sesion: Session = Depends(obtenerSesionBd),
):
    """HU-32: desglose de base gravable, IVA y descuentos con los valores congelados de la orden."""
    return servicioOrdenes.consultarLiquidacion(sesion, usuario, ordenId)


@enrutadorOrdenes.post("/{ordenId}/cancelacion", response_model=Respuesta[OrdenCanceladaSalida], responses={401: ERROR_401})
def cancelarOrden(
    ordenId: int,
    datos: Optional[CancelarOrdenEntrada] = None,
    usuario: UsuarioAutenticado = Depends(obtenerUsuarioAutenticado),
    sesion: Session = Depends(obtenerSesionBd),
):
    """HU-34: anula una orden PENDIENTE y libera sus reservas (COM-13). Idempotente."""
    return servicioOrdenes.cancelarOrden(sesion, usuario, ordenId, datos.motivo if datos else None)


@enrutadorOrdenesInterno.get("/{ordenId}", response_model=Respuesta[ContratoCom08Salida])
def obtenerOrdenCom08(ordenId: int, sesion: Session = Depends(obtenerSesionBd)):
    """COM-08 ampliado: datos congelados de la orden para MOD-05."""
    with manejarErroresBd("No fue posible consultar la orden"):
        orden = servicioOrdenes.obtenerContratoCom08(sesion, ordenId)
    if orden is None:
        raise ErrorAplicacion(404, MENSAJE_ORDEN_NO_EXISTE)
    return respuesta("Consulta de orden exitosa", {**orden, "expiraEn": aIsoZ(orden["expiraEn"])})


@enrutadorOrdenesInterno.patch("/{ordenId}/estado", response_model=Respuesta[EstadoOrdenSalida])
def actualizarEstadoOrden(
    ordenId: int,
    datos: ActualizarEstadoOrdenEntrada,
    servicio: ServicioAutenticado = Depends(validarTokenServicio),
    sesion: Session = Depends(obtenerSesionBd),
):
    """HU-35 / COM-09: transición de estado validada (PROCESANDO, PAGADA, CANCELADA, ENTREGADA)."""
    return servicioOrdenes.actualizarEstado(
        sesion, ordenId, datos.estado, transaccionId=datos.transaccionId, solicitante=servicio.modulo
    )
