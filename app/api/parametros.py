from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.domain.parametros import (
    MonedaCreate,
    MonedaResponse,
    ActualizarIvaRequest,
    ActualizarMargenRequest,
    MetodoPagoCreate,
    MetodoPagoResponse
)
from app.services.parametros_service import ParametrosService

# Router público/administrativo para las Historias de Usuario HU-01 a HU-05
router = APIRouter(prefix="/api/v1/parametros", tags=["MOD-00: Parametrización (HU-01 a HU-05)"])

# Router interno para los contratos entre microservicios COM-01 a COM-03 (Tabla 10)
internal_router = APIRouter(prefix="/internal/v1/parametros", tags=["Contratos Internos MOD-00 (COM-01 a COM-03)"])

service = ParametrosService()

# =====================================================================
# HISTORIAS DE USUARIO DEL SPRINT-00 (HU-01 a HU-05)
# =====================================================================

@router.post("/monedas", response_model=MonedaResponse, status_code=status.HTTP_201_CREATED)
def registrar_nueva_moneda(datos: MonedaCreate, db: Session = Depends(get_db)):
    """HU-01 (FUN-00.1.1 / PRO-00.1.1): Registrar nueva moneda habilitada."""
    return service.registrar_moneda(db, datos)


@router.get("/monedas", response_model=list[MonedaResponse])
def consultar_monedas_habilitadas(db: Session = Depends(get_db)):
    """HU-02 (FUN-00.1.2 / PRO-00.1.2): Consultar monedas actualmente activas."""
    service.inicializar_datos_por_defecto(db)
    return service.consultar_monedas_habilitadas(db)


@router.put("/impuesto-iva")
def actualizar_tasa_iva(datos: ActualizarIvaRequest, db: Session = Depends(get_db)):
    """HU-03 (FUN-00.1.3 / PRO-00.1.3): Actualizar porcentaje de impuesto IVA (0 a 100)."""
    config = service.actualizar_tasa_iva(db, datos.tasa_iva)
    return {
        "mensaje": "Tasa de impuesto IVA actualizada correctamente.",
        "tasa_iva_porcentaje": config.tasa_iva
    }


@router.put("/margen-ganancia")
def configurar_margen_ganancia(datos: ActualizarMargenRequest, db: Session = Depends(get_db)):
    """HU-04 (FUN-00.1.4 / PRO-00.1.4): Configurar margen de ganancia / markup (> 0)."""
    config = service.configurar_margen_ganancia(db, datos.margen_ganancia)
    return {
        "mensaje": "Margen comercial (markup) actualizado correctamente.",
        "margen_ganancia_porcentaje": config.margen_ganancia
    }


@router.get("/metodos-pago", response_model=list[MetodoPagoResponse])
def listar_metodos_de_pago(db: Session = Depends(get_db)):
    """Consulta el listado de métodos de pago y su estado (Activo/Inactivo)."""
    return service.listar_metodos_pago(db)


@router.post("/metodos-pago", response_model=MetodoPagoResponse, status_code=status.HTTP_201_CREATED)
def registrar_metodo_de_pago(datos: MetodoPagoCreate, db: Session = Depends(get_db)):
    """Endpoint auxiliar para registrar métodos de pago adicionales."""
    return service.crear_metodo_pago(db, datos)


@router.patch("/metodos-pago/{metodo_id}/inactivar", response_model=MetodoPagoResponse)
def inactivar_metodo_de_pago(metodo_id: int, db: Session = Depends(get_db)):
    """HU-05 (FUN-00.1.5 / PRO-00.1.5): Inactivar método de pago mediante borrado lógico."""
    return service.inactivar_metodo_pago(db, metodo_id)


# =====================================================================
# CONTRATOS INTERNOS DE INTEROPERABILIDAD (Tabla 10 del Informe)
# =====================================================================

@internal_router.get("/financieros")
def obtener_parametros_financieros_com01(db: Session = Depends(get_db)):
    """COM-01: Entrega {taxRate, margin} al módulo MOD-02 (Catálogo de Juegos)."""
    return service.obtener_contrato_com01(db)


@internal_router.get("/orden-config")
def obtener_configuracion_orden_com02(db: Session = Depends(get_db)):
    """COM-02: Entrega {taxRate, currency} al módulo MOD-04 (Carrito y Órdenes)."""
    return service.obtener_contrato_com02(db)


@internal_router.get("/tasa-cambio/{currency}")
def obtener_tasa_cambio_com03(currency: str, db: Session = Depends(get_db)):
    """COM-03: Entrega {currency, exchangeRate} al módulo MOD-05 (Transacciones y Pagos)."""
    return service.obtener_contrato_com03(db, currency)