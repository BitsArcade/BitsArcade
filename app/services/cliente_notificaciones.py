"""
PLACEHOLDER – Cliente de la API externa Notificaciones (simulada).

MOD-01 es el módulo responsable de la API Notificaciones (Tabla 9). Aún no existe un proveedor
real: este cliente simula el envío y deja registro en memoria (`ENVIOS_SIMULADOS`) para pruebas.
Cuando exista la API real, se reemplaza el cuerpo de `enviar` por la llamada HTTP manteniendo la firma.
"""
import itertools
import logging

registro = logging.getLogger("bitarcade.notificaciones")


class NotificacionesNoDisponible(Exception):
    """La API Notificaciones no respondió."""


ENVIOS_SIMULADOS: list[dict] = []
_secuencia = itertools.count(301)


class ClienteNotificaciones:
    """Envío de correos transaccionales (HU-06, HU-10 y HU-44)."""

    disponible: bool = True

    def enviar(self, destinatario: str, plantilla: str, datos: dict) -> dict:
        """Envía la plantilla al destinatario. Retorna {notificacionId, estado}."""
        if not self.disponible:
            raise NotificacionesNoDisponible("El servicio de notificaciones no está disponible")
        envio = {
            "notificacionId": f"NTF-{next(_secuencia)}",
            "destinatario": destinatario,
            "plantilla": plantilla,
            "datos": datos,
        }
        ENVIOS_SIMULADOS.append(envio)
        registro.info("Notificación %s simulada para plantilla %s", envio["notificacionId"], plantilla)
        return {"notificacionId": envio["notificacionId"], "estado": "ENVIADA"}
