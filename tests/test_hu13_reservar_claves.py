"""Pruebas de HU-13: Reservar clave temporalmente (POST /interno/v1/inventario/reservas) y COM-13."""
from datetime import timedelta

from sqlalchemy.exc import OperationalError

from app.domain.inventario import ClaveLicencia, ReservaClave
from app.repositories.repositorio_inventario import RepositorioInventario
from app.services.tareas_programadas import ejecutarCiclo
from tests.apoyo_modulos import cargarClaves

URL = "/interno/v1/inventario/reservas"


def _estados(sesion):
    sesion.expire_all()
    return sorted(k.estado for k in sesion.query(ClaveLicencia).all())


def test_flujoExitosoReserva15Minutos(cliente, sesion):
    cargarClaves(sesion, 101, ["AAAAA-00001", "AAAAA-00002", "AAAAA-00003"])
    respuesta = cliente.post(URL, json={"ordenId": 5001, "juegoId": 101, "cantidad": 2})
    assert respuesta.status_code == 201
    cuerpo = respuesta.json()
    assert cuerpo["message"] == "Claves reservadas exitosamente" and cuerpo["success"] is True
    assert len(cuerpo["data"]["reservaIds"]) == 2 and cuerpo["data"]["expiraEn"].endswith("Z")
    reserva = sesion.query(ReservaClave).first()
    assert timedelta(minutes=14) < reserva.expiraEn - reserva.creadaEn <= timedelta(minutes=15, seconds=1)
    assert _estados(sesion) == ["DISPONIBLE", "RESERVADA", "RESERVADA"]


def test_reservasSucesivasNuncaCompartenClave(cliente, sesion):
    cargarClaves(sesion, 101, ["AAAAA-00001", "AAAAA-00002"])
    cliente.post(URL, json={"ordenId": 1, "juegoId": 101, "cantidad": 1})
    cliente.post(URL, json={"ordenId": 2, "juegoId": 101, "cantidad": 1})
    claveIds = [r.claveId for r in sesion.query(ReservaClave).all()]
    assert len(set(claveIds)) == 2


def test_atomicaSiNoAlcanzaNoReservaNinguna(cliente, sesion):
    cargarClaves(sesion, 101, ["AAAAA-00001"])
    respuesta = cliente.post(URL, json={"ordenId": 5001, "juegoId": 101, "cantidad": 2})
    assert respuesta.status_code == 409
    assert respuesta.json() == {"message": "Stock insuficiente para el juego solicitado", "data": None, "success": False}
    assert _estados(sesion) == ["DISPONIBLE"]


def test_error400QuantityCero(cliente):
    respuesta = cliente.post(URL, json={"ordenId": 5001, "juegoId": 101, "cantidad": 0})
    assert respuesta.status_code == 400
    assert respuesta.json()["message"] == "cantidad debe ser mayor o igual a 1"


def test_com13LiberacionIdempotente(cliente, sesion):
    cargarClaves(sesion, 101, ["AAAAA-00001", "AAAAA-00002"])
    ids = cliente.post(URL, json={"ordenId": 1, "juegoId": 101, "cantidad": 2}).json()["data"]["reservaIds"]
    primera = cliente.post(f"{URL}/liberar", json={"reservaIds": ids})
    segunda = cliente.post(f"{URL}/liberar", json={"reservaIds": ids})
    assert primera.json()["data"] == {"liberadas": 2}
    assert segunda.json()["data"] == {"liberadas": 0}
    assert _estados(sesion) == ["DISPONIBLE", "DISPONIBLE"]


def test_tt04DevuelveADisponibleLasReservasVencidas(cliente, sesion):
    cargarClaves(sesion, 101, ["AAAAA-00001"])
    cliente.post(URL, json={"ordenId": 1, "juegoId": 101, "cantidad": 1})
    reserva = sesion.query(ReservaClave).one()
    reserva.expiraEn = reserva.expiraEn - timedelta(minutes=20)
    sesion.commit()
    assert ejecutarCiclo(sesion)["reservasLiberadas"] == 1
    assert _estados(sesion) == ["DISPONIBLE"]


def test_com12StockDisponible(cliente, sesion):
    cargarClaves(sesion, 101, ["AAAAA-00001", "AAAAA-00002"])
    respuesta = cliente.get("/interno/v1/inventario/stock/101")
    assert respuesta.json()["data"] == {"juegoId": 101, "cantidadDisponible": 2}


def test_error503BaseDeDatos(cliente, monkeypatch):
    def _falla(*_args, **_kwargs):
        raise OperationalError("SELECT", {}, Exception("BD caída"))

    monkeypatch.setattr(RepositorioInventario, "obtenerIdsDisponibles", _falla)
    respuesta = cliente.post(URL, json={"ordenId": 5001, "juegoId": 101, "cantidad": 1})
    assert respuesta.status_code == 503
    assert respuesta.json()["message"] == "No fue posible reservar las claves"
