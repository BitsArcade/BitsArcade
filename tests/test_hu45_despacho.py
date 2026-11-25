from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.base_datos import Base, get_db
from app.core.respuestas import ErrorAplicacion
from app.domain.despacho import (
    LicenciaUsuario,
    LicenciaUsuarioORM,
    ReglasDespacho,
)
from app.domain.inventario import KeyLicencia
from app.repositories.repositorio_despacho import RepositorioDespacho
from app.services.servicio_despacho import ServicioDespacho
from main import app


def _crear_sesion_memoria():
    motor = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=motor)
    Sesion = sessionmaker(autocommit=False, autoflush=False, bind=motor)
    return Sesion()


def _crear_key_inventario_si_aplica(db, orden_id: int, juego_id: int, reserva_id: str, codigo: str):
    kwargs = {
        "juego_id": juego_id,
        "estado": "RESERVADA",
    }
    if hasattr(KeyLicencia, "plataforma"):
        kwargs["plataforma"] = "PC"
    if hasattr(KeyLicencia, "clave"):
        kwargs["clave"] = codigo
    elif hasattr(KeyLicencia, "clave_cifrada"):
        kwargs["clave_cifrada"] = codigo
    elif hasattr(KeyLicencia, "valor"):
        kwargs["valor"] = codigo
    if hasattr(KeyLicencia, "hash_clave"):
        kwargs["hash_clave"] = f"hash-{codigo}"
    if hasattr(KeyLicencia, "orden_id"):
        kwargs["orden_id"] = orden_id
    if hasattr(KeyLicencia, "reserva_id"):
        kwargs["reserva_id"] = reserva_id
    elif hasattr(KeyLicencia, "codigo_reserva"):
        kwargs["codigo_reserva"] = reserva_id

    key_obj = KeyLicencia(**kwargs)
    db.add(key_obj)
    db.commit()
    db.refresh(key_obj)
    return key_obj


# =====================================================================
# 1. PRUEBAS UNITARIAS DE DOMINIO E INMUTABILIDAD (HU-45 / RN-10)
# =====================================================================


def test_hu45_dominio_autoriza_orden_sin_entregas_previas():
    resultado = ReglasDespacho.validar_elegibilidad_entrega(
        orden_id=5001,
        reserva_ids=["res-9f1"],
        asignaciones_existentes=[],
    )
    assert resultado == {
        "ordenId": 5001,
        "autorizado": True,
        "items": [{"reservaId": "res-9f1", "entregada": False}],
    }


def test_hu45_dominio_idempotente_misma_orden_y_rechaza_otra_orden_409():
    asignacion_previa = LicenciaUsuario(
        licencia_id="LIC-1",
        despacho_id="DSP-4999",
        orden_id=4999,
        usuario_id=77,
        juego_id=101,
        titulo_juego="Aurora Quest",
        plataforma="PC",
        reserva_id="res-9f1",
        key_inventario_id=10,
        clave_digital="AAAAA-BBBBB-CCCCC-DDDDD",
        clave_enmascarada="AAAAA-BBBBB-CCCCC-****",
        revelada=False,
        revelada_en=None,
        asignada_en=datetime.now(timezone.utc),
    )

    # Reintentar sobre la misma orden 4999 es idempotente
    resultado_misma = ReglasDespacho.validar_elegibilidad_entrega(
        orden_id=4999,
        reserva_ids=["res-9f1"],
        asignaciones_existentes=[asignacion_previa],
    )
    assert resultado_misma["autorizado"] is True
    assert resultado_misma["items"] == [{"reservaId": "res-9f1", "entregada": True}]

    # Asignar la misma reserva a otra orden (5001) lanza 409
    with pytest.raises(ErrorAplicacion) as exc:
        ReglasDespacho.validar_elegibilidad_entrega(
            orden_id=5001,
            reserva_ids=["res-9f1"],
            asignaciones_existentes=[asignacion_previa],
        )
    assert exc.value.status_code == 409
    assert exc.value.message == "La licencia ya fue entregada y no puede reasignarse"


