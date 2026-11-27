from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.base_datos import obtenerSesionBd
from app.core.seguridad import validarTokenServicio
from app.core.respuestas import Respuesta, respuesta
from app.domain.catalogo import (
    LIMITE_DESTACADOS_POR_DEFECTO,
    FichaTecnicaSalida,
    TAMANO_PAGINA_POR_DEFECTO,
    JuegoResumenSalida,
    MultimediaSalida,
    ContratoCom11Salida,
    PaginaJuegosConPrecioSalida,
    PaginaJuegosSalida,
    PrecioSalida,
    RequisitosSalida,
    StockSalida,
)
from app.services.servicio_catalogo import ServicioCatalogo

enrutadorCatalogo = APIRouter(
    prefix="/api/v1/catalogo",
    tags=["MOD-02: Catálogo de Juegos (HU-16 a HU-25)"],
)

enrutadorCatalogoInterno = APIRouter(
    prefix="/interno/v1/catalogo",
    tags=["Contratos Internos MOD-02 (COM-11)"],
    dependencies=[Depends(validarTokenServicio)],
)

servicioCatalogo = ServicioCatalogo()

ERROR_503 = {"description": "La base de datos no está disponible"}
ERROR_404 = {"description": "El juego indicado no existe"}


# Nota: las rutas estáticas (/juegos/buscar, ...) se declaran antes de /juegos/{juegoId}.

@enrutadorCatalogo.get(
    "/juegos/buscar",
    response_model=Respuesta[PaginaJuegosSalida],
    responses={400: {"description": "El texto de búsqueda debe tener al menos 2 caracteres"}, 503: ERROR_503},
)
def buscarJuegosPorNombre(
    texto: str = Query("", description="Texto a buscar en el título (mínimo 2 caracteres)"),
    pagina: int = Query(0, description="Número de página (desde 0)"),
    tamano: int = Query(TAMANO_PAGINA_POR_DEFECTO, description="Tamaño de página (1 a 100)"),
    sesion: Session = Depends(obtenerSesionBd),
):
    """
    HU-16: Buscar videojuegos por nombre.

    Coincidencia parcial sobre el título, sin distinguir mayúsculas, solo juegos publicados.
    Ejemplo: `GET /api/v1/catalogo/juegos/buscar?texto=aurora`.
    """
    return servicioCatalogo.buscarPorNombre(sesion, texto, pagina, tamano)


@enrutadorCatalogo.get(
    "/juegos/filtrar",
    response_model=Respuesta[PaginaJuegosConPrecioSalida],
    responses={
        400: {"description": "precioMin no puede ser mayor que precioMax"},
        503: {"description": "No fue posible obtener los parámetros financieros / filtrar el catálogo"},
    },
)
def filtrarPorGeneroYPrecio(
    genero: str | None = Query(None, description="Género del juego (ej. RPG)"),
    precioMin: float | None = Query(None, description="Precio final mínimo en COP"),
    precioMax: float | None = Query(None, description="Precio final máximo en COP"),
    pagina: int = Query(0, description="Número de página (desde 0)"),
    tamano: int = Query(TAMANO_PAGINA_POR_DEFECTO, description="Tamaño de página (1 a 100)"),
    sesion: Session = Depends(obtenerSesionBd),
):
    """
    HU-18: Filtrado combinado por género y precio.

    El rango se expresa en precio final (RN-01) y se convierte a rango de costo base con los
    parámetros vigentes de COM-01 (una sola llamada por petición). Cada ítem incluye `precioFinal`.
    Ejemplo: `GET /api/v1/catalogo/juegos/filtrar?genero=RPG&precioMin=100000&precioMax=300000`.
    """
    return servicioCatalogo.filtrarPorGeneroYPrecio(sesion, genero, precioMin, precioMax, pagina, tamano)


@enrutadorCatalogo.get(
    "/juegos/destacados",
    response_model=Respuesta[list[JuegoResumenSalida]],
    responses={400: {"description": "limite debe estar entre 1 y 20"}, 503: ERROR_503},
)
def listarJuegosDestacados(
    limite: int = Query(LIMITE_DESTACADOS_POR_DEFECTO, description="Cantidad máxima (1 a 20, por defecto 10)"),
    sesion: Session = Depends(obtenerSesionBd),
):
    """
    HU-19: Listar juegos destacados y novedades.

    Juegos publicados con marca `destacado` o en estado ESTRENO/PREVENTA, ordenados por
    fecha de lanzamiento descendente. No usa datos de ventas.
    """
    return servicioCatalogo.listarDestacados(sesion, limite)


