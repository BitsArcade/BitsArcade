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
from app.domain.despacho import LicenciaUsuarioORM
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
    licencia_id: str,
    usuario_id: int,
    orden_id: int,
    juego_id: int,
    titulo: str,
    clave_digital: str,
    clave_enmascarada: str,
    asignada_en: datetime,
) -> LicenciaUsuarioORM:
    registro = LicenciaUsuarioORM(
        licencia_id=licencia_id,
        despacho_id=f"DSP-{orden_id}",
        orden_id=orden_id,
        usuario_id=usuario_id,
        juego_id=juego_id,
        titulo_juego=titulo,
        plataforma="PC",
        reserva_id=f"RES-{licencia_id}",
        key_inventario_id=None,
        clave_digital=clave_digital,
        clave_enmascarada=clave_enmascarada,
        huella_clave=f"huella-{licencia_id}",
        revelada=False,
        revelada_en=None,
        asignada_en=asignada_en,
    )
    db.add(registro)
    db.commit()
    db.refresh(registro)
    return registro


# =====================================================================
# 1. PRUEBAS UNITARIAS Y REPOSITORIO (HU-44)
# =====================================================================


def test_hu44_repositorio_filtra_por_usuario_y_ordena_descendente():
    db = _crear_sesion_memoria()
    try:
        _insertar_licencia(
            db,
            licencia_id="LIC-1001",
            usuario_id=10,
            orden_id=5001,
            juego_id=101,
            titulo="Juego Antiguo",
            clave_digital="AAAA-BBBB-CCCC-1111",
            clave_enmascarada="AAAA-BBBB-CCCC-****",
            asignada_en=datetime(2026, 10, 20, 10, 0, 0, tzinfo=timezone.utc),
        )
        _insertar_licencia(
            db,
            licencia_id="LIC-1002",
            usuario_id=10,
            orden_id=5002,
            juego_id=102,
            titulo="Juego Reciente",
            clave_digital="DDDD-EEEE-FFFF-2222",
            clave_enmascarada="DDDD-EEEE-FFFF-****",
            asignada_en=datetime(2026, 10, 25, 10, 0, 0, tzinfo=timezone.utc),
        )
        _insertar_licencia(
            db,
            licencia_id="LIC-9999",
            usuario_id=99,
            orden_id=5099,
            juego_id=103,
            titulo="Juego Otro Usuario",
            clave_digital="GGGG-HHHH-IIII-3333",
            clave_enmascarada="GGGG-HHHH-IIII-****",
            asignada_en=datetime(2026, 10, 26, 10, 0, 0, tzinfo=timezone.utc),
        )

        repo = RepositorioDespacho(db)
        licencias_u10 = repo.listar_licencias_por_usuario(usuario_id=10)

        assert [lic.licencia_id for lic in licencias_u10] == ["LIC-1002", "LIC-1001"]
    finally:
        db.close()


# =====================================================================
# 2. PRUEBAS FUNCIONALES DEL ENDPOINT GET /api/v1/biblioteca/licencias
# =====================================================================


def test_hu44_caso1_y_caso2_despliegue_biblioteca_exitoso_enmascarado():
    db = _crear_sesion_memoria()
    try:
        _insertar_licencia(
            db,
            licencia_id="LIC-8001",
            usuario_id=10,
            orden_id=5001,
            juego_id=101,
            titulo="Cyberpunk 2077",
            clave_digital="ABCD-1234-EFGH-5678",
            clave_enmascarada="ABCD-1234-EFGH-****",
            asignada_en=datetime(2026, 10, 25, 10, 5, 0, tzinfo=timezone.utc),
        )
        _insertar_licencia(
            db,
            licencia_id="LIC-8002",
            usuario_id=99,
            orden_id=5002,
            juego_id=102,
            titulo="Elden Ring",
            clave_digital="WXYZ-9876-QRST-5432",
            clave_enmascarada="WXYZ-9876-QRST-****",
            asignada_en=datetime(2026, 10, 25, 11, 0, 0, tzinfo=timezone.utc),
        )

        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides[obtener_usuario_autenticado] = lambda: UsuarioAutenticado(
            id=10, rol="CLIENTE"
        )

        cliente = TestClient(app)
        respuesta = cliente.get("/api/v1/biblioteca/licencias")

        assert respuesta.status_code == 200
        cuerpo = respuesta.json()
        assert set(cuerpo.keys()) == {"message", "data", "success"}
        assert cuerpo["success"] is True
        assert cuerpo["message"] == "Biblioteca de licencias obtenida exitosamente"
        assert len(cuerpo["data"]) == 1

        item = cuerpo["data"][0]
        assert item["licenciaId"] == "LIC-8001"
        assert item["ordenId"] == 5001
        assert item["juegoId"] == 101
        assert item["titulo"] == "Cyberpunk 2077"
        assert item["claveEnmascarada"] == "ABCD-1234-EFGH-****"
        assert "claveDigital" not in item
        assert "5678" not in item["claveEnmascarada"]
    finally:
        app.dependency_overrides.clear()
        db.close()


def test_hu44_caso3_biblioteca_vacia_retorna_200_lista_vacia():
    db = _crear_sesion_memoria()
    try:
        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides[obtener_usuario_autenticado] = lambda: UsuarioAutenticado(
            id=10, rol="CLIENTE"
        )

        cliente = TestClient(app)
        respuesta = cliente.get("/api/v1/biblioteca/licencias")

        assert respuesta.status_code == 200
        cuerpo = respuesta.json()
        assert cuerpo["success"] is False
        assert cuerpo["data"] == []
    finally:
        app.dependency_overrides.clear()
        db.close()


def test_hu44_error_401_sin_token():
    app.dependency_overrides.clear()
    cliente = TestClient(app)
    respuesta = cliente.get("/api/v1/biblioteca/licencias")
    assert respuesta.status_code == 401


def test_hu44_caso4_error_503_fallo_base_datos():
    sesion_mock = MagicMock()
    sesion_mock.query.side_effect = OperationalError("SELECT 1", {}, Exception("DB caída"))

    repo = RepositorioDespacho(sesion_mock)
    servicio = ServicioDespacho(repositorio=repo)

    with pytest.raises(ErrorAplicacion) as exc:
        servicio.listar_biblioteca_usuario(usuario_id=10)

    assert exc.value.status_code == 503
    assert exc.value.message == "No fue posible consultar la biblioteca de licencias"