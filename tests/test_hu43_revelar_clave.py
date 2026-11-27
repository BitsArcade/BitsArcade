"""Pruebas de HU-43: Formateo y visualización segura de la clave (POST /api/v1/biblioteca/licencias/{id}/revelar)."""
import logging

import pytest
from sqlalchemy.exc import OperationalError

from app.domain.despacho import formatearClave
from app.repositories.repositorio_despacho import RepositorioDespacho
from tests.apoyo_modulos import crearUsuario, despacharOrden, limpiarSimulaciones
from tests.conftest import encabezadoAuth


@pytest.fixture(autouse=True)
def _limpiar():
    limpiarSimulaciones()


@pytest.fixture
def licencia(cliente, sesion):
    usuario = crearUsuario(sesion)
    respuesta, _ = despacharOrden(cliente, sesion, usuario.id)
    return usuario, respuesta.json()["data"]["licencias"][0]["licenciaId"]


def _url(licenciaId):
    return f"/api/v1/biblioteca/licencias/{licenciaId}/revelar"


def test_flujoExitosoRevelaYNoCachea(cliente, licencia, caplog):
    usuario, licenciaId = licencia
    with caplog.at_level(logging.DEBUG):
        respuesta = cliente.post(_url(licenciaId), headers=encabezadoAuth(usuario.id))
    assert respuesta.status_code == 200
    assert respuesta.headers["Cache-Control"] == "no-store"
    cuerpo = respuesta.json()
    assert cuerpo["message"] == "Clave revelada exitosamente"
    assert cuerpo["data"]["claveLicencia"] == "AAAAA-BBBBB-CCCCC" and cuerpo["data"]["juegoId"] == 101
    assert cuerpo["data"]["reembolsable"] is False and cuerpo["data"]["reveladaEn"].endswith("Z")
    assert "AAAAA-BBBBB-CCCCC" not in caplog.text


def test_primerReveladoNoSeModifica(cliente, licencia):
    usuario, licenciaId = licencia
    primera = cliente.post(_url(licenciaId), headers=encabezadoAuth(usuario.id)).json()["data"]["reveladaEn"]
    segunda = cliente.post(_url(licenciaId), headers=encabezadoAuth(usuario.id)).json()["data"]["reveladaEn"]
    assert primera == segunda


def test_formateoDeClaveSinSeparadores():
    assert formatearClave("aaaaabbbbbccccc") == "AAAAA-BBBBB-CCCCC"


def test_error404LicenciaDeOtroUsuario(cliente, licencia):
    _, licenciaId = licencia
    respuesta = cliente.post(_url(licenciaId), headers=encabezadoAuth(999))
    assert respuesta.status_code == 404
    assert respuesta.json() == {"message": "La licencia indicada no existe", "data": None, "success": False}


def test_error401SinToken(cliente):
    assert cliente.post(_url("LIC-1")).status_code == 401


def test_error503BaseDeDatos(cliente, monkeypatch):
    def _falla(*_args, **_kwargs):
        raise OperationalError("SELECT", {}, Exception("BD caída"))

    monkeypatch.setattr(RepositorioDespacho, "obtenerAsignacion", _falla)
    respuesta = cliente.post(_url("LIC-1"), headers=encabezadoAuth(1))
    assert respuesta.status_code == 503
    assert respuesta.json()["message"] == "No fue posible revelar la clave"
