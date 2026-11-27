"""Pruebas de HU-47: Consultar detalle de compra pasada (GET /api/v1/biblioteca/compras/{ordenId})."""
import pytest
from sqlalchemy.exc import OperationalError

from app.repositories.repositorio_despacho import RepositorioDespacho
from tests.apoyo_modulos import crearUsuario, despacharOrden, limpiarSimulaciones
from tests.conftest import encabezadoAuth


@pytest.fixture(autouse=True)
def _limpiar():
    limpiarSimulaciones()


def test_flujoExitoso(cliente, sesion):
    usuario = crearUsuario(sesion)
    despacharOrden(cliente, sesion, usuario.id)
    respuesta = cliente.get("/api/v1/biblioteca/compras/5001", headers=encabezadoAuth(usuario.id))
    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["message"] == "Consulta de compra exitosa"
    datos = cuerpo["data"]
    assert (datos["ordenId"], datos["moneda"], datos["total"], datos["tasaCambio"], datos["transaccionId"],
            datos["estadoOrden"]) == (5001, "COP", 238000, 1, "TX-5001", "ENTREGADA")
    assert datos["items"] == [{"juegoId": 101, "titulo": "Aurora Quest", "precioUnitario": 238000,
                               "claveLicencia": "*****-*****-*****"}]


def test_error404CompraAjena(cliente, sesion):
    usuario = crearUsuario(sesion)
    despacharOrden(cliente, sesion, usuario.id)
    respuesta = cliente.get("/api/v1/biblioteca/compras/5001", headers=encabezadoAuth(999))
    assert respuesta.status_code == 404
    assert respuesta.json() == {"message": "La compra indicada no existe", "data": None, "success": False}


def test_error401SinToken(cliente):
    assert cliente.get("/api/v1/biblioteca/compras/5001").status_code == 401


def test_error503BaseDeDatos(cliente, monkeypatch):
    def _falla(*_args, **_kwargs):
        raise OperationalError("SELECT", {}, Exception("BD caída"))

    monkeypatch.setattr(RepositorioDespacho, "obtenerRegistroCompra", _falla)
    respuesta = cliente.get("/api/v1/biblioteca/compras/5001", headers=encabezadoAuth(1))
    assert respuesta.status_code == 503
    assert respuesta.json()["message"] == "No fue posible consultar la compra"
