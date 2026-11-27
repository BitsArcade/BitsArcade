"""Pruebas de HU-05: Inactivar método de pago (PATCH /api/v1/parametrizacion/metodos-pago/{id}/inactivar)."""
from sqlalchemy.exc import OperationalError

from app.repositories.repositorio_parametros import RepositorioParametros
from tests.conftest import encabezadoAuth

ADMIN = encabezadoAuth(1, rol="ADMIN")


def _url(metodoPagoId):
    return f"/api/v1/parametrizacion/metodos-pago/{metodoPagoId}/inactivar"


def test_flujoExitosoInactivaTarjeta(cliente):
    respuesta = cliente.patch(_url(2), headers=ADMIN)
    assert respuesta.status_code == 200
    assert respuesta.json() == {
        "message": "Método de pago inactivado exitosamente",
        "data": {"metodoPagoId": 2, "nombre": "Tarjeta de crédito", "estado": "INACTIVO"},
        "success": True,
    }


def test_error409YaInactivo(cliente):
    cliente.patch(_url(2), headers=ADMIN)
    respuesta = cliente.patch(_url(2), headers=ADMIN)
    assert respuesta.status_code == 409
    assert respuesta.json()["message"] == "El método de pago ya se encuentra inactivo"


def test_error404MetodoInexistente(cliente):
    respuesta = cliente.patch(_url(999), headers=ADMIN)
    assert respuesta.status_code == 404
    assert respuesta.json()["message"] == "El método de pago indicado no existe"


def test_error401Y403(cliente):
    assert cliente.patch(_url(2)).status_code == 401
    assert cliente.patch(_url(2), headers=encabezadoAuth(5)).status_code == 403


def test_error503BaseDeDatos(cliente, monkeypatch):
    def _falla(*_args, **_kwargs):
        raise OperationalError("SELECT", {}, Exception("BD caída"))

    monkeypatch.setattr(RepositorioParametros, "obtenerMetodoPago", _falla)
    respuesta = cliente.patch(_url(2), headers=ADMIN)
    assert respuesta.status_code == 503
    assert respuesta.json()["message"] == "No fue posible inactivar el método de pago"
