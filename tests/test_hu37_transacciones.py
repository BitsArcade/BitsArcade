import asyncio
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.api.transacciones import obtener_servicio_transacciones
from app.core.respuestas import ErrorAplicacion
from app.domain.transacciones import (
    Comprobante,
    EstadoTransaccion,
    OrdenParaCobro,
    ReglasTransaccion,
    Transaccion,
)
from app.services.servicio_transacciones import (
    ErrorReservaExpiradaDespacho,
    ServicioTransacciones,
)
from main import app

SECRETO_PRUEBA = "secreto-webhook-test"


def _firmar(payload: dict) -> tuple[bytes, str]:
    crudo = json.dumps(payload).encode("utf-8")
    firma = ReglasTransaccion.calcular_firma_hmac(crudo, SECRETO_PRUEBA)
    return crudo, firma


def _tx_en_proceso(estado: EstadoTransaccion = EstadoTransaccion.EN_PROCESO) -> Transaccion:
    return Transaccion(
        transaccion_id="TX-9001",
        orden_id=5001,
        usuario_id=77,
        metodo_pago_id=2,
        monto=238000,
        moneda="COP",
        tasa_cambio=1,
        estado=estado,
    )


def _orden_pagada() -> OrdenParaCobro:
    return OrdenParaCobro(
        orden_id=5001,
        usuario_id=77,
        estado="PAGADA",
        total=238000,
        moneda="COP",
        tasa_cambio=1,
        expira_en=datetime.now(timezone.utc) + timedelta(minutes=10),
        items=[
            {
                "juegoId": 101,
                "titulo": "Aurora Quest",
                "reservaId": "res-9f1",
                "precioUnitario": 238000,
            }
        ],
    )


# ==============================================================================
# PRUEBAS UNITARIAS DE DOMINIO
# ==============================================================================
def test_dominio_firma_hmac_valida_e_invalida():
    cuerpo = b'{"transaccionId":"TX-9001"}'
    firma = ReglasTransaccion.calcular_firma_hmac(cuerpo, SECRETO_PRUEBA)
    ReglasTransaccion.verificar_firma_hmac(cuerpo, firma, SECRETO_PRUEBA)

    with pytest.raises(ErrorAplicacion) as exc:
        ReglasTransaccion.verificar_firma_hmac(cuerpo, "firma-falsa", SECRETO_PRUEBA)
    assert exc.value.status_code == 401
    assert exc.value.message == "Firma de la notificación de la pasarela inválida"


def test_dominio_validacion_monto_y_moneda():
    tx = _tx_en_proceso()
    ReglasTransaccion.validar_aprobacion_pasarela(tx, 238000, "COP")

    with pytest.raises(ErrorAplicacion) as exc:
        ReglasTransaccion.validar_aprobacion_pasarela(tx, 150000, "COP")
    assert exc.value.status_code == 409
    assert exc.value.message == "El monto o la moneda no coinciden con la orden"


def test_servicio_idempotencia_por_transaccion_id():
    tx_ya_aprobada = _tx_en_proceso(estado=EstadoTransaccion.APROBADA)
    repo = MagicMock()
    repo.obtener_por_transaccion_id.return_value = tx_ya_aprobada

    adaptador_ordenes = AsyncMock()
    cliente_pasarela = AsyncMock()
    adaptador_despacho = AsyncMock()

    servicio = ServicioTransacciones(
        repo,
        adaptador_ordenes,
        cliente_pasarela,
        adaptador_despacho=adaptador_despacho,
        secreto_webhook=SECRETO_PRUEBA,
    )

    payload = {
        "transaccionId": "TX-9001",
        "ordenId": 5001,
        "estado": "APROBADO",
        "referenciaPasarela": "SIM-77123",
        "monto": 238000,
        "moneda": "COP",
    }
    crudo, firma = _firmar(payload)
    from app.domain.transacciones import SolicitudNotificacionPasarela

    resultado = asyncio.run(
        servicio.procesar_aprobacion_pasarela(
            crudo, firma, SolicitudNotificacionPasarela(**payload)
        )
    )
    assert resultado == {
        "transaccionId": "TX-9001",
        "estado": "APROBADA",
        "estadoOrden": "PAGADA",
        "estadoDespacho": "ACTIVADO",
    }
    adaptador_despacho.activar_despacho_com10.assert_not_called()


