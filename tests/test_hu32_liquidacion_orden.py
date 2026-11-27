"""Pruebas de HU-32: Liquidación financiera de la orden (GET /api/v1/ordenes/{ordenId}/liquidacion)."""
from sqlalchemy.exc import OperationalError

from app.domain.ordenes import calcularLiquidacion
from app.repositories.repositorio_ordenes import RepositorioOrdenes
from tests.apoyo_modulos import prepararOrden
from tests.conftest import encabezadoAuth, configurarParametros


def _url(ordenId):
    return f"/api/v1/ordenes/{ordenId}/liquidacion"


def test_flujoExitosoDesgloseCop(cliente, sesion, crearJuego):
    usuario, juego, datos = prepararOrden(cliente, sesion, crearJuego)
    respuesta = cliente.get(_url(datos["ordenId"]), headers=encabezadoAuth(usuario.id))
    assert respuesta.status_code == 200
    assert respuesta.json() == {
        "message": "Liquidación obtenida exitosamente",
        "data": {
            "ordenId": datos["ordenId"], "moneda": "COP", "tasaCambio": 1.0,
            "desglose": {"subtotal": 238000, "descuentos": 0, "baseGravable": 200000, "valorIva": 38000,
                         "total": 238000},
            "lineas": [{"juegoId": juego.id, "cantidad": 1, "precioUnitario": 238000}],
        },
        "success": True,
    }


def test_valoresCongeladosAunqueCambieElIva(cliente, sesion, crearJuego):
    usuario, _, datos = prepararOrden(cliente, sesion, crearJuego)
    configurarParametros(cliente, tasaIva=5)
    desglose = cliente.get(_url(datos["ordenId"]), headers=encabezadoAuth(usuario.id)).json()["data"]["desglose"]
    assert desglose["valorIva"] == 38000   # RN-09: no se recalcula con el IVA nuevo


def test_redondeoUsdDosDecimalesYSumaCuadra():
    desglose = calcularLiquidacion(238000, 0, 19, 4000, "USD")
    assert desglose["total"] == 59.5 and desglose["baseGravable"] == 50.0 and desglose["valorIva"] == 9.5
    assert round(desglose["baseGravable"] + desglose["valorIva"], 2) == desglose["total"]


def test_error404OrdenAjena(cliente, sesion, crearJuego):
    _, _, datos = prepararOrden(cliente, sesion, crearJuego)
    respuesta = cliente.get(_url(datos["ordenId"]), headers=encabezadoAuth(999))
    assert respuesta.status_code == 404
    assert respuesta.json() == {"message": "La orden indicada no existe", "data": None, "success": False}


def test_error401SinToken(cliente):
    assert cliente.get(_url(1)).status_code == 401


def test_error503BaseDeDatos(cliente, monkeypatch):
    def _falla(*_args, **_kwargs):
        raise OperationalError("SELECT", {}, Exception("BD caída"))

    monkeypatch.setattr(RepositorioOrdenes, "obtenerDeUsuario", _falla)
    respuesta = cliente.get(_url(1), headers=encabezadoAuth(1))
    assert respuesta.status_code == 503
    assert respuesta.json()["message"] == "No fue posible obtener la liquidación"
