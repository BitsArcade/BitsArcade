from datetime import datetime, timezone
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
from app.domain.transacciones import (
    Comprobante,
    EstadoTransaccion,
    ReglasTransaccion,
    Transaccion,
)
from app.repositories.repositorio_transacciones import RepositorioTransacciones
from app.services.servicio_transacciones import ServicioTransacciones
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
        monto=57.35,
        moneda="USD",
        tasa_cambio=4150.25,
        estado=estado,
        referencia_pasarela="SIM-77123",
    )


def _comprobante(usuario_id: int = 77) -> Comprobante:
    return Comprobante(
        comprobante_id="CMP-8801",
        transaccion_id="TX-9001",
        orden_id=5001,
        usuario_id=usuario_id,
        fecha=datetime(2026, 11, 25, 1, 30, 0, tzinfo=timezone.utc),
        monto=57.35,
        moneda="USD",
        tasa_cambio=4150.25,
        referencia_pasarela="SIM-77123",
    )


# ==============================================================================
# PRUEBAS UNITARIAS DE DOMINIO Y PERSISTENCIA (Inmutabilidad y Unicidad)
# ==============================================================================
def test_dominio_comprobante_inmutable_frozen_dataclass():
    comp = _comprobante()
    with pytest.raises(AttributeError):
        comp.monto = 100.0  # type: ignore[misc]


def test_dominio_validar_comprobante_disponible_rechaza_no_aprobada():
    with pytest.raises(ErrorAplicacion) as exc:
        ReglasTransaccion.validar_comprobante_disponible(
            _tx(estado=EstadoTransaccion.EN_PROCESO)
        )
    assert exc.value.status_code == 409
    assert exc.value.message == "La transacción no está aprobada y no cuenta con comprobante"


def test_repositorio_unicidad_comprobante_por_transaccion():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    SessionTesting = sessionmaker(bind=engine)
    db = SessionTesting()
    try:
        repo = RepositorioTransacciones(db)
        primero = repo.crear_o_obtener_comprobante(_comprobante())
        segundo_intento = Comprobante(
            comprobante_id="CMP-OTRO99",
            transaccion_id="TX-9001",
            orden_id=5001,
            usuario_id=77,
            fecha=datetime.now(timezone.utc),
            monto=999.99,
            moneda="COP",
            tasa_cambio=1.0,
            referencia_pasarela="SIM-DUPLICADO",
        )
        resultado = repo.crear_o_obtener_comprobante(segundo_intento)

        assert resultado.comprobante_id == primero.comprobante_id == "CMP-8801"
        assert resultado.monto == 57.35
        assert resultado.moneda == "USD"
    finally:
        db.close()


# ==============================================================================
# PRUEBAS FUNCIONALES DE ENDPOINTS DE COMPROBANTES (HU-39)
# ==============================================================================
@pytest.fixture(autouse=True)
def limpiar_overrides():
    yield
    app.dependency_overrides.clear()


def _construir_servicio(repo: MagicMock) -> ServicioTransacciones:
    return ServicioTransacciones(
        repositorio=repo,
        adaptador_ordenes=AsyncMock(),
        cliente_pasarela=AsyncMock(),
    )


def test_get_comprobante_por_transaccion_exitoso():
    repo = MagicMock()
    repo.obtener_por_transaccion_id.return_value = _tx(EstadoTransaccion.APROBADA, usuario_id=77)
    repo.obtener_comprobante_por_transaccion_id.return_value = _comprobante(usuario_id=77)

    app.dependency_overrides[obtener_usuario_autenticado] = lambda: UsuarioAutenticado(
        id=77, rol="CLIENTE"
    )
    app.dependency_overrides[obtener_servicio_transacciones] = lambda: _construir_servicio(repo)

    cliente = TestClient(app)
    respuesta = cliente.get("/api/v1/pagos/TX-9001/comprobante")
    cuerpo = respuesta.json()

    assert respuesta.status_code == 200
    assert set(cuerpo.keys()) == {"message", "data", "success"}
    assert cuerpo["success"] is True
    assert cuerpo["message"] == "Consulta de comprobante exitosa"
    assert cuerpo["data"] == {
        "comprobanteId": "CMP-8801",
        "transaccionId": "TX-9001",
        "ordenId": 5001,
        "fecha": "2026-11-25T01:30:00+00:00",
        "monto": 57.35,
        "moneda": "USD",
        "tasaCambio": 4150.25,
        "referenciaPasarela": "SIM-77123",
    }


