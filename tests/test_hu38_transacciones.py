import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.api.transacciones import obtener_servicio_transacciones
from app.core.respuestas import ErrorAplicacion
from app.core.seguridad import UsuarioAutenticado, obtener_usuario_autenticado
from app.domain.transacciones import (
    EstadoTransaccion,
    ReglasTransaccion,
    SolicitudNotificacionPasarela,
    Transaccion,
)
from app.services.servicio_transacciones import ServicioTransacciones
from main import app

SECRETO_PRUEBA = "secreto-webhook-test"


def _firmar(payload: dict) -> tuple[bytes, str]:
    crudo = json.dumps(payload).encode("utf-8")
    firma = ReglasTransaccion.calcular_firma_hmac(crudo, SECRETO_PRUEBA)
    return crudo, firma


def _tx(
    estado: EstadoTransaccion = EstadoTransaccion.EN_PROCESO,
    usuario_id: int = 77,
    mensaje_usuario: str | None = None,
) -> Transaccion:
    return Transaccion(
        transaccion_id="TX-9001",
        orden_id=5001,
        usuario_id=usuario_id,
        metodo_pago_id=2,
        monto=238000,
        moneda="COP",
        tasa_cambio=1,
        estado=estado,
        mensaje_usuario=mensaje_usuario,
    )


# ==============================================================================
# PRUEBAS UNITARIAS DE DOMINIO (Mapeo de estados y mensajes al usuario)
# ==============================================================================
def test_dominio_mapeo_rechazado_fallido_expirado():
    est_rec, msg_rec, usr_rec = ReglasTransaccion.mapear_rechazo_pasarela("RECHAZADO")
    assert est_rec == EstadoTransaccion.FALLIDA
    assert msg_rec == "Pago rechazado procesado"
    assert usr_rec == "El pago fue rechazado. Genera una nueva orden para reintentar."

    est_fal, _, usr_fal = ReglasTransaccion.mapear_rechazo_pasarela("FALLIDO")
    assert est_fal == EstadoTransaccion.FALLIDA
    assert "falló" in usr_fal

    est_exp, _, usr_exp = ReglasTransaccion.mapear_rechazo_pasarela("EXPIRADO")
    assert est_exp == EstadoTransaccion.EXPIRADA
    assert "expiró" in usr_exp


def test_servicio_idempotencia_rechazo_ya_fallida():
    tx_fallida = _tx(
        estado=EstadoTransaccion.FALLIDA,
        mensaje_usuario="El pago fue rechazado. Genera una nueva orden para reintentar.",
    )
    repo = MagicMock()
    repo.obtener_por_transaccion_id.return_value = tx_fallida
    adaptador_ordenes = AsyncMock()

    servicio = ServicioTransacciones(
        repositorio=repo,
        adaptador_ordenes=adaptador_ordenes,
        cliente_pasarela=AsyncMock(),
        secreto_webhook=SECRETO_PRUEBA,
    )

    payload = {
        "transaccionId": "TX-9001",
        "ordenId": 5001,
        "estado": "RECHAZADO",
        "motivo": "FONDOS_INSUFICIENTES",
    }
    crudo, firma = _firmar(payload)
    mensaje, datos = asyncio.run(
        servicio.procesar_rechazo_pasarela(
            crudo, firma, SolicitudNotificacionPasarela(**payload)
        )
    )
    assert mensaje == "Pago rechazado procesado"
    assert datos["estado"] == "FALLIDA"
    assert datos["estadoOrden"] == "CANCELADA"
    adaptador_ordenes.notificar_resultado_com09.assert_not_called()


# ==============================================================================
# PRUEBAS FUNCIONALES DEL ENDPOINT POST /api/v1/pagos/notificacion-pasarela
# ==============================================================================
@pytest.fixture(autouse=True)
def limpiar_overrides():
    yield
    app.dependency_overrides.clear()


def _construir_servicio_mock(repo=None, adaptador_ordenes=None):
    return ServicioTransacciones(
        repositorio=repo or MagicMock(),
        adaptador_ordenes=adaptador_ordenes or AsyncMock(),
        cliente_pasarela=AsyncMock(),
        secreto_webhook=SECRETO_PRUEBA,
    )


