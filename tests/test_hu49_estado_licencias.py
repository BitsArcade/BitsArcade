from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.despacho import obtener_servicio_despacho
from app.core.base_datos import Base, get_db
from app.core.seguridad import UsuarioAutenticado, obtener_usuario_autenticado
from app.domain.despacho import LicenciaUsuario, LicenciaUsuarioORM, ReglasDespacho
from app.repositories.repositorio_despacho import RepositorioDespacho
from app.services.servicio_despacho import ServicioDespacho
from main import app


def crearSesionMemoria():
    motor = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=motor)
    Sesion = sessionmaker(autocommit=False, autoflush=False, bind=motor)
    return Sesion()


def crearLicenciaDominio(
    licenciaId: str,
    revelada: bool,
    reveladaEn: datetime | None,
) -> LicenciaUsuario:
    fechaAsignacion = datetime(2026, 10, 25, 9, 0, 0, tzinfo=timezone.utc)
    return LicenciaUsuario(
        licencia_id=licenciaId,
        despacho_id="DSP-5001",
        orden_id=5001,
        usuario_id=77,
        juego_id=101,
        titulo_juego="Aurora Quest",
        plataforma="PC",
        reserva_id=f"res-{licenciaId}",
        key_inventario_id=None,
        clave_digital="AAAA-BBBB-CCCC-DDDD",
        clave_enmascarada="AAAA-BBBB-CCCC-****",
        revelada=revelada,
        revelada_en=reveladaEn,
        asignada_en=fechaAsignacion,
    )


def insertarLicencia(
    sesion,
    licenciaId: str,
    usuarioId: int,
    revelada: bool,
    reveladaEn: datetime | None,
    asignadaEn: datetime,
):
    sesion.add(
        LicenciaUsuarioORM(
            licencia_id=licenciaId,
            despacho_id=f"DSP-{licenciaId}",
            orden_id=5001,
            usuario_id=usuarioId,
            juego_id=101,
            titulo_juego="Aurora Quest",
            plataforma="PC",
            precio_unitario=238000,
            reserva_id=f"res-{licenciaId}",
            key_inventario_id=None,
            clave_digital=f"AAAA-BBBB-CCCC-{licenciaId[-4:]}",
            clave_enmascarada="AAAA-BBBB-CCCC-****",
            huella_clave=f"huella-{licenciaId}",
            revelada=revelada,
            revelada_en=reveladaEn,
            asignada_en=asignadaEn,
        )
    )


@pytest.fixture(autouse=True)
def limpiarDependencias():
    yield
    app.dependency_overrides.clear()


def test_hu49_dominio_calcula_estado_y_elegibilidad_segun_revelacion():
    sinRevelar = ReglasDespacho.calcularEstadoLicencia(
        crearLicenciaDominio("LIC-1", False, None)
    )
    fechaRevelacion = datetime(2026, 10, 25, 10, 0, 0, tzinfo=timezone.utc)
    revelada = ReglasDespacho.calcularEstadoLicencia(
        crearLicenciaDominio("LIC-2", True, fechaRevelacion)
    )
    reveladaConRegistroIncompleto = ReglasDespacho.calcularEstadoLicencia(
        crearLicenciaDominio("LIC-3", False, fechaRevelacion)
    )

    assert sinRevelar == {
        "licenciaId": "LIC-1",
        "juegoId": 101,
        "estado": "ENTREGADA",
        "revelada": False,
        "reveladaEn": None,
        "reembolsable": True,
    }
    assert revelada == {
        "licenciaId": "LIC-2",
        "juegoId": 101,
        "estado": "REVELADA",
        "revelada": True,
        "reveladaEn": "2026-10-25T10:00:00+00:00",
        "reembolsable": False,
    }
    assert reveladaConRegistroIncompleto["revelada"] is True
    assert reveladaConRegistroIncompleto["reembolsable"] is False


