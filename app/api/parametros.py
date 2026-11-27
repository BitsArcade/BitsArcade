from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.base_datos import obtenerSesionBd
from app.core.fechas import aIsoZ
from app.core.respuestas import Respuesta, manejarErroresBd, respuesta
from app.core.seguridad import UsuarioAutenticado, obtenerUsuarioAdmin, validarTokenServicio
from app.domain.parametros import (
    ActualizarIvaEntrada,
    ActualizarMargenEntrada,
    CrearMonedaEntrada,
    ImpuestoSalida,
    MargenSalida,
    MetodoPagoSalida,
    MonedaResumenSalida,
    MonedaSalida,
    ParametrosFinancierosSalida,
    TasaCambioSalida,
)
from app.services.servicio_parametros import ServicioParametros

enrutadorParametros = APIRouter(prefix="/api/v1/parametrizacion", tags=["MOD-00: Parametrización (HU-01 a HU-05)"])
enrutadorParametrosInterno = APIRouter(
    prefix="/interno/v1/parametrizacion",
    tags=["MOD-00: Contratos internos (COM-01 a COM-03)"],
    dependencies=[Depends(validarTokenServicio)],
)
servicioParametros = ServicioParametros()


@enrutadorParametros.post("/monedas", status_code=201, response_model=Respuesta[MonedaSalida])
def registrarMoneda(
    datos: CrearMonedaEntrada,
    _admin: UsuarioAutenticado = Depends(obtenerUsuarioAdmin),
    sesion: Session = Depends(obtenerSesionBd),
):
    """HU-01: registra una moneda ISO 4217 en estado ACTIVO (sin tasa de cambio)."""
    return servicioParametros.registrarMoneda(sesion, datos)


@enrutadorParametros.get("/monedas", response_model=Respuesta[list[MonedaResumenSalida]])
def consultarMonedas(
    estado: str | None = Query(default="ACTIVO", description="ACTIVO o INACTIVO"),
    sesion: Session = Depends(obtenerSesionBd),
):
    """HU-02: lista pública de monedas por estado (por defecto ACTIVO), sin tasas de cambio."""
    return servicioParametros.consultarMonedas(sesion, estado)


@enrutadorParametros.put("/impuestos/{impuestoId}", response_model=Respuesta[ImpuestoSalida])
def actualizarTasaIva(
    impuestoId: int,
    datos: ActualizarIvaEntrada,
    _admin: UsuarioAutenticado = Depends(obtenerUsuarioAdmin),
    sesion: Session = Depends(obtenerSesionBd),
):
    """HU-03: actualiza el porcentaje global de IVA (0 a 100)."""
    return servicioParametros.actualizarTasaIva(sesion, impuestoId, datos.tasaIva)


@enrutadorParametros.put("/margenes/ganancia", response_model=Respuesta[MargenSalida])
def configurarMargenGanancia(
    datos: ActualizarMargenEntrada,
    _admin: UsuarioAutenticado = Depends(obtenerUsuarioAdmin),
    sesion: Session = Depends(obtenerSesionBd),
):
    """HU-04: fija el porcentaje global de margen de ganancia (> 0)."""
    return servicioParametros.configurarMargenGanancia(sesion, datos.margenGanancia)


@enrutadorParametros.patch("/metodos-pago/{metodoPagoId}/inactivar", response_model=Respuesta[MetodoPagoSalida])
def inactivarMetodoPago(
    metodoPagoId: int,
    _admin: UsuarioAutenticado = Depends(obtenerUsuarioAdmin),
    sesion: Session = Depends(obtenerSesionBd),
):
    """HU-05: inactivación lógica de un método de pago (no se elimina el registro)."""
    return servicioParametros.inactivarMetodoPago(sesion, metodoPagoId)


@enrutadorParametrosInterno.get("/financieros", response_model=Respuesta[ParametrosFinancierosSalida])
def obtenerParametrosFinancieros(sesion: Session = Depends(obtenerSesionBd)):
    """COM-01 / COM-02: {tasaIva, margenGanancia, monedaBase} en porcentaje 0-100."""
    with manejarErroresBd("No fue posible obtener los parámetros financieros"):
        return respuesta("Parámetros financieros vigentes", servicioParametros.obtenerContratoCom01(sesion))


@enrutadorParametrosInterno.get("/tasa-cambio/{codigoIso}", response_model=Respuesta[TasaCambioSalida])
def obtenerTasaCambio(codigoIso: str, sesion: Session = Depends(obtenerSesionBd)):
    """COM-03: tasa vigente en COP por 1 unidad de la moneda (consulta la API externa de Divisas)."""
    tasa = servicioParametros.obtenerContratoCom03(sesion, codigoIso)
    return respuesta("Tasa de cambio vigente", {**tasa, "consultadaEn": aIsoZ(tasa["consultadaEn"])})
