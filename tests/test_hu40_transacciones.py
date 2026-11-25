import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.transacciones import obtener_servicio_transacciones
from app.core.base_datos import Base
from app.core.respuestas import ErrorAplicacion
from app.core.seguridad import UsuarioAutenticado, obtener_usuario_autenticado
from app.domain.orden import Orden
from app.domain.transacciones import (
    EstadoTransaccion,
    ReglasTransaccion,
    Transaccion,
)
from app.services.servicio_transacciones import (
    AdaptadorOrdenesLocal,
    ServicioTransacciones,
)
from main import app


def _tx(
    estado: EstadoTransaccion = EstadoTransaccion.APROBADA,
    usuario_id: int = 77,
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
    )


# ==============================================================================
# PRUEBAS UNITARIAS DE DOMINIO E INTEGRACIÓN COM-09
# ==============================================================================
def test_dominio_mapeo_estado_final_orden():
    assert ReglasTransaccion.mapear_estado_final_orden(EstadoTransaccion.APROBADA) == "PAGADA"
    assert (
        ReglasTransaccion.mapear_estado_final_orden(EstadoTransaccion.REQUIERE_REVISION) == "PAGADA"
    )
    assert ReglasTransaccion.mapear_estado_final_orden(EstadoTransaccion.FALLIDA) == "CANCELADA"
    assert ReglasTransaccion.mapear_estado_final_orden(EstadoTransaccion.EXPIRADA) == "CANCELADA"

    with pytest.raises(ErrorAplicacion) as exc:
        ReglasTransaccion.mapear_estado_final_orden(EstadoTransaccion.EN_PROCESO)
    assert exc.value.status_code == 409


def test_dominio_transiciones_com09_idempotencia_e_irreversibilidad():
    # Ya en destino -> False (idempotente sin error)
    assert ReglasTransaccion.validar_transicion_orden_com09("PAGADA", "PAGADA") is False
    assert ReglasTransaccion.validar_transicion_orden_com09("CANCELADA", "CANCELADA") is False

    # Transiciones válidas desde PROCESANDO -> True
    assert ReglasTransaccion.validar_transicion_orden_com09("PROCESANDO", "PAGADA") is True
    assert ReglasTransaccion.validar_transicion_orden_com09("PROCESANDO", "CANCELADA") is True

    # CANCELADA es irreversible -> 409
    with pytest.raises(ErrorAplicacion) as exc:
        ReglasTransaccion.validar_transicion_orden_com09("CANCELADA", "PAGADA")
    assert exc.value.status_code == 409
    assert exc.value.message == "Transición de estado no permitida"


def test_adaptador_com09_sqlite_memoria_pagada_cancelada_e_irreversible():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    SessionTesting = sessionmaker(bind=engine)
    db = SessionTesting()
    try:
        ahora = datetime.now(timezone.utc)
        columnas_orden = {col.name for col in Orden.__table__.columns}
        kwargs_orden: dict = {
            "id": 5001,
            "usuario_id": 77,
            "estado": "PROCESANDO",
            "total": 238000,
            "moneda": "COP",
        }
        if "tasa_cambio_congelada" in columnas_orden:
            kwargs_orden["tasa_cambio_congelada"] = 1.0
        elif "tasa_cambio" in columnas_orden:
            kwargs_orden["tasa_cambio"] = 1.0

        if "fecha_expiracion_reserva" in columnas_orden:
            kwargs_orden["fecha_expiracion_reserva"] = ahora + timedelta(minutes=10)
        elif "expira_en" in columnas_orden:
            kwargs_orden["expira_en"] = ahora + timedelta(minutes=10)

        orden = Orden(**kwargs_orden)
        db.add(orden)
        db.commit()

        adaptador = AdaptadorOrdenesLocal(db)
        assert asyncio.run(adaptador.notificar_resultado_com09(5001, "CANCELADA", "TX-9001")) is True
        db.refresh(orden)
        assert orden.estado == "CANCELADA"

        # Reintento idempotente sobre CANCELADA -> True
        assert asyncio.run(adaptador.notificar_resultado_com09(5001, "CANCELADA", "TX-9001")) is True

        # Intentar pasar de CANCELADA a PAGADA -> 409
        with pytest.raises(ErrorAplicacion) as exc:
            asyncio.run(adaptador.notificar_resultado_com09(5001, "PAGADA", "TX-9001"))
        assert exc.value.status_code == 409
    finally:
        db.close()


# ==============================================================================
# PRUEBAS FUNCIONALES DEL ENDPOINT POST /api/v1/pagos/{transaccionId}/sincronizar-orden
# ==============================================================================
@pytest.fixture(autouse=True)
def limpiar_overrides():
    yield
    app.dependency_overrides.clear()


def _construir_servicio(repo: MagicMock, adaptador_ordenes: AsyncMock) -> ServicioTransacciones:
    return ServicioTransacciones(
        repositorio=repo,
        adaptador_ordenes=adaptador_ordenes,
        cliente_pasarela=AsyncMock(),
    )


