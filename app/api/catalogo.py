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
