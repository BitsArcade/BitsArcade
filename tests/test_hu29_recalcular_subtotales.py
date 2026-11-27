"""Pruebas de HU-29: Recalcular subtotales con promociones y volumen (PATCH /api/v1/carrito/items/{itemId})."""
from sqlalchemy.exc import OperationalError

from app.domain.carrito import UMBRAL_DESCUENTO_VOLUMEN, PORCENTAJE_DESCUENTO_VOLUMEN, calcularDesglose
from app.repositories.repositorio_carrito import RepositorioCarrito
from app.services.servicio_catalogo import ClienteParametrosFinancieros
from tests.conftest import configurarParametros, encabezadoAuth


def _agregar(cliente, juegoId, cantidad=1, usuarioId=1) -> int:
    respuesta = cliente.post("/api/v1/carrito/items", json={"juegoId": juegoId, "cantidad": cantidad},
                             headers=encabezadoAuth(usuarioId))
    assert respuesta.status_code == 201
    return respuesta.json()["data"]["items"][0]["itemId"]


def _patch(cliente, itemId, cantidad, usuarioId=1):
    return cliente.patch(f"/api/v1/carrito/items/{itemId}", json={"cantidad": cantidad},
                         headers=encabezadoAuth(usuarioId))


# --- Pruebas unitarias de dominio ---

def test_configuracionEstaticaRn08():
    assert UMBRAL_DESCUENTO_VOLUMEN == 3 and PORCENTAJE_DESCUENTO_VOLUMEN == 0.10


def test_rn08DescuentoPorVolumen():
    assert calcularDesglose(238000, 190400, 3, "ACTIVO") == {
        "precioUnitario": 238000, "descuentoVolumen": 71400, "subtotal": 642600,
    }


def test_rn08BajoUmbralSinDescuento():
    assert calcularDesglose(238000, 190400, 2, "ACTIVO")["descuentoVolumen"] == 0


def test_rn07PreventaYEstrenoSinDescuento():
    for estado in ("PREVENTA", "ESTRENO"):
        assert calcularDesglose(238000, 190400, 5, estado)["descuentoVolumen"] == 0


def test_rn02DescuentoNoBajaDePisoPrecio():
    # Precio 100, piso 95: el 10 % (10) se limita a 5 para no bajar de 95.
    desglose = calcularDesglose(100, 95, 3, "ACTIVO")
    assert desglose["descuentoVolumen"] == 15
    assert desglose["subtotal"] / 3 >= 95


# --- Pruebas funcionales ---

def test_flujoExitoso(cliente, crearJuego, crearClaves):
    juego = crearJuego(costoAdquisicion=160000)
    crearClaves(juego.id, disponibles=10)
    itemId = _agregar(cliente, juego.id)
    respuesta = _patch(cliente, itemId, 3)
    assert respuesta.status_code == 200
    assert respuesta.json() == {
        "message": "Subtotales recalculados",
        "data": {"itemId": itemId, "juegoId": juego.id, "cantidad": 3, "precioUnitario": 238000,
                 "descuentoVolumen": 71400, "subtotal": 642600, "moneda": "COP"},
        "success": True,
    }
    # La cantidad queda persistida en el carrito
    carrito = cliente.get("/api/v1/carrito", headers=encabezadoAuth()).json()["data"]
    assert carrito["items"][0]["cantidad"] == 3


def test_estrenoSinDescuento(cliente, crearJuego, crearClaves):
    juego = crearJuego(estado="ESTRENO")
    crearClaves(juego.id, disponibles=10)
    datos = _patch(cliente, _agregar(cliente, juego.id), 4).json()["data"]
    assert datos["descuentoVolumen"] == 0 and datos["subtotal"] == 238000 * 4


def test_rn02ConMargenBajo(cliente, crearJuego, crearClaves):
    juego = crearJuego(costoAdquisicion=100000)
    crearClaves(juego.id, disponibles=10)
    configurarParametros(cliente, margenGanancia=5)  # M=5 % < 10 %
    datos = _patch(cliente, _agregar(cliente, juego.id), 3).json()["data"]
    piso = 100000 * 1.19
    assert round((datos["subtotal"]) / 3, 2) >= round(piso, 2)


def test_error400CantidadCero(cliente, crearJuego, crearClaves):
    juego = crearJuego()
    crearClaves(juego.id, disponibles=10)
    respuesta = _patch(cliente, _agregar(cliente, juego.id), 0)
    assert respuesta.status_code == 400
    assert respuesta.json() == {
        "message": "cantidad debe ser mayor o igual a 1. Use DELETE para retirar el ítem", "data": None,
        "success": False,
    }


def test_error409PreventaCantidad2(cliente, crearJuego, crearClaves):
    juego = crearJuego(estado="PREVENTA")
    crearClaves(juego.id, disponibles=10)
    respuesta = _patch(cliente, _agregar(cliente, juego.id), 2)
    assert respuesta.status_code == 409
    assert respuesta.json()["message"] == "Solo se permite adquirir una licencia por título en preventa"


def test_error409StockInsuficiente(cliente, crearJuego, crearClaves):
    juego = crearJuego()
    crearClaves(juego.id, disponibles=2)
    respuesta = _patch(cliente, _agregar(cliente, juego.id), 3)
    assert respuesta.status_code == 409
    assert respuesta.json()["message"] == "Stock insuficiente para la cantidad solicitada"


def test_error404ItemAjeno(cliente, crearJuego, crearClaves):
    juego = crearJuego()
    crearClaves(juego.id, disponibles=10)
    itemId = _agregar(cliente, juego.id, usuarioId=1)
    respuesta = _patch(cliente, itemId, 2, usuarioId=2)
    assert respuesta.status_code == 404
    assert respuesta.json() == {"message": "El ítem no existe en tu carrito", "data": None, "success": False}


def test_error401SinToken(cliente):
    respuesta = cliente.patch("/api/v1/carrito/items/1", json={"cantidad": 2})
    assert respuesta.status_code == 401
    assert respuesta.json() == {"message": "Token inválido, expirado o ausente", "data": None, "success": False}


def test_error503Com11NoResponde(cliente, crearJuego, crearClaves, monkeypatch):
    juego = crearJuego()
    crearClaves(juego.id, disponibles=10)
    itemId = _agregar(cliente, juego.id)

    def _falla(self, sesion):
        raise ConnectionError("MOD-00 caído")

    monkeypatch.setattr(ClienteParametrosFinancieros, "obtenerContratoCom01", _falla)
    assert _patch(cliente, itemId, 2).status_code == 503


def test_error503BaseDeDatos(cliente, monkeypatch):
    def _falla(*_args, **_kwargs):
        raise OperationalError("UPDATE", {}, Exception("BD caída"))

    monkeypatch.setattr(RepositorioCarrito, "obtenerItemDeUsuario", _falla)
    respuesta = _patch(cliente, 1, 2)
    assert respuesta.status_code == 503
    assert respuesta.json() == {"message": "No fue posible recalcular los subtotales", "data": None, "success": False}