def test_hu45_bd_constraint_unico_impide_duplicar_reserva():
    db = _crear_sesion_memoria()
    try:
        primera = LicenciaUsuarioORM(
            licencia_id="LIC-1",
            despacho_id="DSP-1",
            orden_id=5001,
            usuario_id=77,
            juego_id=101,
            titulo_juego="Aurora Quest",
            plataforma="PC",
            reserva_id="res-9f1",
            key_inventario_id=1,
            clave_digital="AAAAA-BBBBB-CCCCC-11111",
            clave_enmascarada="AAAAA-BBBBB-CCCCC-****",
            huella_clave="huella-1",
            revelada=False,
            revelada_en=None,
            asignada_en=datetime.now(timezone.utc),
        )
        db.add(primera)
        db.commit()

        duplicada = LicenciaUsuarioORM(
            licencia_id="LIC-2",
            despacho_id="DSP-2",
            orden_id=5002,
            usuario_id=88,
            juego_id=101,
            titulo_juego="Aurora Quest",
            plataforma="PC",
            reserva_id="res-9f1",
            key_inventario_id=2,
            clave_digital="EEEEE-FFFFF-GGGGG-22222",
            clave_enmascarada="EEEEE-FFFFF-GGGGG-****",
            huella_clave="huella-2",
            revelada=False,
            revelada_en=None,
            asignada_en=datetime.now(timezone.utc),
        )
        db.add(duplicada)
        with pytest.raises(IntegrityError):
            db.commit()
    finally:
        db.rollback()
        db.close()


# =====================================================================
# 2. PRUEBAS FUNCIONALES DEL ENDPOINT GET /interno/v1/despacho/ordenes/{ordenId}/elegibilidad
# =====================================================================


def test_hu45_caso1_y_caso2_flujo_exitoso_y_contrato_json():
    db = _crear_sesion_memoria()
    try:
        _crear_key_inventario_si_aplica(
            db, orden_id=5001, juego_id=101, reserva_id="res-9f1", codigo="KEY-5001-1"
        )

        app.dependency_overrides[get_db] = lambda: db
        cliente = TestClient(app)

        respuesta = cliente.get(
            "/interno/v1/despacho/ordenes/5001/elegibilidad",
            params={"reservaId": "res-9f1"},
        )

        assert respuesta.status_code == 200
        cuerpo = respuesta.json()
        assert set(cuerpo.keys()) == {"message", "data", "success"}
        assert cuerpo["success"] is True
        assert cuerpo["message"] == "Entrega autorizada"

        data = cuerpo["data"]
        assert set(data.keys()) == {"ordenId", "autorizado", "items"}
        assert data["ordenId"] == 5001
        assert data["autorizado"] is True
        assert data["items"] == [{"reservaId": "res-9f1", "entregada": False}]
    finally:
        app.dependency_overrides.clear()
        db.close()


def test_hu45_caso3_error_409_reserva_ya_asignada_a_otra_orden():
    db = _crear_sesion_memoria()
    try:
        asignada_otra = LicenciaUsuarioORM(
            licencia_id="LIC-4999",
            despacho_id="DSP-4999",
            orden_id=4999,
            usuario_id=77,
            juego_id=101,
            titulo_juego="Aurora Quest",
            plataforma="PC",
            reserva_id="res-9f1",
            key_inventario_id=10,
            clave_digital="AAAAA-BBBBB-CCCCC-99999",
            clave_enmascarada="AAAAA-BBBBB-CCCCC-****",
            huella_clave="huella-4999",
            revelada=False,
            revelada_en=None,
            asignada_en=datetime.now(timezone.utc),
        )
        db.add(asignada_otra)
        db.commit()

        app.dependency_overrides[get_db] = lambda: db
        cliente = TestClient(app)

        respuesta = cliente.get(
            "/interno/v1/despacho/ordenes/5001/elegibilidad",
            params={"reservaId": "res-9f1"},
        )

        assert respuesta.status_code == 409
        cuerpo = respuesta.json()
        assert cuerpo["success"] is False
        assert cuerpo["data"] is None
        assert cuerpo["message"] == "La licencia ya fue entregada y no puede reasignarse"
    finally:
        app.dependency_overrides.clear()
        db.close()


def test_hu45_caso4_error_503_fallo_base_datos():
    sesion_mock = MagicMock()
    sesion_mock.query.side_effect = OperationalError("SELECT 1", {}, Exception("DB caída"))

    repo = RepositorioDespacho(sesion_mock)
    servicio = ServicioDespacho(repositorio=repo)

    with pytest.raises(ErrorAplicacion) as exc:
        servicio.validar_unicidad_entrega_orden(orden_id=5001)

    assert exc.value.status_code == 503
    assert exc.value.message == "No fue posible validar la entrega"