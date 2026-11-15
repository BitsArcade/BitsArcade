from fastapi import FastAPI
from app.core.config import settings
from app.core.database import engine, Base
from app.domain import parametros as parametros_models  # Importar modelos para que SQLAlchemy cree sus tablas
from app.api.parametros import router as parametros_router, internal_router as parametros_internal_router

# Crear físicamente las tablas en SQLite (dev.db) si aún no existen
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title=settings.APP_NAME,
    description="Backend oficial de BitArcade - Arquitectura de 5 capas (API, Service, Domain, Repository, DB).",
    version="1.0.0"
)

# Registrar routers del Módulo de Parametrización Global (MOD-00)
app.include_router(parametros_router)
app.include_router(parametros_internal_router)

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
def health_check():
    """Endpoint de verificación de salud (Health Check) del microservicio."""
    return {
        "status": "healthy",
        "service": settings.APP_NAME,
        "environment": settings.APP_ENV,
        "database_configured": bool(settings.DATABASE_URL)
    }