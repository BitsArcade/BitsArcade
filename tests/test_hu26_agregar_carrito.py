"""Pruebas de HU-26: Agregar juego al carrito de compras (POST /api/v1/carrito/items)."""
import pytest
from sqlalchemy.exc import OperationalError

from app.core.respuestas import ErrorAplicacion
from app.domain.carrito import validarLimitePreventa
from app.repositories.repositorio_carrito import RepositorioCarrito
from app.services.cliente_inventario import ClienteInventario, InventarioNoDisponible
from app.services.servicio_carrito import ClienteOrdenes
from tests.conftest import encabezadoAuth, generarToken

URL = "/api/v1/carrito/items"


def test_flujoExitoso(cliente, crearJuego, crearClaves):
    juego = crearJuego(costoAdquisicion=160000)
    crearClaves(juego.id, disponibles=5)
    respuesta = cliente.post(URL, json={"juegoId": juego.id, "cantidad": 1}, headers=encabezadoAuth(7))
    assert respuesta.status_code == 201
    cuerpo = respuesta.json()
    assert cuerpo["success"] is True
    assert cuerpo["message"] == "Juego agregado al carrito"
    datos = cuerpo["data"]
    assert set(datos) == {"carritoId", "items", "subtotal", "moneda"}
    assert datos["items"] == [{"itemId": datos["items"][0]["itemId"], "juegoId": juego.id,
                               "titulo": "Aurora Quest", "cantidad": 1, "precioUnitario": 238000}]
    assert datos["subtotal"] == 238000 and datos["moneda"] == "COP"


def test_acumulaCantidadSiElJuegoYaEsta(cliente, crearJuego, crearClaves):
    juego = crearJuego()
    crearClaves(juego.id, disponibles=5)
    cliente.post(URL, json={"juegoId": juego.id, "cantidad": 1}, headers=encabezadoAuth())
    datos = cliente.post(URL, json={"juegoId": juego.id, "cantidad": 2}, headers=encabezadoAuth()).json()["data"]
    assert len(datos["items"]) == 1
    assert datos["items"][0]["cantidad"] == 3
    assert datos["subtotal"] == 238000 * 3


def test_usuarioIdSaleDelJwtCarritosSeparados(cliente, crearJuego, crearClaves):
    juego = crearJuego()
    crearClaves(juego.id, disponibles=5)
    carrito1 = cliente.post(URL, json={"juegoId": juego.id}, headers=encabezadoAuth(1)).json()["data"]
    carrito2 = cliente.post(URL, json={"juegoId": juego.id}, headers=encabezadoAuth(2)).json()["data"]
    assert carrito1["carritoId"] != carrito2["carritoId"]
    assert carrito2["items"][0]["cantidad"] == 1


def test_error400CantidadCero(cliente, crearJuego):
    juego = crearJuego()
    respuesta = cliente.post(URL, json={"juegoId": juego.id, "cantidad": 0}, headers=encabezadoAuth())
    assert respuesta.status_code == 400
    assert respuesta.json() == {"message": "cantidad debe ser mayor o igual a 1", "data": None, "success": False}


def test_error404JuegoInexistente(cliente):
    respuesta = cliente.post(URL, json={"juegoId": 9999, "cantidad": 1}, headers=encabezadoAuth())
    assert respuesta.status_code == 404
    assert respuesta.json() == {"message": "El juego indicado no existe", "data": None, "success": False}


def test_error404JuegoInactivo(cliente, crearJuego, crearClaves):
    juego = crearJuego(estado="INACTIVO")
    crearClaves(juego.id, disponibles=5)
    respuesta = cliente.post(URL, json={"juegoId": juego.id, "cantidad": 1}, headers=encabezadoAuth())
    assert respuesta.status_code == 404


def test_error409StockInsuficiente(cliente, crearJuego, crearClaves):
    juego = crearJuego()
    crearClaves(juego.id, disponibles=2, estadoExtra="VENDIDA", cantidadExtra=5)
    respuesta = cliente.post(URL, json={"juegoId": juego.id, "cantidad": 3}, headers=encabezadoAuth())
    assert respuesta.status_code == 409
    assert respuesta.json() == {
        "message": "Stock insuficiente para la cantidad solicitada", "data": None, "success": False,
    }


