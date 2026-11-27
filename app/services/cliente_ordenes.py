"""
Cliente de los contratos COM-08 y COM-09 de MOD-04 (Órdenes), usado por MOD-05 y MOD-06.

Se resuelve en proceso con `ServicioOrdenes` (mismas reglas que las rutas
GET /interno/v1/ordenes/{ordenId} y PATCH /interno/v1/ordenes/{ordenId}/estado, que exigen token
de servicio). Si los módulos se separan, basta con reemplazar estos métodos por llamadas HTTP
con `encabezadosServicio(modulo)` manteniendo las firmas.
"""
from datetime import datetime

from sqlalchemy.orm import Session

from app.core.respuestas import ErrorAplicacion
from app.domain.ordenes import (  # noqa: F401  (reexportados para los consumidores)
    ESTADO_ORDEN_CANCELADA,
    ESTADO_ORDEN_ENTREGADA,
    ESTADO_ORDEN_PAGADA,
    ESTADO_ORDEN_PENDIENTE,
    ESTADO_ORDEN_PROCESANDO,
)


class OrdenesNoDisponible(Exception):
    """MOD-04 no respondió (503 o error de infraestructura)."""


class TransicionNoPermitida(Exception):
    """MOD-04 respondió 409 (transición no permitida u orden expirada) o 404."""

    def __init__(self, mensaje: str, codigoHttp: int = 409):
        super().__init__(mensaje)
        self.mensaje = mensaje
        self.codigoHttp = codigoHttp


class ClienteOrdenes:
    disponible: bool = True

    def __init__(self, modulo: str = "MOD-05"):
        self.modulo = modulo

    def _servicio(self):
        if not self.disponible:
            raise OrdenesNoDisponible("MOD-04 no disponible")
        from app.services.servicio_ordenes import ServicioOrdenes

        return ServicioOrdenes()

    def obtenerOrden(self, sesion: Session, ordenId: int) -> dict | None:
        """COM-08 ampliado: {ordenId, usuarioId, estado, moneda, tasaCambio, total, expiraEn, items[...]}."""
        try:
            return self._servicio().obtenerContratoCom08(sesion, ordenId)
        except OrdenesNoDisponible:
            raise
        except Exception as error:
            raise OrdenesNoDisponible(str(error)) from error

    def actualizarEstado(
        self,
        sesion: Session,
        ordenId: int,
        estado: str,
        transaccionId: str | None = None,
        entregadaEn: datetime | None = None,
    ) -> dict:
        """COM-09 con el módulo solicitante (MOD-05 o MOD-06). Repetir el mismo estado es idempotente."""
        servicio = self._servicio()
        try:
            resultado = servicio.actualizarEstado(
                sesion, ordenId, estado, transaccionId=transaccionId, entregadaEn=entregadaEn, solicitante=self.modulo
            )
        except ErrorAplicacion as error:
            if error.codigoHttp in (404, 409):
                raise TransicionNoPermitida(error.mensaje, error.codigoHttp) from error
            raise OrdenesNoDisponible(error.mensaje) from error
        except Exception as error:
            raise OrdenesNoDisponible(str(error)) from error
        return resultado["data"]