@enrutadorCatalogo.get(
    "/juegos",
    response_model=Respuesta[PaginaJuegosSalida],
    responses={
        400: {"description": "tamano debe estar entre 1 y 100 / Plataforma no válida. Use PC o CONSOLA"},
        503: ERROR_503,
    },
)
def consultarCatalogo(
    plataforma: str | None = Query(None, description="HU-17: filtrar por plataforma (PC o CONSOLA)"),
    pagina: int = Query(0, description="Número de página (desde 0)"),
    tamano: int = Query(TAMANO_PAGINA_POR_DEFECTO, description="Tamaño de página (1 a 100)"),
    sesion: Session = Depends(obtenerSesionBd),
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
        return servicioCatalogo.filtrarPorPlataforma(sesion, plataforma, pagina, tamano)
    return servicioCatalogo.consultarCatalogo(sesion, pagina, tamano)


@enrutadorCatalogo.get(
    "/juegos/{juegoId}",
    response_model=Respuesta[FichaTecnicaSalida],
    responses={404: ERROR_404, 503: ERROR_503},
)
def consultarFichaTecnica(juegoId: int, sesion: Session = Depends(obtenerSesionBd)):
    """
    HU-21: Consultar detalles de ficha técnica.

    Retorna título, descripción, género, plataformas, desarrollador, fecha de lanzamiento y
    estado. No incluye costo de adquisición ni margen; el precio se obtiene con HU-24.
    """
    return servicioCatalogo.consultarFichaTecnica(sesion, juegoId)


@enrutadorCatalogo.get(
    "/juegos/{juegoId}/requisitos",
    response_model=Respuesta[RequisitosSalida],
    responses={404: ERROR_404, 503: ERROR_503},
)
def consultarRequisitosSistema(juegoId: int, sesion: Session = Depends(obtenerSesionBd)):
    """
    HU-22: Ver requisitos del sistema.

    Retorna los requisitos `minimos` y `recomendados` (sistemaOperativo, procesador, memoria, grafica,
    almacenamiento). Si el juego no tiene requisitos registrados (p. ej. juegos de consola)
    responde 200 con `success=false` y un mensaje informativo.
    """
    return servicioCatalogo.consultarRequisitos(sesion, juegoId)


@enrutadorCatalogo.get(
    "/juegos/{juegoId}/multimedia",
    response_model=Respuesta[MultimediaSalida],
    responses={404: ERROR_404, 503: ERROR_503},
)
def consultarGaleriaYTrailers(juegoId: int, sesion: Session = Depends(obtenerSesionBd)):
    """
    HU-23: Visualizar galería y trailers.

    Retorna las URLs almacenadas agrupadas en `imagenes` y `videos`. No se integra ninguna
    API externa de video.
    """
    return servicioCatalogo.consultarMultimedia(sesion, juegoId)


@enrutadorCatalogo.get(
    "/juegos/{juegoId}/precio",
    response_model=Respuesta[PrecioSalida],
    responses={
        404: ERROR_404,
        422: {"description": "El precio calculado viola la política de margen mínimo (RN-02)"},
        503: {"description": "No fue posible obtener los parámetros financieros / calcular el precio"},
    },
)
def consultarPrecioFinal(juegoId: int, sesion: Session = Depends(obtenerSesionBd)):
    """
    HU-24: Calcular y consultar precio final público.

    RN-01: `precioFinal = costoAdquisicion × (1 + margenGanancia/100) × (1 + tasaIva/100)` con {tasaIva, margenGanancia} vigentes de MOD-00 (COM-01).
    RN-02: `precioFinal >= costoAdquisicion × (1 + tasaIva/100)`; si se viola responde 409. La respuesta
    no expone costoAdquisicion ni margenGanancia. Moneda de presentación: COP (moneda base del sistema).
    """
    return servicioCatalogo.consultarPrecioFinal(sesion, juegoId)


@enrutadorCatalogoInterno.get("/juegos/{juegoId}", response_model=Respuesta[ContratoCom11Salida])
def obtenerJuegoCom11(juegoId: int, sesion: Session = Depends(obtenerSesionBd)):
    """COM-11: {juegoId, existe, titulo, estado, precioFinal, precioMinimo} para MOD-04 (Carrito y Órdenes)."""
    return respuesta("Consulta de juego exitosa", servicioCatalogo.obtenerContratoCom11(sesion, juegoId))


@enrutadorCatalogo.get(
    "/juegos/{juegoId}/stock",
    response_model=Respuesta[StockSalida],
    responses={
        404: ERROR_404,
        503: {"description": "No fue posible verificar la disponibilidad (COM-12) / el stock (BD)"},
    },
)
def verificarDisponibilidadStock(juegoId: int, sesion: Session = Depends(obtenerSesionBd)):
    """
    HU-25: Verificar disponibilidad de stock.

    Consulta el stock a MOD-03 (COM-12) y retorna `DISPONIBLE` o `AGOTADO` sin exponer el
    conteo exacto de claves. Si MOD-03 no responde se retorna 503 (nunca se asume DISPONIBLE).
    """
    return servicioCatalogo.verificarStock(sesion, juegoId)
