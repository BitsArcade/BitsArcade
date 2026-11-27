from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.domain.catalogo import (
    ESTADO_ESTRENO,
    ESTADO_PREVENTA,
    ESTADOS_PUBLICADOS,
    Juego,
    MultimediaJuego,
    PlataformaJuego,
    RequisitoSistema,
)


class RepositorioCatalogo:
    """Capa Repository de MOD-02: acceso a datos del catálogo de juegos."""

    def _consultaPublicados(self, sesion: Session):
        return sesion.query(Juego).filter(Juego.estado.in_(ESTADOS_PUBLICADOS))

    def _paginar(self, consulta, pagina: int, tamano: int) -> tuple[list[Juego], int]:
        total = consulta.count()
        juegos = consulta.order_by(Juego.titulo, Juego.id).offset(pagina * tamano).limit(tamano).all()
        return juegos, total

    def buscarPorTitulo(self, sesion: Session, texto: str, pagina: int, tamano: int) -> tuple[list[Juego], int]:
        """HU-16: coincidencia parcial sin distinguir mayúsculas, solo juegos publicados."""
        consulta = self._consultaPublicados(sesion).filter(
            func.lower(Juego.titulo).contains(texto.lower(), autoescape=True)
        )
        return self._paginar(consulta, pagina, tamano)

    def filtrarPorPlataforma(
        self, sesion: Session, plataforma: str, pagina: int, tamano: int
    ) -> tuple[list[Juego], int]:
        """HU-17: juegos publicados asociados a la plataforma, en orden alfabético por título."""
        consulta = self._consultaPublicados(sesion).filter(
            Juego.plataformas.any(PlataformaJuego.plataforma == plataforma)
        )
        return self._paginar(consulta, pagina, tamano)

    def filtrarPorGeneroYCosto(
        self,
        sesion: Session,
        genero: str | None,
        costoMin: float | None,
        costoMax: float | None,
        pagina: int,
        tamano: int,
    ) -> tuple[list[Juego], int]:
        """HU-18: juegos publicados por género (sin distinguir mayúsculas) y rango de costo base."""
        consulta = self._consultaPublicados(sesion)
        if genero:
            consulta = consulta.filter(func.lower(Juego.genero) == genero.lower())
        if costoMin is not None:
            consulta = consulta.filter(Juego.costoAdquisicion >= costoMin)
        if costoMax is not None:
            consulta = consulta.filter(Juego.costoAdquisicion <= costoMax)
        return self._paginar(consulta, pagina, tamano)

    def listarDestacados(self, sesion: Session, limite: int) -> list[Juego]:
        """HU-19: juegos publicados con marca destacado o en ESTRENO/PREVENTA, por lanzamiento descendente."""
        return (
            self._consultaPublicados(sesion)
            .filter(or_(Juego.destacado.is_(True), Juego.estado.in_((ESTADO_ESTRENO, ESTADO_PREVENTA))))
            .order_by(Juego.fechaLanzamiento.is_(None), Juego.fechaLanzamiento.desc(), Juego.id.desc())
            .limit(limite)
            .all()
        )

    def obtenerPorId(self, sesion: Session, juegoId: int) -> Juego | None:
        """COM-11: juego por identificador en cualquier estado (incluido INACTIVO)."""
        return sesion.query(Juego).filter(Juego.id == juegoId).first()

    def obtenerPublicadoPorId(self, sesion: Session, juegoId: int) -> Juego | None:
        """HU-21: juego publicado (no INACTIVO) por su identificador."""
        return self._consultaPublicados(sesion).filter(Juego.id == juegoId).first()

    def listarRequisitos(self, sesion: Session, juegoId: int) -> list[RequisitoSistema]:
        """HU-22: requisitos de sistema registrados para el juego."""
        return sesion.query(RequisitoSistema).filter(RequisitoSistema.juegoId == juegoId).all()

    def listarMultimedia(self, sesion: Session, juegoId: int) -> list[MultimediaJuego]:
        """HU-23: enlaces multimedia almacenados para el juego."""
        return sesion.query(MultimediaJuego).filter(MultimediaJuego.juegoId == juegoId).all()

    def listarPublicados(self, sesion: Session, pagina: int, tamano: int) -> tuple[list[Juego], int]:
        """HU-20: juegos en PREVENTA, ESTRENO o ACTIVO, paginados y ordenados por título."""
        return self._paginar(self._consultaPublicados(sesion), pagina, tamano)
