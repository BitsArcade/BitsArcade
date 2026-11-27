from datetime import date
from typing import Optional

from pydantic import BaseModel
from sqlalchemy import Boolean, Column, Date, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.core.base_datos import Base
from app.core.respuestas import ErrorAplicacion


def porcentajeADecimal(porcentaje: float) -> float:
    """Convierte un porcentaje (19) a decimal (0.19). Los parámetros de COM-01 llegan de 0 a 100."""
    return float(porcentaje) / 100.0

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


def validarTextoBusqueda(texto: str | None) -> str:
    """HU-16: el texto de búsqueda debe tener al menos 2 caracteres (sin contar espacios extremos)."""
    textoLimpio = (texto or "").strip()
    if len(textoLimpio) < LONGITUD_MINIMA_BUSQUEDA:
        raise ErrorAplicacion(400, "El texto de búsqueda debe tener al menos 2 caracteres")
    return textoLimpio


def validarPlataforma(plataforma: str) -> str:
    """HU-17: valores válidos PC o CONSOLA (no distingue mayúsculas)."""
    valor = (plataforma or "").strip().upper()
    if valor not in PLATAFORMAS_VALIDAS:
        raise ErrorAplicacion(400, "Plataforma no válida. Use PC o CONSOLA")
    return valor


LIMITE_DESTACADOS_POR_DEFECTO = 10
LIMITE_DESTACADOS_MAXIMO = 20


def validarLimiteDestacados(limite: int) -> None:
    """HU-19: limite entre 1 y 20."""
    if limite < 1 or limite > LIMITE_DESTACADOS_MAXIMO:
        raise ErrorAplicacion(400, f"limite debe estar entre 1 y {LIMITE_DESTACADOS_MAXIMO}")


def validarPaginacion(pagina: int, tamano: int) -> None:
    """HU-20: pagina >= 0 y tamano entre 1 y 100."""
    if tamano < 1 or tamano > TAMANO_PAGINA_MAXIMO:
        raise ErrorAplicacion(400, f"tamano debe estar entre 1 y {TAMANO_PAGINA_MAXIMO}")
    if pagina < 0:
        raise ErrorAplicacion(400, "pagina debe ser mayor o igual a 0")


# ---------------------------------------------------------------------
# HU-24: Política de precios. La fórmula vive ÚNICAMENTE en Catalogo.Domain;
# MOD-04 (Carrito) la consume vía COM-11 y no la recalcula.
# ---------------------------------------------------------------------

MENSAJE_VIOLACION_RN02 = "El precio calculado viola la política de margen mínimo (RN-02)"


def calcularPrecioPiso(costoAdquisicion: float, tasaIva: float) -> float:
    """RN-02: precioMinimo = costoAdquisicion × (1 + tasaIva/100). tasaIva en porcentaje (19)."""
    return round(costoAdquisicion * (1 + porcentajeADecimal(tasaIva)), 2)


def calcularPrecioFinal(costoAdquisicion: float, margenGanancia: float, tasaIva: float) -> float:
    """
    RN-01: precioFinal = costoAdquisicion × (1 + margenGanancia/100) × (1 + tasaIva/100).
    RN-02: precioFinal >= costoAdquisicion × (1 + tasaIva/100); si se viola se responde 409.
    """
    precioVenta = costoAdquisicion * (1 + porcentajeADecimal(margenGanancia)) * (1 + porcentajeADecimal(tasaIva))
    precioPiso = costoAdquisicion * (1 + porcentajeADecimal(tasaIva))
    if precioVenta + 1e-9 < precioPiso:
        raise ErrorAplicacion(409, MENSAJE_VIOLACION_RN02)
    return round(precioVenta, 2)


def validarRangoPrecios(precioMin: float | None, precioMax: float | None) -> None:
    """HU-18: precios no negativos y precioMin <= precioMax."""
    if (precioMin is not None and precioMin < 0) or (precioMax is not None and precioMax < 0):
        raise ErrorAplicacion(400, "Los precios no pueden ser negativos")
    if precioMin is not None and precioMax is not None and precioMin > precioMax:
        raise ErrorAplicacion(400, "precioMin no puede ser mayor que precioMax")


