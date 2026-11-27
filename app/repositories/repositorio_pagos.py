from sqlalchemy.orm import Session

from app.domain.pagos import Comprobante, NotificacionOrden, Transaccion


class RepositorioPagos:
    """Capa Repository de MOD-05: transacciones, comprobantes y notificaciones COM-09."""

    # ===== COMÚN MOD-05: transacciones =====

    def obtenerTransaccion(self, sesion: Session, transaccionId: str) -> Transaccion | None:
        return sesion.query(Transaccion).filter(Transaccion.transaccionId == transaccionId).first()

    def guardar(self, sesion: Session, *entidades) -> None:
        for entidad in entidades:
            sesion.add(entidad)
        sesion.commit()

    # ===== HU-36: Transmitir cobro a la pasarela de pago simulada =====

    def obtenerTransaccionPorOrden(self, sesion: Session, ordenId: int) -> Transaccion | None:
        return (
            sesion.query(Transaccion)
            .filter(Transaccion.ordenId == ordenId)
            .order_by(Transaccion.id.desc())
            .first()
        )

    # ===== HU-39: Registrar comprobante digital de transacción =====

    def obtenerComprobante(self, sesion: Session, transaccionId: str) -> Comprobante | None:
        return sesion.query(Comprobante).filter(Comprobante.transaccionId == transaccionId).first()

    # ===== HU-40: Notificar resultado del cobro a Órdenes =====

    def obtenerNotificacion(self, sesion: Session, transaccionId: str) -> NotificacionOrden | None:
        return sesion.query(NotificacionOrden).filter(NotificacionOrden.transaccionId == transaccionId).first()
