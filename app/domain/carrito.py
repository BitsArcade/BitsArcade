from typing import Optional

from pydantic import BaseModel
from sqlalchemy import Column, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from app.core.base_datos import Base
from app.core.respuestas import ErrorAplicacion

# =====================================================================
# 1. CONSTANTES Y REGLAS DE DOMINIO (MOD-04: Carrito de Compras)
# =====================================================================

ESTADO_CARRITO_ACTIVO = "ACTIVO"

ESTADO_JUEGO_PREVENTA = "PREVENTA"
ESTADO_JUEGO_INACTIVO = "INACTIVO"

MAXIMO_LICENCIAS_PREVENTA = 1

MENSAJE_JUEGO_NO_EXISTE = "El juego indicado no existe"
MENSAJE_STOCK_INSUFICIENTE = "Stock insuficiente para la cantidad solicitada"
MENSAJE_LIMITE_PREVENTA = "Solo se permite adquirir una licencia por título en preventa"
MENSAJE_ITEM_NO_EXISTE = "El ítem no existe en tu carrito"


def validarCantidadAgregar(cantidad: int) -> None:
    """HU-26: cantidad >= 1."""
    if cantidad is None or cantidad < 1:
        raise ErrorAplicacion(400, "cantidad debe ser mayor o igual a 1")


def validarJuegoVendible(contratoJuego: dict) -> None:
    """HU-26: el juego debe existir (COM-11) y no estar INACTIVO."""
    if not contratoJuego.get("existe") or contratoJuego.get("estado") == ESTADO_JUEGO_INACTIVO:
        raise ErrorAplicacion(404, MENSAJE_JUEGO_NO_EXISTE)


def validarLimitePreventa(estadoJuego: str, cantidadEnCarrito: int, licenciasEnOrdenes: int) -> None:
    """
    RN-05: en PREVENTA el máximo es 1 licencia por usuario, considerando el carrito y las
    órdenes previas no canceladas del usuario.
    """
    if estadoJuego == ESTADO_JUEGO_PREVENTA and cantidadEnCarrito + licenciasEnOrdenes > MAXIMO_LICENCIAS_PREVENTA:
        raise ErrorAplicacion(409, MENSAJE_LIMITE_PREVENTA)


def validarStockSuficiente(cantidadSolicitada: int, disponibles: int) -> None:
    """HU-26 / HU-29: la cantidad total del ítem no puede superar las claves disponibles (COM-12)."""
    if cantidadSolicitada > disponibles:
        raise ErrorAplicacion(409, MENSAJE_STOCK_INSUFICIENTE)


# ---------------------------------------------------------------------
# HU-29: Descuento progresivo por volumen (RN-08). Configuración estática de Carrito.Domain.
# ---------------------------------------------------------------------

ESTADO_JUEGO_ESTRENO = "ESTRENO"
UMBRAL_DESCUENTO_VOLUMEN = 3          # cantidad mínima para aplicar RN-08
PORCENTAJE_DESCUENTO_VOLUMEN = 0.10   # 10 % por unidad
# RN-07: no se aplican descuentos a juegos en PREVENTA o ESTRENO (no existen cupones en el alcance).
ESTADOS_SIN_DESCUENTO = (ESTADO_JUEGO_PREVENTA, ESTADO_JUEGO_ESTRENO)


def validarCantidadActualizar(cantidad: int) -> None:
    """HU-29: cantidad >= 1; para retirar el ítem se usa DELETE (HU-28)."""
    if cantidad is None or cantidad < 1:
        raise ErrorAplicacion(400, "cantidad debe ser mayor o igual a 1. Use DELETE para retirar el ítem")


def calcularDesglose(precioUnitario: float, precioPiso: float, cantidad: int, estadoJuego: str) -> dict:
    """
    HU-29: desglose monetario de un ítem.
    - RN-07: PREVENTA / ESTRENO sin descuentos.
    - RN-08: si el juego está ACTIVO y cantidad >= umbral, descuento del 10 % por unidad.
    - RN-02: ningún precio unitario con descuento puede ser menor que precioMinimo.
    """
    descuentoUnitario = 0.0
    if estadoJuego not in ESTADOS_SIN_DESCUENTO and cantidad >= UMBRAL_DESCUENTO_VOLUMEN:
        descuentoUnitario = precioUnitario * PORCENTAJE_DESCUENTO_VOLUMEN
        descuentoUnitario = min(descuentoUnitario, max(precioUnitario - precioPiso, 0.0))
    descuentoTotal = round(descuentoUnitario * cantidad, 2)
    return {
        "precioUnitario": round(precioUnitario, 2),
        "descuentoVolumen": descuentoTotal,
        "subtotal": round(precioUnitario * cantidad - descuentoTotal, 2),
    }


# =====================================================================
# 2. ENTIDADES DE DOMINIO (Mapeo de tablas para SQLite)
# =====================================================================

class Carrito(Base):
    """Carrito temporal de compras de un cliente (uno ACTIVO por usuario)."""
    __tablename__ = "carritos"

    id = Column(Integer, primary_key=True, index=True)
    usuarioId = Column(Integer, nullable=False, index=True)
    estado = Column(String(20), nullable=False, default=ESTADO_CARRITO_ACTIVO)

    items = relationship(
        "ItemCarrito",
        back_populates="carrito",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="ItemCarrito.id",
    )


class ItemCarrito(Base):
    """
    Ítem del carrito. No almacena el precio: los precios vigentes se obtienen siempre del
    Catálogo vía COM-11 (MOD-04 no recalcula RN-01).
    """
    __tablename__ = "items_carrito"

    id = Column(Integer, primary_key=True, index=True)
    carritoId = Column(Integer, ForeignKey("carritos.id"), nullable=False, index=True)
    juegoId = Column(Integer, nullable=False, index=True)
    cantidad = Column(Integer, nullable=False, default=1)

    carrito = relationship("Carrito", back_populates="items")


# =====================================================================
# 3. ESQUEMAS DE ENTRADA / SALIDA (Pydantic DTOs)
# =====================================================================

class AgregarItemEntrada(BaseModel):
    """Contrato de entrada de HU-26."""
    juegoId: int
    cantidad: int = 1

    model_config = {"json_schema_extra": {"examples": [{"juegoId": 101, "cantidad": 1}]}}


class ItemCarritoSalida(BaseModel):
    itemId: int
    juegoId: int
    titulo: Optional[str] = None
    cantidad: int
    precioUnitario: float


class CarritoSalida(BaseModel):
    carritoId: int
    items: list[ItemCarritoSalida]
    subtotal: float
    moneda: str


class ActualizarCantidadEntrada(BaseModel):
    """Contrato de entrada de HU-29."""
    cantidad: int

    model_config = {"json_schema_extra": {"examples": [{"cantidad": 3}]}}


class DesgloseItemSalida(BaseModel):
    itemId: int
    juegoId: int
    cantidad: int
    precioUnitario: float
    descuentoVolumen: float
    subtotal: float
    moneda: str
