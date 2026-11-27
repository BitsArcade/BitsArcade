"""Pruebas de HU-35: Actualizar estado de la orden (COM-09: PATCH /interno/v1/ordenes/{ordenId}/estado)."""
from sqlalchemy.exc import OperationalError

from app.core.seguridad import encabezadosServicio
from app.domain.inventario import ClaveLicencia
from app.repositories.repositorio_ordenes import RepositorioOrdenes
from tests.apoyo_modulos import crearOrdenPrueba, obtenerOrden, prepararOrden


def _url(ordenId):
    return f"/interno/v1/ordenes/{ordenId}/estado"


def test_flujoExitosoPendienteAProcesando(cliente, sesion):
    crearOrdenPrueba(sesion, 5001)
    respuesta = cliente.patch(_url(5001), json={"estado": "PROCESANDO"}, headers=encabezadosServicio("MOD-05"))
    assert respuesta.status_code == 200
    assert respuesta.json() == {"message": "Estado de la orden actualizado",
                                "data": {"ordenId": 5001, "estado": "PROCESANDO", "confirmado": True},
                                "success": True}


def test_mismoEstadoEsIdempotente(cliente, sesion):
    crearOrdenPrueba(sesion, 5001, estado="PROCESANDO")
    respuesta = cliente.patch(_url(5001), json={"estado": "PROCESANDO"}, headers=encabezadosServicio("MOD-05"))
    assert respuesta.status_code == 200


def test_cancelarDesdeProcesandoLiberaReservas(cliente, sesion, crearJuego):
    _, _, datos = prepararOrden(cliente, sesion, crearJuego)
    ordenId = datos["ordenId"]
    cliente.patch(_url(ordenId), json={"estado": "PROCESANDO"}, headers=encabezadosServicio("MOD-05"))
    respuesta = cliente.patch(_url(ordenId), json={"estado": "CANCELADA"}, headers=encabezadosServicio("MOD-05"))
    assert respuesta.json()["data"]["estado"] == "CANCELADA"
    assert sesion.query(ClaveLicencia).one().estado == "DISPONIBLE"


def test_error409TransicionNoPermitida(cliente, sesion):
    crearOrdenPrueba(sesion, 5001, estado="CANCELADA")
    respuesta = cliente.patch(_url(5001), json={"estado": "PAGADA"}, headers=encabezadosServicio("MOD-05"))
    assert respuesta.status_code == 409
    assert respuesta.json()["message"] == "Transición de estado no permitida"


def test_error409OrdenExpirada(cliente, sesion):
    crearOrdenPrueba(sesion, 5001, minutosVigencia=-1)
    respuesta = cliente.patch(_url(5001), json={"estado": "PROCESANDO"}, headers=encabezadosServicio("MOD-05"))
    assert respuesta.status_code == 409
    assert respuesta.json()["message"] == "La orden expiró"


def test_soloMod06PuedeMarcarEntregada(cliente, sesion):
    crearOrdenPrueba(sesion, 5001, estado="PAGADA")
    assert cliente.patch(_url(5001), json={"estado": "ENTREGADA"},
                         headers=encabezadosServicio("MOD-05")).status_code == 409
    assert cliente.patch(_url(5001), json={"estado": "ENTREGADA"},
                         headers=encabezadosServicio("MOD-06")).status_code == 200
    assert obtenerOrden(sesion, 5001).entregadaEn is not None


def test_error401SinTokenDeServicio(clienteSinTokenServicio, sesion):
    crearOrdenPrueba(sesion, 5001)
    respuesta = clienteSinTokenServicio.patch(_url(5001), json={"estado": "PROCESANDO"})
    assert respuesta.status_code == 401
    assert respuesta.json()["message"] == "Token de servicio inválido o ausente"


def test_error404OrdenInexistente(cliente):
    respuesta = cliente.patch(_url(999), json={"estado": "PROCESANDO"}, headers=encabezadosServicio("MOD-05"))
    assert respuesta.status_code == 404


def test_error503BaseDeDatos(cliente, monkeypatch):
    def _falla(*_args, **_kwargs):
        raise OperationalError("SELECT", {}, Exception("BD caída"))

    monkeypatch.setattr(RepositorioOrdenes, "obtenerPorId", _falla)
    respuesta = cliente.patch(_url(1), json={"estado": "PROCESANDO"}, headers=encabezadosServicio("MOD-05"))
    assert respuesta.status_code == 503
    assert respuesta.json()["message"] == "No fue posible actualizar el estado de la orden"
