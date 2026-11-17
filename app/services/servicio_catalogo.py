from sqlalchemy.orm import Session

from app.core.respuestas import manejar_errores_bd, respuesta
from app.domain.catalogo import juego_a_item, validar_paginacion, validar_plataforma, validar_texto_busqueda
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
