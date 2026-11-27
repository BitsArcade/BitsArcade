"""Pruebas de HU-37: Recibir y procesar aprobación de pago (POST /api/v1/pagos/notificacion-pasarela)."""
import pytest
from sqlalchemy.exc import OperationalError

from app.domain.despacho import AsignacionLicencia
from app.domain.pagos import Comprobante
from app.repositories.repositorio_pagos import RepositorioPagos
from tests.apoyo_modulos import (
    obtenerOrden,
    cargarClaves,
    crearOrdenPrueba,
    crearUsuario,
    cuerpoFirmado,
    limpiarSimulaciones,
    reservar,
)
from tests.conftest import encabezadoAuth

URL = "/api/v1/pagos/notificacion-pasarela"


@pytest.fixture(autouse=True)
def _limpiar():
    limpiarSimulaciones()


@pytest.fixture
def pagoEnProceso(cliente, sesion):
    usuario = crearUsuario(sesion)
    cargarClaves(sesion, 101, ["AAAAA-BBBBB-CCCCC"])
    [reservaId] = reservar(sesion, ordenId=5001, juegoId=101)
    crearOrdenPrueba(sesion, 5001, usuarioId=usuario.id, total=238000, items=[
        {"juegoId": 101, "titulo": "Aurora Quest", "reservaId": reservaId, "precioUnitario": 238000}])
    datos = cliente.post("/api/v1/pagos", json={"ordenId": 5001, "metodoPagoId": 2},
                         headers=encabezadoAuth(usuario.id)).json()["data"]
    return datos["transaccionId"]


def _aprobar(cliente, transaccionId, monto=238000, moneda="COP", secreto=None):
    cuerpo, encabezados = cuerpoFirmado({"transaccionId": transaccionId, "ordenId": 5001, "estado": "APROBADO",
                                          "referenciaPasarela": "SIM-77123", "monto": monto, "moneda": moneda}, secreto)
    return cliente.post(URL, content=cuerpo, headers=encabezados)


def test_flujoExitosoPagadaYDespachoActivado(cliente, sesion, pagoEnProceso):
    respuesta = _aprobar(cliente, pagoEnProceso)
    assert respuesta.status_code == 200
    assert respuesta.json() == {
        "message": "Pago aprobado procesado",
        "data": {"transaccionId": pagoEnProceso, "estado": "APROBADA", "estadoOrden": "PAGADA",
                 "estadoDespacho": "ACTIVADO"},
        "success": True,
    }
    assert sesion.query(Comprobante).count() == 1                   # HU-39
    assert sesion.query(AsignacionLicencia).count() == 1            # COM-10 → HU-41
    assert obtenerOrden(sesion, 5001).estado == "ENTREGADA"         # HU-40 → HU-42


def test_idempotentePorTransaccionId(cliente, sesion, pagoEnProceso):
    primera = _aprobar(cliente, pagoEnProceso).json()
    segunda = _aprobar(cliente, pagoEnProceso).json()
    assert primera == segunda
    assert sesion.query(Comprobante).count() == 1


def test_despachoFallidoQuedaRequiereRevision(cliente, sesion, pagoEnProceso, monkeypatch):
    from app.services import clientes_despacho

    def _falla(*_args, **_kwargs):
        raise clientes_despacho.InventarioVentaNoDisponible("COM-07 caído")

    monkeypatch.setattr(clientes_despacho.ClienteInventarioVenta, "confirmarVenta", _falla)
    datos = _aprobar(cliente, pagoEnProceso).json()["data"]
    assert datos["estado"] == "REQUIERE_REVISION"


def test_error401FirmaInvalida(cliente, pagoEnProceso):
    respuesta = _aprobar(cliente, pagoEnProceso, secreto="otro-secreto")
    assert respuesta.status_code == 401
    assert respuesta.json() == {"message": "Firma de la notificación de la pasarela inválida", "data": None, "success": False}


def test_error404TransaccionDesconocida(cliente):
    respuesta = _aprobar(cliente, "TX-NADA")
    assert respuesta.status_code == 404
    assert respuesta.json()["message"] == "La transacción indicada no existe"


def test_error409MontoDistinto(cliente, pagoEnProceso):
    respuesta = _aprobar(cliente, pagoEnProceso, monto=1000)
    assert respuesta.status_code == 409
    assert respuesta.json()["message"] == "El monto o la moneda no coinciden con la orden"


def test_error409TransaccionFallidaRecibeApproved(cliente, pagoEnProceso):
    cuerpo, encabezados = cuerpoFirmado({"transaccionId": pagoEnProceso, "ordenId": 5001, "estado": "RECHAZADO"})
    cliente.post(URL, content=cuerpo, headers=encabezados)
    respuesta = _aprobar(cliente, pagoEnProceso)
    assert respuesta.status_code == 409
    assert respuesta.json()["message"] == "La transacción ya fue resuelta con otro estado"


def test_error503BaseDeDatos(cliente, monkeypatch):
    def _falla(*_args, **_kwargs):
        raise OperationalError("SELECT", {}, Exception("BD caída"))

    monkeypatch.setattr(RepositorioPagos, "obtenerTransaccion", _falla)
    respuesta = _aprobar(cliente, "TX-1")
    assert respuesta.status_code == 503
    assert respuesta.json()["message"] == "No fue posible procesar la aprobación del pago"
