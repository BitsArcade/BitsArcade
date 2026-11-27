"""
Utilidades de prueba compartidas por las HU de MOD-01, MOD-03 y MOD-04.
"""
from datetime import timedelta

import bcrypt

from app.core.seguridad import encabezadosServicio
from app.core.fechas import ahoraUtc
from app.domain.inventario import CargaLoteEntrada, ReservarClavesEntrada
from app.domain.ordenes import LineaOrden, Orden, ReservaOrden
from app.domain.usuarios import ESTADO_CONFIRMADA, Usuario
from app.services.cliente_notificaciones import ENVIOS_SIMULADOS
from app.services.servicio_inventario import ServicioInventario


def limpiarSimulaciones() -> None:
    ENVIOS_SIMULADOS.clear()


def crearUsuario(sesion, correo="jugador@correo.com", contrasena="Clave#2026", nombre="Ana Pérez",
                  estado=ESTADO_CONFIRMADA, rol="CLIENTE") -> Usuario:
    usuario = Usuario(
        correo=correo, nombre=nombre, rol=rol, estado=estado,
        contrasenaHash=bcrypt.hashpw(contrasena.encode(), bcrypt.gensalt(rounds=4)).decode(),
    )
    sesion.add(usuario)
    sesion.commit()
    sesion.refresh(usuario)
    return usuario


def cargarClaves(sesion, juegoId=101, claves=("AAAAA-BBBBB-CCCCC",), plataforma="PC") -> dict:
    return ServicioInventario().cargarLote(
        sesion, CargaLoteEntrada(juegoId=juegoId, plataforma=plataforma, claves=list(claves))
    )["data"]


def reservar(sesion, ordenId=5001, juegoId=101, cantidad=1) -> list[str]:
    datos = ReservarClavesEntrada(ordenId=ordenId, juegoId=juegoId, cantidad=cantidad)
    return ServicioInventario().reservarClaves(sesion, datos)["data"]["reservaIds"]


def crearOrdenPrueba(sesion, ordenId=5001, usuarioId=77, total=238000.0, items=None, estado="PENDIENTE",
                     minutosVigencia=15, moneda="COP", tasaCambio=1.0, tasaIva=19.0) -> Orden:
    """
    Inserta una orden real de MOD-04 (tablas ordenes / lineas_orden / reservas_orden) con valores
    congelados. `total` y `precioUnitario` se expresan en la moneda de la orden.
    """
    ahora = ahoraUtc()
    totalCop = round(float(total) * float(tasaCambio), 2)
    orden = Orden(
        id=ordenId, usuarioId=usuarioId, estado=estado, moneda=moneda, tasaCambio=tasaCambio, tasaIva=tasaIva,
        subtotalCop=totalCop, descuentosCop=0.0, totalCop=totalCop, claveIdempotencia=f"prueba-{ordenId}",
        expiraEn=ahora + timedelta(minutes=minutosVigencia), creadaEn=ahora, actualizadaEn=ahora,
    )
    items = items or []
    porJuego: dict[int, list[dict]] = {}
    for item in items:
        porJuego.setdefault(item["juegoId"], []).append(item)
    orden.lineas = [
        LineaOrden(juegoId=juegoId, titulo=grupo[0].get("titulo"), cantidad=len(grupo),
                   precioUnitarioCop=round(float(grupo[0]["precioUnitario"]) * tasaCambio, 2), descuentoCop=0.0)
        for juegoId, grupo in porJuego.items()
    ]
    orden.reservas = [
        ReservaOrden(juegoId=i["juegoId"], titulo=i.get("titulo"), reservaId=i["reservaId"],
                     precioUnitarioCop=round(float(i["precioUnitario"]) * tasaCambio, 2))
        for i in items
    ]
    sesion.add(orden)
    sesion.commit()
    sesion.refresh(orden)
    return orden


def obtenerOrden(sesion, ordenId=5001) -> Orden:
    sesion.expire_all()
    return sesion.get(Orden, ordenId)


def encabezadosInternos(modulo="MOD-05") -> dict:
    """Token de servicio exigido por las rutas /interno/v1."""
    return encabezadosServicio(modulo)


def despacharOrden(cliente, sesion, usuarioId, ordenId=5001, claves=("AAAAA-BBBBB-CCCCC",), juegoId=101,
                    titulo="Aurora Quest", precio=238000.0, crearOrden=True):
    """Prepara inventario + reserva y ejecuta COM-10 (HU-41). Retorna la respuesta HTTP."""
    cargarClaves(sesion, juegoId, list(claves))
    reservas = reservar(sesion, ordenId=ordenId, juegoId=juegoId, cantidad=len(claves))
    items = [{"juegoId": juegoId, "titulo": titulo, "reservaId": r, "precioUnitario": precio} for r in reservas]
    if crearOrden:
        crearOrdenPrueba(sesion, ordenId, usuarioId=usuarioId, total=precio * len(claves), items=items, estado="PAGADA")
    payload = {
        "ordenId": ordenId, "usuarioId": usuarioId, "transaccionId": f"TX-{ordenId}", "moneda": "COP",
        "tasaCambio": 1, "total": precio * len(claves), "items": items,
    }
    return cliente.post("/interno/v1/despacho/ordenes", json=payload, headers=encabezadosInternos("MOD-05")), payload


def agregarAlCarrito(cliente, usuarioId, juegoId, cantidad=1):
    from tests.conftest import encabezadoAuth

    respuesta = cliente.post("/api/v1/carrito/items", json={"juegoId": juegoId, "cantidad": cantidad},
                             headers=encabezadoAuth(usuarioId))
    assert respuesta.status_code in (200, 201), respuesta.json()
    return respuesta


def generarOrden(cliente, usuarioId, moneda="COP", claveIdempotencia="orden-1"):
    """HU-31: POST /api/v1/ordenes con el encabezado Idempotency-Key."""
    from tests.conftest import encabezadoAuth

    encabezados = {**encabezadoAuth(usuarioId), "Idempotency-Key": claveIdempotencia}
    return cliente.post("/api/v1/ordenes", json={"moneda": moneda}, headers=encabezados)


def prepararOrden(cliente, sesion, crearJuego, cantidad=1, claves=None, moneda="COP", usuario=None,
                  costoAdquisicion=160000.0):
    """Usuario confirmado + juego con claves cifradas + carrito + orden PENDIENTE. Retorna (usuario, juego, datos)."""
    usuario = usuario or crearUsuario(sesion)
    juego = crearJuego(costoAdquisicion=costoAdquisicion)
    claves = claves or [f"AAAAA-BBBBB-{i:05d}" for i in range(1, cantidad + 1)]
    cargarClaves(sesion, juego.id, claves)
    agregarAlCarrito(cliente, usuario.id, juego.id, cantidad)
    respuesta = generarOrden(cliente, usuario.id, moneda)
    assert respuesta.status_code == 201, respuesta.json()
    return usuario, juego, respuesta.json()["data"]
