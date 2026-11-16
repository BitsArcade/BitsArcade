from sqlalchemy.orm import Session

from app.core.respuestas import ErrorAplicacion, manejar_errores_bd, respuesta
from app.domain.catalogo import (
    MENSAJE_JUEGO_NO_EXISTE,
    juego_a_ficha_tecnica,
    juego_a_item,
    validar_limite_destacados,
    validar_paginacion,
    validar_plataforma,
    validar_texto_busqueda,
)
from app.repositories.repositorio_catalogo import RepositorioCatalogo


def _pagina(juegos, page: int, size: int, total: int) -> dict:
    return {"items": [juego_a_item(j) for j in juegos], "page": page, "size": size, "total": total}


class ServicioCatalogo:
    """Capa Application / Service de MOD-02: casos de uso del catálogo (HU-16 a HU-25)."""

    def __init__(self):
        self.repositorio = RepositorioCatalogo()

    def consultar_catalogo(self, sesion: Session, page: int, size: int) -> dict:
        """HU-20: listado paginado de juegos publicados (sin C_A ni precio)."""
        validar_paginacion(page, size)
        with manejar_errores_bd("No fue posible consultar el catálogo"):
            juegos, total = self.repositorio.listar_publicados(sesion, page, size)
        if total == 0:
            return respuesta("No existen juegos publicados", _pagina([], page, size, 0), False)
        return respuesta("Consulta de catálogo exitosa", _pagina(juegos, page, size, total))

    def buscar_por_nombre(self, sesion: Session, texto: str | None, page: int, size: int) -> dict:
        """HU-16: búsqueda parcial por título sobre juegos publicados."""
        texto_limpio = validar_texto_busqueda(texto)
        validar_paginacion(page, size)
        with manejar_errores_bd("No fue posible realizar la búsqueda"):
            juegos, total = self.repositorio.buscar_por_titulo(sesion, texto_limpio, page, size)
        if total == 0:
            return respuesta("No se encontraron juegos para la búsqueda", _pagina([], page, size, 0), False)
        return respuesta("Búsqueda exitosa", _pagina(juegos, page, size, total))

    def filtrar_por_plataforma(self, sesion: Session, plataforma: str, page: int, size: int) -> dict:
        """HU-17: filtra el catálogo publicado por plataforma (PC / CONSOLA), orden alfabético."""
        plataforma_valida = validar_plataforma(plataforma)
        validar_paginacion(page, size)
        with manejar_errores_bd("No fue posible filtrar el catálogo"):
            juegos, total = self.repositorio.filtrar_por_plataforma(sesion, plataforma_valida, page, size)
        if total == 0:
            return respuesta("No existen juegos para la plataforma indicada", _pagina([], page, size, 0), False)
        return respuesta("Filtrado por plataforma exitoso", _pagina(juegos, page, size, total))

    def listar_destacados(self, sesion: Session, limite: int) -> dict:
        """HU-19: destacados y novedades definidos solo con atributos del catálogo."""
        validar_limite_destacados(limite)
        with manejar_errores_bd("No fue posible consultar los destacados"):
            juegos = self.repositorio.listar_destacados(sesion, limite)
        if not juegos:
            return respuesta("No existen juegos destacados", [], False)
        return respuesta("Consulta de destacados exitosa", [juego_a_item(j) for j in juegos])

    def _obtener_juego_publicado(self, sesion: Session, juego_id: int, mensaje_error_bd: str):
        """Obtiene un juego publicado o lanza 404; los fallos de BD se traducen a 503."""
        with manejar_errores_bd(mensaje_error_bd):
            juego = self.repositorio.obtener_publicado_por_id(sesion, juego_id)
        if juego is None:
            raise ErrorAplicacion(404, MENSAJE_JUEGO_NO_EXISTE)
        return juego

    def consultar_ficha_tecnica(self, sesion: Session, juego_id: int) -> dict:
        """HU-21: ficha técnica completa sin costo de adquisición ni margen."""
        juego = self._obtener_juego_publicado(sesion, juego_id, "No fue posible consultar la ficha técnica")
        return respuesta("Consulta de ficha técnica exitosa", juego_a_ficha_tecnica(juego))
