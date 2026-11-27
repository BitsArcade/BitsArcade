"""Pruebas de HU-45: Validar unicidad e inmutabilidad de entrega."""
import pytest
from sqlalchemy.exc import OperationalError

from app.domain.despacho import AsignacionLicencia, EntregaInmutableError
from app.repositories.repositorio_despacho import RepositorioDespacho
from tests.apoyo_modulos import crearUsuario, despacharOrden, limpiarSimulaciones


@pytest.fixture(autouse=True)
def _limpiar():
    limpiarSimulaciones()


def _url(ordenId):
    return f"/interno/v1/despacho/ordenes/{ordenId}/elegibilidad"


def test_ordenSinEntregasPreviasEsAutorizada(cliente):
    respuesta = cliente.get(_url(5001), params={"reservaIds": ["res-9f1"]})
    assert respuesta.status_code == 200
    assert respuesta.json() == {
        "message": "Entrega autorizada",
        "data": {"ordenId": 5001, "autorizado": True, "items": [{"reservaId": "res-9f1", "entregada": False}]},
        "success": True,
    }


def test_reintentoDeLaMismaOrdenEsIdempotente(cliente, sesion):
    usuario = crearUsuario(sesion)
    _, payload = despacharOrden(cliente, sesion, usuario.id)
    reserva = payload["items"][0]["reservaId"]
    datos = cliente.get(_url(5001), params={"reservaIds": [reserva]}).json()["data"]
    assert datos["autorizado"] is True and datos["items"] == [{"reservaId": reserva, "entregada": True}]


def test_error409ReservaEntregadaAOtraOrden(cliente, sesion):
    usuario = crearUsuario(sesion)
    _, payload = despacharOrden(cliente, sesion, usuario.id)
    respuesta = cliente.get(_url(7000), params={"reservaIds": [payload["items"][0]["reservaId"]]})
    assert respuesta.status_code == 409
    assert respuesta.json() == {"message": "La licencia ya fue entregada y no puede reasignarse", "data": None,
                                "success": False}


def test_rn10AsignacionNoAdmiteUpdateNiDelete(cliente, sesion):
    usuario = crearUsuario(sesion)
    despacharOrden(cliente, sesion, usuario.id)
    asignacion = sesion.query(AsignacionLicencia).one()
    asignacion.usuarioId = 12345
    with pytest.raises(EntregaInmutableError):
        sesion.commit()
    sesion.rollback()
    sesion.delete(sesion.query(AsignacionLicencia).one())
    with pytest.raises(EntregaInmutableError):
        sesion.commit()
    sesion.rollback()


def test_error503BaseDeDatos(cliente, monkeypatch):
    def _falla(*_args, **_kwargs):
        raise OperationalError("SELECT", {}, Exception("BD caída"))

    monkeypatch.setattr(RepositorioDespacho, "obtenerAsignacionesPorReservas", _falla)
    respuesta = cliente.get(_url(5001), params={"reservaIds": ["res-1"]})
    assert respuesta.status_code == 503
    assert respuesta.json()["message"] == "No fue posible validar la entrega"
