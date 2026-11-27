from typing import Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.base_datos import obtenerSesionBd
from app.core.respuestas import Respuesta
from app.core.seguridad import (
    UsuarioAutenticado,
    obtenerUsuarioAdmin,
    validarTokenServicio,
)
from app.domain.inventario import (
    AlertaAgotadaSalida,
    CargaLoteEntrada,
    CargaLoteSalida,
    LiberacionSalida,
    LiberarReservasEntrada,
    ReservaSalida,
    ReservarClavesEntrada,
    StockSalida,
    VentaClaveSalida,
)
from app.services.servicio_inventario import ServicioInventario

enrutadorInventario = APIRouter(
    prefix="/api/v1/inventario",
    tags=["MOD-03: Inventario de claves (HU-11, HU-12, HU-15)"],
)

enrutadorInventarioInterno = APIRouter(
    prefix="/interno/v1/inventario",
    tags=["Contratos Internos MOD-03 (COM-06, COM-07, COM-12, COM-13)"],
    dependencies=[Depends(validarTokenServicio)],
)

servicioInventario = ServicioInventario()

ERRORES_ADMIN = {
    401: {"description": "Token inválido, expirado o ausente"},
    403: {"description": "No cuenta con permisos para realizar esta operación"},
}


# ===== HU-11: Carga masiva de claves al vault =====

@enrutadorInventario.post(
    "/claves/lotes",
    response_model=Respuesta[CargaLoteSalida],
    status_code=status.HTTP_201_CREATED,
    responses={
        400: {"description": "El lote no contiene claves / juegoId y plataforma son obligatorios"},
        **ERRORES_ADMIN,
        503: {"description": "No fue posible cargar las claves"},
    },
)
def cargarLoteDeClaves(
    datos: CargaLoteEntrada,
    _: UsuarioAutenticado = Depends(obtenerUsuarioAdmin),
    sesion: Session = Depends(obtenerSesionBd),
):
    """HU-11: carga un lote de claves cifradas en DISPONIBLE; reporta las rechazadas sin exponer su valor."""
    return servicioInventario.cargarLote(sesion, datos)


# ===== HU-12: Consultar y auditar inventario de claves =====

@enrutadorInventario.get(
    "/claves/metricas",
    response_model=Respuesta[dict],
    responses={
        400: {"description": "juegoId debe ser numérico"},
        **ERRORES_ADMIN,
        503: {"description": "No fue posible consultar el inventario"},
    },
)
def consultarMetricasInventario(
    juegoId: Optional[str] = Query(default=None, description="Filtro opcional por juego"),
    _: UsuarioAutenticado = Depends(obtenerUsuarioAdmin),
    sesion: Session = Depends(obtenerSesionBd),
):
    """HU-12: métricas de stock por juego y estado (DISPONIBLE, RESERVADA, VENDIDA)."""
    return servicioInventario.consultarMetricas(sesion, juegoId)


# ===== HU-15: Reportar y alertar llaves agotadas =====

@enrutadorInventario.get(
    "/claves/agotadas",
    response_model=Respuesta[list[AlertaAgotadaSalida]],
    responses={**ERRORES_ADMIN, 503: {"description": "No fue posible consultar las llaves agotadas"}},
)
def consultarLlavesAgotadas(
    _: UsuarioAutenticado = Depends(obtenerUsuarioAdmin),
    sesion: Session = Depends(obtenerSesionBd),
):
    """HU-15: títulos con alerta de stock agotado (la evaluación periódica la ejecuta TT-04)."""
    return servicioInventario.consultarAgotadas(sesion)


# ===== HU-13: Reservar clave temporalmente =====

@enrutadorInventarioInterno.post(
    "/reservas",
    response_model=Respuesta[ReservaSalida],
    status_code=status.HTTP_201_CREATED,
    responses={
        400: {"description": "cantidad debe ser mayor o igual a 1"},
        409: {"description": "Stock insuficiente para el juego solicitado"},
        503: {"description": "No fue posible reservar las claves"},
    },
)
def reservarClavesCom06(datos: ReservarClavesEntrada, sesion: Session = Depends(obtenerSesionBd)):
    """HU-13 / COM-06: reserva atómica de `cantidad` claves DISPONIBLE durante 15 minutos (RN-04)."""
    return servicioInventario.reservarClaves(sesion, datos)


@enrutadorInventarioInterno.post("/reservas/liberar", response_model=Respuesta[LiberacionSalida])
def liberarReservasCom13(datos: LiberarReservasEntrada, sesion: Session = Depends(obtenerSesionBd)):
    """COM-13: libera reservas (idempotente). Usado por HU-34 y HU-38."""
    return servicioInventario.liberarReservas(sesion, datos)


@enrutadorInventarioInterno.get("/stock/{juegoId}", response_model=Respuesta[StockSalida])
def consultarStockCom12(juegoId: int, sesion: Session = Depends(obtenerSesionBd)):
    """COM-12: cantidad de claves DISPONIBLE de un juego."""
    return servicioInventario.consultarStock(sesion, juegoId)


# ===== HU-14: Actualizar estado de clave a vendida =====

@enrutadorInventarioInterno.post(
    "/reservas/{reservaId}/venta",
    response_model=Respuesta[VentaClaveSalida],
    responses={
        404: {"description": "La reserva indicada no existe"},
        409: {"description": "La reserva expiró o fue liberada"},
        503: {"description": "No fue posible confirmar la venta de la clave"},
    },
)
def confirmarVentaCom07(reservaId: str, sesion: Session = Depends(obtenerSesionBd)):
    """HU-14 / COM-07: marca la clave VENDIDA y retorna su valor descifrado (idempotente)."""
    return servicioInventario.confirmarVenta(sesion, reservaId)
