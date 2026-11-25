from sqlalchemy.orm import Session

from app.domain.inventario import (
    ESTADO_KEY_DISPONIBLE,
    ESTADO_KEY_RESERVADA,
    KeyLicencia,
)

MENSAJE_COM12_NO_DISPONIBLE = "No fue posible verificar la disponibilidad"


class InventarioNoDisponible(Exception):
    """COM-12 no respondió: el consumidor debe responder 503 y NUNCA asumir DISPONIBLE."""


class StockInsuficienteInventario(Exception):
    """No hay suficientes keys DISPONIBLE para reservar."""


class ClienteInventario:
    """
    Adaptador del contrato COM-12 (MOD-02 y MOD-04 -> API Inventario MOD-03).
    """

    def contar_disponibles(self, sesion: Session, juego_id: int) -> int:
        try:
            return (
                sesion.query(KeyLicencia)
                .filter(KeyLicencia.juego_id == juego_id, KeyLicencia.estado == ESTADO_KEY_DISPONIBLE)
                .count()
            )
        except Exception as error:
            raise InventarioNoDisponible(MENSAJE_COM12_NO_DISPONIBLE) from error

    def reservar_keys(self, sesion: Session, juego_id: int, cantidad: int) -> list[int]:
        """Marca `cantidad` keys DISPONIBLE como RESERVADA al consolidar una orden (HU-31)."""
        try:
            keys = (
                sesion.query(KeyLicencia)
                .filter(KeyLicencia.juego_id == juego_id, KeyLicencia.estado == ESTADO_KEY_DISPONIBLE)
                .limit(cantidad)
                .all()
            )
            if len(keys) < cantidad:
                raise StockInsuficienteInventario("Stock insuficiente al intentar reservar licencias")
            for key in keys:
                key.estado = ESTADO_KEY_RESERVADA
            sesion.flush()
            return [k.id for k in keys]
        except StockInsuficienteInventario:
            raise
        except Exception as error:
            raise InventarioNoDisponible(MENSAJE_COM12_NO_DISPONIBLE) from error

    def liberar_keys(self, sesion: Session, juego_id: int, cantidad: int) -> int:
        """Devuelve `cantidad` keys RESERVADA a DISPONIBLE al cancelar una orden (HU-34)."""
        try:
            keys = (
                sesion.query(KeyLicencia)
                .filter(KeyLicencia.juego_id == juego_id, KeyLicencia.estado == ESTADO_KEY_RESERVADA)
                .limit(cantidad)
                .all()
            )
            for key in keys:
                key.estado = ESTADO_KEY_DISPONIBLE
            sesion.flush()
            return len(keys)
        except Exception as error:
            raise InventarioNoDisponible(MENSAJE_COM12_NO_DISPONIBLE) from error