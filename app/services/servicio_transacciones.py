"""
Servicio de aplicación para MOD-05 Transacciones (HU-36).
"""
import uuid
from typing import Any, Optional, Protocol

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.respuestas import ErrorAplicacion
from app.domain.orden import Orden
from app.domain.transacciones import (
    EstadoTransaccion,
    OrdenParaCobro,
    ReglasTransaccion,
    Transaccion,
)
from app.repositories.repositorio_transacciones import RepositorioTransacciones


class AdaptadorOrdenesCOM(Protocol):
    async def obtener_orden_com08(self, orden_id: int) -> Optional[OrdenParaCobro]:
        """Contrato COM-08: obtiene datos congelados de la orden en MOD-04."""
        ...

    async def marcar_orden_procesando_com09(self, orden_id: int) -> bool:
        """Contrato COM-09: cambia estado de la orden a PROCESANDO."""
        ...


class ClientePasarelaPagos(Protocol):
    async def transmitir_cobro(self, payload: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
        """API externa de Pagos simulada con Idempotency-Key = ordenId."""
        ...


class AdaptadorOrdenesLocal:
    """Implementación por defecto sobre el almacenamiento local de MOD-04 (COM-08 / COM-09)."""

    def __init__(self, db: Session):
        self.db = db

    async def obtener_orden_com08(self, orden_id: int) -> Optional[OrdenParaCobro]:
        try:
            orden = self.db.query(Orden).filter(Orden.id == orden_id).first()
            if orden is None:
                return None

            items_serializados = [
                {
                    "juegoId": getattr(item, "juego_id", None),
                    "reservaId": getattr(item, "reserva_id", None),
                    "precioUnitario": float(getattr(item, "precio_unitario", 0.0)),
                }
                for item in getattr(orden, "items", [])
            ]

            tasa = getattr(
                orden,
                "tasa_cambio_congelada",
                getattr(orden, "tasa_cambio", 1.0),
            )
            expira = getattr(
                orden,
                "fecha_expiracion_reserva",
                getattr(orden, "expira_en", None),
            )

            return OrdenParaCobro(
                orden_id=orden.id,
                usuario_id=orden.usuario_id,
                estado=orden.estado,
                total=float(orden.total),
                moneda=orden.moneda,
                tasa_cambio=float(tasa),
                expira_en=expira,
                items=items_serializados,
            )
        except SQLAlchemyError as error:
            raise ErrorAplicacion(503, "No fue posible iniciar el pago") from error

    async def marcar_orden_procesando_com09(self, orden_id: int) -> bool:
        try:
            orden = self.db.query(Orden).filter(Orden.id == orden_id).first()
            if orden is None or orden.estado != "PENDIENTE":
                return False
            orden.estado = "PROCESANDO"
            self.db.commit()
            return True
        except SQLAlchemyError as error:
            self.db.rollback()
            raise ErrorAplicacion(503, "No fue posible iniciar el pago") from error


class ClientePasarelaSimulada:
    """Cliente simulado de la API externa de Pagos."""

    async def transmitir_cobro(
        self, payload: dict[str, Any], idempotency_key: str
    ) -> dict[str, Any]:
        return {
            "recibido": True,
            "idempotencyKey": idempotency_key,
            "transaccionId": payload["transaccionId"],
            "estado": "EN_PROCESO",
        }


class ServicioTransacciones:
    def __init__(
        self,
        repositorio: RepositorioTransacciones,
        adaptador_ordenes: AdaptadorOrdenesCOM,
        cliente_pasarela: ClientePasarelaPagos,
    ):
        self.repositorio = repositorio
        self.adaptador_ordenes = adaptador_ordenes
        self.cliente_pasarela = cliente_pasarela

    async def iniciar_cobro(
        self,
        orden_id: int,
        metodo_pago_id: int,
        usuario_id: int,
    ) -> Transaccion:
        # 1. Idempotencia: si ya existe transacción para este ordenId, validar dueño y retornar
        existente = self.repositorio.obtener_por_orden_id(orden_id)
        if existente is not None:
            if existente.usuario_id != usuario_id:
                raise ErrorAplicacion(404, "La orden indicada no existe")
            return existente

        # 2. Obtener datos congelados de la orden vía COM-08
        orden = await self.adaptador_ordenes.obtener_orden_com08(orden_id)
        if orden is None:
            raise ErrorAplicacion(404, "La orden indicada no existe")

        # 3. Validar dueño, estado PENDIENTE y vigencia >= 2 minutos
        ReglasTransaccion.validar_orden_cobrable(orden, usuario_id)

        # 4. Cambiar estado de la orden a PROCESANDO vía COM-09 (HU-35)
        actualizada = await self.adaptador_ordenes.marcar_orden_procesando_com09(orden_id)
        if not actualizada:
            raise ErrorAplicacion(409, "La orden no está disponible para pago")

        # 5. Construir payload con tasa congelada (RN-09) y enviar con Idempotency-Key = ordenId
        transaccion_id = f"TX-{uuid.uuid4().hex[:8].upper()}"
        payload = ReglasTransaccion.construir_payload_pasarela(
            transaccion_id=transaccion_id,
            orden=orden,
            metodo_pago_id=metodo_pago_id,
        )

        try:
            await self.cliente_pasarela.transmitir_cobro(
                payload=payload,
                idempotency_key=str(orden_id),
            )
        except TimeoutError as error:
            raise ErrorAplicacion(504, "La pasarela de pagos no respondió") from error
        except ErrorAplicacion:
            raise
        except Exception as error:
            raise ErrorAplicacion(503, "No fue posible iniciar el pago") from error

        # 6. Registrar transacción EN_PROCESO
        nueva_transaccion = Transaccion(
            transaccion_id=transaccion_id,
            orden_id=orden.orden_id,
            usuario_id=usuario_id,
            metodo_pago_id=metodo_pago_id,
            monto=orden.total,
            moneda=orden.moneda,
            tasa_cambio=orden.tasa_cambio,
            estado=EstadoTransaccion.EN_PROCESO,
        )
        return self.repositorio.guardar(nueva_transaccion)