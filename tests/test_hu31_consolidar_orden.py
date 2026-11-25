"""Pruebas de HU-31: Consolidar orden de compra pendiente (POST /api/v1/ordenes)."""
from sqlalchemy.exc import OperationalError

from app.repositories.repositorio_carrito import RepositorioCarrito
from app.services.cliente_inventario import ClienteInventario, InventarioNoDisponible
from tests.conftest import encabezado_auth


def _agregar(cliente, juego_id, cantidad=1, usuario_id=1):
    resp = cliente.post(
        "/api/v1/carrito/items",
        json={"juegoId": juego_id, "cantidad": cantidad},
        headers=encabezado_auth(usuario_id),
    )
    assert resp.status_code == 201


def test_flujo_exitoso_consolidar_orden_y_reservar_stock(cliente, crear_juego, crear_keys):
    juego = crear_juego(titulo="Cyber Blade", costo_adquisicion=160000)
    crear_keys(juego.id, disponibles=5)
    _agregar(cliente, juego.id, cantidad=3)  # Aplica descuento volumen 10% (RN-08)

    respuesta = cliente.post("/api/v1/ordenes", headers=encabezado_auth())
    assert respuesta.status_code == 201
    cuerpo = respuesta.json()
    assert cuerpo["success"] is True
    assert cuerpo["message"] == "Orden de compra consolidada exitosamente"

    datos = cuerpo["data"]
    assert datos["estado"] == "PENDIENTE"
    assert datos["moneda"] == "COP"
    assert datos["subtotalBruto"] == 714000.0
    assert datos["descuentoTotal"] == 71400.0
    assert datos["total"] == 642600.0
    assert len(datos["items"]) == 1
    assert datos["items"][0]["juegoId"] == juego.id

    # El carrito quedó vacío tras consolidar
    carrito = cliente.get("/api/v1/carrito", headers=encabezado_auth()).json()
    assert carrito["success"] is False
    assert carrito["data"]["items"] == []


def test_error_400_carrito_vacio(cliente):
    respuesta = cliente.post("/api/v1/ordenes", headers=encabezado_auth())
    assert respuesta.status_code == 400
    assert respuesta.json() == {
        "message": "No es posible generar una orden con el carrito vacío",
        "data": None,
        "success": False,
    }


def test_error_409_rn05_preventa_en_orden_previa(cliente, crear_juego, crear_keys):
    juego = crear_juego(estado="PREVENTA")
    crear_keys(juego.id, disponibles=5)

    # Primera compra en preventa: éxito
    _agregar(cliente, juego.id, cantidad=1)
    assert cliente.post("/api/v1/ordenes", headers=encabezado_auth()).status_code == 201

    # Segundo intento de agregar el mismo juego en preventa debe fallar por RN-05 (409)
    resp_segundo = cliente.post(
        "/api/v1/carrito/items",
        json={"juegoId": juego.id, "cantidad": 1},
        headers=encabezado_auth(),
    )
    assert resp_segundo.status_code == 409
    assert resp_segundo.json()["message"] == "Solo se permite adquirir una licencia por título en preventa"


def test_error_401_sin_token(cliente):
    respuesta = cliente.post("/api/v1/ordenes")
    assert respuesta.status_code == 401
    assert respuesta.json() == {"message": "Token inválido, expirado o ausente", "data": None, "success": False}


def test_error_503_com12_no_disponible(cliente, crear_juego, crear_keys, monkeypatch):
    juego = crear_juego()
    crear_keys(juego.id, disponibles=5)
    _agregar(cliente, juego.id, 1)

    def _falla(*_args, **_kwargs):
        raise InventarioNoDisponible("MOD-03 caído")

    monkeypatch.setattr(ClienteInventario, "reservar_keys", _falla)
    respuesta = cliente.post("/api/v1/ordenes", headers=encabezado_auth())
    assert respuesta.status_code == 503


def test_error_503_base_de_datos(cliente, monkeypatch):
    def _falla(*_args, **_kwargs):
        raise OperationalError("SELECT", {}, Exception("BD caída"))

    monkeypatch.setattr(RepositorioCarrito, "obtener_carrito_activo", _falla)
    respuesta = cliente.post("/api/v1/ordenes", headers=encabezado_auth())
    assert respuesta.status_code == 503