def test_error409StockConsideraCantidadAcumulada(cliente, crearJuego, crearClaves):
    juego = crearJuego()
    crearClaves(juego.id, disponibles=2)
    assert cliente.post(URL, json={"juegoId": juego.id, "cantidad": 2}, headers=encabezadoAuth()).status_code == 201
    assert cliente.post(URL, json={"juegoId": juego.id, "cantidad": 1}, headers=encabezadoAuth()).status_code == 409


def test_error409PreventaCantidad2(cliente, crearJuego, crearClaves):
    juego = crearJuego(estado="PREVENTA")
    crearClaves(juego.id, disponibles=10)
    respuesta = cliente.post(URL, json={"juegoId": juego.id, "cantidad": 2}, headers=encabezadoAuth())
    assert respuesta.status_code == 409
    assert respuesta.json() == {
        "message": "Solo se permite adquirir una licencia por título en preventa", "data": None, "success": False,
    }


def test_error409PreventaYaEnCarrito(cliente, crearJuego, crearClaves):
    juego = crearJuego(estado="PREVENTA")
    crearClaves(juego.id, disponibles=10)
    assert cliente.post(URL, json={"juegoId": juego.id, "cantidad": 1}, headers=encabezadoAuth()).status_code == 201
    assert cliente.post(URL, json={"juegoId": juego.id, "cantidad": 1}, headers=encabezadoAuth()).status_code == 409


def test_error409PreventaYaCompradoEnOrdenPrevia(cliente, crearJuego, crearClaves, monkeypatch):
    juego = crearJuego(estado="PREVENTA")
    crearClaves(juego.id, disponibles=10)
    monkeypatch.setattr(ClienteOrdenes, "contarLicenciasNoCanceladas", lambda self, s, u, j: 1)
    respuesta = cliente.post(URL, json={"juegoId": juego.id, "cantidad": 1}, headers=encabezadoAuth())
    assert respuesta.status_code == 409


def test_dominioRn05():
    validarLimitePreventa("PREVENTA", 1, 0)
    validarLimitePreventa("ACTIVO", 5, 3)
    with pytest.raises(ErrorAplicacion):
        validarLimitePreventa("PREVENTA", 1, 1)


@pytest.mark.parametrize("encabezados", [
    {},
    {"Authorization": "Bearer token-invalido"},
    {"Authorization": f"Bearer {generarToken(minutos=-1)}"},
    {"Authorization": f"Bearer {generarToken(clave='otra-clave')}"},
])
def test_error401TokenAusenteInvalidoOExpirado(cliente, crearJuego, encabezados):
    juego = crearJuego()
    respuesta = cliente.post(URL, json={"juegoId": juego.id, "cantidad": 1}, headers=encabezados)
    assert respuesta.status_code == 401
    assert respuesta.json() == {"message": "Token inválido, expirado o ausente", "data": None, "success": False}


def test_error503Com12NoResponde(cliente, crearJuego, monkeypatch):
    juego = crearJuego()

    def _falla(self, sesion, juegoId):
        raise InventarioNoDisponible("MOD-03 caído")

    monkeypatch.setattr(ClienteInventario, "contarDisponibles", _falla)
    respuesta = cliente.post(URL, json={"juegoId": juego.id, "cantidad": 1}, headers=encabezadoAuth())
    assert respuesta.status_code == 503


def test_error503BaseDeDatos(cliente, crearJuego, crearClaves, monkeypatch):
    juego = crearJuego()
    crearClaves(juego.id, disponibles=5)

    def _falla(*_args, **_kwargs):
        raise OperationalError("INSERT", {}, Exception("BD caída"))

    monkeypatch.setattr(RepositorioCarrito, "obtenerCarritoActivo", _falla)
    respuesta = cliente.post(URL, json={"juegoId": juego.id, "cantidad": 1}, headers=encabezadoAuth())
    assert respuesta.status_code == 503
    assert respuesta.json() == {
        "message": "No fue posible agregar el juego al carrito", "data": None, "success": False,
    }
