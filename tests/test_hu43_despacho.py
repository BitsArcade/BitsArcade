from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.base_datos import Base, get_db
from app.core.respuestas import ErrorAplicacion
from app.core.seguridad import UsuarioAutenticado, obtener_usuario_autenticado
from app.domain.despacho import (
    INSTRUCCION_ACTIVACION_ESTANDAR,
    LicenciaUsuario,
    LicenciaUsuarioORM,
    ReglasDespacho,
)
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


def _insertar_licencia(
    db,
    licencia_id: str = "LIC-8001",
    usuario_id: int = 10,
    juego_id: int = 101,
    clave_digital: str = "ABCD1234EFGH5678",
) -> LicenciaUsuarioORM:
    registro = LicenciaUsuarioORM(
        licencia_id=licencia_id,
        despacho_id="DSP-9001",
        orden_id=5001,
        usuario_id=usuario_id,
        juego_id=juego_id,
        titulo_juego="Cyberpunk 2077",
        plataforma="PC",
        reserva_id="RES-01",
        key_inventario_id=1,
        clave_digital=clave_digital,
        clave_enmascarada="ABCD-1234-EFGH-****",
        huella_clave=f"huella-{licencia_id}",
        revelada=False,
        revelada_en=None,
        asignada_en=datetime(2026, 10, 25, 10, 0, 0, tzinfo=timezone.utc),
    )
    db.add(registro)
    db.commit()
    db.refresh(registro)
    return registro


# =====================================================================
# 1. PRUEBAS UNITARIAS DE DOMINIO (HU-43)
# =====================================================================


def test_hu43_dominio_formateo_clave_en_grupos_de_4():
    assert ReglasDespacho.formatear_clave_legible("ABCD1234EFGH5678") == "ABCD-1234-EFGH-5678"
    assert ReglasDespacho.formatear_clave_legible("abcd-1234-efgh-5678") == "ABCD-1234-EFGH-5678"


def test_hu43_dominio_rechaza_licencia_inexistente_o_ajena():
    licencia_otro = LicenciaUsuario(
        licencia_id="LIC-8001",
        despacho_id="DSP-9001",
        orden_id=5001,
        usuario_id=99,
        juego_id=101,
        titulo_juego="Juego Test",
        plataforma="PC",
        reserva_id=None,
        key_inventario_id=1,
        clave_digital="ABCD-1234-EFGH-5678",
        clave_enmascarada="ABCD-1234-EFGH-****",
        revelada=False,
        revelada_en=None,
        asignada_en=datetime.now(timezone.utc),
    )

    with pytest.raises(ErrorAplicacion) as exc_none:
        ReglasDespacho.validar_propiedad_licencia(None, usuario_id=10)
    assert exc_none.value.status_code == 404
    assert exc_none.value.message == "La licencia indicada no existe"

    with pytest.raises(ErrorAplicacion) as exc_ajena:
        ReglasDespacho.validar_propiedad_licencia(licencia_otro, usuario_id=10)
    assert exc_ajena.value.status_code == 404
    assert exc_ajena.value.message == "La licencia indicada no existe"


# =====================================================================
# 2. PRUEBAS FUNCIONALES DEL ENDPOINT POST /api/v1/biblioteca/licencias/{licenciaId}/revelar
# =====================================================================


def test_hu43_caso1_y_caso2_revelar_clave_exitoso_y_auditoria():
    db = _crear_sesion_memoria()
    try:
        _insertar_licencia(db, licencia_id="LIC-8001", usuario_id=10, juego_id=101)

        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides[obtener_usuario_autenticado] = lambda: UsuarioAutenticado(
            id=10, rol="CLIENTE"
        )

        cliente = TestClient(app)
        respuesta = cliente.post("/api/v1/biblioteca/licencias/LIC-8001/revelar")

        assert respuesta.status_code == 200
        cuerpo = respuesta.json()
        assert set(cuerpo.keys()) == {"message", "data", "success"}
        assert cuerpo["success"] is True
        assert cuerpo["message"] == "Clave digital revelada"

        data = cuerpo["data"]
        assert set(data.keys()) == {
            "licenciaId",
            "juegoId",
            "claveFormateada",
            "instruccionActivacion",
            "reveladaEn",
        }
        assert data["licenciaId"] == "LIC-8001"
        assert data["juegoId"] == 101
        assert data["claveFormateada"] == "ABCD-1234-EFGH-5678"
        assert data["instruccionActivacion"] == INSTRUCCION_ACTIVACION_ESTANDAR
        assert isinstance(data["reveladaEn"], str) and len(data["reveladaEn"]) > 0

        # Verificar auditoría persistida en base de datos
        registro_bd = (
            db.query(LicenciaUsuarioORM)
            .filter(LicenciaUsuarioORM.licencia_id == "LIC-8001")
            .first()
        )
        assert registro_bd.revelada is True
        assert registro_bd.revelada_en is not None
    finally:
        app.dependency_overrides.clear()
        db.close()


def test_hu43_caso3_error_404_licencia_ajena_o_inexistente():
    db = _crear_sesion_memoria()
    try:
        _insertar_licencia(db, licencia_id="LIC-8001", usuario_id=99, juego_id=101)

        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides[obtener_usuario_autenticado] = lambda: UsuarioAutenticado(
            id=10, rol="CLIENTE"
        )

        cliente = TestClient(app)

        resp_ajena = cliente.post("/api/v1/biblioteca/licencias/LIC-8001/revelar")
        assert resp_ajena.status_code == 404
        assert resp_ajena.json()["message"] == "La licencia indicada no existe"
        assert resp_ajena.json()["success"] is False

        resp_inexistente = cliente.post("/api/v1/biblioteca/licencias/LIC-NO-EXISTE/revelar")
        assert resp_inexistente.status_code == 404
        assert resp_inexistente.json()["message"] == "La licencia indicada no existe"
    finally:
        app.dependency_overrides.clear()
        db.close()


def test_hu43_error_401_sin_token():
    app.dependency_overrides.clear()
    cliente = TestClient(app)
    respuesta = cliente.post("/api/v1/biblioteca/licencias/LIC-8001/revelar")
    assert respuesta.status_code == 401


def test_hu43_caso4_error_503_fallo_base_datos():
    sesion_mock = MagicMock()
    sesion_mock.query.side_effect = OperationalError("SELECT 1", {}, Exception("DB caída"))

    repo = RepositorioDespacho(sesion_mock)
    servicio = ServicioDespacho(repositorio=repo)

    with pytest.raises(ErrorAplicacion) as exc:
        servicio.revelar_clave_licencia(licencia_id="LIC-8001", usuario_id=10)

    assert exc.value.status_code == 503
    assert exc.value.message == "No fue posible revelar la clave digital"