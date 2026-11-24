"""Pruebas de HU-30: Vaciar carrito de compras (DELETE /api/v1/carrito)."""
from sqlalchemy.exc import OperationalError

from app.repositories.repositorio_carrito import RepositorioCarrito
from tests.conftest import encabezado_auth


def _agregar(cliente, juego_id, cantidad=1, usuario_id=1):
    resp = cliente.post(
        "/api/v1/carrito/items",
        json={"juegoId": juego_id, "cantidad": cantidad},
        headers=encabezado_auth(usuario_id),
    )
    assert resp.status_code == 201


def test_flujo_exitoso_vaciar_carrito(cliente, crear_juego, crear_keys):
    j1 = crear_juego(titulo="Juego Uno")
    j2 = crear_juego(titulo="Juego Dos")
    crear_keys(j1.id, disponibles=5)
    crear_keys(j2.id, disponibles=5)

    _agregar(cliente, j1.id, 2)
    _agregar(cliente, j2.id, 1)

    respuesta = cliente.delete("/api/v1/carrito", headers=encabezado_auth())
    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["success"] is True
    assert cuerpo["message"] == "Carrito vaciado exitosamente"
    assert cuerpo["data"]["items"] == []
    assert cuerpo["data"]["subtotal"] == 0.0


def test_vaciar_carrito_no_afecta_otro_usuario(cliente, crear_juego, crear_keys):
    juego = crear_juego()
    crear_keys(juego.id, disponibles=10)
    _agregar(cliente, juego.id, 1, usuario_id=1)
    _agregar(cliente, juego.id, 2, usuario_id=2)

    cliente.delete("/api/v1/carrito", headers=encabezado_auth(usuario_id=1))

    carrito_u2 = cliente.get("/api/v1/carrito", headers=encabezado_auth(usuario_id=2)).json()["data"]
    assert len(carrito_u2["items"]) == 1
    assert carrito_u2["items"][0]["cantidad"] == 2


def test_error_401_sin_token(cliente):
    respuesta = cliente.delete("/api/v1/carrito")
    assert respuesta.status_code == 401
    assert respuesta.json() == {"message": "Token inválido, expirado o ausente", "data": None, "success": False}


def test_error_503_base_de_datos(cliente, monkeypatch):
    def _falla(*_args, **_kwargs):
        raise OperationalError("DELETE", {}, Exception("BD caída"))

    monkeypatch.setattr(RepositorioCarrito, "obtener_carrito_activo", _falla)
    respuesta = cliente.delete("/api/v1/carrito", headers=encabezado_auth())
    assert respuesta.status_code == 503
    assert respuesta.json() == {"message": "No fue posible vaciar el carrito", "data": None, "success": False}