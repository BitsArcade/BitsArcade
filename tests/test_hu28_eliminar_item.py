"""Pruebas de HU-28: Eliminar ítem del carrito (DELETE /api/v1/carrito/items/{itemId})."""
from sqlalchemy.exc import OperationalError

from app.repositories.repositorio_carrito import RepositorioCarrito
from tests.conftest import encabezado_auth


def _agregar(cliente, juego_id, cantidad=1, usuario_id=1):
    respuesta = cliente.post("/api/v1/carrito/items", json={"juegoId": juego_id, "cantidad": cantidad},
                             headers=encabezado_auth(usuario_id))
    assert respuesta.status_code == 201
    return respuesta.json()["data"]


def test_flujo_exitoso(cliente, crear_juego, crear_keys):
    juego = crear_juego()
    crear_keys(juego.id, disponibles=5)
    carrito = _agregar(cliente, juego.id)
    item_id = carrito["items"][0]["itemId"]
    respuesta = cliente.delete(f"/api/v1/carrito/items/{item_id}", headers=encabezado_auth())
    assert respuesta.status_code == 200
    assert respuesta.json() == {
        "message": "Ítem eliminado del carrito",
        "data": {"carritoId": carrito["carritoId"], "items": [], "subtotal": 0, "moneda": "COP"},
        "success": True,
    }


def test_recalcula_totales(cliente, crear_juego, crear_keys):
    juego = crear_juego(costo_adquisicion=160000)
    otro = crear_juego(titulo="Space Racer", costo_adquisicion=80000)
    crear_keys(juego.id, disponibles=5)
    crear_keys(otro.id, disponibles=5)
    _agregar(cliente, juego.id)
    carrito = _agregar(cliente, otro.id)
    item_otro = next(i["itemId"] for i in carrito["items"] if i["juegoId"] == otro.id)
    datos = cliente.delete(f"/api/v1/carrito/items/{item_otro}", headers=encabezado_auth()).json()["data"]
    assert [i["juegoId"] for i in datos["items"]] == [juego.id]
    assert datos["subtotal"] == 238000


def test_error_404_item_de_otro_usuario(cliente, crear_juego, crear_keys):
    juego = crear_juego()
    crear_keys(juego.id, disponibles=5)
    item_id = _agregar(cliente, juego.id, usuario_id=1)["items"][0]["itemId"]
    respuesta = cliente.delete(f"/api/v1/carrito/items/{item_id}", headers=encabezado_auth(2))
    assert respuesta.status_code == 404
    assert respuesta.json() == {"message": "El ítem no existe en tu carrito", "data": None, "success": False}
    # El ítem del usuario 1 sigue intacto
    assert len(cliente.get("/api/v1/carrito", headers=encabezado_auth(1)).json()["data"]["items"]) == 1


def test_error_404_item_inexistente(cliente):
    respuesta = cliente.delete("/api/v1/carrito/items/9999", headers=encabezado_auth())
    assert respuesta.status_code == 404


def test_error_401_sin_token(cliente):
    respuesta = cliente.delete("/api/v1/carrito/items/1")
    assert respuesta.status_code == 401
    assert respuesta.json() == {"message": "Token inválido, expirado o ausente", "data": None, "success": False}


def test_error_503_base_de_datos(cliente, monkeypatch):
    def _falla(*_args, **_kwargs):
        raise OperationalError("DELETE", {}, Exception("BD caída"))

    monkeypatch.setattr(RepositorioCarrito, "obtener_item_de_usuario", _falla)
    respuesta = cliente.delete("/api/v1/carrito/items/1", headers=encabezado_auth())
    assert respuesta.status_code == 503
    assert respuesta.json() == {"message": "No fue posible eliminar el ítem", "data": None, "success": False}
