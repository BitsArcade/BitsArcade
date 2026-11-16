from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.base_datos import get_db
from app.core.respuestas import Respuesta
from app.domain.catalogo import TAMANO_PAGINA_POR_DEFECTO, PaginaJuegosSalida
from app.services.servicio_catalogo import ServicioCatalogo

enrutador_catalogo = APIRouter(
    prefix="/api/v1/catalogo",
    tags=["MOD-02: Catálogo de Juegos (HU-16 a HU-25)"],
)

servicio_catalogo = ServicioCatalogo()

ERROR_503 = {"description": "La base de datos no está disponible"}


# Nota: las rutas estáticas (/juegos/buscar, ...) se declaran antes de /juegos/{gameId}.

@enrutador_catalogo.get(
    "/juegos/buscar",
    response_model=Respuesta[PaginaJuegosSalida],
    responses={400: {"description": "El texto de búsqueda debe tener al menos 2 caracteres"}, 503: ERROR_503},
)
def buscar_juegos_por_nombre(
    q: str = Query("", description="Texto a buscar en el título (mínimo 2 caracteres)"),
    page: int = Query(0, description="Número de página (desde 0)"),
    size: int = Query(TAMANO_PAGINA_POR_DEFECTO, description="Tamaño de página (1 a 100)"),
    sesion: Session = Depends(get_db),
):
    """
    HU-16: Buscar videojuegos por nombre.

    Coincidencia parcial sobre el título, sin distinguir mayúsculas, solo juegos publicados.
    Ejemplo: `GET /api/v1/catalogo/juegos/buscar?q=aurora`.
    """
    return servicio_catalogo.buscar_por_nombre(sesion, q, page, size)


@enrutador_catalogo.get(
    "/juegos",
    response_model=Respuesta[PaginaJuegosSalida],
    responses={400: {"description": "size debe estar entre 1 y 100"}, 503: ERROR_503},
)
def consultar_catalogo(
    page: int = Query(0, description="Número de página (desde 0)"),
    size: int = Query(TAMANO_PAGINA_POR_DEFECTO, description="Tamaño de página (1 a 100)"),
    sesion: Session = Depends(get_db),
):
    """
    HU-20: Consultar catálogo completo.

    Retorna el listado paginado de juegos publicados (PREVENTA, ESTRENO, ACTIVO).
    Los juegos INACTIVO se excluyen. No se expone el costo de adquisición ni el precio
    (el precio final se consulta en HU-24).
    """
    return servicio_catalogo.consultar_catalogo(sesion, page, size)
