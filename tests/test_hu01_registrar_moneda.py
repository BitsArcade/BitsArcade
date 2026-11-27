"""Pruebas de HU-01: Registrar moneda (POST /api/v1/parametrizacion/monedas)."""
from sqlalchemy.exc import OperationalError

from app.repositories.repositorio_parametros import RepositorioParametros
from tests.conftest import encabezadoAuth

URL = "/api/v1/parametrizacion/monedas"
ADMIN = encabezadoAuth(1, rol="ADMIN")


def test_flujoExitosoRegistraMonedaActiva(cliente):
    respuesta = cliente.post(URL, json={"nombre": "Dólar estadounidense", "codigoIso": "USD"}, headers=ADMIN)
    assert respuesta.status_code == 201
    cuerpo = respuesta.json()
    assert cuerpo["message"] == "Moneda registrada exitosamente" and cuerpo["success"] is True
    assert cuerpo["data"]["codigoIso"] == "USD" and cuerpo["data"]["estado"] == "ACTIVO"
    assert isinstance(cuerpo["data"]["monedaId"], int)


def test_error400CodigoIsoInvalido(cliente):
    respuesta = cliente.post(URL, json={"nombre": "Moneda", "codigoIso": "co1"}, headers=ADMIN)
    assert respuesta.status_code == 400
    assert respuesta.json() == {"message": "Código ISO inválido. Debe tener 3 letras mayúsculas (ISO 4217)",
                                "data": None, "success": False}


def test_error409MonedaDuplicada(cliente):
    cliente.get("/api/v1/parametrizacion/monedas")  # TT-02 siembra COP
    respuesta = cliente.post(URL, json={"nombre": "Peso colombiano", "codigoIso": "COP"}, headers=ADMIN)
    assert respuesta.status_code == 409
    assert respuesta.json()["message"] == "La moneda con código ISO COP ya existe"


def test_error401SinToken(cliente):
    respuesta = cliente.post(URL, json={"nombre": "Dólar", "codigoIso": "USD"})
    assert respuesta.status_code == 401
    assert respuesta.json()["message"] == "Token inválido, expirado o ausente"


def test_error403RolCliente(cliente):
    respuesta = cliente.post(URL, json={"nombre": "Dólar", "codigoIso": "USD"}, headers=encabezadoAuth(5))
    assert respuesta.status_code == 403
    assert respuesta.json()["message"] == "No cuenta con permisos para realizar esta operación"


def test_error503BaseDeDatos(cliente, monkeypatch):
    def _falla(*_args, **_kwargs):
        raise OperationalError("SELECT", {}, Exception("BD caída"))

    monkeypatch.setattr(RepositorioParametros, "obtenerMonedaPorCodigo", _falla)
    respuesta = cliente.post(URL, json={"nombre": "Dólar", "codigoIso": "USD"}, headers=ADMIN)
    assert respuesta.status_code == 503
    assert respuesta.json()["message"] == "No fue posible registrar la moneda"
