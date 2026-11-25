from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.despacho import obtener_servicio_despacho
from app.core.base_datos import Base, get_db
from app.core.respuestas import ErrorAplicacion
from app.domain.despacho import (
    ReglasDespacho,
    SolicitudDespachoCOM10,
)
from app.domain.inventario import KeyLicencia
from app.domain.orden import Orden
from app.repositories.repositorio_despacho import RepositorioDespacho
from app.services.servicio_despacho import (
    AdaptadorOrdenYInventarioLocal,
    ServicioDespacho,
)
from main import app


def _payload_com10(orden_id: int = 5001, usuario_id: int = 77) -> dict:
    return {
        "ordenId": orden_id,
        "usuarioId": usuario_id,
        "transaccionId": "TX-9001",
        "moneda": "COP",
        "tasaCambio": 1.0,
        "total": 238000,
        "items": [
            {
                "juegoId": 101,
                "titulo": "Aurora Quest",
                "reservaId": "res-9f1",
                "precioUnitario": 238000,
            }
        ],
    }


def _crear_sesion_memoria():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    SessionTesting = sessionmaker(bind=engine)
    return SessionTesting()


def _insertar_orden_y_key(
    db,
    orden_id: int = 5001,
    usuario_id: int = 77,
    estado_orden: str = "PAGADA",
    estado_key: str = "RESERVADA",
    expira_en: datetime | None = None,
):
    ahora = datetime.now(timezone.utc)
    expiracion = expira_en or (ahora + timedelta(minutes=10))
    kwargs_orden: dict = {
        "id": orden_id,
        "usuario_id": usuario_id,
        "estado": estado_orden,
        "total": 238000,
        "moneda": "COP",
    }
    for col in Orden.__table__.columns:
        if "tasa" in col.name:
            kwargs_orden[col.name] = 1.0
        elif "expir" in col.name or "hasta" in col.name:
            kwargs_orden[col.name] = expiracion

    orden = Orden(**kwargs_orden)
    db.add(orden)

    kwargs_key: dict = {
        "juego_id": 101,
        "estado": estado_key,
    }
    for col in KeyLicencia.__table__.columns:
        if col.name == "plataforma":
            kwargs_key["plataforma"] = "PC"
        elif col.name == "orden_id":
            kwargs_key["orden_id"] = orden_id
        elif "expir" in col.name or "hasta" in col.name:
            kwargs_key[col.name] = expiracion

    key = KeyLicencia(**kwargs_key)
    db.add(key)
    db.commit()
    db.refresh(key)
    return orden, key


# ==============================================================================
# PRUEBAS UNITARIAS DE DOMINIO E INTEGRACIÓN EN BD EN MEMORIA
# ==============================================================================
def test_dominio_generacion_clave_y_enmascarado():
    clave, enmascarada, huella = ReglasDespacho.generar_clave_digital(5001, 101, 1)
    partes = clave.split("-")
    assert len(partes) == 4
    assert all(len(p) == 4 for p in partes)
    assert enmascarada.endswith("-****")
    assert enmascarada.startswith(f"{partes[0]}-{partes[1]}-{partes[2]}-")
    assert len(huella) == 64


def test_dominio_rechaza_orden_no_pagada():
    with pytest.raises(ErrorAplicacion) as exc:
        ReglasDespacho.validar_orden_elegible_despacho("PROCESANDO")
    assert exc.value.status_code == 409
    assert exc.value.message == "La orden no está en estado PAGADA y no es elegible para despacho"


def test_servicio_despacho_completo_e_idempotente_sqlite():
    db = _crear_sesion_memoria()
    try:
        _, key = _insertar_orden_y_key(db, estado_orden="PAGADA", estado_key="RESERVADA")
        servicio = ServicioDespacho(
            repositorio=RepositorioDespacho(db),
            adaptador_inventario=AdaptadorOrdenYInventarioLocal(db),
        )
        solicitud = SolicitudDespachoCOM10(**_payload_com10())

        primero = servicio.ejecutar_despacho_com10(solicitud)
        assert primero["ordenId"] == 5001
        assert primero["estadoDespacho"] == "ACTIVADO"
        assert len(primero["licenciasAsignadas"]) == 1
        assert primero["licenciasAsignadas"][0]["revelada"] is False
        assert primero["licenciasAsignadas"][0]["claveEnmascarada"].endswith("-****")

        db.refresh(key)
        assert key.estado == "VENDIDA"

        segundo = servicio.ejecutar_despacho_com10(solicitud)
        assert segundo["despachoId"] == primero["despachoId"]
        assert (
            segundo["licenciasAsignadas"][0]["licenciaId"]
            == primero["licenciasAsignadas"][0]["licenciaId"]
        )
    finally:
        db.close()


