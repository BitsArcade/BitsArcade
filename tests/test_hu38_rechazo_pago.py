"""Pruebas de HU-38: Gestionar rechazo de pago y cancelación de orden."""
import pytest
from sqlalchemy.exc import OperationalError

from app.repositories.repositorio_pagos import RepositorioPagos
from app.domain.inventario import ClaveLicencia
from tests.apoyo_modulos import obtenerOrden, cargarClaves, reservar, crearOrdenPrueba, cuerpoFirmado, limpiarSimulaciones
from tests.conftest import encabezadoAuth

URL = "/api/v1/pagos/notificacion-pasarela"


@pytest.fixture(autouse=True)
def _limpiar():
    limpiarSimulaciones()


@pytest.fixture
def pagoEnProceso(cliente, sesion):
    cargarClaves(sesion, 101, ["AAAAA-BBBBB-CCCCC"])
    [reservaId] = reservar(sesion, ordenId=5001, juegoId=101)
    crearOrdenPrueba(sesion, 5001, usuarioId=77, items=[{"juegoId": 101, "reservaId": reservaId, "precioUnitario": 238000}])
    return cliente.post("/api/v1/pagos", json={"ordenId": 5001}, headers=encabezadoAuth(77)).json()["data"]["transaccionId"]


def _notificarPasarela(cliente, transaccionId, estado="RECHAZADO", secreto=None):
    cuerpo, encabezados = cuerpoFirmado(
        {"transaccionId": transaccionId, "ordenId": 5001, "estado": estado, "motivo": "FONDOS_INSUFICIENTES"}, secreto)
    return cliente.post(URL, content=cuerpo, headers=encabezados)


def test_flujoExitosoRechazoCancelaOrden(cliente, sesion, pagoEnProceso):
    respuesta = _notificarPasarela(cliente, pagoEnProceso)
    assert respuesta.status_code == 200
    assert respuesta.json() == {
        "message": "Pago rechazado procesado",
        "data": {"transaccionId": pagoEnProceso, "estado": "FALLIDA", "estadoOrden": "CANCELADA",
                 "mensajeUsuario": "El pago fue rechazado. Genera una nueva orden para reintentar."},
        "success": True,
    }
    assert obtenerOrden(sesion, 5001).estado == "CANCELADA"
    # MOD-04 libera la reserva al cancelar (RN-06, COM-13): la clave vuelve a DISPONIBLE
    clave = sesion.query(ClaveLicencia).one()
    assert clave.estado == "DISPONIBLE"


def test_expiradoRegistraTransaccionExpirada(cliente, pagoEnProceso):
    assert _notificarPasarela(cliente, pagoEnProceso, "EXPIRADO").json()["data"]["estado"] == "EXPIRADA"


def test_consultaDeEstadoPorElUsuario(cliente, pagoEnProceso):
    _notificarPasarela(cliente, pagoEnProceso)
    respuesta = cliente.get(f"/api/v1/pagos/{pagoEnProceso}/estado", headers=encabezadoAuth(77))
    assert respuesta.status_code == 200
    datos = respuesta.json()["data"]
    assert datos["estado"] == "FALLIDA" and datos["estadoOrden"] == "CANCELADA"
    assert datos["mensajeUsuario"].startswith("El pago fue rechazado")
    assert cliente.get(f"/api/v1/pagos/{pagoEnProceso}/estado", headers=encabezadoAuth(5)).status_code == 404


def test_error401FirmaInvalida(cliente, pagoEnProceso):
    assert _notificarPasarela(cliente, pagoEnProceso, secreto="malo").status_code == 401


def test_error404TransaccionDesconocida(cliente):
    assert _notificarPasarela(cliente, "TX-NADA").status_code == 404


def test_error409AprobadaRecibeDeclined(cliente, sesion, pagoEnProceso):
    from app.domain.pagos import Transaccion

    transaccion = sesion.query(Transaccion).one()
    transaccion.estado = "APROBADA"
    sesion.commit()
    respuesta = _notificarPasarela(cliente, pagoEnProceso)
    assert respuesta.status_code == 409
    assert respuesta.json()["message"] == "La transacción ya fue resuelta con otro estado"


def test_error503BaseDeDatos(cliente, monkeypatch):
    def _falla(*_args, **_kwargs):
        raise OperationalError("SELECT", {}, Exception("BD caída"))

    monkeypatch.setattr(RepositorioPagos, "obtenerTransaccion", _falla)
    respuesta = _notificarPasarela(cliente, "TX-1")
    assert respuesta.status_code == 503
    assert respuesta.json()["message"] == "No fue posible procesar el rechazo del pago"
