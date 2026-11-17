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


def validar_cantidad_agregar(cantidad: int) -> None:
    """HU-26: cantidad >= 1."""
    if cantidad is None or cantidad < 1:
        raise ErrorAplicacion(400, "cantidad debe ser mayor o igual a 1")


def validar_juego_vendible(contrato_juego: dict) -> None:
    """HU-26: el juego debe existir (COM-11) y no estar INACTIVO."""
    if not contrato_juego.get("exists") or contrato_juego.get("status") == ESTADO_JUEGO_INACTIVO:
        raise ErrorAplicacion(404, MENSAJE_JUEGO_NO_EXISTE)


def validar_limite_preventa(estado_juego: str, cantidad_en_carrito: int, licencias_en_ordenes: int) -> None:
    """
    RN-05: en PREVENTA el máximo es 1 licencia por usuario, considerando el carrito y las
    órdenes previas no canceladas del usuario.
    """
    if estado_juego == ESTADO_JUEGO_PREVENTA and cantidad_en_carrito + licencias_en_ordenes > MAXIMO_LICENCIAS_PREVENTA:
        raise ErrorAplicacion(409, MENSAJE_LIMITE_PREVENTA)


def validar_stock_suficiente(cantidad_solicitada: int, disponibles: int) -> None:
    """HU-26 / HU-29: la cantidad total del ítem no puede superar las keys disponibles (COM-12)."""
    if cantidad_solicitada > disponibles:
        raise ErrorAplicacion(409, MENSAJE_STOCK_INSUFICIENTE)


# =====================================================================
# 2. ENTIDADES DE DOMINIO (Mapeo de tablas para SQLite)
# =====================================================================

class Carrito(Base):
    """Carrito temporal de compras de un cliente (uno ACTIVO por usuario)."""
    __tablename__ = "carritos"

    id = Column(Integer, primary_key=True, index=True)
    usuario_id = Column(Integer, nullable=False, index=True)
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
    __tablename__ = "carrito_items"

    id = Column(Integer, primary_key=True, index=True)
    carrito_id = Column(Integer, ForeignKey("carritos.id"), nullable=False, index=True)
    juego_id = Column(Integer, nullable=False, index=True)
    cantidad = Column(Integer, nullable=False, default=1)

    carrito = relationship("Carrito", back_populates="items")


# =====================================================================
# 3. ESQUEMAS DE ENTRADA / SALIDA (Pydantic DTOs)
# =====================================================================

class AgregarItemEntrada(BaseModel):
    """Contrato de entrada de HU-26."""
    gameId: int
    cantidad: int = 1

    model_config = {"json_schema_extra": {"examples": [{"gameId": 101, "cantidad": 1}]}}


class ItemCarritoSalida(BaseModel):
    itemId: int
    gameId: int
    titulo: Optional[str] = None
    cantidad: int
    precioUnitario: float


class CarritoSalida(BaseModel):
    carritoId: int
    items: list[ItemCarritoSalida]
    subtotal: float
    moneda: str
