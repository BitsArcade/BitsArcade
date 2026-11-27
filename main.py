from fastapi import FastAPI
from app.core.configuracion import settings
from app.core.base_datos import engine, Base
from app.domain import parametros as modelos_parametros
from app.api.parametros import enrutadorParametros, enrutadorParametrosInterno
from app.domain import usuarios as modelosUsuarios
from app.domain import catalogo as modelos_catalogo
from app.domain import inventario as modelos_inventario
from app.domain import carrito as modelos_carrito
from app.domain import ordenes as modelos_ordenes
from app.api.usuarios import enrutadorUsuarios, enrutadorUsuariosInterno
from app.api.catalogo import enrutadorCatalogo, enrutadorCatalogoInterno
from app.api.inventario import enrutadorInventario, enrutadorInventarioInterno
from app.api.carrito import enrutadorCarrito
from app.api.ordenes import enrutadorOrdenes, enrutadorOrdenesInterno
from app.core.respuestas import registrar_manejadores_errores
from app.services.tareas_programadas import iniciarTareasProgramadas

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title=settings.APP_NAME,
    description="Backend oficial de BitArcade - Arquitectura de 5 capas (API, Service, Domain, Repository, DB).",
    version="1.0.0"
)

app.include_router(enrutadorParametros)
app.include_router(enrutadorParametrosInterno)
app.include_router(enrutadorUsuarios)
app.include_router(enrutadorUsuariosInterno)
app.include_router(enrutadorCatalogo)
app.include_router(enrutadorCatalogoInterno)
app.include_router(enrutadorInventario)
app.include_router(enrutadorInventarioInterno)
app.include_router(enrutadorCarrito)
app.include_router(enrutadorOrdenes)
app.include_router(enrutadorOrdenesInterno)

registrar_manejadores_errores(app)

# TT-04 (HU-13 / HU-15): tareas periódicas de inventario (reservas vencidas y alertas de stock).
# Solo arrancan si la variable de entorno INTERVALO_TAREAS_SEGUNDOS es mayor que 0.
iniciarTareasProgramadas()

@app.get("/", tags=["General"])
def leer_raiz():
    """Endpoint raíz de bienvenida al sistema BitArcade."""
    return {
        "sistema": settings.APP_NAME,
        "entorno": settings.APP_ENV,
        "version": "1.0.0",
        "documentacion_swagger": "/docs"
    }

@app.get("/health", tags=["Monitoreo"])
def verificar_salud():
    """Endpoint de verificación de salud (Health Check) del microservicio."""
    return {
        "status": "healthy",
        "service": settings.APP_NAME,
        "environment": settings.APP_ENV,
        "database_configured": bool(settings.DATABASE_URL)
    }