from typing import Optional

from fastapi import APIRouter, Depends, Query, Response
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.core.base_datos import obtenerSesionBd
from app.core.respuestas import Respuesta
from app.core.seguridad import UsuarioAutenticado, obtenerUsuarioAutenticado
from app.domain.despacho import (
    ClaveReveladaSalida,
    CompraHistorialSalida,
    DetalleCompraSalida,
    EstadoLicenciaSalida,
    LicenciaBibliotecaSalida,
)
from app.services.servicio_biblioteca import ServicioBiblioteca

enrutadorBiblioteca = APIRouter(
    prefix="/api/v1/biblioteca",
    tags=["MOD-06: Biblioteca del Cliente (HU-43, HU-46 a HU-50)"],
)

servicioBiblioteca = ServicioBiblioteca()

ERROR_401 = {"description": "Token inválido, expirado o ausente"}


# ===== HU-46: Consultar biblioteca personal de juegos =====

@enrutadorBiblioteca.get(
    "",
    response_model=Respuesta[list[LicenciaBibliotecaSalida]],
    responses={401: ERROR_401, 503: {"description": "No fue posible consultar la biblioteca"}},
)
def consultarBiblioteca(
    usuario: UsuarioAutenticado = Depends(obtenerUsuarioAutenticado),
    sesion: Session = Depends(obtenerSesionBd),
):
    """HU-46: licencias del usuario autenticado con claves enmascaradas."""
    return servicioBiblioteca.consultarBiblioteca(sesion, usuario)


# ===== HU-50: Filtrar historial por fechas =====

@enrutadorBiblioteca.get(
    "/compras",
    response_model=Respuesta[list[CompraHistorialSalida]],
    responses={
        400: {"description": "Formato de fecha no válido / La fecha 'desde' no puede ser posterior a 'hasta'"},
        401: ERROR_401,
        503: {"description": "No fue posible consultar el historial"},
    },
)
def filtrarHistorialPorFechas(
    desde: Optional[str] = Query(default=None, description="YYYY-MM-DD (inclusive, America/Bogota)"),
    hasta: Optional[str] = Query(default=None, description="YYYY-MM-DD (inclusive, America/Bogota)"),
    orden: Optional[str] = Query(default="desc", description="asc | desc"),
    usuario: UsuarioAutenticado = Depends(obtenerUsuarioAutenticado),
    sesion: Session = Depends(obtenerSesionBd),
):
    """HU-50: compras del usuario en el rango indicado, ordenadas por fecha."""
    return servicioBiblioteca.filtrarHistorial(sesion, usuario, desde, hasta, orden)


# ===== HU-47: Consultar detalle de compra pasada =====

@enrutadorBiblioteca.get(
    "/compras/{ordenId}",
    response_model=Respuesta[DetalleCompraSalida],
    responses={
        401: ERROR_401,
        404: {"description": "La compra indicada no existe"},
        503: {"description": "No fue posible consultar la compra"},
    },
)
def consultarDetalleCompra(
    ordenId: int,
    usuario: UsuarioAutenticado = Depends(obtenerUsuarioAutenticado),
    sesion: Session = Depends(obtenerSesionBd),
):
    """HU-47: detalle de una compra propia con claves enmascaradas."""
    return servicioBiblioteca.consultarCompra(sesion, usuario, ordenId)


# ===== HU-48: Descargar comprobante digital de compra =====

@enrutadorBiblioteca.get(
    "/compras/{ordenId}/comprobante",
    response_model=Respuesta[dict],
    responses={
        401: ERROR_401,
        404: {"description": "La compra indicada no existe"},
        503: {"description": "No fue posible generar el comprobante"},
    },
)
def descargarComprobanteCompra(
    ordenId: int,
    usuario: UsuarioAutenticado = Depends(obtenerUsuarioAutenticado),
    sesion: Session = Depends(obtenerSesionBd),
):
    """HU-48: comprobante descargable (Content-Disposition: attachment, JSON)."""
    contenido = servicioBiblioteca.generarComprobante(sesion, usuario, ordenId)
    nombreArchivo = f"comprobante-{contenido['data']['numero']}.json"
    return JSONResponse(
        content=contenido,
        headers={"Content-Disposition": f'attachment; filename="{nombreArchivo}"'},
    )


# ===== HU-49: Consultar estado de licencias =====

@enrutadorBiblioteca.get(
    "/licencias/estado",
    response_model=Respuesta[list[EstadoLicenciaSalida]],
    responses={401: ERROR_401, 503: {"description": "No fue posible consultar el estado de las licencias"}},
)
def consultarEstadoLicencias(
    usuario: UsuarioAutenticado = Depends(obtenerUsuarioAutenticado),
    sesion: Session = Depends(obtenerSesionBd),
):
    """HU-49: estado de cada licencia (ENTREGADA/revelada) y si aún es reembolsable."""
    return servicioBiblioteca.consultarEstadoLicencias(sesion, usuario)


# ===== HU-43: Formateo y visualización segura de la clave =====

@enrutadorBiblioteca.post(
    "/licencias/{licenciaId}/revelar",
    response_model=Respuesta[ClaveReveladaSalida],
    responses={
        401: ERROR_401,
        404: {"description": "La licencia indicada no existe"},
        503: {"description": "No fue posible revelar la clave"},
    },
)
def revelarClaveLicencia(
    licenciaId: str,
    response: Response,
    usuario: UsuarioAutenticado = Depends(obtenerUsuarioAutenticado),
    sesion: Session = Depends(obtenerSesionBd),
):
    """HU-43 (RN-11): revela la clave de una licencia propia; la respuesta no se almacena en caché."""
    response.headers["Cache-Control"] = "no-store"
    return servicioBiblioteca.revelarClave(sesion, usuario, licenciaId)