def convertirRangoPrecioACosto(
    precioMin: float | None, precioMax: float | None, margenGanancia: float, tasaIva: float
) -> tuple[float | None, float | None]:
    """
    HU-18: convierte el rango de precio final (RN-01) a rango de costo base:
    costoAdquisicion entre precioMin/((1 + margenGanancia/100)(1 + tasaIva/100)) y precioMax/(...).
    Se aplica una tolerancia mínima para no excluir por redondeo de punto flotante.
    """
    factor = (1 + porcentajeADecimal(margenGanancia)) * (1 + porcentajeADecimal(tasaIva))
    tolerancia = 1e-6
    costoMin = None if precioMin is None else precioMin / factor - tolerancia
    costoMax = None if precioMax is None else precioMax / factor + tolerancia
    return costoMin, costoMax


STOCK_DISPONIBLE = "DISPONIBLE"
STOCK_AGOTADO = "AGOTADO"


def determinarEstadoStock(disponibles: int) -> str:
    """HU-25: DISPONIBLE si hay al menos una clave disponible; AGOTADO en caso contrario."""
    return STOCK_DISPONIBLE if disponibles > 0 else STOCK_AGOTADO


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
    fechaLanzamiento = Column(Date, nullable=True)
    estado = Column(String(20), nullable=False, default=ESTADO_ACTIVO)
    # HU-19: marca editorial del propio catálogo (no depende de datos de ventas).
    destacado = Column(Boolean, nullable=False, default=False)
    # Costo de adquisición (C_A) en COP. Dato sensible: NUNCA se expone en respuestas públicas.
    costoAdquisicion = Column(Float, nullable=False, default=0.0)

    plataformas = relationship(
        "PlataformaJuego",
        back_populates="juego",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    @property
    def nombresPlataformas(self) -> list[str]:
        nombres = {p.plataforma for p in self.plataformas}
        return [p for p in PLATAFORMAS_VALIDAS if p in nombres] + sorted(nombres - set(PLATAFORMAS_VALIDAS))


class PlataformaJuego(Base):
    """Plataformas (PC / CONSOLA) en las que está disponible un juego."""
    __tablename__ = "plataformas_juego"

    id = Column(Integer, primary_key=True, index=True)
    juegoId = Column(Integer, ForeignKey("juegos.id"), nullable=False, index=True)
    plataforma = Column(String(20), nullable=False)

    juego = relationship("Juego", back_populates="plataformas")


REQUISITO_MINIMO = "MINIMO"
REQUISITO_RECOMENDADO = "RECOMENDADO"


class RequisitoSistema(Base):
    """HU-22: requisitos de sistema (mínimos / recomendados) de un juego."""
    __tablename__ = "requisitos_juego"

    id = Column(Integer, primary_key=True, index=True)
    juegoId = Column(Integer, ForeignKey("juegos.id"), nullable=False, index=True)
    tipo = Column(String(20), nullable=False)  # MINIMO | RECOMENDADO
    sistemaOperativo = Column(String(100), nullable=True)
    procesador = Column(String(100), nullable=True)
    memoria = Column(String(50), nullable=True)
    grafica = Column(String(100), nullable=True)
    almacenamiento = Column(String(50), nullable=True)


def _requisitoADict(requisito: RequisitoSistema | None) -> dict | None:
    if requisito is None:
        return None
    return {
        "sistemaOperativo": requisito.sistemaOperativo,
        "procesador": requisito.procesador,
        "memoria": requisito.memoria,
        "grafica": requisito.grafica,
        "almacenamiento": requisito.almacenamiento,
    }


def formatearRequisitos(requisitos: list[RequisitoSistema]) -> dict | None:
    """HU-22: agrupa los requisitos en {minimos, recomendados}; None si no hay registros."""
    if not requisitos:
        return None
    porTipo = {r.tipo.upper(): r for r in requisitos}
    return {
        "minimos": _requisitoADict(porTipo.get(REQUISITO_MINIMO)),
        "recomendados": _requisitoADict(porTipo.get(REQUISITO_RECOMENDADO)),
    }


MULTIMEDIA_IMAGEN = "IMAGEN"
MULTIMEDIA_VIDEO = "VIDEO"


class MultimediaJuego(Base):
    """HU-23: URLs almacenadas de imágenes y videos (trailers) de un juego."""
    __tablename__ = "multimedia_juego"

    id = Column(Integer, primary_key=True, index=True)
    juegoId = Column(Integer, ForeignKey("juegos.id"), nullable=False, index=True)
    tipo = Column(String(10), nullable=False)  # IMAGEN | VIDEO
    url = Column(String(500), nullable=False)
    orden = Column(Integer, nullable=False, default=0)


def agruparMultimedia(recursos: list[MultimediaJuego]) -> dict:
    """HU-23: agrupa las URLs almacenadas en {imagenes, videos} respetando el orden."""
    ordenados = sorted(recursos, key=lambda r: (r.orden or 0, r.id or 0))
    return {
        "imagenes": [r.url for r in ordenados if r.tipo.upper() == MULTIMEDIA_IMAGEN],
        "videos": [r.url for r in ordenados if r.tipo.upper() == MULTIMEDIA_VIDEO],
    }


def juegoAItem(juego: Juego) -> dict:
    """Representación pública resumida de un juego (sin C_A ni precio)."""
    return {
        "juegoId": juego.id,
        "titulo": juego.titulo,
        "genero": juego.genero,
        "plataformas": juego.nombresPlataformas,
        "estado": juego.estado,
    }


def juegoAFichaTecnica(juego: Juego) -> dict:
    """HU-21: ficha técnica pública. NO incluye costo de adquisición, margen ni precio."""
    return {
        "juegoId": juego.id,
        "titulo": juego.titulo,
        "descripcion": juego.descripcion,
        "genero": juego.genero,
        "plataformas": juego.nombresPlataformas,
        "desarrollador": juego.desarrollador,
        "fechaLanzamiento": juego.fechaLanzamiento.isoformat() if juego.fechaLanzamiento else None,
        "estado": juego.estado,
    }


MENSAJE_JUEGO_NO_EXISTE = "El juego indicado no existe"


# =====================================================================
# 3. ESQUEMAS DE SALIDA (Pydantic DTOs para Swagger)
# =====================================================================

class JuegoResumenSalida(BaseModel):
    juegoId: int
    titulo: str
    genero: str
    plataformas: list[str]
    estado: str


class JuegoConPrecioSalida(JuegoResumenSalida):
    precioFinal: float
    moneda: str


class PaginaJuegosConPrecioSalida(BaseModel):
    items: list[JuegoConPrecioSalida]
    pagina: int
    tamano: int
    total: int


class PaginaJuegosSalida(BaseModel):
    items: list[JuegoResumenSalida]
    pagina: int
    tamano: int
    total: int


class FichaTecnicaSalida(BaseModel):
    juegoId: int
    titulo: str
    descripcion: Optional[str] = None
    genero: str
    plataformas: list[str]
    desarrollador: Optional[str] = None
    fechaLanzamiento: Optional[date] = None
    estado: str


class EspecificacionSalida(BaseModel):
    sistemaOperativo: Optional[str] = None
    procesador: Optional[str] = None
    memoria: Optional[str] = None
    grafica: Optional[str] = None
    almacenamiento: Optional[str] = None


class RequisitosSalida(BaseModel):
    minimos: Optional[EspecificacionSalida] = None
    recomendados: Optional[EspecificacionSalida] = None


class MultimediaSalida(BaseModel):
    imagenes: list[str]
    videos: list[str]


class PrecioSalida(BaseModel):
    juegoId: int
    moneda: str
    tasaIva: float
    precioFinal: float


class ContratoCom11Salida(BaseModel):
    """COM-11 (proveedor MOD-02 → consumidor MOD-04)."""
    juegoId: int
    existe: bool
    titulo: Optional[str] = None
    estado: Optional[str] = None
    precioFinal: Optional[float] = None
    precioMinimo: Optional[float] = None


class StockSalida(BaseModel):
    juegoId: int
    estadoStock: str
