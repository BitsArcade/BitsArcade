import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.api.transacciones import obtener_servicio_transacciones
from app.core.respuestas import ErrorAplicacion
from app.core.seguridad import UsuarioAutenticado, obtener_usuario_autenticado
from app.domain.transacciones import (
    EstadoTransaccion,
    OrdenParaCobro,
    ReglasTransaccion,
    Transaccion,
)
from app.services.servicio_transacciones import ServicioTransacciones
from main import app


def _orden_valida(usuario_id: int = 77) -> OrdenParaCobro:
    return OrdenParaCobro(
        orden_id=5001,
        usuario_id=usuario_id,
        estado="PENDIENTE",
        total=57.35,
        moneda="USD",
        tasa_cambio=4150.25,
        expira_en=datetime.now(timezone.utc) + timedelta(minutes=10),
        items=[{"juegoId": 101, "reservaId": "res-9f1", "precioUnitario": 238000}],
    )


# ==============================================================================
# PRUEBAS UNITARIAS DE DOMINIO Y SERVICIO
# ==============================================================================
def test_rn09_payload_pasarela_usa_tasa_congelada():
    orden = _orden_valida()
    payload = ReglasTransaccion.construir_payload_pasarela("TX-9001", orden, 2)
    assert payload == {
        "transaccionId": "TX-9001",
        "ordenId": 5001,
        "metodoPagoId": 2,
        "monto": 57.35,
        "moneda": "USD",
        "tasaCambio": 4150.25,
    }


def test_dominio_error_404_orden_ajena():
    orden = _orden_valida(usuario_id=99)
    with pytest.raises(ErrorAplicacion) as exc:
        ReglasTransaccion.validar_orden_cobrable(orden, usuario_autenticado_id=77)
    assert exc.value.status_code == 404
    assert exc.value.message == "La orden indicada no existe"


def test_dominio_error_409_orden_cancelada_o_pagada():
    orden = OrdenParaCobro(
        orden_id=5001,
        usuario_id=77,
        estado="CANCELADA",
        total=238000,
        moneda="COP",
        tasa_cambio=1,
        expira_en=datetime.now(timezone.utc) + timedelta(minutes=10),
        items=[],
    )
    with pytest.raises(ErrorAplicacion) as exc:
        ReglasTransaccion.validar_orden_cobrable(orden, usuario_autenticado_id=77)
    assert exc.value.status_code == 409
    assert exc.value.message == "La orden no está disponible para pago"


def test_dominio_error_409_orden_por_expirar():
    ahora = datetime.now(timezone.utc)
    orden = OrdenParaCobro(
        orden_id=5001,
        usuario_id=77,
        estado="PENDIENTE",
        total=238000,
        moneda="COP",
        tasa_cambio=1,
        expira_en=ahora + timedelta(seconds=90),
        items=[],
    )
    with pytest.raises(ErrorAplicacion) as exc:
        ReglasTransaccion.validar_orden_cobrable(orden, usuario_autenticado_id=77, ahora=ahora)
    assert exc.value.status_code == 409
    assert exc.value.message == "La orden está por expirar. Genera una nueva orden"


def test_servicio_idempotencia_por_orden_id():
    existente = Transaccion(
        transaccion_id="TX-9001",
        orden_id=5001,
        usuario_id=77,
        metodo_pago_id=2,
        monto=57.35,
        moneda="USD",
        tasa_cambio=4150.25,
        estado=EstadoTransaccion.EN_PROCESO,
    )
    repo = MagicMock()
    repo.obtener_por_orden_id.return_value = existente
    adaptador_ordenes = AsyncMock()
    cliente_pasarela = AsyncMock()

    servicio = ServicioTransacciones(repo, adaptador_ordenes, cliente_pasarela)
    resultado = asyncio.run(
        servicio.iniciar_cobro(orden_id=5001, metodo_pago_id=2, usuario_id=77)
    )

    assert resultado.transaccion_id == "TX-9001"
    cliente_pasarela.transmitir_cobro.assert_not_called()


# ==============================================================================
# PRUEBAS FUNCIONALES DEL ENDPOINT POST /api/v1/pagos (Casos 1 a 8)
# ==============================================================================
@pytest.fixture
def cliente_autenticado():
    app.dependency_overrides[obtener_usuario_autenticado] = lambda: UsuarioAutenticado(
        id=77, rol="CLIENTE"
    )
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_caso_1_y_2_flujo_exitoso_y_contrato(cliente_autenticado):
    repo = MagicMock()
    repo.obtener_por_orden_id.return_value = None
    repo.guardar.side_effect = lambda tx: tx

    adaptador_ordenes = AsyncMock()
    adaptador_ordenes.obtener_orden_com08.return_value = _orden_valida()
    adaptador_ordenes.marcar_orden_procesando_com09.return_value = True

    cliente_pasarela = AsyncMock()
    cliente_pasarela.transmitir_cobro.return_value = {"recibido": True}

    servicio = ServicioTransacciones(repo, adaptador_ordenes, cliente_pasarela)
    app.dependency_overrides[obtener_servicio_transacciones] = lambda: servicio

    respuesta = cliente_autenticado.post(
        "/api/v1/pagos", json={"ordenId": 5001, "metodoPagoId": 2}
    )
    cuerpo = respuesta.json()

    assert respuesta.status_code == 202
    assert set(cuerpo.keys()) == {"message", "data", "success"}
    assert cuerpo["success"] is True
    assert cuerpo["message"] == "Pago en proceso"
    assert set(cuerpo["data"].keys()) == {"transaccionId", "ordenId", "estado"}
    assert cuerpo["data"]["ordenId"] == 5001
    assert cuerpo["data"]["estado"] == "EN_PROCESO"
    assert cliente_pasarela.transmitir_cobro.call_args.kwargs["idempotency_key"] == "5001"


