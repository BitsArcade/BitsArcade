from datetime import datetime

from sqlalchemy.orm import Session

from app.domain.ordenes import ESTADO_ORDEN_CANCELADA, ESTADO_ORDEN_PENDIENTE, LineaOrden, Orden


class RepositorioOrdenes:
    """Capa Repository de MOD-04: persistencia de órdenes, líneas y reservas asociadas."""

    def obtenerPorId(self, sesion: Session, ordenId: int) -> Orden | None:
        return sesion.get(Orden, ordenId)

    def obtenerDeUsuario(self, sesion: Session, ordenId: int, usuarioId: int) -> Orden | None:
        return sesion.query(Orden).filter(Orden.id == ordenId, Orden.usuarioId == usuarioId).first()

    def obtenerPorIdempotencia(self, sesion: Session, usuarioId: int, claveIdempotencia: str) -> Orden | None:
        return (
            sesion.query(Orden)
            .filter(Orden.usuarioId == usuarioId, Orden.claveIdempotencia == claveIdempotencia)
            .first()
        )

    def listarPorEstado(self, sesion: Session, usuarioId: int, estado: str) -> list[Orden]:
        return (
            sesion.query(Orden)
            .filter(Orden.usuarioId == usuarioId, Orden.estado == estado)
            .order_by(Orden.creadaEn.desc(), Orden.id.desc())
            .all()
        )

    def listarPendientesVencidas(self, sesion: Session, ahora: datetime, usuarioId: int | None = None) -> list[Orden]:
        consulta = sesion.query(Orden).filter(Orden.estado == ESTADO_ORDEN_PENDIENTE, Orden.expiraEn < ahora)
        if usuarioId is not None:
            consulta = consulta.filter(Orden.usuarioId == usuarioId)
        return consulta.all()

    def contarLicenciasNoCanceladas(self, sesion: Session, usuarioId: int, juegoId: int) -> int:
        lineas = (
            sesion.query(LineaOrden)
            .join(Orden, Orden.id == LineaOrden.ordenId)
            .filter(Orden.usuarioId == usuarioId, Orden.estado != ESTADO_ORDEN_CANCELADA, LineaOrden.juegoId == juegoId)
            .all()
        )
        return sum(linea.cantidad for linea in lineas)

    def guardar(self, sesion: Session, *entidades) -> None:
        for entidad in entidades:
            sesion.add(entidad)
        sesion.commit()
        for entidad in entidades:
            sesion.refresh(entidad)

    def eliminar(self, sesion: Session, orden: Orden) -> None:
        sesion.delete(orden)
        sesion.commit()
