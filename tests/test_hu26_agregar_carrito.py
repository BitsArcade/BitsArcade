"""Pruebas de HU-26: Agregar juego al carrito de compras (POST /api/v1/carrito/items)."""
import pytest
from sqlalchemy.exc import OperationalError

from app.core.respuestas import ErrorAplicacion
from app.domain.carrito import validar_limite_preventa
from app.repositories.repositorio_carrito import RepositorioCarrito
from app.services.cliente_inventario import ClienteInventario, InventarioNoDisponible
from app.services.servicio_carrito import ClienteOrdenes
from tests.conftest import encabezado_auth, generar_token

URL = "/api/v1/carrito/items"


def test_flujo_exitoso(cliente, crear_juego, crear_keys):
    juego = crear_juego(costo_adquisicion=160000)
    crear_keys(juego.id, disponibles=5)
    respuesta = cliente.post(URL, json={"juegoId": juego.id, "cantidad": 1}, headers=encabezado_auth(7))
    assert respuesta.status_code == 201
    cuerpo = respuesta.json()
    assert cuerpo["success"] is True
    assert cuerpo["message"] == "Juego agregado al carrito"
    datos = cuerpo["data"]
    assert set(datos) == {"carritoId", "items", "subtotal", "moneda"}
    assert datos["items"] == [{"itemId": datos["items"][0]["itemId"], "juegoId": juego.id,
                               "titulo": "Aurora Quest", "cantidad": 1, "precioUnitario": 238000}]
    assert datos["subtotal"] == 238000 and datos["moneda"] == "COP"


def test_acumula_cantidad_si_el_juego_ya_esta(cliente, crear_juego, crear_keys):
    juego = crear_juego()
    crear_keys(juego.id, disponibles=5)
    cliente.post(URL, json={"juegoId": juego.id, "cantidad": 1}, headers=encabezado_auth())
    datos = cliente.post(URL, json={"juegoId": juego.id, "cantidad": 2}, headers=encabezado_auth()).json()["data"]
    assert len(datos["items"]) == 1
    assert datos["items"][0]["cantidad"] == 3
    assert datos["subtotal"] == 238000 * 3


def test_user_id_sale_del_jwt_carritos_separados(cliente, crear_juego, crear_keys):
    juego = crear_juego()
    crear_keys(juego.id, disponibles=5)
    carrito_1 = cliente.post(URL, json={"juegoId": juego.id}, headers=encabezado_auth(1)).json()["data"]
    carrito_2 = cliente.post(URL, json={"juegoId": juego.id}, headers=encabezado_auth(2)).json()["data"]
    assert carrito_1["carritoId"] != carrito_2["carritoId"]
    assert carrito_2["items"][0]["cantidad"] == 1


def test_error_400_cantidad_cero(cliente, crear_juego):
    juego = crear_juego()
    respuesta = cliente.post(URL, json={"juegoId": juego.id, "cantidad": 0}, headers=encabezado_auth())
    assert respuesta.status_code == 400
    assert respuesta.json() == {"message": "cantidad debe ser mayor o igual a 1", "data": None, "success": False}


def test_error_404_juego_inexistente(cliente):
    respuesta = cliente.post(URL, json={"juegoId": 9999, "cantidad": 1}, headers=encabezado_auth())
    assert respuesta.status_code == 404
    assert respuesta.json() == {"message": "El juego indicado no existe", "data": None, "success": False}


def test_error_404_juego_inactivo(cliente, crear_juego, crear_keys):
    juego = crear_juego(estado="INACTIVO")
    crear_keys(juego.id, disponibles=5)
    respuesta = cliente.post(URL, json={"juegoId": juego.id, "cantidad": 1}, headers=encabezado_auth())
    assert respuesta.status_code == 404


def test_error_409_stock_insuficiente(cliente, crear_juego, crear_keys):
    juego = crear_juego()
    crear_keys(juego.id, disponibles=2, estado_extra="VENDIDA", cantidad_extra=5)
    respuesta = cliente.post(URL, json={"juegoId": juego.id, "cantidad": 3}, headers=encabezado_auth())
    assert respuesta.status_code == 409
    assert respuesta.json() == {
        "message": "Stock insuficiente para la cantidad solicitada", "data": None, "success": False,
    }


