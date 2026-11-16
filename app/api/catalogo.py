from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.base_datos import get_db
from app.core.respuestas import Respuesta
from app.domain.catalogo import (
    LIMITE_DESTACADOS_POR_DEFECTO,
    FichaTecnicaSalida,
    TAMANO_PAGINA_POR_DEFECTO,
    JuegoResumenSalida,
    MultimediaSalida,
    ContratoCom11Salida,
    PaginaJuegosSalida,
    PrecioSalida,
    RequisitosSalida,
)
from app.services.servicio_catalogo import ServicioCatalogo

enrutador_catalogo = APIRouter(
    prefix="/api/v1/catalogo",
    tags=["MOD-02: Catálogo de Juegos (HU-16 a HU-25)"],
)

enrutador_catalogo_interno = APIRouter(
    prefix="/internal/v1/catalogo",
    tags=["Contratos Internos MOD-02 (COM-11)"],
)

servicio_catalogo = ServicioCatalogo()

ERROR_503 = {"description": "La base de datos no está disponible"}
ERROR_404 = {"description": "El juego indicado no existe"}


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
    "/juegos/destacados",
    response_model=Respuesta[list[JuegoResumenSalida]],
    responses={400: {"description": "limite debe estar entre 1 y 20"}, 503: ERROR_503},
)
def listar_juegos_destacados(
    limite: int = Query(LIMITE_DESTACADOS_POR_DEFECTO, description="Cantidad máxima (1 a 20, por defecto 10)"),
    sesion: Session = Depends(get_db),
):
    """
    HU-19: Listar juegos destacados y novedades.

    Juegos publicados con marca `destacado` o en estado ESTRENO/PREVENTA, ordenados por
    fecha de lanzamiento descendente. No usa datos de ventas.
    """
    return servicio_catalogo.listar_destacados(sesion, limite)


@enrutador_catalogo.get(
    "/juegos",
    response_model=Respuesta[PaginaJuegosSalida],
    responses={
        400: {"description": "size debe estar entre 1 y 100 / Plataforma no válida. Use PC o CONSOLA"},
        503: ERROR_503,
    },
)
def consultar_catalogo(
    plataforma: str | None = Query(None, description="HU-17: filtrar por plataforma (PC o CONSOLA)"),
    page: int = Query(0, description="Número de página (desde 0)"),
    size: int = Query(TAMANO_PAGINA_POR_DEFECTO, description="Tamaño de página (1 a 100)"),
    sesion: Session = Depends(get_db),
):
    """
    HU-20: Consultar catálogo completo.

    Retorna el listado paginado de juegos publicados (PREVENTA, ESTRENO, ACTIVO).
    Los juegos INACTIVO se excluyen. No se expone el costo de adquisición ni el precio
    (el precio final se consulta en HU-24).

    HU-17: Filtrar catálogo por plataforma. Si se envía `plataforma` (PC o CONSOLA) se
    retornan solo los juegos asociados a ella, en orden alfabético por título.
    Ejemplo: `GET /api/v1/catalogo/juegos?plataforma=PC`.
    """
    if plataforma is not None:
        return servicio_catalogo.filtrar_por_plataforma(sesion, plataforma, page, size)
    return servicio_catalogo.consultar_catalogo(sesion, page, size)


@enrutador_catalogo.get(
    "/juegos/{gameId}",
    response_model=Respuesta[FichaTecnicaSalida],
    responses={404: ERROR_404, 503: ERROR_503},
)
def consultar_ficha_tecnica(gameId: int, sesion: Session = Depends(get_db)):
    """
    HU-21: Consultar detalles de ficha técnica.

    Retorna título, descripción, género, plataformas, desarrollador, fecha de lanzamiento y
    estado. No incluye costo de adquisición ni margen; el precio se obtiene con HU-24.
    """
    return servicio_catalogo.consultar_ficha_tecnica(sesion, gameId)


@enrutador_catalogo.get(
    "/juegos/{gameId}/requisitos",
    response_model=Respuesta[RequisitosSalida],
    responses={404: ERROR_404, 503: ERROR_503},
)
def consultar_requisitos_sistema(gameId: int, sesion: Session = Depends(get_db)):
    """
    HU-22: Ver requisitos del sistema.

    Retorna los requisitos `minimos` y `recomendados` (so, procesador, memoria, grafica,
    almacenamiento). Si el juego no tiene requisitos registrados (p. ej. juegos de consola)
    responde 200 con `success=false` y un mensaje informativo.
    """
    return servicio_catalogo.consultar_requisitos(sesion, gameId)


@enrutador_catalogo.get(
    "/juegos/{gameId}/multimedia",
    response_model=Respuesta[MultimediaSalida],
    responses={404: ERROR_404, 503: ERROR_503},
)
def consultar_galeria_y_trailers(gameId: int, sesion: Session = Depends(get_db)):
    """
    HU-23: Visualizar galería y trailers.

    Retorna las URLs almacenadas agrupadas en `imagenes` y `videos`. No se integra ninguna
    API externa de video.
    """
    return servicio_catalogo.consultar_multimedia(sesion, gameId)


@enrutador_catalogo.get(
    "/juegos/{gameId}/precio",
    response_model=Respuesta[PrecioSalida],
    responses={
        404: ERROR_404,
        422: {"description": "El precio calculado viola la política de margen mínimo (RN-02)"},
        503: {"description": "No fue posible obtener los parámetros financieros / calcular el precio"},
    },
)
def consultar_precio_final(gameId: int, sesion: Session = Depends(get_db)):
    """
    HU-24: Calcular y consultar precio final público.

    RN-01: `P_venta = C_A × (1 + M) × (1 + IVA)` con {taxRate, margin} vigentes de MOD-00 (COM-01).
    RN-02: `P_venta >= C_A × (1 + IVA)`; si se viola responde 422. La respuesta no expone C_A
    ni margen. Moneda de presentación: COP (moneda base del sistema).
    """
    return servicio_catalogo.consultar_precio_final(sesion, gameId)


@enrutador_catalogo_interno.get("/juegos/{gameId}", response_model=ContratoCom11Salida)
def obtener_juego_com11(gameId: int, sesion: Session = Depends(get_db)):
    """COM-11: Entrega {exists, title, status, finalPrice, floorPrice} al módulo MOD-04 (Carrito)."""
    return servicio_catalogo.obtener_contrato_com11(sesion, gameId)
