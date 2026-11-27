"""Pruebas de HU-41: Asignar clave digital al perfil del usuario (POST /interno/v1/despacho/ordenes)."""
import pytest
from sqlalchemy.exc import OperationalError

from app.core.cifrado import descifrarClave
from app.domain.despacho import AsignacionLicencia, RegistroCompra
from app.repositories.repositorio_despacho import RepositorioDespacho
from app.services import clientes_despacho
from tests.apoyo_modulos import crearUsuario, despacharOrden, limpiarSimulaciones

URL = "/interno/v1/despacho/ordenes"


@pytest.fixture(autouse=True)
def _limpiar():
    limpiarSimulaciones()


def test_flujoExitosoSinValoresDeClave(cliente, sesion):
    usuario = crearUsuario(sesion)
    respuesta, _ = despacharOrden(cliente, sesion, usuario.id)
    assert respuesta.status_code == 201
    cuerpo = respuesta.json()
    assert cuerpo["message"] == "Licencias asignadas exitosamente"
    assert cuerpo["data"]["ordenId"] == 5001 and cuerpo["data"]["estadoDespacho"] == "ENTREGADO"
    assert [l["juegoId"] for l in cuerpo["data"]["licencias"]] == [101]
    assert cuerpo["data"]["licencias"][0]["licenciaId"].startswith("LIC-")
    assert "AAAAA" not in respuesta.text
    asignacion = sesion.query(AsignacionLicencia).one()
    assert asignacion.estado == "ENTREGADA" and asignacion.revelada is False
    assert descifrarClave(asignacion.claveCifrada) == "AAAAA-BBBBB-CCCCC"


def test_guardaRegistroPropioDeLaCompra(cliente, sesion):
    usuario = crearUsuario(sesion)
    despacharOrden(cliente, sesion, usuario.id)
    compra = sesion.query(RegistroCompra).one()
    assert (compra.correo, compra.transaccionId, compra.moneda, compra.total) == \
        ("jugador@correo.com", "TX-5001", "COP", 238000)
    assert compra.baseGravable == 200000 and compra.iva == 38000


def test_idempotentePorOrdenId(cliente, sesion):
    usuario = crearUsuario(sesion)
    primera, payload = despacharOrden(cliente, sesion, usuario.id)
    segunda = cliente.post(URL, json=payload)
    assert segunda.status_code == 201 and segunda.json() == primera.json()
    assert sesion.query(AsignacionLicencia).count() == 1


def test_error404CompradorInexistente(cliente, sesion):
    respuesta, _ = despacharOrden(cliente, sesion, usuarioId=999)
    assert respuesta.status_code == 404
    assert respuesta.json() == {"message": "El comprador no existe", "data": None, "success": False}


def test_error409ReservaYaAsignadaAOtraOrden(cliente, sesion):
    usuario = crearUsuario(sesion)
    _, payload = despacharOrden(cliente, sesion, usuario.id)
    respuesta = cliente.post(URL, json={**payload, "ordenId": 6000})
    assert respuesta.status_code == 409
    assert respuesta.json()["message"] == "La licencia ya fue entregada y no puede reasignarse"


def test_error503Com07NoRespondeQuedaPendienteReintento(cliente, sesion, monkeypatch):
    usuario = crearUsuario(sesion)

    def _falla(*_args, **_kwargs):
        raise clientes_despacho.InventarioVentaNoDisponible("COM-07 caído")

    monkeypatch.setattr(clientes_despacho.ClienteInventarioVenta, "confirmarVenta", _falla)
    respuesta, _ = despacharOrden(cliente, sesion, usuario.id)
    assert respuesta.status_code == 503
    assert respuesta.json()["message"] == "No fue posible obtener la clave del inventario"
    assert sesion.query(RegistroCompra).one().estadoDespacho == "PENDIENTE_REINTENTO"


def test_error503BaseDeDatos(cliente, sesion, monkeypatch):
    def _falla(*_args, **_kwargs):
        raise OperationalError("SELECT", {}, Exception("BD caída"))

    monkeypatch.setattr(RepositorioDespacho, "obtenerRegistroCompra", _falla)
    respuesta, _ = despacharOrden(cliente, sesion, 1)
    assert respuesta.status_code == 503
    assert respuesta.json()["message"] == "No fue posible asignar la licencia"
