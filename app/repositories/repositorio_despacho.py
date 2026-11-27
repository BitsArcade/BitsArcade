from datetime import datetime

from sqlalchemy.orm import Session

from app.domain.despacho import AsignacionLicencia, NotificacionDespacho, RegistroCompra


class RepositorioDespacho:
    """Capa Repository de MOD-06: asignaciones, registro de compras y notificaciones de despacho."""

    # ===== COMÚN MOD-06: consultas compartidas =====

    def obtenerRegistroCompra(self, sesion: Session, ordenId: int) -> RegistroCompra | None:
        return sesion.query(RegistroCompra).filter(RegistroCompra.ordenId == ordenId).first()

    def listarAsignacionesOrden(self, sesion: Session, ordenId: int) -> list[AsignacionLicencia]:
        return (
            sesion.query(AsignacionLicencia)
            .filter(AsignacionLicencia.ordenId == ordenId)
            .order_by(AsignacionLicencia.id)
            .all()
        )

    def listarAsignacionesUsuario(self, sesion: Session, usuarioId: int) -> list[AsignacionLicencia]:
        return (
            sesion.query(AsignacionLicencia)
            .filter(AsignacionLicencia.usuarioId == usuarioId)
            .order_by(AsignacionLicencia.titulo, AsignacionLicencia.entregadaEn)
            .all()
        )

    def guardar(self, sesion: Session, *entidades) -> None:
        for entidad in entidades:
            sesion.add(entidad)
        sesion.commit()

    # ===== HU-43: Formateo y visualización segura de la clave =====

    def obtenerAsignacion(self, sesion: Session, licenciaId: str) -> AsignacionLicencia | None:
        return sesion.query(AsignacionLicencia).filter(AsignacionLicencia.licenciaId == licenciaId).first()

    # ===== HU-44: Notificación automática de despacho =====

    def obtenerNotificacion(self, sesion: Session, ordenId: int) -> NotificacionDespacho | None:
        return sesion.query(NotificacionDespacho).filter(NotificacionDespacho.ordenId == ordenId).first()

    # ===== HU-45: Validar unicidad e inmutabilidad de entrega =====

    def obtenerAsignacionesPorReservas(self, sesion: Session, reservaIds: list[str]) -> list[AsignacionLicencia]:
        if not reservaIds:
            return []
        return sesion.query(AsignacionLicencia).filter(AsignacionLicencia.reservaId.in_(reservaIds)).all()

    def obtenerAsignacionPorHash(self, sesion: Session, claveHash: str) -> AsignacionLicencia | None:
        return sesion.query(AsignacionLicencia).filter(AsignacionLicencia.claveHash == claveHash).first()

    # ===== HU-50: Filtrar historial por fechas =====

    def listarComprasUsuario(
        self,
        sesion: Session,
        usuarioId: int,
        desde: datetime | None,
        hasta: datetime | None,
        ascendente: bool,
    ) -> list[RegistroCompra]:
        consulta = sesion.query(RegistroCompra).filter(RegistroCompra.usuarioId == usuarioId)
        if desde is not None:
            consulta = consulta.filter(RegistroCompra.fecha >= desde)
        if hasta is not None:
            consulta = consulta.filter(RegistroCompra.fecha < hasta)
        orden = RegistroCompra.fecha.asc() if ascendente else RegistroCompra.fecha.desc()
        return consulta.order_by(orden, RegistroCompra.ordenId).all()
