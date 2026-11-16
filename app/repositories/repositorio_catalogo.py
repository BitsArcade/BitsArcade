from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.domain.catalogo import (
    ESTADO_ESTRENO,
    ESTADO_PREVENTA,
    ESTADOS_PUBLICADOS,
    Juego,
    PlataformaJuego,
)


class RepositorioCatalogo:
    """Capa Repository de MOD-02: acceso a datos del catálogo de juegos."""

    def _consulta_publicados(self, sesion: Session):
        return sesion.query(Juego).filter(Juego.estado.in_(ESTADOS_PUBLICADOS))

    def _paginar(self, consulta, page: int, size: int) -> tuple[list[Juego], int]:
        total = consulta.count()
        juegos = consulta.order_by(Juego.titulo, Juego.id).offset(page * size).limit(size).all()
        return juegos, total

    def buscar_por_titulo(self, sesion: Session, texto: str, page: int, size: int) -> tuple[list[Juego], int]:
        """HU-16: coincidencia parcial sin distinguir mayúsculas, solo juegos publicados."""
        consulta = self._consulta_publicados(sesion).filter(
            func.lower(Juego.titulo).contains(texto.lower(), autoescape=True)
        )
        return self._paginar(consulta, page, size)

    def filtrar_por_plataforma(
        self, sesion: Session, plataforma: str, page: int, size: int
    ) -> tuple[list[Juego], int]:
        """HU-17: juegos publicados asociados a la plataforma, en orden alfabético por título."""
        consulta = self._consulta_publicados(sesion).filter(
            Juego.plataformas.any(PlataformaJuego.plataforma == plataforma)
        )
        return self._paginar(consulta, page, size)

    def listar_destacados(self, sesion: Session, limite: int) -> list[Juego]:
        """HU-19: juegos publicados con marca destacado o en ESTRENO/PREVENTA, por lanzamiento descendente."""
        return (
            self._consulta_publicados(sesion)
            .filter(or_(Juego.destacado.is_(True), Juego.estado.in_((ESTADO_ESTRENO, ESTADO_PREVENTA))))
            .order_by(Juego.fecha_lanzamiento.is_(None), Juego.fecha_lanzamiento.desc(), Juego.id.desc())
            .limit(limite)
            .all()
        )

    def obtener_publicado_por_id(self, sesion: Session, juego_id: int) -> Juego | None:
        """HU-21: juego publicado (no INACTIVO) por su identificador."""
        return self._consulta_publicados(sesion).filter(Juego.id == juego_id).first()

    def listar_publicados(self, sesion: Session, page: int, size: int) -> tuple[list[Juego], int]:
        """HU-20: juegos en PREVENTA, ESTRENO o ACTIVO, paginados y ordenados por título."""
        return self._paginar(self._consulta_publicados(sesion), page, size)
