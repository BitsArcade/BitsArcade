"""Pruebas de HU-39: Registrar comprobante digital de transacción (GET /api/v1/pagos/{id}/comprobante)."""
import pytest
from sqlalchemy.exc import OperationalError

from app.repositories.repositorio_pagos import RepositorioPagos
from tests.apoyo_modulos import crearOrdenPrueba, cuerpoFirmado, limpiarSimulaciones
from tests.conftest import encabezadoAuth


@pytest.fixture(autouse=True)
def _limpiar():
    limpiarSimulaciones()


def _transaccion(cliente, sesion, resultado="APROBADO"):
    crearOrdenPrueba(sesion, 5001, usuarioId=77, total=238000, items=[])
    transaccionId = cliente.post("/api/v1/pagos", json={"ordenId": 5001},
                                  headers=encabezadoAuth(77)).json()["data"]["transaccionId"]
    cuerpo, encabezados = cuerpoFirmado({"transaccionId": transaccionId, "ordenId": 5001, "estado": resultado,
                                          "referenciaPasarela": "SIM-77123", "monto": 238000, "moneda": "COP"})
    cliente.post("/api/v1/pagos/notificacion-pasarela", content=cuerpo, headers=encabezados)
    return transaccionId


def test_flujoExitosoComprobanteGeneradoAutomaticamente(cliente, sesion):
    transaccionId = _transaccion(cliente, sesion)
    respuesta = cliente.get(f"/api/v1/pagos/{transaccionId}/comprobante", headers=encabezadoAuth(77))
    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["message"] == "Consulta de comprobante exitosa"
    datos = cuerpo["data"]
    assert datos["comprobanteId"] == transaccionId.replace("TX-", "CMP-")
    assert datos["transaccionId"] == transaccionId and datos["ordenId"] == 5001
    assert datos["monto"] == 238000 and datos["moneda"] == "COP" and datos["tasaCambio"] == 1
    assert datos["referenciaPasarela"] == "SIM-77123" and datos["fecha"].endswith("Z")


def test_error404TransaccionFallida(cliente, sesion):
    transaccionId = _transaccion(cliente, sesion, "RECHAZADO")
    respuesta = cliente.get(f"/api/v1/pagos/{transaccionId}/comprobante", headers=encabezadoAuth(77))
    assert respuesta.status_code == 404
    assert respuesta.json() == {"message": "No existe comprobante para la transacción indicada", "data": None,
                                "success": False}


def test_error404TransaccionAjena(cliente, sesion):
    transaccionId = _transaccion(cliente, sesion)
    assert cliente.get(f"/api/v1/pagos/{transaccionId}/comprobante", headers=encabezadoAuth(5)).status_code == 404


def test_error401SinToken(cliente):
    assert cliente.get("/api/v1/pagos/TX-1/comprobante").status_code == 401


def test_error503BaseDeDatos(cliente, monkeypatch):
    def _falla(*_args, **_kwargs):
        raise OperationalError("SELECT", {}, Exception("BD caída"))

    monkeypatch.setattr(RepositorioPagos, "obtenerComprobante", _falla)
    respuesta = cliente.get("/api/v1/pagos/TX-1/comprobante", headers=encabezadoAuth(77))
    assert respuesta.status_code == 503
    assert respuesta.json()["message"] == "No fue posible consultar el comprobante"