def test_p02_reserva_expirada_marca_requiere_revision():
    repo = MagicMock()
    repo.obtener_por_transaccion_id.return_value = _tx_en_proceso()
    repo.actualizar_estado.side_effect = lambda **kw: _tx_en_proceso(estado=kw["nuevo_estado"])
    repo.crear_o_obtener_comprobante.side_effect = lambda comp, **kw: comp

    adaptador_ordenes = AsyncMock()
    adaptador_ordenes.notificar_resultado_com09.return_value = True
    adaptador_ordenes.obtener_orden_com08.return_value = _orden_pagada()

    adaptador_despacho = AsyncMock()
    adaptador_despacho.activar_despacho_com10.side_effect = ErrorReservaExpiradaDespacho()

    servicio = ServicioTransacciones(
        repo,
        adaptador_ordenes,
        AsyncMock(),
        adaptador_despacho=adaptador_despacho,
        secreto_webhook=SECRETO_PRUEBA,
    )

    payload = {
        "transaccionId": "TX-9001",
        "ordenId": 5001,
        "estado": "APROBADO",
        "referenciaPasarela": "SIM-77123",
        "monto": 238000,
        "moneda": "COP",
    }
    crudo, firma = _firmar(payload)
    from app.domain.transacciones import SolicitudNotificacionPasarela

    resultado = asyncio.run(
        servicio.procesar_aprobacion_pasarela(
            crudo, firma, SolicitudNotificacionPasarela(**payload)
        )
    )
    assert resultado["estado"] == "REQUIERE_REVISION"
    assert resultado["estadoDespacho"] == "REQUIERE_REVISION"


# ==============================================================================
# PRUEBAS FUNCIONALES DEL ENDPOINT POST /api/v1/pagos/notificacion-pasarela
# ==============================================================================
@pytest.fixture(autouse=True)
def limpiar_overrides():
    yield
    app.dependency_overrides.clear()


def _construir_servicio_mock(repo=None, adaptador_ordenes=None, adaptador_despacho=None):
    repo = repo or MagicMock()
    adaptador_ordenes = adaptador_ordenes or AsyncMock()
    adaptador_despacho = adaptador_despacho or AsyncMock()
    return ServicioTransacciones(
        repositorio=repo,
        adaptador_ordenes=adaptador_ordenes,
        cliente_pasarela=AsyncMock(),
        adaptador_despacho=adaptador_despacho,
        secreto_webhook=SECRETO_PRUEBA,
    )


def test_caso_1_y_2_flujo_exitoso_y_contrato():
    repo = MagicMock()
    repo.obtener_por_transaccion_id.return_value = _tx_en_proceso()
    repo.actualizar_estado.return_value = _tx_en_proceso(estado=EstadoTransaccion.APROBADA)
    repo.crear_o_obtener_comprobante.side_effect = lambda comp, **kw: Comprobante(
        comprobante_id=comp.comprobante_id,
        transaccion_id=comp.transaccion_id,
        orden_id=comp.orden_id,
        usuario_id=comp.usuario_id,
        fecha=comp.fecha,
        monto=comp.monto,
        moneda=comp.moneda,
        tasa_cambio=comp.tasa_cambio,
        referencia_pasarela=comp.referencia_pasarela,
    )

    adaptador_ordenes = AsyncMock()
    adaptador_ordenes.notificar_resultado_com09.return_value = True
    adaptador_ordenes.obtener_orden_com08.return_value = _orden_pagada()

    adaptador_despacho = AsyncMock()
    adaptador_despacho.activar_despacho_com10.return_value = {"estadoDespacho": "ACTIVADO"}

    app.dependency_overrides[obtener_servicio_transacciones] = lambda: _construir_servicio_mock(
        repo, adaptador_ordenes, adaptador_despacho
    )

    payload = {
        "transaccionId": "TX-9001",
        "ordenId": 5001,
        "estado": "APROBADO",
        "referenciaPasarela": "SIM-77123",
        "monto": 238000,
        "moneda": "COP",
    }
    crudo, firma = _firmar(payload)

    cliente = TestClient(app)
    respuesta = cliente.post(
        "/api/v1/pagos/notificacion-pasarela",
        content=crudo,
        headers={"Content-Type": "application/json", "X-Signature": firma},
    )
    cuerpo = respuesta.json()

    assert respuesta.status_code == 200
    assert set(cuerpo.keys()) == {"message", "data", "success"}
    assert cuerpo["success"] is True
    assert cuerpo["message"] == "Pago aprobado procesado"
    assert cuerpo["data"] == {
        "transaccionId": "TX-9001",
        "estado": "APROBADA",
        "estadoOrden": "PAGADA",
        "estadoDespacho": "ACTIVADO",
    }
    adaptador_ordenes.notificar_resultado_com09.assert_awaited_once_with(
        orden_id=5001, nuevo_estado="PAGADA", transaccion_id="TX-9001"
    )
    adaptador_despacho.activar_despacho_com10.assert_awaited_once()


