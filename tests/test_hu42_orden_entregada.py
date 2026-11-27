"""Pruebas de HU-42: Marcar orden como entregada (COM-09 saliente con MOD-06 como solicitante)."""
import pytest

from app.core.respuestas import ErrorAplicacion
from app.domain.despacho import RegistroCompra
from app.services.servicio_despacho import ServicioDespacho
from tests.apoyo_modulos import obtenerOrden, crearOrdenPrueba, crearUsuario, despacharOrden, limpiarSimulaciones


@pytest.fixture(autouse=True)
def _limpiar():
    limpiarSimulaciones()


def test_flujoExitosoDesdePagada(sesion):
    crearOrdenPrueba(sesion, 5001, estado="PAGADA")
    resultado = ServicioDespacho().marcarOrdenEntregada(sesion, 5001)
    assert resultado == {"message": "Orden cerrada como entregada",
                         "data": {"ordenId": 5001, "estado": "ENTREGADA", "confirmado": True}, "success": True}
    assert obtenerOrden(sesion, 5001).estado == "ENTREGADA"
    assert obtenerOrden(sesion, 5001).entregadaEn is not None   # Fecha y hora exactas


def test_despachoCompletoCierraLaOrdenYRegistraFecha(cliente, sesion):
    usuario = crearUsuario(sesion)
    despacharOrden(cliente, sesion, usuario.id)
    compra = sesion.query(RegistroCompra).one()
    assert compra.estadoOrden == "ENTREGADA" and compra.entregadaEn is not None


def test_transicionNoPermitidaSiNoEstaPagada(sesion):
    crearOrdenPrueba(sesion, 5001, estado="PENDIENTE")
    resultado = ServicioDespacho().marcarOrdenEntregada(sesion, 5001)
    assert resultado["success"] is False and resultado["message"] == "Transición de estado no permitida"
    assert obtenerOrden(sesion, 5001).estado == "PENDIENTE"


def test_error503Mod04NoDisponible(sesion):
    servicio = ServicioDespacho()
    servicio.clienteOrdenes.disponible = False
    with pytest.raises(ErrorAplicacion) as error:
        servicio.marcarOrdenEntregada(sesion, 5001)
    assert error.value.codigoHttp == 503
    assert error.value.mensaje == "No fue posible marcar la orden como entregada"
