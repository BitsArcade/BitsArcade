"""Pruebas de HU-30: Vaciar carrito de compras (DELETE /api/v1/carrito)."""
from sqlalchemy.exc import OperationalError

from app.repositories.repositorio_carrito import RepositorioCarrito
from tests.apoyo_modulos import agregarAlCarrito
from tests.conftest import encabezadoAuth

URL = "/api/v1/carrito"


def test_flujoExitosoVaciaTodosLosItems(cliente, crearJuego, crearClaves):
    juego = crearJuego()
    otro = crearJuego(titulo="Neon Drift")
    crearClaves(juego.id, disponibles=3)
    crearClaves(otro.id, disponibles=3)
    agregarAlCarrito(cliente, 1, juego.id, 2)
    agregarAlCarrito(cliente, 1, otro.id, 1)
    respuesta = cliente.delete(URL, headers=encabezadoAuth())
    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["message"] == "Carrito vaciado exitosamente" and cuerpo["success"] is True
    assert cuerpo["data"]["items"] == [] and cuerpo["data"]["subtotal"] == 0 and cuerpo["data"]["moneda"] == "COP"
    assert cliente.get(URL, headers=encabezadoAuth()).json()["data"]["items"] == []


def test_carritoYaVacioEsIdempotente(cliente):
    primera = cliente.delete(URL, headers=encabezadoAuth())
    segunda = cliente.delete(URL, headers=encabezadoAuth())
    assert primera.status_code == segunda.status_code == 200
    assert segunda.json()["data"]["items"] == []


def test_soloVaciaElCarritoDelPropioUsuario(cliente, crearJuego, crearClaves):
    juego = crearJuego()
    crearClaves(juego.id, disponibles=3)
    agregarAlCarrito(cliente, 2, juego.id, 1)
    cliente.delete(URL, headers=encabezadoAuth(1))
    assert len(cliente.get(URL, headers=encabezadoAuth(2)).json()["data"]["items"]) == 1


def test_error401SinToken(cliente):
    respuesta = cliente.delete(URL)
    assert respuesta.status_code == 401
    assert respuesta.json()["message"] == "Token inválido, expirado o ausente"


def test_error503BaseDeDatos(cliente, monkeypatch):
    def _falla(*_args, **_kwargs):
        raise OperationalError("SELECT", {}, Exception("BD caída"))

    monkeypatch.setattr(RepositorioCarrito, "obtenerCarritoActivo", _falla)
    respuesta = cliente.delete(URL, headers=encabezadoAuth())
    assert respuesta.status_code == 503
    assert respuesta.json() == {"message": "No fue posible vaciar el carrito", "data": None, "success": False}
