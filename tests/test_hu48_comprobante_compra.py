"""Pruebas de HU-48: Descargar comprobante digital de compra (GET /api/v1/biblioteca/compras/{ordenId}/comprobante)."""
import pytest
from sqlalchemy.exc import OperationalError

from app.repositories.repositorio_despacho import RepositorioDespacho
from tests.apoyo_modulos import crearUsuario, despacharOrden, limpiarSimulaciones
from tests.conftest import encabezadoAuth

URL = "/api/v1/biblioteca/compras/5001/comprobante"


@pytest.fixture(autouse=True)
def _limpiar():
    limpiarSimulaciones()


def test_flujoExitosoDescargableConDesglose(cliente, sesion):
    usuario = crearUsuario(sesion)
    despacharOrden(cliente, sesion, usuario.id)
    respuesta = cliente.get(URL, headers=encabezadoAuth(usuario.id))
    assert respuesta.status_code == 200
    assert respuesta.headers["Content-Disposition"] == 'attachment; filename="comprobante-CMP-5001.json"'
    cuerpo = respuesta.json()
    assert cuerpo["message"] == "Comprobante generado"
    datos = cuerpo["data"]
    assert datos["numero"] == "CMP-5001" and datos["emisor"] == "BitArcade"
    assert datos["comprador"] == {"nombre": "Ana Pérez", "correo": "jugador@correo.com"}
    assert datos["desglose"] == {"baseGravable": 200000, "valorIva": 38000, "total": 238000}
    assert datos["transaccionId"] == "TX-5001" and datos["tasaCambio"] == 1
    assert datos["items"] == [{"titulo": "Aurora Quest", "cantidad": 1}]


def test_error404CompraAjena(cliente, sesion):
    usuario = crearUsuario(sesion)
    despacharOrden(cliente, sesion, usuario.id)
    respuesta = cliente.get(URL, headers=encabezadoAuth(999))
    assert respuesta.status_code == 404
    assert respuesta.json()["message"] == "La compra indicada no existe"


def test_error401SinToken(cliente):
    assert cliente.get(URL).status_code == 401


def test_error503BaseDeDatos(cliente, monkeypatch):
    def _falla(*_args, **_kwargs):
        raise OperationalError("SELECT", {}, Exception("BD caída"))

    monkeypatch.setattr(RepositorioDespacho, "obtenerRegistroCompra", _falla)
    respuesta = cliente.get(URL, headers=encabezadoAuth(1))
    assert respuesta.status_code == 503
    assert respuesta.json()["message"] == "No fue posible generar el comprobante"
