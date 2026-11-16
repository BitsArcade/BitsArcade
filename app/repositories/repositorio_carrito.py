from sqlalchemy.orm import Session

from app.domain.carrito import ESTADO_CARRITO_ACTIVO, Carrito, ItemCarrito


class RepositorioCarrito:
    """Capa Repository de MOD-04: acceso a datos del carrito de compras."""

    def obtener_carrito_activo(self, sesion: Session, usuario_id: int) -> Carrito | None:
        return (
            sesion.query(Carrito)
            .filter(Carrito.usuario_id == usuario_id, Carrito.estado == ESTADO_CARRITO_ACTIVO)
            .first()
        )

    def crear_carrito(self, sesion: Session, usuario_id: int) -> Carrito:
        carrito = Carrito(usuario_id=usuario_id, estado=ESTADO_CARRITO_ACTIVO)
        sesion.add(carrito)
        sesion.commit()
        sesion.refresh(carrito)
        return carrito

    def obtener_item_por_juego(self, sesion: Session, carrito_id: int, juego_id: int) -> ItemCarrito | None:
        return (
            sesion.query(ItemCarrito)
            .filter(ItemCarrito.carrito_id == carrito_id, ItemCarrito.juego_id == juego_id)
            .first()
        )

    def guardar_item(self, sesion: Session, carrito: Carrito, juego_id: int, cantidad: int) -> ItemCarrito:
        """Crea el ítem o acumula la cantidad si el juego ya estaba en el carrito."""
        item = self.obtener_item_por_juego(sesion, carrito.id, juego_id)
        if item is None:
            item = ItemCarrito(carrito_id=carrito.id, juego_id=juego_id, cantidad=cantidad)
            sesion.add(item)
        else:
            item.cantidad = cantidad
        sesion.commit()
        sesion.refresh(carrito)
        return item
