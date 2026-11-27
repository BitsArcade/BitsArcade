"""Pruebas de HU-28: Eliminar ítem del carrito (DELETE /api/v1/carrito/items/{itemId})."""
from sqlalchemy.exc import OperationalError

from app.repositories.repositorio_carrito import RepositorioCarrito
from tests.conftest import encabezadoAuth


def _agregar(cliente, juegoId, cantidad=1, usuarioId=1):
    respuesta = cliente.post("/api/v1/carrito/items", json={"juegoId": juegoId, "cantidad": cantidad},
                             headers=encabezadoAuth(usuarioId))
    assert respuesta.status_code == 201
    return respuesta.json()["data"]


def test_flujoExitoso(cliente, crearJuego, crearClaves):
    juego = crearJuego()
    crearClaves(juego.id, disponibles=5)
    carrito = _agregar(cliente, juego.id)
    itemId = carrito["items"][0]["itemId"]
    respuesta = cliente.delete(f"/api/v1/carrito/items/{itemId}", headers=encabezadoAuth())
    assert respuesta.status_code == 200
    assert respuesta.json() == {
        "message": "Ítem eliminado del carrito",
        "data": {"carritoId": carrito["carritoId"], "items": [], "subtotal": 0, "moneda": "COP"},
        "success": True,
    }


def test_recalculaTotales(cliente, crearJuego, crearClaves):
    juego = crearJuego(costoAdquisicion=160000)
    otro = crearJuego(titulo="Space Racer", costoAdquisicion=80000)
    crearClaves(juego.id, disponibles=5)
    crearClaves(otro.id, disponibles=5)
    _agregar(cliente, juego.id)
    carrito = _agregar(cliente, otro.id)
    itemOtro = next(i["itemId"] for i in carrito["items"] if i["juegoId"] == otro.id)
    datos = cliente.delete(f"/api/v1/carrito/items/{itemOtro}", headers=encabezadoAuth()).json()["data"]
    assert [i["juegoId"] for i in datos["items"]] == [juego.id]
    assert datos["subtotal"] == 238000


def test_error404ItemDeOtroUsuario(cliente, crearJuego, crearClaves):
    juego = crearJuego()
    crearClaves(juego.id, disponibles=5)
    itemId = _agregar(cliente, juego.id, usuarioId=1)["items"][0]["itemId"]
    respuesta = cliente.delete(f"/api/v1/carrito/items/{itemId}", headers=encabezadoAuth(2))
    assert respuesta.status_code == 404
    assert respuesta.json() == {"message": "El ítem no existe en tu carrito", "data": None, "success": False}
    # El ítem del usuario 1 sigue intacto
    assert len(cliente.get("/api/v1/carrito", headers=encabezadoAuth(1)).json()["data"]["items"]) == 1


def test_error404ItemInexistente(cliente):
    respuesta = cliente.delete("/api/v1/carrito/items/9999", headers=encabezadoAuth())
    assert respuesta.status_code == 404


def test_error401SinToken(cliente):
    respuesta = cliente.delete("/api/v1/carrito/items/1")
    assert respuesta.status_code == 401
    assert respuesta.json() == {"message": "Token inválido, expirado o ausente", "data": None, "success": False}


def test_error503BaseDeDatos(cliente, monkeypatch):
    def _falla(*_args, **_kwargs):
        raise OperationalError("DELETE", {}, Exception("BD caída"))

    monkeypatch.setattr(RepositorioCarrito, "obtenerItemDeUsuario", _falla)
    respuesta = cliente.delete("/api/v1/carrito/items/1", headers=encabezadoAuth())
    assert respuesta.status_code == 503
    assert respuesta.json() == {"message": "No fue posible eliminar el ítem", "data": None, "success": False}
