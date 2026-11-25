from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session
from app.core.base_datos import get_db
from app.domain.parametros import (
    CrearMonedaEntrada,
    MonedaSalida,
    ActualizarIvaEntrada,
    ActualizarMargenEntrada,
    CrearMetodoPagoEntrada,
    MetodoPagoSalida
)
from app.services.servicio_parametros import ServicioParametros

enrutador_parametros = APIRouter(
    prefix="/api/v1/parametros",
    tags=["MOD-00: Parametrización (HU-01 a HU-05)"]
)

enrutador_interno = APIRouter(
    prefix="/internal/v1/parametros",
    tags=["Contratos Internos MOD-00 (COM-01 a COM-03)"]
)

servicio = ServicioParametros()

# =====================================================================
# HISTORIAS DE USUARIO DEL SPRINT-00 (HU-01 a HU-05)
# =====================================================================

@enrutador_parametros.post("/monedas", response_model=MonedaSalida, status_code=status.HTTP_201_CREATED)
def registrar_nueva_moneda(datos: CrearMonedaEntrada, sesion: Session = Depends(get_db)):
    """HU-01 (FUN-00.1.1 / PRO-00.1.1): Registrar nueva moneda habilitada."""
    return servicio.registrar_moneda(sesion, datos)


@enrutador_parametros.get("/monedas", response_model=list[MonedaSalida])
def consultar_monedas_habilitadas(sesion: Session = Depends(get_db)):
    """HU-02 (FUN-00.1.2 / PRO-00.1.2): Consultar monedas actualmente activas."""
    servicio.inicializar_datos_por_defecto(sesion)
    return servicio.consultar_monedas_habilitadas(sesion)


@enrutador_parametros.put("/impuesto-iva")
def actualizar_tasa_iva(datos: ActualizarIvaEntrada, sesion: Session = Depends(get_db)):
    """HU-03 (FUN-00.1.3 / PRO-00.1.3): Actualizar porcentaje de impuesto IVA (0 a 100)."""
    configuracion = servicio.actualizar_tasa_iva(sesion, datos.tasa_iva)
    return {
        "mensaje": "Tasa de impuesto IVA actualizada correctamente.",
        "tasa_iva_porcentaje": configuracion.tasa_iva
    }


@enrutador_parametros.put("/margen-ganancia")
def configurar_margen_ganancia(datos: ActualizarMargenEntrada, sesion: Session = Depends(get_db)):
    """HU-04 (FUN-00.1.4 / PRO-00.1.4): Configurar margen de ganancia / markup (> 0)."""
    configuracion = servicio.configurar_margen_ganancia(sesion, datos.margen_ganancia)
    return {
        "mensaje": "Margen comercial (markup) actualizado correctamente.",
        "margen_ganancia_porcentaje": configuracion.margen_ganancia
    }


@enrutador_parametros.get("/metodos-pago", response_model=list[MetodoPagoSalida])
def listar_metodos_de_pago(sesion: Session = Depends(get_db)):
    """Consulta el listado de métodos de pago y su estado (Activo/Inactivo)."""
    return servicio.listar_metodos_pago(sesion)


@enrutador_parametros.post("/metodos-pago", response_model=MetodoPagoSalida, status_code=status.HTTP_201_CREATED)
def registrar_metodo_de_pago(datos: CrearMetodoPagoEntrada, sesion: Session = Depends(get_db)):
    """Endpoint auxiliar para registrar métodos de pago adicionales."""
    return servicio.crear_metodo_pago(sesion, datos)


@enrutador_parametros.patch("/metodos-pago/{metodo_id}/inactivar", response_model=MetodoPagoSalida)
def inactivar_metodo_de_pago(metodo_id: int, sesion: Session = Depends(get_db)):
    """HU-05 (FUN-00.1.5 / PRO-00.1.5): Inactivar método de pago mediante borrado lógico."""
    return servicio.inactivar_metodo_pago(sesion, metodo_id)


# =====================================================================
# CONTRATOS INTERNOS DE INTEROPERABILIDAD (Tabla 10 del Informe)
# =====================================================================

@enrutador_interno.get("/financieros")
def obtener_parametros_financieros_com01(sesion: Session = Depends(get_db)):
    """COM-01: Entrega {taxRate, margin} al módulo MOD-02 (Catálogo de Juegos)."""
    return servicio.obtener_contrato_com01(sesion)


@enrutador_interno.get("/orden-config")
def obtener_configuracion_orden_com02(sesion: Session = Depends(get_db)):
    """COM-02: Entrega {taxRate, currency} al módulo MOD-04 (Carrito y Órdenes)."""
    return servicio.obtener_contrato_com02(sesion)


@enrutador_interno.get("/tasa-cambio/{moneda_iso}")
def obtener_tasa_cambio_com03(moneda_iso: str, sesion: Session = Depends(get_db)):
    """COM-03: Entrega {currency, exchangeRate} al módulo MOD-05 (Transacciones y Pagos)."""
    return servicio.obtener_contrato_com03(sesion, moneda_iso)