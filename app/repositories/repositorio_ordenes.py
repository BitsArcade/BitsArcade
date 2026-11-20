from sqlalchemy.orm import Session
from app.domain.inventario import (
    ESTADO_KEY_DISPONIBLE,
    ESTADO_KEY_RESERVADA,
    KeyLicencia,
)
from app.domain.ordenes import (
    ESTADO_ORDEN_CANCELADA,
    ESTADO_ORDEN_PENDIENTE,
    ESTADO_ORDEN_PROCESANDO,
    DetalleOrden,
    OrdenCompra,
    ReservaOrdenKey,
)


class RepositorioOrdenes:
    """Capa Repository de MOD-04 / SUB-04.2: acceso a datos de órdenes y reservas de stock."""

    def reservarKeysDisponibles(self, sesion: Session, juegoId: int, cantidad: int) -> list[KeyLicencia]:
        """RN-04: Selecciona N keys disponibles y las marca como RESERVADA."""
        keysDisponibles = (
            sesion.query(KeyLicencia)
            .filter(KeyLicencia.juego_id == juegoId, KeyLicencia.estado == ESTADO_KEY_DISPONIBLE)
            .limit(cantidad)
            .all()
        )
        for key in keysDisponibles:
            key.estado = ESTADO_KEY_RESERVADA
        return keysDisponibles

    def liberarKeysDeOrden(self, sesion: Session, orden: OrdenCompra) -> None:
        """HU-34 / RN-06: Devuelve a DISPONIBLE todas las keys reservadas por una orden anulada."""
        for reserva in orden.reservas:
            key = sesion.query(KeyLicencia).filter(KeyLicencia.id == reserva.keyId).first()
            if key and key.estado == ESTADO_KEY_RESERVADA:
                key.estado = ESTADO_KEY_DISPONIBLE

    def crearOrdenConDetalles(
        self,
        sesion: Session,
        usuarioId: int,
        moneda: str,
        tasaCambio: float,
        liquidacion: dict,
        itemsCalculados: list[dict],
        keysReservadas: list[KeyLicencia],
    ) -> OrdenCompra:
        """HU-31: Persiste la orden pendiente, sus líneas y el vínculo de keys reservadas."""
        nuevaOrden = OrdenCompra(
            usuarioId=usuarioId,
            estado=ESTADO_ORDEN_PENDIENTE,
            moneda=moneda,
            tasaCambioCongelada=tasaCambio,
            subtotalBase=liquidacion["subtotalBase"],
            descuentoAplicado=liquidacion["descuentoAplicado"],
            montoIva=liquidacion["montoIva"],
            totalPagar=liquidacion["totalPagar"],
        )
        sesion.add(nuevaOrden)
        sesion.flush()  # Obtiene el ID de la orden antes del commit final

        for item in itemsCalculados:
            detalle = DetalleOrden(
                ordenId=nuevaOrden.id,
                juegoId=item["juegoId"],
                tituloJuego=item["tituloJuego"],
                cantidad=item["cantidad"],
                precioUnitario=item["precioUnitario"],
                descuentoVolumen=item["descuentoVolumen"],
                subtotal=item["subtotal"],
            )
            sesion.add(detalle)

        for key in keysReservadas:
            vinculo = ReservaOrdenKey(ordenId=nuevaOrden.id, keyId=key.id)
            sesion.add(vinculo)

        sesion.commit()
        sesion.refresh(nuevaOrden)
        return nuevaOrden

    def obtenerOrdenPorId(self, sesion: Session, ordenId: int) -> OrdenCompra | None:
        return sesion.query(OrdenCompra).filter(OrdenCompra.id == ordenId).first()

    def obtenerOrdenDeUsuario(self, sesion: Session, ordenId: int, usuarioId: int) -> OrdenCompra | None:
        return (
            sesion.query(OrdenCompra)
            .filter(OrdenCompra.id == ordenId, OrdenCompra.usuarioId == usuarioId)
            .first()
        )

    def listarOrdenesPendientesUsuario(self, sesion: Session, usuarioId: int) -> list[OrdenCompra]:
        """HU-33: Consulta las órdenes en estado PENDIENTE del usuario autenticado."""
        return (
            sesion.query(OrdenCompra)
            .filter(OrdenCompra.usuarioId == usuarioId, OrdenCompra.estado == ESTADO_ORDEN_PENDIENTE)
            .order_by(OrdenCompra.id.desc())
            .all()
        )

    def cancelarOrden(self, sesion: Session, orden: OrdenCompra, motivo: str) -> OrdenCompra:
        """HU-34: Cambia el estado de la orden a CANCELADA y libera sus keys."""
        self.liberarKeysDeOrden(sesion, orden)
        orden.estado = ESTADO_ORDEN_CANCELADA
        orden.motivoCancelacion = motivo
        sesion.commit()
        sesion.refresh(orden)
        return orden

    def cambiarEstadoProcesando(self, sesion: Session, orden: OrdenCompra) -> OrdenCompra:
        """HU-35: Bloquea la orden pasándola a PROCESANDO al iniciar el pago."""
        orden.estado = ESTADO_ORDEN_PROCESANDO
        sesion.commit()
        sesion.refresh(orden)
        return orden

    def actualizarEstadoCom09(self, sesion: Session, orden: OrdenCompra, nuevoEstado: str) -> OrdenCompra:
        """COM-09 / RN-06: Actualiza el estado tras el cobro; si falla/cancela libera stock."""
        if nuevoEstado == ESTADO_ORDEN_CANCELADA:
            self.liberarKeysDeOrden(sesion, orden)
            if not orden.motivoCancelacion:
                orden.motivoCancelacion = "Pago rechazado o expirado en pasarela (RN-06)"
        orden.estado = nuevoEstado
        sesion.commit()
        sesion.refresh(orden)
        return orden