def test_error_409_stock_considera_cantidad_acumulada(cliente, crear_juego, crear_keys):
    juego = crear_juego()
    crear_keys(juego.id, disponibles=2)
    assert cliente.post(URL, json={"juegoId": juego.id, "cantidad": 2}, headers=encabezado_auth()).status_code == 201
    assert cliente.post(URL, json={"juegoId": juego.id, "cantidad": 1}, headers=encabezado_auth()).status_code == 409


def test_error_409_preventa_cantidad_2(cliente, crear_juego, crear_keys):
    juego = crear_juego(estado="PREVENTA")
    crear_keys(juego.id, disponibles=10)
    respuesta = cliente.post(URL, json={"juegoId": juego.id, "cantidad": 2}, headers=encabezado_auth())
    assert respuesta.status_code == 409
    assert respuesta.json() == {
        "message": "Solo se permite adquirir una licencia por título en preventa", "data": None, "success": False,
    }


def test_error_409_preventa_ya_en_carrito(cliente, crear_juego, crear_keys):
    juego = crear_juego(estado="PREVENTA")
    crear_keys(juego.id, disponibles=10)
    assert cliente.post(URL, json={"juegoId": juego.id, "cantidad": 1}, headers=encabezado_auth()).status_code == 201
    assert cliente.post(URL, json={"juegoId": juego.id, "cantidad": 1}, headers=encabezado_auth()).status_code == 409


def test_error_409_preventa_ya_comprado_en_orden_previa(cliente, crear_juego, crear_keys, monkeypatch):
    juego = crear_juego(estado="PREVENTA")
    crear_keys(juego.id, disponibles=10)
    monkeypatch.setattr(ClienteOrdenes, "contar_licencias_no_canceladas", lambda self, s, u, j: 1)
    respuesta = cliente.post(URL, json={"juegoId": juego.id, "cantidad": 1}, headers=encabezado_auth())
    assert respuesta.status_code == 409


def test_dominio_rn05():
    validar_limite_preventa("PREVENTA", 1, 0)
    validar_limite_preventa("ACTIVO", 5, 3)
    with pytest.raises(ErrorAplicacion):
        validar_limite_preventa("PREVENTA", 1, 1)


@pytest.mark.parametrize("encabezados", [
    {},
    {"Authorization": "Bearer token-invalido"},
    {"Authorization": f"Bearer {generar_token(minutos=-1)}"},
    {"Authorization": f"Bearer {generar_token(clave='otra-clave')}"},
])
def test_error_401_token_ausente_invalido_o_expirado(cliente, crear_juego, encabezados):
    juego = crear_juego()
    respuesta = cliente.post(URL, json={"juegoId": juego.id, "cantidad": 1}, headers=encabezados)
    assert respuesta.status_code == 401
    assert respuesta.json() == {"message": "Token inválido, expirado o ausente", "data": None, "success": False}


def test_error_503_com12_no_responde(cliente, crear_juego, monkeypatch):
    juego = crear_juego()

    def _falla(self, sesion, juego_id):
        raise InventarioNoDisponible("MOD-03 caído")

    monkeypatch.setattr(ClienteInventario, "contar_disponibles", _falla)
    respuesta = cliente.post(URL, json={"juegoId": juego.id, "cantidad": 1}, headers=encabezado_auth())
    assert respuesta.status_code == 503


def test_error_503_base_de_datos(cliente, crear_juego, crear_keys, monkeypatch):
    juego = crear_juego()
    crear_keys(juego.id, disponibles=5)

    def _falla(*_args, **_kwargs):
        raise OperationalError("INSERT", {}, Exception("BD caída"))

    monkeypatch.setattr(RepositorioCarrito, "obtener_carrito_activo", _falla)
    respuesta = cliente.post(URL, json={"juegoId": juego.id, "cantidad": 1}, headers=encabezado_auth())
    assert respuesta.status_code == 503
    assert respuesta.json() == {
        "message": "No fue posible agregar el juego al carrito", "data": None, "success": False,
    }
