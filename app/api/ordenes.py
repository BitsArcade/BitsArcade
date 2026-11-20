from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.base_datos import get_db
from app.core.respuestas import Respuesta
from app.core.seguridad import UsuarioAutenticado, obtener_usuario_autenticado
from app.domain.ordenes import (
    ActualizarEstadoOrdenEntrada,
    CancelarOrdenEntrada,
    LiquidacionOrdenSalida,
    OrdenCompraSalida,
)
from app.services.servicio_ordenes import ServicioOrdenes

enrutador_ordenes = APIRouter(
    prefix="/api/v1/ordenes",
    tags=["MOD-04: Gestión de Órdenes y Liquidación (HU-31 a HU-35)"],
)

enrutador_ordenes_interno = APIRouter(
    prefix="/internal/v1/ordenes",
    tags=["Contratos Internos MOD-04 (COM-08 y COM-09)"],
)

servicioOrdenes = ServicioOrdenes()

ERROR_401 = {"description": "Token inválido, expirado o ausente"}


# =====================================================================
# HISTORIAS DE USUARIO DEL SPRINT-05 (HU-31 a HU-35)
# =====================================================================

@enrutador_ordenes.post(
    "",
    response_model=Respuesta[OrdenCompraSalida],
    status_code=status.HTTP_201_CREATED,
    responses={
        400: {"description": "El carrito está vacío"},
        401: ERROR_401,
        409: {"description": "Stock insuficiente / Límite de preventa superado"},
        503: {"description": "Error de comunicación con Catálogo, Inventario o Base de Datos"},
    },
)
def consolidar_orden_de_compra(
    usuario: UsuarioAutenticado = Depends(obtener_usuario_autenticado),
    sesion: Session = Depends(get_db),
):
    """
    HU-31 (FUN-04.2.1 / PRO-04.2.1): Consolidar orden de compra pendiente.

    Toma los ítems del carrito activo del usuario (JWT), reserva las keys por 15 minutos (RN-04),
    congela la moneda y tasa de cambio (RN-09), liquida totales y vacía el carrito.
    """
    return servicioOrdenes.consolidarOrden(sesion, usuario)


@enrutador_ordenes.get(
    "/{ordenId}/liquidacion",
    response_model=Respuesta[LiquidacionOrdenSalida],
    responses={
        401: ERROR_401,
        404: {"description": "La orden no existe o no pertenece al usuario"},
    },
)
def consultar_liquidacion_financiera(
    ordenId: int,
    usuario: UsuarioAutenticado = Depends(obtener_usuario_autenticado),
    sesion: Session = Depends(get_db),
):
    """
    HU-32 (FUN-04.2.2 / PRO-04.2.2): Calcular y consultar liquidación financiera de la orden.

    Muestra el desglose de base gravable, descuentos por volumen (RN-08), IVA y total final.
    """
    return servicioOrdenes.obtenerLiquidacionOrden(sesion, usuario, ordenId)


@enrutador_ordenes.get(
    "/pendientes",
    response_model=Respuesta[list[OrdenCompraSalida]],
    responses={
        401: ERROR_401,
    },
)
def consultar_ordenes_pendientes(
    usuario: UsuarioAutenticado = Depends(obtener_usuario_autenticado),
    sesion: Session = Depends(get_db),
):
    """
    HU-33 (FUN-04.2.3 / PRO-04.2.3): Consultar órdenes pendientes de pago del usuario.
    """
    return servicioOrdenes.consultarOrdenesPendientes(sesion, usuario)


@enrutador_ordenes.patch(
    "/{ordenId}/cancelar",
    response_model=Respuesta[OrdenCompraSalida],
    responses={
        401: ERROR_401,
        404: {"description": "La orden no existe o no pertenece al usuario"},
        409: {"description": "La orden no está en estado PENDIENTE"},
    },
)
def cancelar_orden_de_compra(
    ordenId: int,
    datos: CancelarOrdenEntrada,
    usuario: UsuarioAutenticado = Depends(obtener_usuario_autenticado),
    sesion: Session = Depends(get_db),
):
    """
    HU-34 (FUN-04.2.4 / PRO-04.2.4): Cancelar orden de compra y liberar stock reservado.
    """
    return servicioOrdenes.cancelarOrden(sesion, usuario, ordenId, datos)


@enrutador_ordenes.patch(
    "/{ordenId}/procesar",
    response_model=Respuesta[OrdenCompraSalida],
    responses={
        401: ERROR_401,
        404: {"description": "La orden no existe o no pertenece al usuario"},
        409: {"description": "La orden no está en estado PENDIENTE"},
    },
)
def cambiar_estado_a_procesando(
    ordenId: int,
    usuario: UsuarioAutenticado = Depends(obtener_usuario_autenticado),
    sesion: Session = Depends(get_db),
):
    """
    HU-35 (FUN-04.2.5 / PRO-04.2.5): Bloquear orden pasando su estado a PROCESANDO al iniciar el pago.
    """
    return servicioOrdenes.bloquearOrdenProcesando(sesion, usuario, ordenId)


# =====================================================================
# CONTRATOS INTERNOS DE INTEROPERABILIDAD (Tabla 10 del Informe)
# =====================================================================

@enrutador_ordenes_interno.get("/{ordenId}")
def obtener_datos_orden_com08(ordenId: int, sesion: Session = Depends(get_db)):
    """COM-08: Entrega {ordenId, usuarioId, moneda, total, items} al módulo MOD-05 (Pagos)."""
    return servicioOrdenes.obtenerContratoCom08(sesion, ordenId)


@enrutador_ordenes_interno.patch("/estado")
def actualizar_estado_orden_com09(datos: ActualizarEstadoOrdenEntrada, sesion: Session = Depends(get_db)):
    """COM-09: Permite a MOD-05 (Pagos) marcar la orden como PAGADA o CANCELADA (RN-06)."""
    return servicioOrdenes.procesarContratoCom09(sesion, datos)