def test_caso_3_error_404_orden_ajena(cliente_autenticado):
    repo = MagicMock()
    repo.obtener_por_orden_id.return_value = None
    adaptador_ordenes = AsyncMock()
    adaptador_ordenes.obtener_orden_com08.return_value = _orden_valida(usuario_id=99)
    cliente_pasarela = AsyncMock()

    app.dependency_overrides[obtener_servicio_transacciones] = lambda: ServicioTransacciones(
        repo, adaptador_ordenes, cliente_pasarela
    )

    respuesta = cliente_autenticado.post(
        "/api/v1/pagos", json={"ordenId": 5001, "metodoPagoId": 2}
    )
    assert respuesta.status_code == 404
    assert respuesta.json() == {
        "message": "La orden indicada no existe",
        "data": None,
        "success": False,
    }


def test_caso_4_error_409_orden_cancelada_o_pagada(cliente_autenticado):
    repo = MagicMock()
    repo.obtener_por_orden_id.return_value = None
    adaptador_ordenes = AsyncMock()
    adaptador_ordenes.obtener_orden_com08.return_value = OrdenParaCobro(
        orden_id=5001,
        usuario_id=77,
        estado="CANCELADA",
        total=238000,
        moneda="COP",
        tasa_cambio=1,
        expira_en=datetime.now(timezone.utc) + timedelta(minutes=10),
        items=[],
    )
    cliente_pasarela = AsyncMock()

    app.dependency_overrides[obtener_servicio_transacciones] = lambda: ServicioTransacciones(
        repo, adaptador_ordenes, cliente_pasarela
    )

    respuesta = cliente_autenticado.post(
        "/api/v1/pagos", json={"ordenId": 5001, "metodoPagoId": 2}
    )
    assert respuesta.status_code == 409
    assert respuesta.json() == {
        "message": "La orden no está disponible para pago",
        "data": None,
        "success": False,
    }


def test_caso_5_error_409_orden_por_expirar(cliente_autenticado):
    repo = MagicMock()
    repo.obtener_por_orden_id.return_value = None
    adaptador_ordenes = AsyncMock()
    adaptador_ordenes.obtener_orden_com08.return_value = OrdenParaCobro(
        orden_id=5001,
        usuario_id=77,
        estado="PENDIENTE",
        total=238000,
        moneda="COP",
        tasa_cambio=1,
        expira_en=datetime.now(timezone.utc) + timedelta(seconds=60),
        items=[],
    )
    cliente_pasarela = AsyncMock()

    app.dependency_overrides[obtener_servicio_transacciones] = lambda: ServicioTransacciones(
        repo, adaptador_ordenes, cliente_pasarela
    )

    respuesta = cliente_autenticado.post(
        "/api/v1/pagos", json={"ordenId": 5001, "metodoPagoId": 2}
    )
    assert respuesta.status_code == 409
    assert respuesta.json() == {
        "message": "La orden está por expirar. Genera una nueva orden",
        "data": None,
        "success": False,
    }


def test_caso_6_error_504_timeout_pasarela(cliente_autenticado):
    repo = MagicMock()
    repo.obtener_por_orden_id.return_value = None
    adaptador_ordenes = AsyncMock()
    adaptador_ordenes.obtener_orden_com08.return_value = _orden_valida()
    adaptador_ordenes.marcar_orden_procesando_com09.return_value = True

    cliente_pasarela = AsyncMock()
    cliente_pasarela.transmitir_cobro.side_effect = TimeoutError("Timeout pasarela")

    app.dependency_overrides[obtener_servicio_transacciones] = lambda: ServicioTransacciones(
        repo, adaptador_ordenes, cliente_pasarela
    )

    respuesta = cliente_autenticado.post(
        "/api/v1/pagos", json={"ordenId": 5001, "metodoPagoId": 2}
    )
    assert respuesta.status_code == 504
    assert respuesta.json() == {
        "message": "La pasarela de pagos no respondió",
        "data": None,
        "success": False,
    }


def test_caso_7_error_401_sin_token():
    app.dependency_overrides.clear()
    cliente = TestClient(app)
    respuesta = cliente.post("/api/v1/pagos", json={"ordenId": 5001, "metodoPagoId": 2})
    assert respuesta.status_code == 401
    assert respuesta.json() == {
        "message": "Token inválido, expirado o ausente",
        "data": None,
        "success": False,
    }


def test_caso_8_error_503_base_de_datos_caida(cliente_autenticado):
    repo = MagicMock()
    repo.obtener_por_orden_id.side_effect = ErrorAplicacion(503, "No fue posible iniciar el pago")
    adaptador_ordenes = AsyncMock()
    cliente_pasarela = AsyncMock()

    app.dependency_overrides[obtener_servicio_transacciones] = lambda: ServicioTransacciones(
        repo, adaptador_ordenes, cliente_pasarela
    )

    respuesta = cliente_autenticado.post(
        "/api/v1/pagos", json={"ordenId": 5001, "metodoPagoId": 2}
    )
    assert respuesta.status_code == 503
    assert respuesta.json() == {
        "message": "No fue posible iniciar el pago",
        "data": None,
        "success": False,
    }