"""
Configuración común de pruebas: base de datos SQLite en memoria aislada por prueba,
sin tocar el archivo dev.db del proyecto.
"""
import os
import tempfile
from datetime import date

_DIRECTORIO_TEMPORAL = tempfile.mkdtemp(prefix="bitarcade-tests-")
os.environ["URL_BASE_DATOS"] = f"sqlite:///{_DIRECTORIO_TEMPORAL}/import.db"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.core.base_datos import Base, obtenerSesionBd  # noqa: E402
from app.domain.catalogo import Juego, PlataformaJuego  # noqa: E402
from main import app  # noqa: E402

motorPruebas = create_engine(
    "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
)
SesionPruebas = sessionmaker(autocommit=False, autoflush=False, bind=motorPruebas)


@pytest.fixture
def sesion():
    Base.metadata.create_all(bind=motorPruebas)
    db = SesionPruebas()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=motorPruebas)


@pytest.fixture
def cliente(sesion):
    """
    Cliente HTTP de pruebas. Lleva por defecto el token de servicio (X-Token-Servicio) que un módulo
    envía al invocar las rutas /interno/v1; las rutas públicas lo ignoran. Las pruebas que verifican
    el 401 de las rutas internas usan `clienteSinTokenServicio`.
    """
    from app.core.seguridad import encabezadosServicio

    def _obtenerSesionPruebas():
        yield sesion

    app.dependency_overrides[obtenerSesionBd] = _obtenerSesionPruebas
    with TestClient(app, headers=encabezadosServicio("MOD-05")) as clienteHttp:
        yield clienteHttp
    app.dependency_overrides.clear()


@pytest.fixture
def clienteSinTokenServicio(sesion):
    def _obtenerSesionPruebas():
        yield sesion

    app.dependency_overrides[obtenerSesionBd] = _obtenerSesionPruebas
    with TestClient(app) as clienteHttp:
        yield clienteHttp
    app.dependency_overrides.clear()


@pytest.fixture
def crearJuego(sesion):
    """Fábrica de juegos de prueba (datos base TT-01)."""

    def _crear(
        titulo="Aurora Quest",
        genero="RPG",
        plataformas=("PC", "CONSOLA"),
        estado="ACTIVO",
        costoAdquisicion=160000.0,
        destacado=False,
        fechaLanzamiento=date(2026, 3, 15),
        descripcion="RPG de mundo abierto",
        desarrollador="Nova Studio",
        **extra,
    ) -> Juego:
        juego = Juego(
            titulo=titulo,
            genero=genero,
            estado=estado,
            costoAdquisicion=costoAdquisicion,
            destacado=destacado,
            fechaLanzamiento=fechaLanzamiento,
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


@pytest.fixture
def crearClaves(sesion):
    """Registra claves de inventario (modelo provisional de MOD-03 usado por COM-12)."""
    from app.domain.inventario import ClaveLicencia

    def _crear(juegoId: int, disponibles: int = 0, estadoExtra: str | None = None, cantidadExtra: int = 0):
        sesion.add_all([ClaveLicencia(juegoId=juegoId, estado="DISPONIBLE") for _ in range(disponibles)])
        if estadoExtra:
            sesion.add_all([ClaveLicencia(juegoId=juegoId, estado=estadoExtra) for _ in range(cantidadExtra)])
        sesion.commit()

    return _crear


def generarToken(usuarioId: int = 1, rol: str = "CLIENTE", minutos: int = 30, clave: str | None = None) -> str:
    """Genera un JWT de prueba equivalente al emitido por MOD-01 (HU-07)."""
    from datetime import datetime, timedelta, timezone

    import jwt

    from app.core.configuracion import configuracion

    carga = {"sub": str(usuarioId), "rol": rol, "exp": datetime.now(timezone.utc) + timedelta(minutes=minutos)}
    return jwt.encode(carga, clave or configuracion.CLAVE_SECRETA, algorithm="HS256")


def encabezadoAuth(usuarioId: int = 1, **kwargs) -> dict:
    return {"Authorization": f"Bearer {generarToken(usuarioId, **kwargs)}"}


def configurarParametros(cliente, tasaIva: float | None = None, margenGanancia: float | None = None) -> None:
    """Actualiza los parámetros financieros de MOD-00 por sus endpoints (HU-03 / HU-04), como ADMIN."""
    admin = encabezadoAuth(1, rol="ADMIN")
    if tasaIva is not None:
        # El IVA es el primer impuesto sembrado por TT-02 (impuestoId = 1)
        respuesta = cliente.put("/api/v1/parametrizacion/impuestos/1", json={"tasaIva": tasaIva}, headers=admin)
        assert respuesta.status_code == 200, respuesta.json()
    if margenGanancia is not None:
        respuesta = cliente.put("/api/v1/parametrizacion/margenes/ganancia", json={"margenGanancia": margenGanancia},
                                headers=admin)
        assert respuesta.status_code == 200, respuesta.json()
