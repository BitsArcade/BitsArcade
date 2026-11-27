from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.domain.inventario import (
    ESTADO_CLAVE_DISPONIBLE,
    ESTADO_CLAVE_RESERVADA,
    ESTADO_RESERVA_ACTIVA,
    AlertaStock,
    ClaveLicencia,
    ReservaClave,
)


class RepositorioInventario:
    """Capa Repository de MOD-03: acceso a datos del vault de claves, reservas y alertas."""

    # ===== HU-11: Carga masiva de claves al vault =====

    def obtenerHashesExistentes(self, sesion: Session, juegoId: int, plataforma: str, hashes: list[str]) -> set:
        if not hashes:
            return set()
        filas = (
            sesion.query(ClaveLicencia.claveHash)
            .filter(
                ClaveLicencia.juegoId == juegoId,
                ClaveLicencia.plataforma == plataforma,
                ClaveLicencia.claveHash.in_(hashes),
            )
            .all()
        )
        return {fila[0] for fila in filas}

    def guardarClaves(self, sesion: Session, claves: list[ClaveLicencia]) -> None:
        sesion.add_all(claves)
        sesion.commit()

    # ===== HU-12: Consultar y auditar inventario de claves =====

    def contarPorJuegoYEstado(self, sesion: Session, juegoId: int | None = None) -> list[tuple]:
        """Retorna filas (juegoId, plataforma, estado, cantidad). Nunca lee valores de claves."""
        consulta = sesion.query(
            ClaveLicencia.juegoId, ClaveLicencia.plataforma, ClaveLicencia.estado, func.count(ClaveLicencia.id)
        )
        if juegoId is not None:
            consulta = consulta.filter(ClaveLicencia.juegoId == juegoId)
        return (
            consulta.group_by(ClaveLicencia.juegoId, ClaveLicencia.plataforma, ClaveLicencia.estado)
            .order_by(ClaveLicencia.juegoId, ClaveLicencia.plataforma)
            .all()
        )

    # ===== HU-13: Reservar clave temporalmente =====

    def obtenerIdsDisponibles(self, sesion: Session, juegoId: int, cantidad: int) -> list[int]:
        filas = (
            sesion.query(ClaveLicencia.id)
            .filter(ClaveLicencia.juegoId == juegoId, ClaveLicencia.estado == ESTADO_CLAVE_DISPONIBLE)
            .order_by(ClaveLicencia.id)
            .limit(cantidad)
            .with_for_update(skip_locked=True)  # En SQLite se ignora; en PostgreSQL evita colisiones
            .all()
        )
        return [fila[0] for fila in filas]

    def marcarReservadaSiDisponible(self, sesion: Session, claveId: int) -> bool:
        """UPDATE condicional: solo una transacción concurrente puede tomar cada clave."""
        filas = (
            sesion.query(ClaveLicencia)
            .filter(ClaveLicencia.id == claveId, ClaveLicencia.estado == ESTADO_CLAVE_DISPONIBLE)
            .update({ClaveLicencia.estado: ESTADO_CLAVE_RESERVADA}, synchronize_session=False)
        )
        return filas == 1

    def obtenerReservas(self, sesion: Session, reservaIds: list[str]) -> list[ReservaClave]:
        if not reservaIds:
            return []
        return sesion.query(ReservaClave).filter(ReservaClave.reservaId.in_(reservaIds)).all()

    def obtenerReservasVencidas(self, sesion: Session, ahora) -> list[ReservaClave]:
        return (
            sesion.query(ReservaClave)
            .filter(ReservaClave.estado == ESTADO_RESERVA_ACTIVA, ReservaClave.expiraEn < ahora)
            .all()
        )

    def contarDisponibles(self, sesion: Session, juegoId: int) -> int:
        return (
            sesion.query(ClaveLicencia)
            .filter(ClaveLicencia.juegoId == juegoId, ClaveLicencia.estado == ESTADO_CLAVE_DISPONIBLE)
            .count()
        )

    # ===== HU-14: Actualizar estado de clave a vendida =====

    def obtenerReserva(self, sesion: Session, reservaId: str) -> ReservaClave | None:
        return sesion.query(ReservaClave).filter(ReservaClave.reservaId == reservaId).first()

    def obtenerClave(self, sesion: Session, claveId: int) -> ClaveLicencia | None:
        return sesion.get(ClaveLicencia, claveId)

    # ===== HU-15: Reportar y alertar llaves agotadas =====

    def disponiblesPorJuegoYPlataforma(self, sesion: Session) -> list[tuple]:
        """(juegoId, plataforma, cantidad DISPONIBLE) para todo título con claves registradas."""
        disponibles = func.sum(case((ClaveLicencia.estado == ESTADO_CLAVE_DISPONIBLE, 1), else_=0))
        return (
            sesion.query(ClaveLicencia.juegoId, ClaveLicencia.plataforma, disponibles)
            .group_by(ClaveLicencia.juegoId, ClaveLicencia.plataforma)
            .all()
        )

    def obtenerAlertaActiva(self, sesion: Session, juegoId: int, plataforma: str | None) -> AlertaStock | None:
        return (
            sesion.query(AlertaStock)
            .filter(
                AlertaStock.juegoId == juegoId,
                AlertaStock.plataforma == plataforma,
                AlertaStock.activa.is_(True),
            )
            .first()
        )

    def listarAlertasActivas(self, sesion: Session) -> list[AlertaStock]:
        return (
            sesion.query(AlertaStock)
            .filter(AlertaStock.activa.is_(True))
            .order_by(AlertaStock.alertaDesde, AlertaStock.juegoId)
            .all()
        )
