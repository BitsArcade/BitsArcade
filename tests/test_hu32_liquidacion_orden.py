"""Pruebas de HU-32: Liquidación financiera de la orden (GET /api/v1/ordenes/{ordenId}/liquidacion)."""
from sqlalchemy.exc import OperationalError

from app.repositories.repositorio_orden import RepositorioOrden
from tests.conftest import encabezado_auth


def _crear_orden(cliente, crear_juego, crear_keys, usuario_id=1) -> int:
    juego = crear_juego(costo_adquisicion=160000)  # P_venta = 238.000 COP (IVA 19%)
    crear_keys(juego.id, disponibles=5)
    cliente.post(
        "/api/v1/carrito/items",
        json={"juegoId": juego.id, "cantidad": 1},
        headers=encabezado_auth(usuario_id),
    )
    resp = cliente.post("/api/v1/ordenes", headers=encabezado_auth(usuario_id))
    assert resp.status_code == 201
    return resp.json()["data"]["ordenId"]


def test_flujo_exitoso_liquidacion_orden(cliente, crear_juego, crear_keys):
    orden_id = _crear_orden(cliente, crear_juego, crear_keys)

    respuesta = cliente.get(f"/api/v1/ordenes/{orden_id}/liquidacion", headers=encabezado_auth())
    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["success"] is True
    assert cuerpo["message"] == "Liquidación financiera de la orden obtenida"
    assert cuerpo["data"] == {
        "ordenId": orden_id,
        "estado": "PENDIENTE",
        "moneda": "COP",
        "tasaIvaPorcentaje": 19.0,
        "subtotalBruto": 238000.0,
        "descuentoVolumenTotal": 0.0,
        "baseGravable": 200000.0,
        "valorIva": 38000.0,
        "totalPagar": 238000.0,
    }


def test_error_404_orden_inexistente_o_ajena(cliente, crear_juego, crear_keys):
    orden_id = _crear_orden(cliente, crear_juego, crear_keys, usuario_id=1)

    resp_ajena = cliente.get(f"/api/v1/ordenes/{orden_id}/liquidacion", headers=encabezado_auth(usuario_id=2))
    assert resp_ajena.status_code == 404
    assert resp_ajena.json() == {"message": "La orden indicada no existe", "data": None, "success": False}


def test_error_401_sin_token(cliente):
    respuesta = cliente.get("/api/v1/ordenes/1/liquidacion")
    assert respuesta.status_code == 401


def test_error_503_base_de_datos(cliente, monkeypatch):
    def _falla(*_args, **_kwargs):
        raise OperationalError("SELECT", {}, Exception("BD caída"))

    monkeypatch.setattr(RepositorioOrden, "obtener_por_id_y_usuario", _falla)
    respuesta = cliente.get("/api/v1/ordenes/1/liquidacion", headers=encabezado_auth())
    assert respuesta.status_code == 503