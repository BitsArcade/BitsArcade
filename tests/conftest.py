"""
Configuración común de pruebas: base de datos SQLite en memoria aislada por prueba,
sin tocar el archivo dev.db del proyecto.
"""
import os
import tempfile
from datetime import date

_DIRECTORIO_TEMPORAL = tempfile.mkdtemp(prefix="bitarcade-tests-")
os.environ["DATABASE_URL"] = f"sqlite:///{_DIRECTORIO_TEMPORAL}/import.db"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.core.base_datos import Base, get_db  # noqa: E402
from app.domain.catalogo import Juego, PlataformaJuego  # noqa: E402
from main import app  # noqa: E402

motor_pruebas = create_engine(
    "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
)
SesionPruebas = sessionmaker(autocommit=False, autoflush=False, bind=motor_pruebas)


@pytest.fixture
def sesion():
    Base.metadata.create_all(bind=motor_pruebas)
    db = SesionPruebas()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=motor_pruebas)


@pytest.fixture
def cliente(sesion):
    def _obtener_sesion_pruebas():
        yield sesion

    app.dependency_overrides[get_db] = _obtener_sesion_pruebas
    with TestClient(app) as cliente_http:
        yield cliente_http
    app.dependency_overrides.clear()


@pytest.fixture
def crear_juego(sesion):
    """Fábrica de juegos de prueba (datos base TT-01)."""

    def _crear(
        titulo="Aurora Quest",
        genero="RPG",
        plataformas=("PC", "CONSOLA"),
        estado="ACTIVO",
        costo_adquisicion=160000.0,
        destacado=False,
        fecha_lanzamiento=date(2026, 3, 15),
        descripcion="RPG de mundo abierto",
        desarrollador="Nova Studio",
        **extra,
    ) -> Juego:
        juego = Juego(
            titulo=titulo,
            genero=genero,
            estado=estado,
            costo_adquisicion=costo_adquisicion,
            destacado=destacado,
            fecha_lanzamiento=fecha_lanzamiento,
            descripcion=descripcion,
            desarrollador=desarrollador,
            **extra,
        )
        juego.plataformas = [PlataformaJuego(plataforma=p) for p in plataformas]
        sesion.add(juego)
        sesion.commit()
        sesion.refresh(juego)
        return juego

    return _crear
