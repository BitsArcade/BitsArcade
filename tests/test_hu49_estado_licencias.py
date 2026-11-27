"""Pruebas de HU-49: Consultar estado de licencias (GET /api/v1/biblioteca/licencias/estado)."""
import pytest
from sqlalchemy.exc import OperationalError

from app.repositories.repositorio_despacho import RepositorioDespacho
from tests.apoyo_modulos import crearUsuario, despacharOrden, limpiarSimulaciones
from tests.conftest import encabezadoAuth

URL = "/api/v1/biblioteca/licencias/estado"


@pytest.fixture(autouse=True)
def _limpiar():
    limpiarSimulaciones()


def test_flujoExitosoReembolsableHastaRevelar(cliente, sesion):
    usuario = crearUsuario(sesion)
    respuestaDespacho, _ = despacharOrden(cliente, sesion, usuario.id, claves=("AAAAA-00001", "AAAAA-00002"))
    licenciaId = respuestaDespacho.json()["data"]["licencias"][0]["licenciaId"]
    cliente.post(f"/api/v1/biblioteca/licencias/{licenciaId}/revelar", headers=encabezadoAuth(usuario.id))
    respuesta = cliente.get(URL, headers=encabezadoAuth(usuario.id))
    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["message"] == "Consulta de estado de licencias exitosa"
    porId = {l["licenciaId"]: l for l in cuerpo["data"]}
    revelada = porId.pop(licenciaId)
    [sinRevelar] = porId.values()
    assert revelada["estado"] == "ENTREGADA" and revelada["revelada"] is True and revelada["reembolsable"] is False
    assert sinRevelar == {"licenciaId": sinRevelar["licenciaId"], "juegoId": 101, "estado": "ENTREGADA",
                           "revelada": False, "reveladaEn": None, "reembolsable": True}


def test_sinLicencias(cliente):
    respuesta = cliente.get(URL, headers=encabezadoAuth(5))
    assert respuesta.json() == {"message": "No tienes licencias registradas", "data": [], "success": False}


def test_error401SinToken(cliente):
    assert cliente.get(URL).status_code == 401


def test_error503BaseDeDatos(cliente, monkeypatch):
    def _falla(*_args, **_kwargs):
        raise OperationalError("SELECT", {}, Exception("BD caída"))

    monkeypatch.setattr(RepositorioDespacho, "listarAsignacionesUsuario", _falla)
    respuesta = cliente.get(URL, headers=encabezadoAuth(1))
    assert respuesta.status_code == 503
    assert respuesta.json()["message"] == "No fue posible consultar el estado de las licencias"
