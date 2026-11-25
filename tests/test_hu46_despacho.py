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
    *,
    licencia_id: str,
    usuario_id: int,
    orden_id: int,
    juego_id: int,
    titulo: str,
    plataforma: str = "PC",
    clave_digital: str = "ABCD-1234-EFGH-5678",
    clave_enmascarada: str = "ABCD-1234-EFGH-****",
    revelada: bool = False,
    asignada_en: datetime | None = None,
):
    registro = LicenciaUsuarioORM(
        licencia_id=licencia_id,
        despacho_id=f"DSP-{orden_id}",
        orden_id=orden_id,
        usuario_id=usuario_id,
        juego_id=juego_id,
        titulo_juego=titulo,
        plataforma=plataforma,
        reserva_id=f"res-{licencia_id}",
        key_inventario_id=None,
        clave_digital=clave_digital,
        clave_enmascarada=clave_enmascarada,
        huella_clave=f"huella-{licencia_id}",
        revelada=revelada,
        revelada_en=asignada_en if revelada else None,
        asignada_en=asignada_en or datetime.now(timezone.utc),
    )
    db.add(registro)
    db.commit()
    db.refresh(registro)
    return registro


# =====================================================================
# 1. PRUEBAS UNITARIAS DE DOMINIO (HU-46)
# =====================================================================


def test_hu46_dominio_filtra_por_propietario_y_criterios_opcionales():
    ahora = datetime.now(timezone.utc)
    licencias = [
        LicenciaUsuario(
            licencia_id="LIC-1",
            despacho_id="DSP-1",
            orden_id=10,
            usuario_id=15,
            juego_id=101,
            titulo_juego="Cyberpunk 2077",
            plataforma="PC",
            reserva_id="res-1",
            key_inventario_id=1,
            clave_digital="AAAA-BBBB-CCCC-1111",
            clave_enmascarada="AAAA-BBBB-CCCC-****",
            revelada=False,
            revelada_en=None,
            asignada_en=ahora,
        ),
        LicenciaUsuario(
            licencia_id="LIC-2",
            despacho_id="DSP-2",
            orden_id=11,
            usuario_id=15,
            juego_id=102,
            titulo_juego="Halo Infinite",
            plataforma="Xbox",
            reserva_id="res-2",
            key_inventario_id=2,
            clave_digital="DDDD-EEEE-FFFF-2222",
            clave_enmascarada="DDDD-EEEE-FFFF-****",
            revelada=True,
            revelada_en=ahora,
            asignada_en=ahora,
        ),
        LicenciaUsuario(
            licencia_id="LIC-3",
            despacho_id="DSP-3",
            orden_id=12,
            usuario_id=99,
            juego_id=103,
            titulo_juego="Cyberpunk 2077",
            plataforma="PC",
            reserva_id="res-3",
            key_inventario_id=3,
            clave_digital="GGGG-HHHH-IIII-3333",
            clave_enmascarada="GGGG-HHHH-IIII-****",
            revelada=False,
            revelada_en=None,
            asignada_en=ahora,
        ),
    ]

    solo_usuario_15 = ReglasDespacho.filtrar_biblioteca_usuario(
        licencias=licencias, usuario_id=15
    )
    assert [lic.licencia_id for lic in solo_usuario_15] == ["LIC-1", "LIC-2"]

    filtrado_titulo_y_plataforma = ReglasDespacho.filtrar_biblioteca_usuario(
        licencias=licencias,
        usuario_id=15,
        titulo="cyber",
        plataforma="pc",
    )
    assert [lic.licencia_id for lic in filtrado_titulo_y_plataforma] == ["LIC-1"]


# =====================================================================
# 2. PRUEBAS FUNCIONALES DEL ENDPOINT GET /api/v1/biblioteca
# =====================================================================


