"""Pruebas de HU-27: Consultar ítems del carrito activo (GET /api/v1/carrito)."""
from sqlalchemy.exc import OperationalError

from app.repositories.repositorio_carrito import RepositorioCarrito
from app.services.servicio_catalogo import ClienteParametrosFinancieros
from tests.conftest import configurarParametros, encabezadoAuth

URL = "/api/v1/carrito"


def _agregar(cliente, juegoId, cantidad=1, usuarioId=1):
    respuesta = cliente.post("/api/v1/carrito/items", json={"juegoId": juegoId, "cantidad": cantidad},
                             headers=encabezadoAuth(usuarioId))
    assert respuesta.status_code == 201
    return respuesta.json()["data"]


def test_flujoExitoso(cliente, crearJuego, crearClaves):
    juego = crearJuego(costoAdquisicion=160000)
    crearClaves(juego.id, disponibles=5)
    agregado = _agregar(cliente, juego.id)
    respuesta = cliente.get(URL, headers=encabezadoAuth())
    assert respuesta.status_code == 200
    assert respuesta.json() == {
        "message": "Consulta de carrito exitosa",
        "data": {
            "carritoId": agregado["carritoId"],
            "items": [{"itemId": agregado["items"][0]["itemId"], "juegoId": juego.id, "titulo": "Aurora Quest",
                       "cantidad": 1, "precioUnitario": 238000}],
            "subtotal": 238000,
            "moneda": "COP",
        },
        "success": True,
    }


def test_subtotalPreliminarSinDescuentos(cliente, crearJuego, crearClaves):
    juego = crearJuego(costoAdquisicion=160000)
    otro = crearJuego(titulo="Space Racer", costoAdquisicion=80000)  # 119000
    crearClaves(juego.id, disponibles=5)
    crearClaves(otro.id, disponibles=5)
    _agregar(cliente, juego.id, cantidad=3)  # 3 unidades: sin descuento por volumen aquí
    _agregar(cliente, otro.id, cantidad=1)
    datos = cliente.get(URL, headers=encabezadoAuth()).json()["data"]
    assert datos["subtotal"] == 238000 * 3 + 119000


def test_preciosVigentesProvienenDelCatalogo(cliente, crearJuego, crearClaves):
    juego = crearJuego(costoAdquisicion=100000)
    crearClaves(juego.id, disponibles=5)
    _agregar(cliente, juego.id)
    configurarParametros(cliente, margenGanancia=50)
    datos = cliente.get(URL, headers=encabezadoAuth()).json()["data"]
    assert datos["items"][0]["precioUnitario"] == 178500  # 100000 × 1.5 × 1.19


def test_soloVeSuPropioCarrito(cliente, crearJuego, crearClaves):
    juego = crearJuego()
    crearClaves(juego.id, disponibles=5)
    _agregar(cliente, juego.id, usuarioId=1)
    assert cliente.get(URL, headers=encabezadoAuth(2)).json()["data"]["items"] == []


def test_carritoVacio(cliente):
    respuesta = cliente.get(URL, headers=encabezadoAuth())
    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["message"] == "El carrito está vacío"
    assert cuerpo["success"] is False
    assert cuerpo["data"]["items"] == [] and cuerpo["data"]["subtotal"] == 0
    assert cuerpo["data"]["moneda"] == "COP" and isinstance(cuerpo["data"]["carritoId"], int)


def test_error401SinToken(cliente):
    respuesta = cliente.get(URL)
    assert respuesta.status_code == 401
    assert respuesta.json() == {"message": "Token inválido, expirado o ausente", "data": None, "success": False}


def test_error503Com11NoResponde(cliente, crearJuego, crearClaves, monkeypatch):
    juego = crearJuego()
    crearClaves(juego.id, disponibles=5)
    _agregar(cliente, juego.id)

    def _falla(self, sesion):
        raise ConnectionError("MOD-00 caído")

    monkeypatch.setattr(ClienteParametrosFinancieros, "obtenerContratoCom01", _falla)
    respuesta = cliente.get(URL, headers=encabezadoAuth())
    assert respuesta.status_code == 503
    assert respuesta.json() == {"message": "No fue posible obtener los precios vigentes", "data": None, "success": False}


def test_error503BaseDeDatos(cliente, monkeypatch):
    def _falla(*_args, **_kwargs):
        raise OperationalError("SELECT", {}, Exception("BD caída"))

    monkeypatch.setattr(RepositorioCarrito, "obtenerCarritoActivo", _falla)
    respuesta = cliente.get(URL, headers=encabezadoAuth())
    assert respuesta.status_code == 503
    assert respuesta.json() == {"message": "No fue posible consultar el carrito", "data": None, "success": False}
