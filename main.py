"""
BitArcade - Backend (FastAPI). Arquitectura por capas: api / services / domain / repositories / core.

Prefijos: /api/v1 (público y clientes), /interno/v1 (contratos entre módulos, token de servicio)
y /externo/v1 (servicios externos simulados).
"""
from fastapi import FastAPI

from app.core.base_datos import Base, motor
from app.core.configuracion import configuracion
from app.core.respuestas import registrarManejadoresErrores

# Modelos (registran sus tablas en Base.metadata)
from app.domain import parametros as modelosParametros  # noqa: F401
from app.domain import usuarios as modelosUsuarios  # noqa: F401
from app.domain import catalogo as modelosCatalogo  # noqa: F401
from app.domain import inventario as modelosInventario  # noqa: F401
from app.domain import carrito as modelosCarrito  # noqa: F401
from app.domain import ordenes as modelosOrdenes  # noqa: F401
from app.domain import pagos as modelosPagos  # noqa: F401
from app.domain import despacho as modelosDespacho  # noqa: F401

from app.api.parametros import enrutadorParametros, enrutadorParametrosInterno
from app.api.usuarios import enrutadorUsuarios, enrutadorUsuariosInterno
from app.api.catalogo import enrutadorCatalogo, enrutadorCatalogoInterno
from app.api.inventario import enrutadorInventario, enrutadorInventarioInterno
from app.api.carrito import enrutadorCarrito
from app.api.ordenes import enrutadorOrdenes, enrutadorOrdenesInterno
from app.api.pagos import enrutadorPagos
from app.api.despacho import enrutadorDespachoInterno
from app.api.biblioteca import enrutadorBiblioteca
from app.api.notificaciones_simuladas import enrutadorNotificacionesExternas
from app.services.tareas_programadas import iniciarTareasProgramadas

Base.metadata.create_all(bind=motor)

app = FastAPI(
    title=configuracion.NOMBRE_APLICACION,
    description="Backend oficial de BitArcade - Arquitectura por capas (API, Servicio, Dominio, Repositorio, BD).",
    version="1.0.0",
)

for enrutador in (
    enrutadorParametros,
    enrutadorParametrosInterno,
    enrutadorUsuarios,
    enrutadorUsuariosInterno,
    enrutadorCatalogo,
    enrutadorCatalogoInterno,
    enrutadorInventario,
    enrutadorInventarioInterno,
    enrutadorCarrito,
    enrutadorOrdenes,
    enrutadorOrdenesInterno,
    enrutadorPagos,
    enrutadorDespachoInterno,
    enrutadorBiblioteca,
    enrutadorNotificacionesExternas,
):
    app.include_router(enrutador)

registrarManejadoresErrores(app)

# TT-04 / HU-34: tareas periódicas (reservas vencidas, alertas de stock y órdenes expiradas).
# Solo arrancan si la variable de entorno INTERVALO_TAREAS_SEGUNDOS es mayor que 0.
iniciarTareasProgramadas()


@app.get("/", tags=["General"])
def leerRaiz():
    """Endpoint raíz de bienvenida al sistema BitArcade."""
    return {
        "sistema": configuracion.NOMBRE_APLICACION,
        "entorno": configuracion.ENTORNO,
        "version": "1.0.0",
        "documentacion": "/docs",
    }


@app.get("/salud", tags=["Monitoreo"])
def verificarSalud():
    """Verificación de salud del servicio."""
    return {"estado": "ACTIVO", "servicio": configuracion.NOMBRE_APLICACION, "entorno": configuracion.ENTORNO}
