"""
Pruebas de extremo a extremo del flujo de compra de BitArcade:
registro → confirmación → inicio de sesión → catálogo → carrito → orden → pago (aprobado / rechazado)
→ entrega de N licencias → biblioteca, más la protección de las rutas internas con token de servicio.
"""
import pytest

from app.api.pagos import servicioPagos
from app.domain.despacho import AsignacionLicencia
from app.domain.inventario import ClaveLicencia
from app.domain.pagos import Comprobante
from app.services.cliente_notificaciones import ENVIOS_SIMULADOS
from tests.apoyo_modulos import cargarClaves, cuerpoFirmado, limpiarSimulaciones, obtenerOrden

URL_NOTIFICACION = "/api/v1/pagos/notificacion-pasarela"
CLAVES = ["AAAAA-BBBBB-00001", "AAAAA-BBBBB-00002", "AAAAA-BBBBB-00003"]


@pytest.fixture(autouse=True)
def _limpiar():
    limpiarSimulaciones()


def _registrarYConfirmar(cliente, correo="jugador@correo.com") -> dict:
    registro = cliente.post("/api/v1/usuarios/autenticacion/registro",
                            json={"correo": correo, "contrasena": "Clave#2026", "nombre": "Ana Pérez"})
    assert registro.status_code == 201
    codigo = ENVIOS_SIMULADOS[-1]["datos"]["codigo"]
    confirmacion = cliente.post("/api/v1/usuarios/autenticacion/registro/confirmar",
                                json={"correo": correo, "codigo": codigo})
    assert confirmacion.status_code == 200
    inicio = cliente.post("/api/v1/usuarios/autenticacion/inicio-sesion",
                          json={"correo": correo, "contrasena": "Clave#2026"})
    assert inicio.status_code == 200
    return {"Authorization": f"Bearer {inicio.json()['data']['token']}"}


def _comprarHastaPago(cliente, sesion, crearJuego, cantidad=2):
    auth = _registrarYConfirmar(cliente)
    juego = crearJuego(costoAdquisicion=160000)
    cargarClaves(sesion, juego.id, CLAVES)

    catalogo = cliente.get("/api/v1/catalogo/juegos").json()
    assert any(j["juegoId"] == juego.id for j in catalogo["data"]["items"])
    assert cliente.get(f"/api/v1/catalogo/juegos/{juego.id}/precio").json()["data"]["precioFinal"] == 238000
    assert cliente.get(f"/api/v1/catalogo/juegos/{juego.id}/stock").json()["data"]["estadoStock"] == "DISPONIBLE"

    agregado = cliente.post("/api/v1/carrito/items", json={"juegoId": juego.id, "cantidad": cantidad}, headers=auth)
    assert agregado.status_code in (200, 201)
    subtotalCarrito = cliente.get("/api/v1/carrito", headers=auth).json()["data"]["subtotal"]

    orden = cliente.post("/api/v1/ordenes", json={"moneda": "COP"}, headers={**auth, "Idempotency-Key": "compra-1"})
    assert orden.status_code == 201
    datosOrden = orden.json()["data"]
    assert datosOrden["total"] == subtotalCarrito
    assert sesion.query(ClaveLicencia).filter_by(estado="RESERVADA").count() == cantidad

    liquidacion = cliente.get(f"/api/v1/ordenes/{datosOrden['ordenId']}/liquidacion", headers=auth).json()["data"]
    assert liquidacion["desglose"]["total"] == datosOrden["total"]

    pago = cliente.post("/api/v1/pagos", json={"ordenId": datosOrden["ordenId"], "metodoPagoId": 1}, headers=auth)
    assert pago.status_code == 202
    assert obtenerOrden(sesion, datosOrden["ordenId"]).estado == "PROCESANDO"
    return auth, juego, datosOrden, pago.json()["data"]["transaccionId"]


def _notificar(cliente, transaccionId, ordenId, estado, monto):
    cuerpo, encabezados = cuerpoFirmado({"transaccionId": transaccionId, "ordenId": ordenId, "estado": estado,
                                          "referenciaPasarela": "SIM-1", "monto": monto, "moneda": "COP"})
    return cliente.post(URL_NOTIFICACION, content=cuerpo, headers=encabezados)


