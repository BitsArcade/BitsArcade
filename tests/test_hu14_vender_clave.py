"""Pruebas de HU-14: Actualizar estado de clave a vendida (POST /interno/v1/inventario/reservas/{id}/venta)."""
import logging
from datetime import timedelta

from sqlalchemy.exc import OperationalError

from app.domain.inventario import ClaveLicencia, ReservaClave
from app.repositories.repositorio_inventario import RepositorioInventario
from tests.apoyo_modulos import cargarClaves, reservar


def _url(reservaId: str) -> str:
    return f"/interno/v1/inventario/reservas/{reservaId}/venta"


def test_flujoExitosoRetornaClaveDescifrada(cliente, sesion):
    cargarClaves(sesion, 101, ["AAAAA-BBBBB-CCCCC"])
    [reservaId] = reservar(sesion)
    respuesta = cliente.post(_url(reservaId))
    assert respuesta.status_code == 200
    assert respuesta.json() == {
        "message": "Clave confirmada como vendida",
        "data": {"reservaId": reservaId, "estado": "VENDIDA", "claveLicencia": "AAAAA-BBBBB-CCCCC"},
        "success": True,
    }
    sesion.expire_all()
    assert sesion.query(ClaveLicencia).one().estado == "VENDIDA"


def test_idempotenteMismaReservaMismaClave(cliente, sesion):
    cargarClaves(sesion, 101, ["AAAAA-BBBBB-CCCCC"])
    [reservaId] = reservar(sesion)
    primera = cliente.post(_url(reservaId)).json()
    segunda = cliente.post(_url(reservaId)).json()
    assert primera == segunda


def test_valorDeClaveNoSeRegistraEnLogs(cliente, sesion, caplog):
    cargarClaves(sesion, 101, ["AAAAA-BBBBB-CCCCC"])
    [reservaId] = reservar(sesion)
    with caplog.at_level(logging.DEBUG):
        cliente.post(_url(reservaId))
    assert "AAAAA-BBBBB-CCCCC" not in caplog.text


def test_error404ReservaInexistente(cliente):
    respuesta = cliente.post(_url("res-nada"))
    assert respuesta.status_code == 404
    assert respuesta.json() == {"message": "La reserva indicada no existe", "data": None, "success": False}


def test_error409ReservaLiberada(cliente, sesion):
    cargarClaves(sesion, 101, ["AAAAA-BBBBB-CCCCC"])
    [reservaId] = reservar(sesion)
    cliente.post("/interno/v1/inventario/reservas/liberar", json={"reservaIds": [reservaId]})
    respuesta = cliente.post(_url(reservaId))
    assert respuesta.status_code == 409
    assert respuesta.json()["message"] == "La reserva expiró o fue liberada"


def test_error409ReservaExpirada(cliente, sesion):
    cargarClaves(sesion, 101, ["AAAAA-BBBBB-CCCCC"])
    [reservaId] = reservar(sesion)
    reserva = sesion.query(ReservaClave).one()
    reserva.expiraEn = reserva.expiraEn - timedelta(minutes=30)
    sesion.commit()
    assert cliente.post(_url(reservaId)).status_code == 409


def test_error503BaseDeDatos(cliente, monkeypatch):
    def _falla(*_args, **_kwargs):
        raise OperationalError("SELECT", {}, Exception("BD caída"))

    monkeypatch.setattr(RepositorioInventario, "obtenerReserva", _falla)
    respuesta = cliente.post(_url("res-1"))
    assert respuesta.status_code == 503
    assert respuesta.json()["message"] == "No fue posible confirmar la venta de la clave"
