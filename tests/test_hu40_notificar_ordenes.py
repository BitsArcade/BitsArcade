"""Pruebas de HU-40: Notificar resultado del cobro a Órdenes (COM-09 saliente)."""
import pytest

from app.core.respuestas import ErrorAplicacion
from app.domain.pagos import NotificacionOrden
from app.services.cliente_ordenes import OrdenesNoDisponible
from app.services.servicio_pagos import ServicioPagos
from tests.apoyo_modulos import obtenerOrden, crearOrdenPrueba, limpiarSimulaciones


@pytest.fixture(autouse=True)
def _limpiar():
    limpiarSimulaciones()


@pytest.fixture
def servicio():
    servicio = ServicioPagos()
    servicio.esperas = []
    servicio.esperar = servicio.esperas.append  # backoff sin dormir en pruebas
    return servicio


def test_flujoExitosoNotificaPagada(sesion, servicio):
    crearOrdenPrueba(sesion, 5001, estado="PROCESANDO")
    resultado = servicio.notificarResultado(sesion, 5001, "PAGADA", "TX-9001")
    assert resultado == {"message": "Resultado notificado a Órdenes",
                         "data": {"ordenId": 5001, "estado": "PAGADA", "confirmado": True}, "success": True}
    assert obtenerOrden(sesion, 5001).estado == "PAGADA"
    assert obtenerOrden(sesion, 5001).transaccionId == "TX-9001"


def test_idempotentePorTransaccionId(sesion, servicio):
    crearOrdenPrueba(sesion, 5001, estado="PROCESANDO")
    servicio.notificarResultado(sesion, 5001, "PAGADA", "TX-9001")
    servicio.notificarResultado(sesion, 5001, "PAGADA", "TX-9001")
    assert sesion.query(NotificacionOrden).one().intentos == 1


def test_409DeMod04SeRegistraYAlerta(sesion, servicio, caplog):
    crearOrdenPrueba(sesion, 5001, estado="CANCELADA")
    resultado = servicio.notificarResultado(sesion, 5001, "PAGADA", "TX-9001")
    assert resultado["success"] is False and resultado["message"] == "Transición de estado no permitida"
    assert sesion.query(NotificacionOrden).one().confirmado is False
    assert "ALERTA COM-09" in caplog.text


def test_reintentaTresVecesConBackoffYResponde503(sesion, servicio, monkeypatch):
    llamadas = []

    def _caido(*args, **kwargs):
        llamadas.append(args)
        raise OrdenesNoDisponible("MOD-04 caído")

    monkeypatch.setattr(servicio.clienteOrdenes, "actualizarEstado", _caido)
    with pytest.raises(ErrorAplicacion) as error:
        servicio.notificarResultado(sesion, 5001, "PAGADA", "TX-9001")
    assert error.value.codigoHttp == 503
    assert error.value.mensaje == "MOD-04 no disponible tras los reintentos"
    assert len(llamadas) == 3 and servicio.esperas == [0.2, 0.4]


def test_recuperaSiMod04RespondeEnUnReintento(sesion, servicio, monkeypatch):
    crearOrdenPrueba(sesion, 5001, estado="PROCESANDO")
    original = servicio.clienteOrdenes.actualizarEstado
    intentos = {"n": 0}

    def _intermitente(*args, **kwargs):
        intentos["n"] += 1
        if intentos["n"] == 1:
            raise OrdenesNoDisponible("timeout")
        return original(*args, **kwargs)

    monkeypatch.setattr(servicio.clienteOrdenes, "actualizarEstado", _intermitente)
    assert servicio.notificarResultado(sesion, 5001, "PAGADA", "TX-9001")["data"]["confirmado"] is True
