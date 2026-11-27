"""Pruebas de HU-34: Cancelar orden de compra y liberar stock (POST /api/v1/ordenes/{ordenId}/cancelacion)."""
from sqlalchemy.exc import OperationalError

from app.api.ordenes import servicioOrdenes
from app.domain.inventario import ClaveLicencia
from app.repositories.repositorio_ordenes import RepositorioOrdenes
from app.services.servicio_ordenes import ReservaNoDisponible
from app.services.tareas_programadas import ejecutarCiclo
from tests.apoyo_modulos import crearOrdenPrueba, obtenerOrden, prepararOrden
from tests.conftest import encabezadoAuth


def _url(ordenId):
    return f"/api/v1/ordenes/{ordenId}/cancelacion"


def test_flujoExitosoCancelaYLiberaClaves(cliente, sesion, crearJuego):
    usuario, _, datos = prepararOrden(cliente, sesion, crearJuego, cantidad=2)
    respuesta = cliente.post(_url(datos["ordenId"]), json={"motivo": "Cambio de opinión"},
                             headers=encabezadoAuth(usuario.id))
    assert respuesta.status_code == 200
    assert respuesta.json() == {"message": "Orden cancelada exitosamente",
                                "data": {"ordenId": datos["ordenId"], "estado": "CANCELADA"}, "success": True}
    assert sesion.query(ClaveLicencia).filter_by(estado="DISPONIBLE").count() == 2   # COM-13


def test_cancelacionIdempotente(cliente, sesion, crearJuego):
    usuario, _, datos = prepararOrden(cliente, sesion, crearJuego)
    cliente.post(_url(datos["ordenId"]), json={}, headers=encabezadoAuth(usuario.id))
    segunda = cliente.post(_url(datos["ordenId"]), json={}, headers=encabezadoAuth(usuario.id))
    assert segunda.status_code == 200 and segunda.json()["data"]["estado"] == "CANCELADA"


def test_jobCancelaOrdenesExpiradas(cliente, sesion, crearJuego):
    _, _, datos = prepararOrden(cliente, sesion, crearJuego)
    orden = obtenerOrden(sesion, datos["ordenId"])
    orden.expiraEn = orden.creadaEn.replace(year=2000)
    sesion.commit()
    assert ejecutarCiclo(sesion)["ordenesCanceladas"] == 1
    assert obtenerOrden(sesion, datos["ordenId"]).estado == "CANCELADA"
    assert sesion.query(ClaveLicencia).filter_by(estado="DISPONIBLE").count() == 1


def test_error409OrdenEnProceso(cliente, sesion):
    crearOrdenPrueba(sesion, 9001, usuarioId=5, estado="PROCESANDO")
    respuesta = cliente.post(_url(9001), json={}, headers=encabezadoAuth(5))
    assert respuesta.status_code == 409
    assert respuesta.json()["message"] == "Solo se pueden cancelar órdenes en estado PENDIENTE"


def test_error404OrdenAjena(cliente, sesion):
    crearOrdenPrueba(sesion, 9001, usuarioId=5)
    respuesta = cliente.post(_url(9001), json={}, headers=encabezadoAuth(6))
    assert respuesta.status_code == 404
    assert respuesta.json()["message"] == "La orden indicada no existe"


def test_error503Com13NoRespondeLaOrdenNoCambia(cliente, sesion, crearJuego, monkeypatch):
    usuario, _, datos = prepararOrden(cliente, sesion, crearJuego)

    def _caido(*_args, **_kwargs):
        raise ReservaNoDisponible("COM-13 caído")

    monkeypatch.setattr(servicioOrdenes, "_liberarReservas", _caido)
    respuesta = cliente.post(_url(datos["ordenId"]), json={}, headers=encabezadoAuth(usuario.id))
    assert respuesta.status_code == 503
    assert respuesta.json()["message"] == "No fue posible liberar el stock reservado"
    assert obtenerOrden(sesion, datos["ordenId"]).estado == "PENDIENTE"


def test_error401SinToken(cliente):
    assert cliente.post(_url(1), json={}).status_code == 401


def test_error503BaseDeDatos(cliente, monkeypatch):
    def _falla(*_args, **_kwargs):
        raise OperationalError("SELECT", {}, Exception("BD caída"))

    monkeypatch.setattr(RepositorioOrdenes, "obtenerDeUsuario", _falla)
    respuesta = cliente.post(_url(1), json={}, headers=encabezadoAuth(5))
    assert respuesta.status_code == 503
    assert respuesta.json()["message"] == "No fue posible cancelar la orden"
