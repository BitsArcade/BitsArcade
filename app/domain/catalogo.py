from datetime import date
from typing import Optional

from pydantic import BaseModel
from sqlalchemy import Boolean, Column, Date, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.core.base_datos import Base
from app.core.respuestas import ErrorAplicacion

# =====================================================================
# 1. CONSTANTES Y REGLAS DE DOMINIO (MOD-02: Catálogo de Juegos)
# =====================================================================

ESTADO_PREVENTA = "PREVENTA"
ESTADO_ESTRENO = "ESTRENO"
ESTADO_ACTIVO = "ACTIVO"
ESTADO_INACTIVO = "INACTIVO"

# Estados que se consideran "publicados" en la tienda (HU-20).
ESTADOS_PUBLICADOS = (ESTADO_PREVENTA, ESTADO_ESTRENO, ESTADO_ACTIVO)

PLATAFORMAS_VALIDAS = ("PC", "CONSOLA")

TAMANO_PAGINA_POR_DEFECTO = 20
TAMANO_PAGINA_MAXIMO = 100


LONGITUD_MINIMA_BUSQUEDA = 2


def validar_texto_busqueda(texto: str | None) -> str:
    """HU-16: el texto de búsqueda debe tener al menos 2 caracteres (sin contar espacios extremos)."""
    texto_limpio = (texto or "").strip()
    if len(texto_limpio) < LONGITUD_MINIMA_BUSQUEDA:
        raise ErrorAplicacion(400, "El texto de búsqueda debe tener al menos 2 caracteres")
    return texto_limpio


def validar_plataforma(plataforma: str) -> str:
    """HU-17: valores válidos PC o CONSOLA (no distingue mayúsculas)."""
    valor = (plataforma or "").strip().upper()
    if valor not in PLATAFORMAS_VALIDAS:
        raise ErrorAplicacion(400, "Plataforma no válida. Use PC o CONSOLA")
    return valor


LIMITE_DESTACADOS_POR_DEFECTO = 10
LIMITE_DESTACADOS_MAXIMO = 20


def validar_limite_destacados(limite: int) -> None:
    """HU-19: limite entre 1 y 20."""
    if limite < 1 or limite > LIMITE_DESTACADOS_MAXIMO:
        raise ErrorAplicacion(400, f"limite debe estar entre 1 y {LIMITE_DESTACADOS_MAXIMO}")


def validar_paginacion(page: int, size: int) -> None:
    """HU-20: page >= 0 y size entre 1 y 100."""
    if size < 1 or size > TAMANO_PAGINA_MAXIMO:
        raise ErrorAplicacion(400, f"size debe estar entre 1 y {TAMANO_PAGINA_MAXIMO}")
    if page < 0:
        raise ErrorAplicacion(400, "page debe ser mayor o igual a 0")


# =====================================================================
# 2. ENTIDADES DE DOMINIO (Mapeo de tablas para SQLite)
# =====================================================================

class Juego(Base):
    """Videojuego del catálogo (HU-16 a HU-25)."""
    __tablename__ = "juegos"

    id = Column(Integer, primary_key=True, index=True)
    titulo = Column(String(150), nullable=False, index=True)
    descripcion = Column(Text, nullable=True)
    genero = Column(String(50), nullable=False, index=True)
    desarrollador = Column(String(100), nullable=True)
    fecha_lanzamiento = Column(Date, nullable=True)
    estado = Column(String(20), nullable=False, default=ESTADO_ACTIVO)
    # HU-19: marca editorial del propio catálogo (no depende de datos de ventas).
    destacado = Column(Boolean, nullable=False, default=False)
    # Costo de adquisición (C_A) en COP. Dato sensible: NUNCA se expone en respuestas públicas.
    costo_adquisicion = Column(Float, nullable=False, default=0.0)

    plataformas = relationship(
        "PlataformaJuego",
        back_populates="juego",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    @property
    def nombres_plataformas(self) -> list[str]:
        nombres = {p.plataforma for p in self.plataformas}
        return [p for p in PLATAFORMAS_VALIDAS if p in nombres] + sorted(nombres - set(PLATAFORMAS_VALIDAS))


class PlataformaJuego(Base):
    """Plataformas (PC / CONSOLA) en las que está disponible un juego."""
    __tablename__ = "juego_plataformas"

    id = Column(Integer, primary_key=True, index=True)
    juego_id = Column(Integer, ForeignKey("juegos.id"), nullable=False, index=True)
    plataforma = Column(String(20), nullable=False)

    juego = relationship("Juego", back_populates="plataformas")


def juego_a_item(juego: Juego) -> dict:
    """Representación pública resumida de un juego (sin C_A ni precio)."""
    return {
        "gameId": juego.id,
        "titulo": juego.titulo,
        "genero": juego.genero,
        "plataformas": juego.nombres_plataformas,
        "estado": juego.estado,
    }


def juego_a_ficha_tecnica(juego: Juego) -> dict:
    """HU-21: ficha técnica pública. NO incluye costo de adquisición, margen ni precio."""
    return {
        "gameId": juego.id,
        "titulo": juego.titulo,
        "descripcion": juego.descripcion,
        "genero": juego.genero,
        "plataformas": juego.nombres_plataformas,
        "desarrollador": juego.desarrollador,
        "fechaLanzamiento": juego.fecha_lanzamiento.isoformat() if juego.fecha_lanzamiento else None,
        "estado": juego.estado,
    }


MENSAJE_JUEGO_NO_EXISTE = "El juego indicado no existe"


# =====================================================================
# 3. ESQUEMAS DE SALIDA (Pydantic DTOs para Swagger)
# =====================================================================

class JuegoResumenSalida(BaseModel):
    gameId: int
    titulo: str
    genero: str
    plataformas: list[str]
    estado: str


class PaginaJuegosSalida(BaseModel):
    items: list[JuegoResumenSalida]
    page: int
    size: int
    total: int


class FichaTecnicaSalida(BaseModel):
    gameId: int
    titulo: str
    descripcion: Optional[str] = None
    genero: str
    plataformas: list[str]
    desarrollador: Optional[str] = None
    fechaLanzamiento: Optional[date] = None
    estado: str
