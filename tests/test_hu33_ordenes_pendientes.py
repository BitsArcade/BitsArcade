"""Pruebas de HU-33: Consultar órdenes pendientes (GET /api/v1/ordenes?estado=PENDIENTE)."""
from sqlalchemy.exc import OperationalError

from app.repositories.repositorio_ordenes import RepositorioOrdenes
from tests.apoyo_modulos import crearOrdenPrueba, obtenerOrden, prepararOrden
from tests.conftest import encabezadoAuth

URL = "/api/v1/ordenes"


def test_flujoExitosoListaPendientesDelUsuario(cliente, sesion, crearJuego):
    usuario, _, datos = prepararOrden(cliente, sesion, crearJuego)
    crearOrdenPrueba(sesion, 9001, usuarioId=999)   # Orden de otro usuario
    respuesta = cliente.get(URL, params={"estado": "PENDIENTE"}, headers=encabezadoAuth(usuario.id))
    assert respuesta.status_code == 200
    assert respuesta.json() == {
        "message": "Consulta de órdenes pendientes exitosa",
        "data": [{"ordenId": datos["ordenId"], "total": 238000, "moneda": "COP", "expiraEn": datos["expiraEn"]}],
        "success": True,
    }


def test_sinOrdenesPendientes(cliente):
    respuesta = cliente.get(URL, headers=encabezadoAuth(5))
    assert respuesta.status_code == 200
    assert respuesta.json() == {"message": "No tienes órdenes pendientes", "data": [], "success": False}


def test_ordenVencidaSeCancelaYNoSeLista(cliente, sesion):
    crearOrdenPrueba(sesion, 9001, usuarioId=5, minutosVigencia=-1)
    assert cliente.get(URL, headers=encabezadoAuth(5)).json()["data"] == []
    assert obtenerOrden(sesion, 9001).estado == "CANCELADA"


def test_error400EstadoInvalido(cliente):
    respuesta = cliente.get(URL, params={"estado": "XYZ"}, headers=encabezadoAuth(5))
    assert respuesta.status_code == 400
    assert respuesta.json()["message"] == "El estado indicado no es válido"


def test_error401SinToken(cliente):
    assert cliente.get(URL).status_code == 401


def test_error503BaseDeDatos(cliente, monkeypatch):
    def _falla(*_args, **_kwargs):
        raise OperationalError("SELECT", {}, Exception("BD caída"))

    monkeypatch.setattr(RepositorioOrdenes, "listarPorEstado", _falla)
    respuesta = cliente.get(URL, headers=encabezadoAuth(5))
    assert respuesta.status_code == 503
    assert respuesta.json()["message"] == "No fue posible consultar las órdenes"
