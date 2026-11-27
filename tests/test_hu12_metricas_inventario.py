"""Pruebas de HU-12: Consultar y auditar inventario de claves (GET /api/v1/inventario/claves/metricas)."""
from sqlalchemy.exc import OperationalError

from app.repositories.repositorio_inventario import RepositorioInventario
from tests.apoyo_modulos import cargarClaves, reservar
from tests.conftest import encabezadoAuth

URL = "/api/v1/inventario/claves/metricas"
ADMIN = encabezadoAuth(1, rol="ADMIN")


def test_flujoExitosoMetricasPorJuegoYEstado(cliente, sesion):
    cargarClaves(sesion, 101, ["AAAAA-00001", "AAAAA-00002", "AAAAA-00003"])
    cargarClaves(sesion, 202, ["BBBBB-00001"])
    reservar(sesion, ordenId=1, juegoId=101, cantidad=1)
    respuesta = cliente.get(URL, headers=ADMIN)
    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["message"] == "Consulta de inventario exitosa"
    assert cuerpo["data"]["porJuego"] == [
        {"juegoId": 101, "plataforma": "PC", "disponibles": 2, "reservadas": 1, "vendidas": 0},
        {"juegoId": 202, "plataforma": "PC", "disponibles": 1, "reservadas": 0, "vendidas": 0},
    ]
    assert cuerpo["data"]["totales"] == {"disponibles": 3, "reservadas": 1, "vendidas": 0}
    assert "AAAAA" not in respuesta.text


def test_filtroPorJuegoId(cliente, sesion):
    cargarClaves(sesion, 101, ["AAAAA-00001"])
    cargarClaves(sesion, 202, ["BBBBB-00001"])
    datos = cliente.get(URL, params={"juegoId": "202"}, headers=ADMIN).json()["data"]
    assert [g["juegoId"] for g in datos["porJuego"]] == [202]


def test_sinDatos(cliente):
    respuesta = cliente.get(URL, headers=ADMIN)
    assert respuesta.status_code == 200
    assert respuesta.json() == {
        "message": "No existen claves registradas",
        "data": {"porJuego": [], "totales": {"disponibles": 0, "reservadas": 0, "vendidas": 0}},
        "success": False,
    }


def test_error400JuegoIdNoNumerico(cliente):
    respuesta = cliente.get(URL, params={"juegoId": "abc"}, headers=ADMIN)
    assert respuesta.status_code == 400
    assert respuesta.json()["message"] == "juegoId debe ser numérico"


def test_error401Y403(cliente):
    assert cliente.get(URL).status_code == 401
    assert cliente.get(URL, headers=encabezadoAuth(2)).status_code == 403


def test_error503BaseDeDatos(cliente, monkeypatch):
    def _falla(*_args, **_kwargs):
        raise OperationalError("SELECT", {}, Exception("BD caída"))

    monkeypatch.setattr(RepositorioInventario, "contarPorJuegoYEstado", _falla)
    respuesta = cliente.get(URL, headers=ADMIN)
    assert respuesta.status_code == 503
    assert respuesta.json()["message"] == "No fue posible consultar el inventario"