def test_sincronizar_orden_aprobada_a_pagada():
    repo = MagicMock()
    repo.obtener_por_transaccion_id.return_value = _tx(EstadoTransaccion.APROBADA, usuario_id=77)
    adaptador_ordenes = AsyncMock()
    adaptador_ordenes.notificar_resultado_com09.return_value = True

    app.dependency_overrides[obtener_usuario_autenticado] = lambda: UsuarioAutenticado(
        id=77, rol="CLIENTE"
    )
    app.dependency_overrides[obtener_servicio_transacciones] = lambda: _construir_servicio(
        repo, adaptador_ordenes
    )

    cliente = TestClient(app)
    respuesta = cliente.post("/api/v1/pagos/TX-9001/sincronizar-orden")
    cuerpo = respuesta.json()

    assert respuesta.status_code == 200
    assert cuerpo == {
        "message": "Estado final de la orden actualizado",
        "data": {
            "transaccionId": "TX-9001",
            "ordenId": 5001,
            "estadoTransaccion": "APROBADA",
            "estadoOrden": "PAGADA",
            "sincronizado": True,
        },
        "success": True,
    }
    adaptador_ordenes.notificar_resultado_com09.assert_awaited_once_with(
        orden_id=5001, nuevo_estado="PAGADA", transaccion_id="TX-9001"
    )


def test_sincronizar_orden_fallida_a_cancelada():
    repo = MagicMock()
    repo.obtener_por_transaccion_id.return_value = _tx(EstadoTransaccion.FALLIDA, usuario_id=77)
    adaptador_ordenes = AsyncMock()
    adaptador_ordenes.notificar_resultado_com09.return_value = True

    app.dependency_overrides[obtener_usuario_autenticado] = lambda: UsuarioAutenticado(
        id=77, rol="CLIENTE"
    )
    app.dependency_overrides[obtener_servicio_transacciones] = lambda: _construir_servicio(
        repo, adaptador_ordenes
    )

    cliente = TestClient(app)
    respuesta = cliente.post("/api/v1/pagos/TX-9001/sincronizar-orden")
    assert respuesta.status_code == 200
    assert respuesta.json()["data"]["estadoOrden"] == "CANCELADA"


def test_sincronizar_orden_409_transaccion_en_proceso():
    repo = MagicMock()
    repo.obtener_por_transaccion_id.return_value = _tx(EstadoTransaccion.EN_PROCESO, usuario_id=77)
    adaptador_ordenes = AsyncMock()

    app.dependency_overrides[obtener_usuario_autenticado] = lambda: UsuarioAutenticado(
        id=77, rol="CLIENTE"
    )
    app.dependency_overrides[obtener_servicio_transacciones] = lambda: _construir_servicio(
        repo, adaptador_ordenes
    )

    cliente = TestClient(app)
    respuesta = cliente.post("/api/v1/pagos/TX-9001/sincronizar-orden")
    assert respuesta.status_code == 409
    assert respuesta.json() == {
        "message": "La transacción aún se encuentra en proceso y no tiene estado final",
        "data": None,
        "success": False,
    }


def test_sincronizar_orden_404_transaccion_ajena():
    repo = MagicMock()
    repo.obtener_por_transaccion_id.return_value = _tx(EstadoTransaccion.APROBADA, usuario_id=99)
    adaptador_ordenes = AsyncMock()

    app.dependency_overrides[obtener_usuario_autenticado] = lambda: UsuarioAutenticado(
        id=77, rol="CLIENTE"
    )
    app.dependency_overrides[obtener_servicio_transacciones] = lambda: _construir_servicio(
        repo, adaptador_ordenes
    )

    cliente = TestClient(app)
    respuesta = cliente.post("/api/v1/pagos/TX-9001/sincronizar-orden")
    assert respuesta.status_code == 404
    assert respuesta.json() == {
        "message": "La transacción indicada no existe",
        "data": None,
        "success": False,
    }


def test_sincronizar_orden_401_sin_token():
    cliente = TestClient(app)
    respuesta = cliente.post("/api/v1/pagos/TX-9001/sincronizar-orden")
    assert respuesta.status_code == 401
    assert respuesta.json() == {
        "message": "Token inválido, expirado o ausente",
        "data": None,
        "success": False,
    }


def test_sincronizar_orden_503_error_com09():
    repo = MagicMock()
    repo.obtener_por_transaccion_id.return_value = _tx(EstadoTransaccion.APROBADA, usuario_id=77)
    adaptador_ordenes = AsyncMock()
    adaptador_ordenes.notificar_resultado_com09.side_effect = ErrorAplicacion(
        503, "No fue posible procesar la aprobación del pago"
    )

    app.dependency_overrides[obtener_usuario_autenticado] = lambda: UsuarioAutenticado(
        id=77, rol="CLIENTE"
    )
    app.dependency_overrides[obtener_servicio_transacciones] = lambda: _construir_servicio(
        repo, adaptador_ordenes
    )

    cliente = TestClient(app)
    respuesta = cliente.post("/api/v1/pagos/TX-9001/sincronizar-orden")
    assert respuesta.status_code == 503
    assert respuesta.json()["success"] is False