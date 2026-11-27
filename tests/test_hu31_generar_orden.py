"""Pruebas de HU-31: Consolidar orden de compra pendiente (POST /api/v1/ordenes)."""
from sqlalchemy.exc import OperationalError

from app.api.ordenes import servicioOrdenes
from app.domain.inventario import ClaveLicencia
from app.domain.ordenes import Orden, ReservaOrden
from app.domain.usuarios import ESTADO_PENDIENTE_CONFIRMACION
from app.repositories.repositorio_ordenes import RepositorioOrdenes
from tests.apoyo_modulos import agregarAlCarrito, cargarClaves, crearUsuario, generarOrden, prepararOrden
from tests.conftest import encabezadoAuth


def test_flujoExitosoOrdenPendienteConReservas(cliente, sesion, crearJuego):
    usuario, juego, datos = prepararOrden(cliente, sesion, crearJuego, cantidad=2)
    assert datos["estado"] == "PENDIENTE" and datos["moneda"] == "COP" and datos["tasaCambio"] == 1
    assert datos["total"] == 238000 * 2 and datos["expiraEn"].endswith("Z")
    orden = sesion.get(Orden, datos["ordenId"])
    assert orden.tasaIva == 19.0                                            # IVA congelado (RN-09)
    assert sesion.query(ReservaOrden).count() == 2                          # Una reserva por unidad
    assert sesion.query(ClaveLicencia).filter_by(estado="RESERVADA").count() == 2
    carrito = cliente.get("/api/v1/carrito", headers=encabezadoAuth(usuario.id)).json()["data"]
    assert carrito["items"] == []                                           # El carrito queda vacío


def test_idempotentePorIdempotencyKey(cliente, sesion, crearJuego):
    usuario, juego, datos = prepararOrden(cliente, sesion, crearJuego)
    repetida = generarOrden(cliente, usuario.id).json()
    assert repetida["data"]["ordenId"] == datos["ordenId"]
    assert sesion.query(Orden).count() == 1


def test_monedaExtranjeraUsaTasaCongelada(cliente, sesion, crearJuego):
    cliente.post("/api/v1/parametrizacion/monedas", json={"nombre": "Dólar estadounidense", "codigoIso": "USD"},
                  headers=encabezadoAuth(1, rol="ADMIN"))
    _, _, datos = prepararOrden(cliente, sesion, crearJuego, moneda="USD")
    assert datos["moneda"] == "USD" and datos["tasaCambio"] == 4000.0
    assert datos["total"] == 59.5                                           # 238000 / 4000, 2 decimales


def test_error409CarritoVacio(cliente, sesion):
    usuario = crearUsuario(sesion)
    respuesta = generarOrden(cliente, usuario.id)
    assert respuesta.status_code == 409
    assert respuesta.json() == {"message": "No es posible generar una orden con el carrito vacío", "data": None,
                                "success": False}


def test_error409MonedaNoHabilitada(cliente, sesion, crearJuego):
    usuario = crearUsuario(sesion)
    juego = crearJuego()
    cargarClaves(sesion, juego.id, ["AAAAA-BBBBB-00001"])
    agregarAlCarrito(cliente, usuario.id, juego.id)
    respuesta = generarOrden(cliente, usuario.id, moneda="EUR")
    assert respuesta.status_code == 409
    assert respuesta.json()["message"] == "La moneda indicada no está habilitada"


def test_error409StockInsuficienteNoDejaReservas(cliente, sesion, crearJuego):
    usuario = crearUsuario(sesion)
    juego = crearJuego()
    cargarClaves(sesion, juego.id, ["AAAAA-BBBBB-00001", "AAAAA-BBBBB-00002"])
    agregarAlCarrito(cliente, usuario.id, juego.id, 2)
    sesion.query(ClaveLicencia).filter(ClaveLicencia.id == 1).update({"estado": "VENDIDA"})
    sesion.commit()
    respuesta = generarOrden(cliente, usuario.id)
    assert respuesta.status_code == 409
    assert respuesta.json()["message"] == "Stock insuficiente para generar la orden"
    assert sesion.query(Orden).count() == 0
    assert sesion.query(ClaveLicencia).filter_by(estado="RESERVADA").count() == 0   # Todo o nada (RN-04)


def test_error503TasaDeCambioNoDisponible(cliente, sesion, crearJuego, monkeypatch):
    cliente.post("/api/v1/parametrizacion/monedas", json={"nombre": "Dólar", "codigoIso": "USD"},
                  headers=encabezadoAuth(1, rol="ADMIN"))
    usuario = crearUsuario(sesion)
    juego = crearJuego()
    cargarClaves(sesion, juego.id, ["AAAAA-BBBBB-00001"])
    agregarAlCarrito(cliente, usuario.id, juego.id)
    monkeypatch.setattr(servicioOrdenes.servicioParametros.clienteDivisas, "disponible", False)
    respuesta = generarOrden(cliente, usuario.id, moneda="USD")
    assert respuesta.status_code == 503
    assert respuesta.json()["message"] == "No fue posible obtener la tasa de cambio vigente"


def test_error403CuentaSinConfirmar(cliente, sesion, crearJuego):
    usuario = crearUsuario(sesion, estado=ESTADO_PENDIENTE_CONFIRMACION)
    juego = crearJuego()
    cargarClaves(sesion, juego.id, ["AAAAA-BBBBB-00001"])
    agregarAlCarrito(cliente, usuario.id, juego.id)
    respuesta = generarOrden(cliente, usuario.id)
    assert respuesta.status_code == 403
    assert respuesta.json()["message"] == "Debe confirmar su cuenta para realizar compras"


def test_error400SinIdempotencyKey(cliente, sesion):
    usuario = crearUsuario(sesion)
    respuesta = cliente.post("/api/v1/ordenes", json={"moneda": "COP"}, headers=encabezadoAuth(usuario.id))
    assert respuesta.status_code == 400
    assert respuesta.json()["message"] == "El encabezado Idempotency-Key es obligatorio"


def test_error401SinToken(cliente):
    respuesta = cliente.post("/api/v1/ordenes", json={"moneda": "COP"}, headers={"Idempotency-Key": "x"})
    assert respuesta.status_code == 401


def test_error503BaseDeDatos(cliente, sesion, monkeypatch):
    def _falla(*_args, **_kwargs):
        raise OperationalError("SELECT", {}, Exception("BD caída"))

    monkeypatch.setattr(RepositorioOrdenes, "obtenerPorIdempotencia", _falla)
    respuesta = generarOrden(cliente, 1)
    assert respuesta.status_code == 503
    assert respuesta.json()["message"] == "No fue posible generar la orden"
