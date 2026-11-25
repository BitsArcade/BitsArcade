"""Pruebas de HU-34: Cancelar orden de compra y liberar stock (POST /api/v1/ordenes/{ordenId}/cancelacion)."""
import pytest
from sqlalchemy.exc import OperationalError

from app.core.respuestas import ErrorAplicacion
from app.domain.orden import validar_cancelacion_orden
from app.repositories.repositorio_orden import RepositorioOrden
from app.services.cliente_inventario import ClienteInventario, InventarioNoDisponible
from tests.conftest import encabezado_auth


# --- Pruebas unitarias de dominio ---

def test_dominio_validar_cancelacion_solo_pendiente():
    validar_cancelacion_orden("PENDIENTE")  # No lanza excepción

    with pytest.raises(ErrorAplicacion) as err_cancelada:
        validar_cancelacion_orden("CANCELADA")
    assert err_cancelada.value.status_code == 409

    with pytest.raises(ErrorAplicacion) as err_procesando:
        validar_cancelacion_orden("PROCESANDO")
    assert err_procesando.value.status_code == 409


# --- Pruebas funcionales ---

def _crear_orden_con_2_keys(cliente, crear_juego, crear_keys, usuario_id=1) -> tuple[int, int]:
    juego = crear_juego()
    crear_keys(juego.id, disponibles=2)
    cliente.post(
        "/api/v1/carrito/items",
        json={"juegoId": juego.id, "cantidad": 2},
        headers=encabezado_auth(usuario_id),
    )
    resp = cliente.post("/api/v1/ordenes", headers=encabezado_auth(usuario_id))
    assert resp.status_code == 201
    return resp.json()["data"]["ordenId"], juego.id


def test_flujo_exitoso_cancelar_y_liberar_stock(cliente, crear_juego, crear_keys):
    orden_id, juego_id = _crear_orden_con_2_keys(cliente, crear_juego, crear_keys)

    # Stock quedó en 0 tras consolidar la orden
    stock_antes = cliente.get(f"/api/v1/catalogo/juegos/{juego_id}/stock").json()["data"]["estado"]
    assert stock_antes == "AGOTADO"

    respuesta = cliente.post(f"/api/v1/ordenes/{orden_id}/cancelacion", headers=encabezado_auth())
    assert respuesta.status_code == 200
    assert respuesta.json() == {
        "message": "Orden cancelada y stock liberado exitosamente",
        "data": {"ordenId": orden_id, "estado": "CANCELADA", "licenciasLiberadas": 2},
        "success": True,
    }

    # Las 2 licencias vuelven a estar DISPONIBLES en catálogo
    stock_despues = cliente.get(f"/api/v1/catalogo/juegos/{juego_id}/stock").json()["data"]["estado"]
    assert stock_despues == "DISPONIBLE"


def test_error_409_cancelar_orden_ya_cancelada(cliente, crear_juego, crear_keys):
    orden_id, _ = _crear_orden_con_2_keys(cliente, crear_juego, crear_keys)
    assert cliente.post(f"/api/v1/ordenes/{orden_id}/cancelacion", headers=encabezado_auth()).status_code == 200

    segunda = cliente.post(f"/api/v1/ordenes/{orden_id}/cancelacion", headers=encabezado_auth())
    assert segunda.status_code == 409
    assert segunda.json()["message"] == "La orden ya se encuentra cancelada"


def test_error_404_orden_ajena_o_inexistente(cliente, crear_juego, crear_keys):
    orden_id, _ = _crear_orden_con_2_keys(cliente, crear_juego, crear_keys, usuario_id=1)
    respuesta = cliente.post(f"/api/v1/ordenes/{orden_id}/cancelacion", headers=encabezado_auth(usuario_id=2))
    assert respuesta.status_code == 404


def test_error_401_sin_token(cliente):
    assert cliente.post("/api/v1/ordenes/1/cancelacion").status_code == 401


def test_error_503_com12_falla_al_liberar(cliente, crear_juego, crear_keys, monkeypatch):
    orden_id, _ = _crear_orden_con_2_keys(cliente, crear_juego, crear_keys)

    def _falla(*_args, **_kwargs):
        raise InventarioNoDisponible("MOD-03 caído")

    monkeypatch.setattr(ClienteInventario, "liberar_keys", _falla)
    assert cliente.post(f"/api/v1/ordenes/{orden_id}/cancelacion", headers=encabezado_auth()).status_code == 503


def test_error_503_base_de_datos(cliente, monkeypatch):
    def _falla(*_args, **_kwargs):
        raise OperationalError("SELECT", {}, Exception("BD caída"))

    monkeypatch.setattr(RepositorioOrden, "obtener_por_id_y_usuario", _falla)
    assert cliente.post("/api/v1/ordenes/1/cancelacion", headers=encabezado_auth()).status_code == 503