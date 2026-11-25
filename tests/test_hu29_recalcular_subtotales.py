"""Pruebas de HU-29: Recalcular subtotales con promociones y volumen (PATCH /api/v1/carrito/items/{itemId})."""
from sqlalchemy.exc import OperationalError

from app.domain.carrito import UMBRAL_DESCUENTO_VOLUMEN, PORCENTAJE_DESCUENTO_VOLUMEN, calcular_desglose
from app.repositories.repositorio_carrito import RepositorioCarrito
from app.services.servicio_parametros import ServicioParametros
from tests.conftest import encabezado_auth


def _agregar(cliente, juego_id, cantidad=1, usuario_id=1) -> int:
    respuesta = cliente.post("/api/v1/carrito/items", json={"juegoId": juego_id, "cantidad": cantidad},
                             headers=encabezado_auth(usuario_id))
    assert respuesta.status_code == 201
    return respuesta.json()["data"]["items"][0]["itemId"]


def _patch(cliente, item_id, cantidad, usuario_id=1):
    return cliente.patch(f"/api/v1/carrito/items/{item_id}", json={"cantidad": cantidad},
                         headers=encabezado_auth(usuario_id))


# --- Pruebas unitarias de dominio ---

def test_configuracion_estatica_rn08():
    assert UMBRAL_DESCUENTO_VOLUMEN == 3 and PORCENTAJE_DESCUENTO_VOLUMEN == 0.10


def test_rn08_descuento_por_volumen():
    assert calcular_desglose(238000, 190400, 3, "ACTIVO") == {
        "precioUnitario": 238000, "descuentoVolumen": 71400, "subtotal": 642600,
    }


def test_rn08_bajo_umbral_sin_descuento():
    assert calcular_desglose(238000, 190400, 2, "ACTIVO")["descuentoVolumen"] == 0


def test_rn07_preventa_y_estreno_sin_descuento():
    for estado in ("PREVENTA", "ESTRENO"):
        assert calcular_desglose(238000, 190400, 5, estado)["descuentoVolumen"] == 0


def test_rn02_descuento_no_baja_de_floor_price():
    # Precio 100, piso 95: el 10 % (10) se limita a 5 para no bajar de 95.
    desglose = calcular_desglose(100, 95, 3, "ACTIVO")
    assert desglose["descuentoVolumen"] == 15
    assert desglose["subtotal"] / 3 >= 95


# --- Pruebas funcionales ---

def test_flujo_exitoso(cliente, crear_juego, crear_keys):
    juego = crear_juego(costo_adquisicion=160000)
    crear_keys(juego.id, disponibles=10)
    item_id = _agregar(cliente, juego.id)
    respuesta = _patch(cliente, item_id, 3)
    assert respuesta.status_code == 200
    assert respuesta.json() == {
        "message": "Subtotales recalculados",
        "data": {"itemId": item_id, "juegoId": juego.id, "cantidad": 3, "precioUnitario": 238000,
                 "descuentoVolumen": 71400, "subtotal": 642600, "moneda": "COP"},
        "success": True,
    }
    # La cantidad queda persistida en el carrito
    carrito = cliente.get("/api/v1/carrito", headers=encabezado_auth()).json()["data"]
    assert carrito["items"][0]["cantidad"] == 3


def test_estreno_sin_descuento(cliente, crear_juego, crear_keys):
    juego = crear_juego(estado="ESTRENO")
    crear_keys(juego.id, disponibles=10)
    datos = _patch(cliente, _agregar(cliente, juego.id), 4).json()["data"]
    assert datos["descuentoVolumen"] == 0 and datos["subtotal"] == 238000 * 4


def test_rn02_con_margen_bajo(cliente, crear_juego, crear_keys):
    juego = crear_juego(costo_adquisicion=100000)
    crear_keys(juego.id, disponibles=10)
    cliente.put("/api/v1/parametros/margen-ganancia", json={"margen_ganancia": 5})  # M=5 % < 10 %
    datos = _patch(cliente, _agregar(cliente, juego.id), 3).json()["data"]
    piso = 100000 * 1.19
    assert round((datos["subtotal"]) / 3, 2) >= round(piso, 2)


def test_error_400_cantidad_cero(cliente, crear_juego, crear_keys):
    juego = crear_juego()
    crear_keys(juego.id, disponibles=10)
    respuesta = _patch(cliente, _agregar(cliente, juego.id), 0)
    assert respuesta.status_code == 400
    assert respuesta.json() == {
        "message": "cantidad debe ser mayor o igual a 1. Use DELETE para retirar el ítem", "data": None,
        "success": False,
    }


def test_error_409_preventa_cantidad_2(cliente, crear_juego, crear_keys):
    juego = crear_juego(estado="PREVENTA")
    crear_keys(juego.id, disponibles=10)
    respuesta = _patch(cliente, _agregar(cliente, juego.id), 2)
    assert respuesta.status_code == 409
    assert respuesta.json()["message"] == "Solo se permite adquirir una licencia por título en preventa"


def test_error_409_stock_insuficiente(cliente, crear_juego, crear_keys):
    juego = crear_juego()
    crear_keys(juego.id, disponibles=2)
    respuesta = _patch(cliente, _agregar(cliente, juego.id), 3)
    assert respuesta.status_code == 409
    assert respuesta.json()["message"] == "Stock insuficiente para la cantidad solicitada"


def test_error_404_item_ajeno(cliente, crear_juego, crear_keys):
    juego = crear_juego()
    crear_keys(juego.id, disponibles=10)
    item_id = _agregar(cliente, juego.id, usuario_id=1)
    respuesta = _patch(cliente, item_id, 2, usuario_id=2)
    assert respuesta.status_code == 404
    assert respuesta.json() == {"message": "El ítem no existe en tu carrito", "data": None, "success": False}


def test_error_401_sin_token(cliente):
    respuesta = cliente.patch("/api/v1/carrito/items/1", json={"cantidad": 2})
    assert respuesta.status_code == 401
    assert respuesta.json() == {"message": "Token inválido, expirado o ausente", "data": None, "success": False}


def test_error_503_com11_no_responde(cliente, crear_juego, crear_keys, monkeypatch):
    juego = crear_juego()
    crear_keys(juego.id, disponibles=10)
    item_id = _agregar(cliente, juego.id)

    def _falla(self, sesion):
        raise ConnectionError("MOD-00 caído")

    monkeypatch.setattr(ServicioParametros, "obtener_contrato_com01", _falla)
    assert _patch(cliente, item_id, 2).status_code == 503


def test_error_503_base_de_datos(cliente, monkeypatch):
    def _falla(*_args, **_kwargs):
        raise OperationalError("UPDATE", {}, Exception("BD caída"))

    monkeypatch.setattr(RepositorioCarrito, "obtener_item_de_usuario", _falla)
    respuesta = _patch(cliente, 1, 2)
    assert respuesta.status_code == 503
    assert respuesta.json() == {"message": "No fue posible recalcular los subtotales", "data": None, "success": False}
