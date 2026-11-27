"""Pruebas de HU-02: Consultar monedas activas (GET /api/v1/parametrizacion/monedas)."""
from sqlalchemy.exc import OperationalError

from app.repositories.repositorio_parametros import RepositorioParametros
from tests.conftest import encabezadoAuth

URL = "/api/v1/parametrizacion/monedas"


def test_flujoExitosoEndpointPublico(cliente):
    cliente.post(URL, json={"nombre": "Dólar estadounidense", "codigoIso": "USD"}, headers=encabezadoAuth(1, rol="ADMIN"))
    respuesta = cliente.get(URL, params={"estado": "ACTIVO"})
    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["message"] == "Consulta de monedas exitosa" and cuerpo["success"] is True
    assert {"codigoIso": "USD", "nombre": "Dólar estadounidense"} in cuerpo["data"]
    assert {"codigoIso": "COP", "nombre": "Peso colombiano"} in cuerpo["data"]   # Semilla TT-02
    assert all(set(m) == {"codigoIso", "nombre"} for m in cuerpo["data"])


def test_sinMonedasInactivasRetornaListaVacia(cliente):
    respuesta = cliente.get(URL, params={"estado": "INACTIVO"})
    assert respuesta.status_code == 200
    assert respuesta.json()["data"] == [] and respuesta.json()["success"] is False


def test_sinMonedasActivas(cliente, monkeypatch):
    monkeypatch.setattr(RepositorioParametros, "listarMonedasPorEstado", lambda *_a, **_k: [])
    respuesta = cliente.get(URL)
    assert respuesta.json() == {"message": "No existen monedas activas", "data": [], "success": False}


def test_error400FiltroInvalido(cliente):
    respuesta = cliente.get(URL, params={"estado": "XYZ"})
    assert respuesta.status_code == 400
    assert respuesta.json()["message"] == "El valor del filtro estado no es válido. Use ACTIVO o INACTIVO"


def test_error503BaseDeDatos(cliente, monkeypatch):
    def _falla(*_args, **_kwargs):
        raise OperationalError("SELECT", {}, Exception("BD caída"))

    monkeypatch.setattr(RepositorioParametros, "listarMonedasPorEstado", _falla)
    respuesta = cliente.get(URL)
    assert respuesta.status_code == 503
    assert respuesta.json()["message"] == "No fue posible consultar las monedas"
