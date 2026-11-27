from sqlalchemy.orm import Session

from app.domain.carrito import ESTADO_CARRITO_ACTIVO, Carrito, ItemCarrito


class RepositorioCarrito:
    """Capa Repository de MOD-04: acceso a datos del carrito de compras."""

    def obtenerCarritoActivo(self, sesion: Session, usuarioId: int) -> Carrito | None:
        return (
            sesion.query(Carrito)
            .filter(Carrito.usuarioId == usuarioId, Carrito.estado == ESTADO_CARRITO_ACTIVO)
            .first()
        )

    def crearCarrito(self, sesion: Session, usuarioId: int) -> Carrito:
        carrito = Carrito(usuarioId=usuarioId, estado=ESTADO_CARRITO_ACTIVO)
        sesion.add(carrito)
        sesion.commit()
        sesion.refresh(carrito)
        return carrito

    def obtenerItemPorJuego(self, sesion: Session, carritoId: int, juegoId: int) -> ItemCarrito | None:
        return (
            sesion.query(ItemCarrito)
            .filter(ItemCarrito.carritoId == carritoId, ItemCarrito.juegoId == juegoId)
            .first()
        )

    def guardarItem(self, sesion: Session, carrito: Carrito, juegoId: int, cantidad: int) -> ItemCarrito:
        """Crea el ítem o acumula la cantidad si el juego ya estaba en el carrito."""
        item = self.obtenerItemPorJuego(sesion, carrito.id, juegoId)
        if item is None:
            item = ItemCarrito(carritoId=carrito.id, juegoId=juegoId, cantidad=cantidad)
            sesion.add(item)
        else:
            item.cantidad = cantidad
        sesion.commit()
        sesion.refresh(carrito)
        return item

    def obtenerItemDeUsuario(self, sesion: Session, itemId: int, usuarioId: int) -> ItemCarrito | None:
        """HU-28 / HU-29: ítem solo si pertenece al carrito ACTIVO del usuario."""
        return (
            sesion.query(ItemCarrito)
            .join(Carrito, ItemCarrito.carritoId == Carrito.id)
            .filter(
                ItemCarrito.id == itemId,
                Carrito.usuarioId == usuarioId,
                Carrito.estado == ESTADO_CARRITO_ACTIVO,
            )
            .first()
        )

    def eliminarItem(self, sesion: Session, item: ItemCarrito) -> Carrito:
        carrito = item.carrito
        sesion.delete(item)
        sesion.commit()
        sesion.refresh(carrito)
        return carrito

    def actualizarCantidad(self, sesion: Session, item: ItemCarrito, cantidad: int) -> ItemCarrito:
        item.cantidad = cantidad
        sesion.commit()
        sesion.refresh(item)
        return item

    def vaciarCarrito(self, sesion: Session, carrito: Carrito) -> Carrito:
        """HU-30: Elimina todos los ítems asociados al carrito activo del usuario."""
        sesion.query(ItemCarrito).filter(ItemCarrito.carritoId == carrito.id).delete()
        sesion.commit()
        sesion.refresh(carrito)
        return carrito

    # Compatibilidad temporal: nombre anterior usado por MOD-04 (órdenes, HU-31) mientras migra.
    def obtener_carrito_activo(self, sesion: Session, usuario_id: int) -> Carrito | None:
        return self.obtenerCarritoActivo(sesion, usuario_id)
