from fastapi import FastAPI
from app.core.configuracion import settings
from app.core.base_datos import engine, Base
from app.domain import parametros as modelos_parametros
from app.api.parametros import enrutador_parametros, enrutador_interno
from app.domain import catalogo as modelos_catalogo
from app.domain import inventario as modelos_inventario
from app.domain import carrito as modelos_carrito
from app.domain import orden as modelos_orden
from app.domain import transacciones as modelos_transacciones
from app.api.catalogo import enrutador_catalogo, enrutador_catalogo_interno
from app.api.carrito import enrutador_carrito
from app.api.ordenes import enrutador_ordenes, enrutador_ordenes_interno
from app.api.transacciones import enrutador_transacciones
from app.core.respuestas import registrar_manejadores_errores

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title=settings.APP_NAME,
    description="Backend oficial de BitArcade - Arquitectura de 5 capas (API, Service, Domain, Repository, DB).",
    version="1.0.0"
)

app.include_router(enrutador_parametros)
app.include_router(enrutador_interno)
app.include_router(enrutador_catalogo)
app.include_router(enrutador_catalogo_interno)
app.include_router(enrutador_carrito)
app.include_router(enrutador_ordenes)
app.include_router(enrutador_ordenes_interno)
app.include_router(enrutador_transacciones)

registrar_manejadores_errores(app)

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