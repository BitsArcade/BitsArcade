from sqlalchemy.orm import Session

from app.domain.inventario import ESTADO_KEY_DISPONIBLE, KeyLicencia

MENSAJE_COM12_NO_DISPONIBLE = "No fue posible verificar la disponibilidad"


class InventarioNoDisponible(Exception):
    """COM-12 no respondió: el consumidor debe responder 503 y NUNCA asumir DISPONIBLE."""


class ClienteInventario:
    """
    Adaptador del contrato COM-12 (MOD-02 y MOD-04 → API Inventario MOD-03).

    Retorna la cantidad de keys DISPONIBLE de un juego. Es de uso interno: el conteo exacto
    nunca se expone en respuestas públicas. Hoy consulta en proceso el modelo provisional
    `KeyLicencia`; si MOD-03 se separa, se reemplaza por un cliente HTTP manteniendo la firma.
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