def test_hu46_caso1_y_caso2_consulta_biblioteca_exitosa_y_enmascarada():
    db = _crear_sesion_memoria()
    try:
        _insertar_licencia(
            db,
            licencia_id="LIC-9001",
            usuario_id=15,
            orden_id=6001,
            juego_id=201,
            titulo="The Witcher 3",
            plataforma="PC",
            clave_digital="QWER-1234-TYUI-5678",
            clave_enmascarada="QWER-1234-TYUI-****",
            asignada_en=datetime(2026, 11, 20, 14, 0, 0, tzinfo=timezone.utc),
        )
        _insertar_licencia(
            db,
            licencia_id="LIC-9002",
            usuario_id=15,
            orden_id=6002,
            juego_id=202,
            titulo="Forza Horizon 5",
            plataforma="Xbox",
            clave_digital="ZXCV-9876-BNMA-5432",
            clave_enmascarada="ZXCV-9876-BNMA-****",
            asignada_en=datetime(2026, 11, 21, 16, 30, 0, tzinfo=timezone.utc),
        )
        # Licencia de otro usuario que NO debe aparecer
        _insertar_licencia(
            db,
            licencia_id="LIC-9099",
            usuario_id=88,
            orden_id=6099,
            juego_id=299,
            titulo="Juego Ajeno",
            plataforma="PC",
            clave_digital="OOOO-0000-PPPP-9999",
            clave_enmascarada="OOOO-0000-PPPP-****",
        )

        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides[obtener_usuario_autenticado] = lambda: UsuarioAutenticado(
            id=15, rol="CLIENTE"
        )

        cliente = TestClient(app)
        respuesta = cliente.get("/api/v1/biblioteca")

        assert respuesta.status_code == 200
        cuerpo = respuesta.json()
        assert set(cuerpo.keys()) == {"message", "data", "success"}
        assert cuerpo["success"] is True
        assert cuerpo["message"] == "Biblioteca de licencias obtenida exitosamente"

        items = cuerpo["data"]
        assert len(items) == 2
        assert items[0]["licenciaId"] == "LIC-9002"
        assert items[1]["licenciaId"] == "LIC-9001"
        assert items[0]["claveEnmascarada"] == "ZXCV-9876-BNMA-****"
        assert items[1]["claveEnmascarada"] == "QWER-1234-TYUI-****"
        assert "claveDigital" not in items[0]
        assert "ZXCV-9876-BNMA-5432" not in respuesta.text
        assert "QWER-1234-TYUI-5678" not in respuesta.text

        # Filtro opcional por plataforma
        resp_filtrada = cliente.get("/api/v1/biblioteca", params={"plataforma": "PC"})
        assert resp_filtrada.status_code == 200
        assert len(resp_filtrada.json()["data"]) == 1
        assert resp_filtrada.json()["data"][0]["licenciaId"] == "LIC-9001"
    finally:
        app.dependency_overrides.clear()
        db.close()


def test_hu46_caso3_biblioteca_vacia_retorna_200_lista_vacia():
    db = _crear_sesion_memoria()
    try:
        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides[obtener_usuario_autenticado] = lambda: UsuarioAutenticado(
            id=15, rol="CLIENTE"
        )

        cliente = TestClient(app)
        respuesta = cliente.get("/api/v1/biblioteca")

        assert respuesta.status_code == 200
        cuerpo = respuesta.json()
        assert cuerpo["data"] == []
        assert cuerpo["success"] is False
    finally:
        app.dependency_overrides.clear()
        db.close()


def test_hu46_error_401_sin_token():
    app.dependency_overrides.clear()
    cliente = TestClient(app)
    respuesta = cliente.get("/api/v1/biblioteca")
    assert respuesta.status_code == 401


def test_hu46_caso4_error_503_fallo_base_datos():
    sesion_mock = MagicMock()
    sesion_mock.query.side_effect = OperationalError("SELECT 1", {}, Exception("DB caída"))

    repo = RepositorioDespacho(sesion_mock)
    servicio = ServicioDespacho(repositorio=repo)

    with pytest.raises(ErrorAplicacion) as exc:
        servicio.listar_biblioteca_usuario(usuario_id=15)

    assert exc.value.status_code == 503
    assert exc.value.message == "No fue posible consultar la biblioteca de licencias"