def test_pagoAprobadoEntregaUnaLicenciaPorUnidad(cliente, sesion, crearJuego):
    auth, juego, orden, transaccionId = _comprarHastaPago(cliente, sesion, crearJuego, cantidad=2)
    respuesta = _notificar(cliente, transaccionId, orden["ordenId"], "APROBADO", orden["total"])
    assert respuesta.status_code == 200
    assert respuesta.json()["data"] == {"transaccionId": transaccionId, "estado": "APROBADA",
                                        "estadoOrden": "PAGADA", "estadoDespacho": "ACTIVADO"}

    assert sesion.query(AsignacionLicencia).count() == 2                       # 2 unidades → 2 licencias
    assert sesion.query(ClaveLicencia).filter_by(estado="VENDIDA").count() == 2
    assert sesion.query(ClaveLicencia).filter_by(estado="DISPONIBLE").count() == 1
    assert sesion.query(Comprobante).count() == 1
    assert obtenerOrden(sesion, orden["ordenId"]).estado == "ENTREGADA"

    biblioteca = cliente.get("/api/v1/biblioteca", headers=auth).json()
    assert biblioteca["success"] is True and len(biblioteca["data"]) == 2
    assert all(l["claveLicencia"] == "*****-*****-*****" for l in biblioteca["data"])

    licenciaId = biblioteca["data"][0]["licenciaId"]
    revelada = cliente.post(f"/api/v1/biblioteca/licencias/{licenciaId}/revelar", headers=auth)
    assert revelada.status_code == 200 and revelada.headers["Cache-Control"] == "no-store"
    assert revelada.json()["data"]["claveLicencia"] in CLAVES[:2]

    compra = cliente.get(f"/api/v1/biblioteca/compras/{orden['ordenId']}", headers=auth).json()
    assert compra["data"]["estadoOrden"] == "ENTREGADA" and len(compra["data"]["items"]) == 2
    estadoPago = cliente.get(f"/api/v1/pagos/{transaccionId}/estado", headers=auth).json()["data"]
    assert estadoPago["estado"] == "APROBADA"


def test_pagoRechazadoLiberaLasClavesYCancelaLaOrden(cliente, sesion, crearJuego):
    auth, juego, orden, transaccionId = _comprarHastaPago(cliente, sesion, crearJuego, cantidad=2)
    respuesta = _notificar(cliente, transaccionId, orden["ordenId"], "RECHAZADO", orden["total"])
    assert respuesta.status_code == 200
    assert respuesta.json()["data"]["estado"] == "FALLIDA" and respuesta.json()["data"]["estadoOrden"] == "CANCELADA"
    assert obtenerOrden(sesion, orden["ordenId"]).estado == "CANCELADA"
    assert sesion.query(ClaveLicencia).filter_by(estado="DISPONIBLE").count() == 3   # Nada queda reservado
    assert sesion.query(AsignacionLicencia).count() == 0
    assert cliente.get("/api/v1/biblioteca", headers=auth).json()["success"] is False


def test_pasarelaSinRespuestaPermiteReintentarElPago(cliente, sesion, crearJuego, monkeypatch):
    auth = _registrarYConfirmar(cliente)
    juego = crearJuego()
    cargarClaves(sesion, juego.id, CLAVES[:1])
    cliente.post("/api/v1/carrito/items", json={"juegoId": juego.id, "cantidad": 1}, headers=auth)
    ordenId = cliente.post("/api/v1/ordenes", json={"moneda": "COP"},
                           headers={**auth, "Idempotency-Key": "k"}).json()["data"]["ordenId"]
    monkeypatch.setattr(servicioPagos.clientePasarela, "simularTimeout", True)
    assert cliente.post("/api/v1/pagos", json={"ordenId": ordenId}, headers=auth).status_code == 504
    monkeypatch.setattr(servicioPagos.clientePasarela, "simularTimeout", False)
    reintento = cliente.post("/api/v1/pagos", json={"ordenId": ordenId}, headers=auth)
    assert reintento.status_code == 202 and reintento.json()["data"]["estado"] == "EN_PROCESO"


@pytest.mark.parametrize("metodo, ruta", [
    ("get", "/interno/v1/parametrizacion/financieros"),
    ("get", "/interno/v1/parametrizacion/tasa-cambio/USD"),
    ("get", "/interno/v1/usuarios/1/validacion"),
    ("get", "/interno/v1/usuarios/1/comprador"),
    ("get", "/interno/v1/catalogo/juegos/1"),
    ("get", "/interno/v1/inventario/stock/1"),
    ("post", "/interno/v1/inventario/reservas"),
    ("post", "/interno/v1/inventario/reservas/liberar"),
    ("post", "/interno/v1/inventario/reservas/res-1/venta"),
    ("get", "/interno/v1/ordenes/1"),
    ("patch", "/interno/v1/ordenes/1/estado"),
    ("post", "/interno/v1/despacho/ordenes"),
    ("get", "/interno/v1/despacho/ordenes/1/elegibilidad"),
])
def test_rutasInternasExigenTokenDeServicio(clienteSinTokenServicio, metodo, ruta):
    respuesta = getattr(clienteSinTokenServicio, metodo)(ruta)
    assert respuesta.status_code == 401
    assert respuesta.json() == {"message": "Token de servicio inválido o ausente", "data": None, "success": False}
    malo = getattr(clienteSinTokenServicio, metodo)(ruta, headers={"X-Token-Servicio": "token-falso"})
    assert malo.status_code == 401
