from sqlalchemy.orm import Session

from app.domain.catalogo import ESTADOS_PUBLICADOS, Juego


class RepositorioCatalogo:
    """Capa Repository de MOD-02: acceso a datos del catálogo de juegos."""

    def _consulta_publicados(self, sesion: Session):
        return sesion.query(Juego).filter(Juego.estado.in_(ESTADOS_PUBLICADOS))

    def listar_publicados(self, sesion: Session, page: int, size: int) -> tuple[list[Juego], int]:
        """HU-20: juegos en PREVENTA, ESTRENO o ACTIVO, paginados y ordenados por título."""
        consulta = self._consulta_publicados(sesion)
        total = consulta.count()
        juegos = consulta.order_by(Juego.titulo, Juego.id).offset(page * size).limit(size).all()
        return juegos, total
