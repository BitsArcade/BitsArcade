from fastapi import FastAPI
from sqlalchemy import inspect, text

from app.api.carrito import enrutador_carrito
from app.api.catalogo import enrutador_catalogo, enrutador_catalogo_interno
from app.api.despacho import enrutador_biblioteca, enrutador_despacho_interno
from app.api.ordenes import enrutador_ordenes, enrutador_ordenes_interno
from app.api.parametros import enrutador_interno, enrutador_parametros
from app.api.transacciones import enrutador_transacciones
from app.core.base_datos import Base, engine
from app.core.configuracion import settings
from app.core.respuestas import registrar_manejadores_errores
from app.domain import carrito as modelos_carrito
from app.domain import catalogo as modelos_catalogo
from app.domain import despacho as modelos_despacho
from app.domain import inventario as modelos_inventario
from app.domain import orden as modelos_orden
from app.domain import parametros as modelos_parametros
from app.domain import transacciones as modelos_transacciones

Base.metadata.create_all(bind=engine)


def _sincronizar_columnas_sqlite() -> None:
    """Garantiza columnas agregadas en HU recientes si ya existía un archivo .db local."""
    inspector = inspect(engine)
    if "ordenes" in inspector.get_table_names():
        columnas = {col["name"] for col in inspector.get_columns("ordenes")}
        if "entregada_en" not in columnas:
            with engine.begin() as conexion:
                conexion.execute(text("ALTER TABLE ordenes ADD COLUMN entregada_en DATETIME"))


_sincronizar_columnas_sqlite()

app = FastAPI(
    title=settings.APP_NAME,
    description="Backend oficial de BitArcade - Arquitectura de 5 capas (API, Service, Domain, Repository, DB).",
    version="1.0.0",
)

app.include_router(enrutador_parametros)
app.include_router(enrutador_interno)
app.include_router(enrutador_catalogo)
app.include_router(enrutador_catalogo_interno)
app.include_router(enrutador_carrito)
app.include_router(enrutador_ordenes)
app.include_router(enrutador_ordenes_interno)
app.include_router(enrutador_transacciones)
app.include_router(enrutador_despacho_interno)
app.include_router(enrutador_biblioteca)

registrar_manejadores_errores(app)


@app.get("/", tags=["General"])
def leer_raiz():
    """Endpoint raíz de bienvenida al sistema BitArcade."""
    return {
        "sistema": settings.APP_NAME,
        "entorno": settings.APP_ENV,
        "version": "1.0.0",
        "documentacion_swagger": "/docs",
    }


@app.get("/health", tags=["Monitoreo"])
def verificar_salud():
    """Endpoint de verificación de salud (Health Check) del microservicio."""
    return {
        "status": "healthy",
        "service": settings.APP_NAME,
        "environment": settings.APP_ENV,
        "database_configured": bool(settings.DATABASE_URL),
    }