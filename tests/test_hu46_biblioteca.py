"""Pruebas de HU-46: Consultar biblioteca personal de juegos (GET /api/v1/biblioteca)."""
import pytest
from sqlalchemy.exc import OperationalError

from app.repositories.repositorio_despacho import RepositorioDespacho
from tests.apoyo_modulos import crearUsuario, despacharOrden, limpiarSimulaciones
from tests.conftest import encabezadoAuth

URL = "/api/v1/biblioteca"


@pytest.fixture(autouse=True)
def _limpiar():
    limpiarSimulaciones()


def test_flujoExitosoClavesEnmascaradas(cliente, sesion):
    usuario = crearUsuario(sesion)
    despacharOrden(cliente, sesion, usuario.id)
    respuesta = cliente.get(URL, headers=encabezadoAuth(usuario.id))
    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["message"] == "Consulta de biblioteca exitosa" and cuerpo["success"] is True
    [licencia] = cuerpo["data"]
    assert licencia["juegoId"] == 101 and licencia["titulo"] == "Aurora Quest" and licencia["plataforma"] == "PC"
    assert licencia["claveLicencia"] == "*****-*****-*****" and licencia["revelada"] is False
    assert licencia["entregadaEn"].endswith("Z")


def test_soloLicenciasDelPropioUsuario(cliente, sesion):
    usuario = crearUsuario(sesion)
    otro = crearUsuario(sesion, correo="otro@correo.com")
    despacharOrden(cliente, sesion, usuario.id)
    respuesta = cliente.get(URL, headers=encabezadoAuth(otro.id))
    assert respuesta.json() == {"message": "Aún no tienes licencias en tu biblioteca", "data": [], "success": False}


def test_error401SinToken(cliente):
    assert cliente.get(URL).status_code == 401


def test_error503BaseDeDatos(cliente, monkeypatch):
    def _falla(*_args, **_kwargs):
        raise OperationalError("SELECT", {}, Exception("BD caída"))

    monkeypatch.setattr(RepositorioDespacho, "listarAsignacionesUsuario", _falla)
    respuesta = cliente.get(URL, headers=encabezadoAuth(1))
    assert respuesta.status_code == 503
    assert respuesta.json()["message"] == "No fue posible consultar la biblioteca"