def test_caso_1_y_2_rechazo_exitoso_y_contrato():
    repo = MagicMock()
    repo.obtener_por_transaccion_id.return_value = _tx(EstadoTransaccion.EN_PROCESO)
    repo.actualizar_estado.side_effect = lambda **kw: _tx(
        estado=kw["nuevo_estado"],
        mensaje_usuario=kw["mensaje_usuario"],
    )

    adaptador_ordenes = AsyncMock()
    adaptador_ordenes.notificar_resultado_com09.return_value = True

    app.dependency_overrides[obtener_servicio_transacciones] = lambda: _construir_servicio_mock(
        repo, adaptador_ordenes
    )

    payload = {
        "transaccionId": "TX-9001",
        "ordenId": 5001,
        "estado": "RECHAZADO",
        "motivo": "FONDOS_INSUFICIENTES",
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
    assert cuerpo["message"] == "Pago rechazado procesado"
    assert cuerpo["data"] == {
        "transaccionId": "TX-9001",
        "estado": "FALLIDA",
        "estadoOrden": "CANCELADA",
        "mensajeUsuario": "El pago fue rechazado. Genera una nueva orden para reintentar.",
    }
    # Verifica que MOD-05 delega cancelación vía COM-09 y NO libera inventario directamente
    adaptador_ordenes.notificar_resultado_com09.assert_awaited_once_with(
        orden_id=5001, nuevo_estado="CANCELADA", transaccion_id="TX-9001"
    )


def test_notificacion_expirado_cambia_a_expirada_y_cancela_orden():
    repo = MagicMock()
    repo.obtener_por_transaccion_id.return_value = _tx(EstadoTransaccion.EN_PROCESO)
    repo.actualizar_estado.side_effect = lambda **kw: _tx(
        estado=kw["nuevo_estado"],
        mensaje_usuario=kw["mensaje_usuario"],
    )
    adaptador_ordenes = AsyncMock()
    adaptador_ordenes.notificar_resultado_com09.return_value = True

    app.dependency_overrides[obtener_servicio_transacciones] = lambda: _construir_servicio_mock(
        repo, adaptador_ordenes
    )

    payload = {
        "transaccionId": "TX-9001",
        "ordenId": 5001,
        "estado": "EXPIRADO",
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
    assert cuerpo["data"]["estado"] == "EXPIRADA"
    assert cuerpo["data"]["estadoOrden"] == "CANCELADA"


def test_caso_3_error_401_firma_invalida():
    app.dependency_overrides[obtener_servicio_transacciones] = lambda: _construir_servicio_mock()
    payload = {
        "transaccionId": "TX-9001",
        "ordenId": 5001,
        "estado": "RECHAZADO",
        "motivo": "FONDOS_INSUFICIENTES",
    }
    cliente = TestClient(app)
    respuesta = cliente.post(
        "/api/v1/pagos/notificacion-pasarela",
        json=payload,
        headers={"X-Signature": "firma-invalida"},
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
        "transaccionId": "TX-DESCONOCIDA",
        "ordenId": 5001,
        "estado": "RECHAZADO",
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


def test_caso_5_error_409_transaccion_aprobada_recibiendo_rechazado():
    repo = MagicMock()
    repo.obtener_por_transaccion_id.return_value = _tx(EstadoTransaccion.APROBADA)
    app.dependency_overrides[obtener_servicio_transacciones] = lambda: _construir_servicio_mock(
        repo
    )

    payload = {
        "transaccionId": "TX-9001",
        "ordenId": 5001,
        "estado": "RECHAZADO",
        "motivo": "FONDOS_INSUFICIENTES",
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


def test_caso_6_error_503_base_de_datos_caida():
    repo = MagicMock()
    repo.obtener_por_transaccion_id.side_effect = ErrorAplicacion(
        503, "No fue posible procesar el rechazo del pago"
    )
    app.dependency_overrides[obtener_servicio_transacciones] = lambda: _construir_servicio_mock(
        repo
    )

    payload = {
        "transaccionId": "TX-9001",
        "ordenId": 5001,
        "estado": "RECHAZADO",
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
        "message": "No fue posible procesar el rechazo del pago",
        "data": None,
        "success": False,
    }


# ==============================================================================
# PRUEBAS FUNCIONALES DEL ENDPOINT GET /api/v1/pagos/{transaccionId}/estado
# ==============================================================================
def test_get_estado_pago_exitoso():
    repo = MagicMock()
    repo.obtener_por_transaccion_id.return_value = _tx(
        estado=EstadoTransaccion.FALLIDA,
        usuario_id=77,
        mensaje_usuario="El pago fue rechazado. Genera una nueva orden para reintentar.",
    )
    app.dependency_overrides[obtener_usuario_autenticado] = lambda: UsuarioAutenticado(
        id=77, rol="CLIENTE"
    )
    app.dependency_overrides[obtener_servicio_transacciones] = lambda: _construir_servicio_mock(
        repo
    )

    cliente = TestClient(app)
    respuesta = cliente.get("/api/v1/pagos/TX-9001/estado")
    assert respuesta.status_code == 200
    assert respuesta.json() == {
        "message": "Consulta de estado de pago exitosa",
        "data": {
            "transaccionId": "TX-9001",
            "ordenId": 5001,
            "estado": "FALLIDA",
            "mensajeUsuario": "El pago fue rechazado. Genera una nueva orden para reintentar.",
        },
        "success": True,
    }


def test_get_estado_pago_404_transaccion_ajena():
    repo = MagicMock()
    repo.obtener_por_transaccion_id.return_value = _tx(
        estado=EstadoTransaccion.FALLIDA, usuario_id=99
    )
    app.dependency_overrides[obtener_usuario_autenticado] = lambda: UsuarioAutenticado(
        id=77, rol="CLIENTE"
    )
    app.dependency_overrides[obtener_servicio_transacciones] = lambda: _construir_servicio_mock(
        repo
    )

    cliente = TestClient(app)
    respuesta = cliente.get("/api/v1/pagos/TX-9001/estado")
    assert respuesta.status_code == 404
    assert respuesta.json() == {
        "message": "La transacción indicada no existe",
        "data": None,
        "success": False,
    }


def test_get_estado_pago_401_sin_token():
    cliente = TestClient(app)
    respuesta = cliente.get("/api/v1/pagos/TX-9001/estado")
    assert respuesta.status_code == 401
    assert respuesta.json() == {
        "message": "Token inválido, expirado o ausente",
        "data": None,
        "success": False,
    }