def test_caso_3_error_401_firma_invalida():
    app.dependency_overrides[obtener_servicio_transacciones] = lambda: _construir_servicio_mock()
    payload = {
        "transaccionId": "TX-9001",
        "ordenId": 5001,
        "estado": "APROBADO",
        "referenciaPasarela": "SIM-77123",
        "monto": 238000,
        "moneda": "COP",
    }
    cliente = TestClient(app)
    respuesta = cliente.post(
        "/api/v1/pagos/notificacion-pasarela",
        json=payload,
        headers={"X-Signature": "firma-incorrecta"},
    )
    assert respuesta.status_code == 401
    assert respuesta.json() == {
        "message": "Firma de la notificación de la pasarela inválida",
        "data": None,
        "success": False,
    }


def test_caso_4_error_404_transaccion_desconocida():
    repo = MagicMock()
    repo.obtener_por_transaccion_id.return_value = None
    app.dependency_overrides[obtener_servicio_transacciones] = lambda: _construir_servicio_mock(
        repo
    )

    payload = {
        "transaccionId": "TX-INEXISTENTE",
        "ordenId": 5001,
        "estado": "APROBADO",
        "referenciaPasarela": "SIM-77123",
        "monto": 238000,
        "moneda": "COP",
    }
    crudo, firma = _firmar(payload)
    cliente = TestClient(app)
    respuesta = cliente.post(
        "/api/v1/pagos/notificacion-pasarela",
        content=crudo,
        headers={"Content-Type": "application/json", "X-Signature": firma},
    )
    assert respuesta.status_code == 404
    assert respuesta.json() == {
        "message": "La transacción indicada no existe",
        "data": None,
        "success": False,
    }


def test_caso_5_error_409_monto_distinto():
    repo = MagicMock()
    repo.obtener_por_transaccion_id.return_value = _tx_en_proceso()
    app.dependency_overrides[obtener_servicio_transacciones] = lambda: _construir_servicio_mock(
        repo
    )

    payload = {
        "transaccionId": "TX-9001",
        "ordenId": 5001,
        "estado": "APROBADO",
        "referenciaPasarela": "SIM-77123",
        "monto": 100000,
        "moneda": "COP",
    }
    crudo, firma = _firmar(payload)
    cliente = TestClient(app)
    respuesta = cliente.post(
        "/api/v1/pagos/notificacion-pasarela",
        content=crudo,
        headers={"Content-Type": "application/json", "X-Signature": firma},
    )
    assert respuesta.status_code == 409
    assert respuesta.json() == {
        "message": "El monto o la moneda no coinciden con la orden",
        "data": None,
        "success": False,
    }


def test_caso_6_error_409_transaccion_fallida_recibiendo_aprobado():
    repo = MagicMock()
    repo.obtener_por_transaccion_id.return_value = _tx_en_proceso(
        estado=EstadoTransaccion.FALLIDA
    )
    app.dependency_overrides[obtener_servicio_transacciones] = lambda: _construir_servicio_mock(
        repo
    )

    payload = {
        "transaccionId": "TX-9001",
        "ordenId": 5001,
        "estado": "APROBADO",
        "referenciaPasarela": "SIM-77123",
        "monto": 238000,
        "moneda": "COP",
    }
    crudo, firma = _firmar(payload)
    cliente = TestClient(app)
    respuesta = cliente.post(
        "/api/v1/pagos/notificacion-pasarela",
        content=crudo,
        headers={"Content-Type": "application/json", "X-Signature": firma},
    )
    assert respuesta.status_code == 409
    assert respuesta.json() == {
        "message": "La transacción ya fue resuelta con otro estado",
        "data": None,
        "success": False,
    }


def test_caso_7_error_503_base_de_datos_no_disponible():
    repo = MagicMock()
    repo.obtener_por_transaccion_id.side_effect = ErrorAplicacion(
        503, "No fue posible procesar la aprobación del pago"
    )
    app.dependency_overrides[obtener_servicio_transacciones] = lambda: _construir_servicio_mock(
        repo
    )

    payload = {
        "transaccionId": "TX-9001",
        "ordenId": 5001,
        "estado": "APROBADO",
        "referenciaPasarela": "SIM-77123",
        "monto": 238000,
        "moneda": "COP",
    }
    crudo, firma = _firmar(payload)
    cliente = TestClient(app)
    respuesta = cliente.post(
        "/api/v1/pagos/notificacion-pasarela",
        content=crudo,
        headers={"Content-Type": "application/json", "X-Signature": firma},
    )
    assert respuesta.status_code == 503
    assert respuesta.json() == {
        "message": "No fue posible procesar la aprobación del pago",
        "data": None,
        "success": False,
    }