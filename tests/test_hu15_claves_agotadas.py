"""Pruebas de HU-15: Reportar y alertar llaves agotadas (GET /api/v1/inventario/claves/agotadas)."""
from sqlalchemy.exc import OperationalError

from app.domain.inventario import AlertaStock
from app.repositories.repositorio_inventario import RepositorioInventario
from app.services.servicio_inventario import ServicioInventario
from app.services.tareas_programadas import ejecutarCiclo
from tests.apoyo_modulos import cargarClaves, reservar
from tests.conftest import encabezadoAuth

URL = "/api/v1/inventario/claves/agotadas"
ADMIN = encabezadoAuth(1, rol="ADMIN")


def test_flujoExitosoDetectaStockCero(cliente, sesion):
    cargarClaves(sesion, 101, ["AAAAA-00001"])
    cargarClaves(sesion, 202, ["BBBBB-00001"])
    reservar(sesion, ordenId=1, juegoId=101, cantidad=1)
    ejecutarCiclo(sesion)
    respuesta = cliente.get(URL, headers=ADMIN)
    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["message"] == "Consulta de llaves agotadas exitosa" and cuerpo["success"] is True
    assert [(a["juegoId"], a["plataforma"]) for a in cuerpo["data"]] == [(101, "PC")]
    assert cuerpo["data"][0]["alertaDesde"].endswith("Z")


def test_alertaIdempotenteNoSeDuplica(sesion):
    cargarClaves(sesion, 101, ["AAAAA-00001"])
    reservar(sesion, ordenId=1, juegoId=101, cantidad=1)
    emitidas = []
    servicio = ServicioInventario()
    servicio.evaluarStockAgotado(sesion, emitirAlerta=emitidas.append)
    servicio.evaluarStockAgotado(sesion, emitirAlerta=emitidas.append)
    assert len(emitidas) == 1
    assert sesion.query(AlertaStock).count() == 1


def test_alertaSeCierraAlReponerStock(cliente, sesion):
    cargarClaves(sesion, 101, ["AAAAA-00001"])
    reservar(sesion, ordenId=1, juegoId=101, cantidad=1)
    ejecutarCiclo(sesion)
    cargarClaves(sesion, 101, ["AAAAA-00002"])
    assert cliente.get(URL, headers=ADMIN).json()["success"] is False


def test_sinDatos(cliente):
    respuesta = cliente.get(URL, headers=ADMIN)
    assert respuesta.status_code == 200
    assert respuesta.json() == {"message": "No existen títulos con stock agotado", "data": [], "success": False}


def test_error401Y403(cliente):
    assert cliente.get(URL).status_code == 401
    respuesta = cliente.get(URL, headers=encabezadoAuth(2, rol="CLIENTE"))
    assert respuesta.status_code == 403
    assert respuesta.json()["message"] == "No cuenta con permisos para realizar esta operación"


def test_error503BaseDeDatos(cliente, monkeypatch):
    def _falla(*_args, **_kwargs):
        raise OperationalError("SELECT", {}, Exception("BD caída"))

    monkeypatch.setattr(RepositorioInventario, "listarAlertasActivas", _falla)
    respuesta = cliente.get(URL, headers=ADMIN)
    assert respuesta.status_code == 503
    assert respuesta.json()["message"] == "No fue posible consultar las llaves agotadas"
