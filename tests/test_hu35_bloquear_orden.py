"""Pruebas de HU-35: Bloquear orden al pasar a procesando (PATCH /interno/v1/ordenes/{ordenId}/estado)."""
import pytest
from sqlalchemy.exc import OperationalError

from app.core.respuestas import ErrorAplicacion
from app.domain.orden import validar_transicion_estado_interno
from app.repositories.repositorio_orden import RepositorioOrden
from tests.conftest import encabezado_auth


# --- Pruebas unitarias de dominio ---

def test_dominio_transiciones_hu35():
    assert validar_transicion_estado_interno("PENDIENTE", "PROCESANDO") == "PROCESANDO"
    assert validar_transicion_estado_interno("PROCESANDO", "PAGADA") == "PAGADA"
    assert validar_transicion_estado_interno("PROCESANDO", "CANCELADA") == "CANCELADA"

    with pytest.raises(ErrorAplicacion) as err_bloqueada:
        validar_transicion_estado_interno("PROCESANDO", "PENDIENTE")
    assert err_bloqueada.value.status_code == 409

    with pytest.raises(ErrorAplicacion) as err_invalido:
        validar_transicion_estado_interno("PENDIENTE", "OTRO")
    assert err_invalido.value.status_code == 400


# --- Pruebas funcionales ---

def _crear_orden(cliente, crear_juego, crear_keys, usuario_id=1) -> tuple[int, int]:
    juego = crear_juego()
    crear_keys(juego.id, disponibles=3)
    cliente.post(
        "/api/v1/carrito/items",
        json={"juegoId": juego.id, "cantidad": 1},
        headers=encabezado_auth(usuario_id),
    )
    resp = cliente.post("/api/v1/ordenes", headers=encabezado_auth(usuario_id))
    assert resp.status_code == 201
    return resp.json()["data"]["ordenId"], juego.id


def test_flujo_exitoso_bloquear_orden_en_procesando(cliente, crear_juego, crear_keys):
    orden_id, _ = _crear_orden(cliente, crear_juego, crear_keys)

    respuesta = cliente.patch(
        f"/interno/v1/ordenes/{orden_id}/estado",
        json={"estado": "PROCESANDO"},
    )
    assert respuesta.status_code == 200
    assert respuesta.json() == {
        "ordenId": orden_id,
        "estadoAnterior": "PENDIENTE",
        "estadoActual": "PROCESANDO",
        "bloqueada": True,
    }

    # Al estar bloqueada en PROCESANDO, el usuario NO puede cancelarla (409)
    cancelar = cliente.post(f"/api/v1/ordenes/{orden_id}/cancelacion", headers=encabezado_auth())
    assert cancelar.status_code == 409
    assert cancelar.json()["message"] == "Solo se pueden cancelar órdenes en estado PENDIENTE"


def test_resolucion_desde_procesando_a_pagada_y_bloqueo_posterior(cliente, crear_juego, crear_keys):
    orden_id, _ = _crear_orden(cliente, crear_juego, crear_keys)
    cliente.patch(f"/interno/v1/ordenes/{orden_id}/estado", json={"estado": "PROCESANDO"})

    pagar = cliente.patch(f"/interno/v1/ordenes/{orden_id}/estado", json={"estado": "PAGADA"})
    assert pagar.status_code == 200
    assert pagar.json()["estadoActual"] == "PAGADA"
    assert pagar.json()["bloqueada"] is False

    # Una orden PAGADA no puede volver a PROCESANDO (409)
    reintento = cliente.patch(f"/interno/v1/ordenes/{orden_id}/estado", json={"estado": "PROCESANDO"})
    assert reintento.status_code == 409


def test_error_400_estado_destino_invalido(cliente, crear_juego, crear_keys):
    orden_id, _ = _crear_orden(cliente, crear_juego, crear_keys)
    respuesta = cliente.patch(f"/interno/v1/ordenes/{orden_id}/estado", json={"estado": "DESCONOCIDO"})
    assert respuesta.status_code == 400


def test_error_404_orden_inexistente(cliente):
    respuesta = cliente.patch("/interno/v1/ordenes/9999/estado", json={"estado": "PROCESANDO"})
    assert respuesta.status_code == 404


def test_error_503_base_de_datos(cliente, monkeypatch):
    def _falla(*_args, **_kwargs):
        raise OperationalError("SELECT", {}, Exception("BD caída"))

    monkeypatch.setattr(RepositorioOrden, "obtener_por_id", _falla)
    assert cliente.patch("/interno/v1/ordenes/1/estado", json={"estado": "PROCESANDO"}).status_code == 503