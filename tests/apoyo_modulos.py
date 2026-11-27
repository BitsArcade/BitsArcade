"""
Utilidades de prueba compartidas por las HU de MOD-01 (Usuarios) y MOD-03 (Inventario).
"""
import bcrypt

from app.domain.inventario import CargaLoteEntrada, ReservarClavesEntrada
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
