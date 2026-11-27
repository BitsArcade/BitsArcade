"""
Adaptadores de MOD-06 hacia otros módulos (en proceso; se reemplazan por HTTP si se separan):

- COM-05 (MOD-01 Usuarios): valida al comprador y entrega {usuarioId, correo, nombre}.
- COM-07 (MOD-03 Inventario): confirma la venta de una reserva y entrega la clave (HU-14).
"""
from sqlalchemy.orm import Session

from app.core.cifrado import descifrarClave
from app.services.cliente_usuarios import ClienteUsuarios  # noqa: F401  (COM-05)


class InventarioVentaNoDisponible(Exception):
    """COM-07 no respondió o rechazó la venta."""


class ClienteInventarioVenta:
    """COM-07: POST /interno/v1/inventario/reservas/{reservaId}/venta."""

    def confirmarVenta(self, sesion: Session, reservaId: str) -> dict:
        from app.services.servicio_inventario import ServicioInventario

        try:
            _reserva, registroClave = ServicioInventario().confirmarVentaInterna(sesion, reservaId)
            return {"claveLicencia": descifrarClave(registroClave.claveCifrada), "plataforma": registroClave.plataforma}
        except Exception as error:
            raise InventarioVentaNoDisponible(str(error)) from error