# ==============================================================================
# PRUEBAS FUNCIONALES DEL ENDPOINT POST /interno/v1/despacho/ordenes (COM-10)
# ==============================================================================
@pytest.fixture(autouse=True)
def limpiar_overrides():
    yield
    app.dependency_overrides.clear()


def test_endpoint_com10_exitoso():
    db = _crear_sesion_memoria()
    try:
        _insertar_orden_y_key(db, estado_orden="PAGADA", estado_key="RESERVADA")
        app.dependency_overrides[get_db] = lambda: db

        cliente = TestClient(app)
        respuesta = cliente.post("/interno/v1/despacho/ordenes", json=_payload_com10())
        cuerpo = respuesta.json()

        assert respuesta.status_code == 200
        assert set(cuerpo.keys()) == {"message", "data", "success"}
        assert cuerpo["success"] is True
        assert cuerpo["message"] == "Licencias digitales asignadas al usuario"
        assert cuerpo["data"]["ordenId"] == 5001
        assert cuerpo["data"]["usuarioId"] == 77
        assert cuerpo["data"]["estadoDespacho"] == "ACTIVADO"
        assert len(cuerpo["data"]["licenciasAsignadas"]) == 1
    finally:
        db.close()


def test_endpoint_com10_404_orden_inexistente():
    db = _crear_sesion_memoria()
    try:
        app.dependency_overrides[get_db] = lambda: db
        cliente = TestClient(app)
        respuesta = cliente.post("/interno/v1/despacho/ordenes", json=_payload_com10())
        assert respuesta.status_code == 404
        assert respuesta.json() == {
            "message": "La orden indicada no existe",
            "data": None,
            "success": False,
        }
    finally:
        db.close()


def test_endpoint_com10_409_orden_no_pagada():
    db = _crear_sesion_memoria()
    try:
        _insertar_orden_y_key(db, estado_orden="PENDIENTE", estado_key="RESERVADA")
        app.dependency_overrides[get_db] = lambda: db

        cliente = TestClient(app)
        respuesta = cliente.post("/interno/v1/despacho/ordenes", json=_payload_com10())
        assert respuesta.status_code == 409
        assert respuesta.json() == {
            "message": "La orden no está en estado PAGADA y no es elegible para despacho",
            "data": None,
            "success": False,
        }
    finally:
        db.close()


def test_endpoint_com10_409_reserva_expirada_p02():
    db = _crear_sesion_memoria()
    try:
        _insertar_orden_y_key(
            db,
            estado_orden="PAGADA",
            estado_key="EXPIRADA",
            expira_en=datetime.now(timezone.utc) - timedelta(minutes=5),
        )
        app.dependency_overrides[get_db] = lambda: db

        cliente = TestClient(app)
        respuesta = cliente.post("/interno/v1/despacho/ordenes", json=_payload_com10())
        assert respuesta.status_code == 409
        assert respuesta.json()["success"] is False
    finally:
        db.close()


def test_endpoint_com10_503_error_base_de_datos():
    repo_mock = MagicMock()
    repo_mock.obtener_despacho_por_orden_id.side_effect = ErrorAplicacion(
        503, "No fue posible procesar el despacho de la orden"
    )
    app.dependency_overrides[obtener_servicio_despacho] = lambda: ServicioDespacho(
        repositorio=repo_mock,
        adaptador_inventario=MagicMock(),
    )

    cliente = TestClient(app)
    respuesta = cliente.post("/interno/v1/despacho/ordenes", json=_payload_com10())
    assert respuesta.status_code == 503
    assert respuesta.json() == {
        "message": "No fue posible procesar el despacho de la orden",
        "data": None,
        "success": False,
    }