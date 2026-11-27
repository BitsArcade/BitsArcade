"""Pruebas de HU-03: Actualizar tasa de IVA (PUT /api/v1/parametrizacion/impuestos/{impuestoId})."""
from sqlalchemy.exc import OperationalError

from app.repositories.repositorio_parametros import RepositorioParametros
from tests.conftest import encabezadoAuth

URL = "/api/v1/parametrizacion/impuestos/1"
ADMIN = encabezadoAuth(1, rol="ADMIN")


def test_flujoExitosoActualizaIva(cliente):
    respuesta = cliente.put(URL, json={"tasaIva": 16}, headers=ADMIN)
    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["message"] == "Tasa de IVA actualizada exitosamente"
    assert cuerpo["data"]["impuestoId"] == 1 and cuerpo["data"]["nombre"] == "IVA"
    assert cuerpo["data"]["tasaIva"] == 16.0 and cuerpo["data"]["actualizadoEn"].endswith("Z")


def test_com01ExponeLaTasaVigenteEnPorcentaje(cliente):
    cliente.put(URL, json={"tasaIva": 16}, headers=ADMIN)
    datos = cliente.get("/interno/v1/parametrizacion/financieros").json()["data"]
    assert datos == {"tasaIva": 16.0, "margenGanancia": 25.0, "monedaBase": "COP"}


def test_com01SinTokenDeServicio(clienteSinTokenServicio):
    assert clienteSinTokenServicio.get("/interno/v1/parametrizacion/financieros").status_code == 401


def test_error400FueraDeRango(cliente):
    respuesta = cliente.put(URL, json={"tasaIva": 120}, headers=ADMIN)
    assert respuesta.status_code == 400
    assert respuesta.json() == {"message": "La tasa de IVA debe estar entre 0 y 100", "data": None, "success": False}


def test_error404ImpuestoInexistente(cliente):
    respuesta = cliente.put("/api/v1/parametrizacion/impuestos/999", json={"tasaIva": 19}, headers=ADMIN)
    assert respuesta.status_code == 404
    assert respuesta.json()["message"] == "El impuesto indicado no existe"


def test_error401Y403(cliente):
    assert cliente.put(URL, json={"tasaIva": 19}).status_code == 401
    assert cliente.put(URL, json={"tasaIva": 19}, headers=encabezadoAuth(5)).status_code == 403


def test_error503BaseDeDatos(cliente, monkeypatch):
    def _falla(*_args, **_kwargs):
        raise OperationalError("SELECT", {}, Exception("BD caída"))

    monkeypatch.setattr(RepositorioParametros, "obtenerImpuesto", _falla)
    respuesta = cliente.put(URL, json={"tasaIva": 19}, headers=ADMIN)
    assert respuesta.status_code == 503
    assert respuesta.json()["message"] == "No fue posible actualizar la tasa de impuesto"