def test_hu49_consulta_estado_solo_del_usuario_y_no_expone_clave():
    sesion = crearSesionMemoria()
    try:
        fechaAsignacion = datetime(2026, 10, 25, 9, 0, 0, tzinfo=timezone.utc)
        fechaRevelacion = datetime(2026, 10, 25, 10, 0, 0, tzinfo=timezone.utc)
        insertarLicencia(
            sesion,
            "LIC-1",
            77,
            False,
            None,
            fechaAsignacion,
        )
        insertarLicencia(
            sesion,
            "LIC-2",
            77,
            True,
            fechaRevelacion,
            fechaAsignacion,
        )
        insertarLicencia(
            sesion,
            "LIC-3",
            88,
            False,
            None,
            fechaAsignacion,
        )
        sesion.commit()

        app.dependency_overrides[get_db] = lambda: sesion
        app.dependency_overrides[obtener_usuario_autenticado] = lambda: UsuarioAutenticado(
            id=77,
            rol="CLIENTE",
        )

        respuesta = TestClient(app).get("/api/v1/biblioteca/licencias/estado")

        assert respuesta.status_code == 200
        cuerpo = respuesta.json()
        assert set(cuerpo) == {"message", "data", "success"}
        assert cuerpo["message"] == "Consulta de estado de licencias exitosa"
        assert cuerpo["success"] is True
        assert all(
            set(licencia)
            == {
                "licenciaId",
                "juegoId",
                "estado",
                "revelada",
                "reveladaEn",
                "reembolsable",
            }
            for licencia in cuerpo["data"]
        )
        licenciasPorId = {
            licencia["licenciaId"]: licencia for licencia in cuerpo["data"]
        }
        assert set(licenciasPorId) == {"LIC-1", "LIC-2"}
        assert licenciasPorId["LIC-1"]["estado"] == "ENTREGADA"
        assert licenciasPorId["LIC-1"]["reembolsable"] is True
        assert licenciasPorId["LIC-2"]["estado"] == "REVELADA"
        assert licenciasPorId["LIC-2"]["reembolsable"] is False
        assert "AAAA-BBBB-CCCC-LIC-1" not in respuesta.text
    finally:
        sesion.close()


def test_hu49_sin_licencias_retorna_lista_vacia():
    sesion = crearSesionMemoria()
    try:
        app.dependency_overrides[get_db] = lambda: sesion
        app.dependency_overrides[obtener_usuario_autenticado] = lambda: UsuarioAutenticado(
            id=77,
            rol="CLIENTE",
        )

        respuesta = TestClient(app).get("/api/v1/biblioteca/licencias/estado")

        assert respuesta.status_code == 200
        assert respuesta.json() == {
            "message": "No tienes licencias registradas",
            "data": [],
            "success": False,
        }
    finally:
        sesion.close()


def test_hu49_requiere_token():
    respuesta = TestClient(app).get("/api/v1/biblioteca/licencias/estado")

    assert respuesta.status_code == 401
    assert respuesta.json() == {
        "message": "Token inválido, expirado o ausente",
        "data": None,
        "success": False,
    }


def test_hu49_fallo_de_base_de_datos_retorna_503():
    sesion = MagicMock()
    sesion.query.side_effect = OperationalError(
        "SELECT",
        {},
        Exception("Base de datos no disponible"),
    )
    repositorio = RepositorioDespacho(sesion)
    servicio = ServicioDespacho(repositorio=repositorio)
    app.dependency_overrides[get_db] = lambda: sesion
    app.dependency_overrides[obtener_usuario_autenticado] = lambda: UsuarioAutenticado(
        id=77,
        rol="CLIENTE",
    )
    app.dependency_overrides[obtener_servicio_despacho] = lambda: servicio

    respuesta = TestClient(app).get("/api/v1/biblioteca/licencias/estado")

    assert respuesta.status_code == 503
    assert respuesta.json() == {
        "message": "No fue posible consultar el estado de las licencias",
        "data": None,
        "success": False,
    }
