"""Pruebas de HU-36: Transmitir cobro a la pasarela de pago simulada (POST /api/v1/pagos)."""
import pytest
from sqlalchemy.exc import OperationalError

from app.api.pagos import servicioPagos
from app.repositories.repositorio_pagos import RepositorioPagos
from app.services.cliente_pasarela import COBROS_SIMULADOS
from tests.apoyo_modulos import obtenerOrden, crearOrdenPrueba, limpiarSimulaciones
from tests.conftest import encabezadoAuth

URL = "/api/v1/pagos"


@pytest.fixture(autouse=True)
def _limpiar():
    limpiarSimulaciones()


def test_flujoExitosoPagoEnProceso(cliente, sesion):
    crearOrdenPrueba(sesion, 5001, usuarioId=77, total=238000, tasaCambio=1)
    respuesta = cliente.post(URL, json={"ordenId": 5001, "metodoPagoId": 2}, headers=encabezadoAuth(77))
    assert respuesta.status_code == 202
    cuerpo = respuesta.json()
    assert cuerpo["message"] == "Pago en proceso" and cuerpo["success"] is True
    assert cuerpo["data"]["ordenId"] == 5001 and cuerpo["data"]["estado"] == "EN_PROCESO"
    assert cuerpo["data"]["transaccionId"].startswith("TX-")
    assert obtenerOrden(sesion, 5001).estado == "PROCESANDO"          # COM-09 / HU-35
    enviado = COBROS_SIMULADOS["5001"]["payload"]                     # Idempotency-Key = ordenId
    assert enviado["tasaCambio"] == 1 and enviado["total"] == 238000  # Tasa congelada (RN-09)


def test_idempotenteMismoOrdenIdMismaTransaccion(cliente, sesion):
    crearOrdenPrueba(sesion, 5001, usuarioId=77)
    primera = cliente.post(URL, json={"ordenId": 5001, "metodoPagoId": 2}, headers=encabezadoAuth(77)).json()
    segunda = cliente.post(URL, json={"ordenId": 5001, "metodoPagoId": 2}, headers=encabezadoAuth(77)).json()
    assert primera["data"]["transaccionId"] == segunda["data"]["transaccionId"]


def test_error404OrdenAjena(cliente, sesion):
    crearOrdenPrueba(sesion, 5001, usuarioId=77)
    respuesta = cliente.post(URL, json={"ordenId": 5001, "metodoPagoId": 2}, headers=encabezadoAuth(78))
    assert respuesta.status_code == 404
    assert respuesta.json() == {"message": "La orden indicada no existe", "data": None, "success": False}


def test_error409OrdenCancelada(cliente, sesion):
    crearOrdenPrueba(sesion, 5001, usuarioId=77, estado="CANCELADA")
    respuesta = cliente.post(URL, json={"ordenId": 5001}, headers=encabezadoAuth(77))
    assert respuesta.status_code == 409
    assert respuesta.json()["message"] == "La orden no está disponible para pago"


def test_error409OrdenPorExpirar(cliente, sesion):
    crearOrdenPrueba(sesion, 5001, usuarioId=77, minutosVigencia=1)
    respuesta = cliente.post(URL, json={"ordenId": 5001}, headers=encabezadoAuth(77))
    assert respuesta.status_code == 409
    assert respuesta.json()["message"] == "La orden está por expirar. Genera una nueva orden"


def test_error504PasarelaSinRespuesta(cliente, monkeypatch, sesion):
    crearOrdenPrueba(sesion, 5001, usuarioId=77)
    monkeypatch.setattr(servicioPagos.clientePasarela, "simularTimeout", True)
    respuesta = cliente.post(URL, json={"ordenId": 5001}, headers=encabezadoAuth(77))
    assert respuesta.status_code == 504
    assert respuesta.json()["message"] == "La pasarela de pagos no respondió"


def test_error401SinToken(cliente):
    assert cliente.post(URL, json={"ordenId": 5001}).status_code == 401


def test_error503BaseDeDatos(cliente, monkeypatch):
    def _falla(*_args, **_kwargs):
        raise OperationalError("SELECT", {}, Exception("BD caída"))

    monkeypatch.setattr(RepositorioPagos, "obtenerTransaccionPorOrden", _falla)
    respuesta = cliente.post(URL, json={"ordenId": 5001}, headers=encabezadoAuth(77))
    assert respuesta.status_code == 503
    assert respuesta.json()["message"] == "No fue posible iniciar el pago"
