"""Pruebas de HU-27: Consultar ítems del carrito activo (GET /api/v1/carrito)."""
from sqlalchemy.exc import OperationalError

from app.repositories.repositorio_carrito import RepositorioCarrito
from app.services.servicio_parametros import ServicioParametros
from tests.conftest import encabezado_auth

URL = "/api/v1/carrito"


def _agregar(cliente, juego_id, cantidad=1, usuario_id=1):
    respuesta = cliente.post("/api/v1/carrito/items", json={"juegoId": juego_id, "cantidad": cantidad},
                             headers=encabezado_auth(usuario_id))
    assert respuesta.status_code == 201
    return respuesta.json()["data"]


def test_flujo_exitoso(cliente, crear_juego, crear_keys):
    juego = crear_juego(costo_adquisicion=160000)
    crear_keys(juego.id, disponibles=5)
    agregado = _agregar(cliente, juego.id)
    respuesta = cliente.get(URL, headers=encabezado_auth())
    assert respuesta.status_code == 200
    assert respuesta.json() == {
        "message": "Consulta de carrito exitosa",
        "data": {
            "carritoId": agregado["carritoId"],
            "items": [{"itemId": agregado["items"][0]["itemId"], "juegoId": juego.id, "titulo": "Aurora Quest",
                       "cantidad": 1, "precioUnitario": 238000}],
            "subtotal": 238000,
            "moneda": "COP",
        },
        "success": True,
    }


def test_subtotal_preliminar_sin_descuentos(cliente, crear_juego, crear_keys):
    juego = crear_juego(costo_adquisicion=160000)
    otro = crear_juego(titulo="Space Racer", costo_adquisicion=80000)  # 119000
    crear_keys(juego.id, disponibles=5)
    crear_keys(otro.id, disponibles=5)
    _agregar(cliente, juego.id, cantidad=3)  # 3 unidades: sin descuento por volumen aquí
    _agregar(cliente, otro.id, cantidad=1)
    datos = cliente.get(URL, headers=encabezado_auth()).json()["data"]
    assert datos["subtotal"] == 238000 * 3 + 119000


def test_precios_vigentes_provienen_del_catalogo(cliente, crear_juego, crear_keys):
    juego = crear_juego(costo_adquisicion=100000)
    crear_keys(juego.id, disponibles=5)
    _agregar(cliente, juego.id)
    cliente.put("/api/v1/parametros/margen-ganancia", json={"margen_ganancia": 50})
    datos = cliente.get(URL, headers=encabezado_auth()).json()["data"]
    assert datos["items"][0]["precioUnitario"] == 178500  # 100000 × 1.5 × 1.19


def test_solo_ve_su_propio_carrito(cliente, crear_juego, crear_keys):
    juego = crear_juego()
    crear_keys(juego.id, disponibles=5)
    _agregar(cliente, juego.id, usuario_id=1)
    assert cliente.get(URL, headers=encabezado_auth(2)).json()["data"]["items"] == []


def test_carrito_vacio(cliente):
    respuesta = cliente.get(URL, headers=encabezado_auth())
    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["message"] == "El carrito está vacío"
    assert cuerpo["success"] is False
    assert cuerpo["data"]["items"] == [] and cuerpo["data"]["subtotal"] == 0
    assert cuerpo["data"]["moneda"] == "COP" and isinstance(cuerpo["data"]["carritoId"], int)


def test_error_401_sin_token(cliente):
    respuesta = cliente.get(URL)
    assert respuesta.status_code == 401
    assert respuesta.json() == {"message": "Token inválido, expirado o ausente", "data": None, "success": False}


def test_error_503_com11_no_responde(cliente, crear_juego, crear_keys, monkeypatch):
    juego = crear_juego()
    crear_keys(juego.id, disponibles=5)
    _agregar(cliente, juego.id)

    def _falla(self, sesion):
        raise ConnectionError("MOD-00 caído")

    monkeypatch.setattr(ServicioParametros, "obtener_contrato_com01", _falla)
    respuesta = cliente.get(URL, headers=encabezado_auth())
    assert respuesta.status_code == 503
    assert respuesta.json() == {"message": "No fue posible obtener los precios vigentes", "data": None, "success": False}


def test_error_503_base_de_datos(cliente, monkeypatch):
    def _falla(*_args, **_kwargs):
        raise OperationalError("SELECT", {}, Exception("BD caída"))

    monkeypatch.setattr(RepositorioCarrito, "obtener_carrito_activo", _falla)
    respuesta = cliente.get(URL, headers=encabezado_auth())
    assert respuesta.status_code == 503
    assert respuesta.json() == {"message": "No fue posible consultar el carrito", "data": None, "success": False}