def test_get_comprobante_por_id_exitoso():
    repo = MagicMock()
    repo.obtener_comprobante_por_id.return_value = _comprobante(usuario_id=77)

    app.dependency_overrides[obtener_usuario_autenticado] = lambda: UsuarioAutenticado(
        id=77, rol="CLIENTE"
    )
    app.dependency_overrides[obtener_servicio_transacciones] = lambda: _construir_servicio(repo)

    cliente = TestClient(app)
    respuesta = cliente.get("/api/v1/pagos/comprobantes/CMP-8801")
    assert respuesta.status_code == 200
    assert respuesta.json()["data"]["comprobanteId"] == "CMP-8801"


def test_get_comprobante_404_transaccion_ajena():
    repo = MagicMock()
    repo.obtener_por_transaccion_id.return_value = _tx(EstadoTransaccion.APROBADA, usuario_id=99)

    app.dependency_overrides[obtener_usuario_autenticado] = lambda: UsuarioAutenticado(
        id=77, rol="CLIENTE"
    )
    app.dependency_overrides[obtener_servicio_transacciones] = lambda: _construir_servicio(repo)

    cliente = TestClient(app)
    respuesta = cliente.get("/api/v1/pagos/TX-9001/comprobante")
    assert respuesta.status_code == 404
    assert respuesta.json() == {
        "message": "La transacción indicada no existe",
        "data": None,
        "success": False,
    }


def test_get_comprobante_409_transaccion_no_aprobada():
    repo = MagicMock()
    repo.obtener_por_transaccion_id.return_value = _tx(EstadoTransaccion.FALLIDA, usuario_id=77)

    app.dependency_overrides[obtener_usuario_autenticado] = lambda: UsuarioAutenticado(
        id=77, rol="CLIENTE"
    )
    app.dependency_overrides[obtener_servicio_transacciones] = lambda: _construir_servicio(repo)

    cliente = TestClient(app)
    respuesta = cliente.get("/api/v1/pagos/TX-9001/comprobante")
    assert respuesta.status_code == 409
    assert respuesta.json() == {
        "message": "La transacción no está aprobada y no cuenta con comprobante",
        "data": None,
        "success": False,
    }


def test_get_comprobante_401_sin_token():
    cliente = TestClient(app)
    respuesta = cliente.get("/api/v1/pagos/TX-9001/comprobante")
    assert respuesta.status_code == 401
    assert respuesta.json() == {
        "message": "Token inválido, expirado o ausente",
        "data": None,
        "success": False,
    }


def test_get_comprobante_503_base_de_datos_caida():
    repo = MagicMock()
    repo.obtener_por_transaccion_id.side_effect = ErrorAplicacion(
        503, "No fue posible consultar el comprobante"
    )

    app.dependency_overrides[obtener_usuario_autenticado] = lambda: UsuarioAutenticado(
        id=77, rol="CLIENTE"
    )
    app.dependency_overrides[obtener_servicio_transacciones] = lambda: _construir_servicio(repo)

    cliente = TestClient(app)
    respuesta = cliente.get("/api/v1/pagos/TX-9001/comprobante")
    assert respuesta.status_code == 503
    assert respuesta.json() == {
        "message": "No fue posible consultar el comprobante",
        "data": None,
        "success": False,
    }