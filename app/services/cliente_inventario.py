from sqlalchemy.orm import Session

from app.domain.inventario import ESTADO_CLAVE_DISPONIBLE, ClaveLicencia

MENSAJE_COM12_NO_DISPONIBLE = "No fue posible verificar la disponibilidad"


class InventarioNoDisponible(Exception):
    """COM-12 no respondió: el consumidor debe responder 503 y NUNCA asumir DISPONIBLE."""


class ClienteInventario:
    """
    Adaptador del contrato COM-12 (MOD-02 y MOD-04 → API Inventario MOD-03).

    Retorna la cantidad de claves DISPONIBLE de un juego. Es de uso interno: el conteo exacto
    nunca se expone en respuestas públicas. Hoy consulta en proceso el modelo provisional
    `ClaveLicencia`; si MOD-03 se separa, se reemplaza por un cliente HTTP manteniendo la firma.
    """

    def contarDisponibles(self, sesion: Session, juegoId: int) -> int:
        try:
            return (
                sesion.query(ClaveLicencia)
                .filter(ClaveLicencia.juegoId == juegoId, ClaveLicencia.estado == ESTADO_CLAVE_DISPONIBLE)
                .count()
            )
        except Exception as error:
            raise InventarioNoDisponible(MENSAJE_COM12_NO_DISPONIBLE) from error

    # Compatibilidad temporal: nombre anterior usado por MOD-04 (órdenes) mientras migra a la convención.
    def contar_disponibles(self, sesion: Session, juego_id: int) -> int:
        return self.contarDisponibles(sesion, juego_id)
