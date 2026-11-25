from sqlalchemy.orm import Session

from app.domain.carrito import ESTADO_CARRITO_ACTIVO, Carrito, ItemCarrito


class RepositorioCarrito:
    """Capa Repository del Carrito de Compras (MOD-04)."""

    def obtener_carrito_activo(self, sesion: Session, usuario_id: int) -> Carrito | None:
        return (
            sesion.query(Carrito)
            .filter(Carrito.usuario_id == usuario_id, Carrito.estado == ESTADO_CARRITO_ACTIVO)
            .first()
        )

    def obtener_o_crear_carrito(self, sesion: Session, usuario_id: int) -> Carrito:
        carrito = self.obtener_carrito_activo(sesion, usuario_id)
        if carrito is None:
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

    def obtener_item_de_usuario(self, sesion: Session, item_id: int, usuario_id: int) -> ItemCarrito | None:
        return (
            sesion.query(ItemCarrito)
            .join(Carrito, Carrito.id == ItemCarrito.carrito_id)
            .filter(
                ItemCarrito.id == item_id,
                Carrito.usuario_id == usuario_id,
                Carrito.estado == ESTADO_CARRITO_ACTIVO,
            )
            .first()
        )

    def agregar_item(self, sesion: Session, carrito_id: int, juego_id: int, cantidad: int) -> ItemCarrito:
        item = ItemCarrito(carrito_id=carrito_id, juego_id=juego_id, cantidad=cantidad)
        sesion.add(item)
        sesion.commit()
        sesion.refresh(item)
        return item

    def actualizar_cantidad_item(self, sesion: Session, item: ItemCarrito, cantidad: int) -> ItemCarrito:
        item.cantidad = cantidad
        sesion.commit()
        sesion.refresh(item)
        return item

    def eliminar_item(self, sesion: Session, item: ItemCarrito) -> None:
        sesion.delete(item)
        sesion.commit()

    def vaciar_carrito(self, sesion: Session, carrito: Carrito) -> Carrito:
        for item in list(carrito.items):
            sesion.delete(item)
        sesion.commit()
        sesion.refresh(carrito)
        return carrito