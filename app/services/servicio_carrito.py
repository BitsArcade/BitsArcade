from sqlalchemy.orm import Session

from app.core.configuracion import configuracion
from app.core.respuestas import ErrorAplicacion, manejarErroresBd, respuesta
from app.core.seguridad import UsuarioAutenticado
from app.domain.carrito import (
    MENSAJE_ITEM_NO_EXISTE,
    AgregarItemEntrada,
    ActualizarCantidadEntrada,
    Carrito,
    calcularDesglose,
    validarCantidadActualizar,
    validarCantidadAgregar,
    validarJuegoVendible,
    validarLimitePreventa,
    validarStockSuficiente,
)
from app.repositories.repositorio_carrito import RepositorioCarrito
from app.services.cliente_inventario import (
    MENSAJE_COM12_NO_DISPONIBLE,
    ClienteInventario,
    InventarioNoDisponible,
)
from app.services.servicio_catalogo import ServicioCatalogo

MENSAJE_COM11_NO_DISPONIBLE = "No fue posible obtener los precios vigentes"


class ClienteCatalogo:
    """
    Adaptador del contrato COM-11 (proveedor MOD-02): {juegoId, existe, titulo, estado, precioFinal, precioMinimo}.
    MOD-04 consume el precio calculado por el Catálogo y NO recalcula RN-01.
    """

    def __init__(self, servicioCatalogo: ServicioCatalogo | None = None):
        self.servicioCatalogo = servicioCatalogo or ServicioCatalogo()

    def obtenerJuego(self, sesion: Session, juegoId: int) -> dict:
        try:
            return self.servicioCatalogo.obtenerContratoCom11(sesion, juegoId)
        except ErrorAplicacion as error:
            if error.codigoHttp == 503:
                raise ErrorAplicacion(503, MENSAJE_COM11_NO_DISPONIBLE) from error
            raise
        except Exception as error:
            raise ErrorAplicacion(503, MENSAJE_COM11_NO_DISPONIBLE) from error


class ClienteOrdenes:
    """Consulta de licencias en órdenes previas NO canceladas del usuario (RN-05), en MOD-04."""

    def contarLicenciasNoCanceladas(self, sesion: Session, usuarioId: int, juegoId: int) -> int:
        """Suma las licencias del juego en las órdenes del usuario que no están CANCELADA (solo lectura)."""
        from sqlalchemy import func

        from app.domain.ordenes import ESTADO_ORDEN_CANCELADA, DetalleOrden, OrdenCompra

        total = (
            sesion.query(func.coalesce(func.sum(DetalleOrden.cantidad), 0))
            .join(OrdenCompra, OrdenCompra.id == DetalleOrden.ordenId)
            .filter(
                OrdenCompra.usuarioId == usuarioId,
                OrdenCompra.estado != ESTADO_ORDEN_CANCELADA,
                DetalleOrden.juegoId == juegoId,
            )
            .scalar()
        )
        return int(total or 0)


class ServicioCarrito:
    """Capa Application / Service de MOD-04: casos de uso del carrito (HU-26 a HU-30)."""

    def __init__(self):
        self.repositorio = RepositorioCarrito()
        self.clienteCatalogo = ClienteCatalogo()
        self.clienteInventario = ClienteInventario()
        self.clienteOrdenes = ClienteOrdenes()

    # --- Utilidades internas ---

    def _obtenerOCrearCarrito(self, sesion: Session, usuarioId: int) -> Carrito:
        carrito = self.repositorio.obtenerCarritoActivo(sesion, usuarioId)
        return carrito or self.repositorio.crearCarrito(sesion, usuarioId)

    def _contarDisponibles(self, sesion: Session, juegoId: int) -> int:
        try:
            return self.clienteInventario.contarDisponibles(sesion, juegoId)
        except InventarioNoDisponible as error:
            raise ErrorAplicacion(503, MENSAJE_COM12_NO_DISPONIBLE) from error

    def _validarReglasCantidad(
        self, sesion: Session, usuarioId: int, juegoId: int, estadoJuego: str, cantidadTotal: int
    ) -> None:
        """RN-05 (preventa) y stock suficiente vía COM-12 (solo consulta, la reserva es HU-31)."""
        licenciasOrdenes = self.clienteOrdenes.contarLicenciasNoCanceladas(sesion, usuarioId, juegoId)
        validarLimitePreventa(estadoJuego, cantidadTotal, licenciasOrdenes)
        validarStockSuficiente(cantidadTotal, self._contarDisponibles(sesion, juegoId))

    def _armarCarrito(self, sesion: Session, carrito: Carrito) -> dict:
        """Lista los ítems con precios vigentes de COM-11 y el subtotal preliminar (sin descuentos)."""
        items = []
        subtotal = 0.0
        for item in carrito.items:
            contrato = self.clienteCatalogo.obtenerJuego(sesion, item.juegoId)
            if not contrato.get("existe"):
                continue
            precioUnitario = float(contrato["precioFinal"])
            subtotal += precioUnitario * item.cantidad
            items.append(
                {
                    "itemId": item.id,
                    "juegoId": item.juegoId,
                    "titulo": contrato.get("titulo"),
                    "cantidad": item.cantidad,
                    "precioUnitario": precioUnitario,
                }
            )
        return {
            "carritoId": carrito.id,
            "items": items,
            "subtotal": round(subtotal, 2),
            "moneda": configuracion.MONEDA_BASE,
        }

    # --- HU-26: Agregar juego al carrito ---

    def agregarItem(self, sesion: Session, usuario: UsuarioAutenticado, datos: AgregarItemEntrada) -> dict:
        """HU-26: valida juego (COM-11), RN-05 y stock (COM-12); guarda o acumula el ítem."""
        validarCantidadAgregar(datos.cantidad)
        contrato = self.clienteCatalogo.obtenerJuego(sesion, datos.juegoId)
        validarJuegoVendible(contrato)

        mensajeErrorBd = "No fue posible agregar el juego al carrito"
        with manejarErroresBd(mensajeErrorBd):
            carrito = self._obtenerOCrearCarrito(sesion, usuario.id)
            existente = self.repositorio.obtenerItemPorJuego(sesion, carrito.id, datos.juegoId)
        cantidadTotal = (existente.cantidad if existente else 0) + datos.cantidad

        self._validarReglasCantidad(sesion, usuario.id, datos.juegoId, contrato["estado"], cantidadTotal)

        with manejarErroresBd(mensajeErrorBd):
            self.repositorio.guardarItem(sesion, carrito, datos.juegoId, cantidadTotal)
        return respuesta("Juego agregado al carrito", self._armarCarrito(sesion, carrito))

    # --- HU-27: Consultar ítems del carrito activo ---

    def consultarCarrito(self, sesion: Session, usuario: UsuarioAutenticado) -> dict:
        """HU-27: ítems con precios vigentes de COM-11 y subtotal preliminar sin descuentos (HU-29)."""
        with manejarErroresBd("No fue posible consultar el carrito"):
            carrito = self._obtenerOCrearCarrito(sesion, usuario.id)
        datos = self._armarCarrito(sesion, carrito)
        if not datos["items"]:
            return respuesta("El carrito está vacío", datos, False)
        return respuesta("Consulta de carrito exitosa", datos)

    # --- HU-28: Eliminar ítem del carrito ---

    def eliminarItem(self, sesion: Session, usuario: UsuarioAutenticado, itemId: int) -> dict:
        """HU-28: solo se eliminan ítems del propio carrito; retorna el carrito recalculado."""
        with manejarErroresBd("No fue posible eliminar el ítem"):
            item = self.repositorio.obtenerItemDeUsuario(sesion, itemId, usuario.id)
            if item is None:
                raise ErrorAplicacion(404, MENSAJE_ITEM_NO_EXISTE)
            carrito = self.repositorio.eliminarItem(sesion, item)
        return respuesta("Ítem eliminado del carrito", self._armarCarrito(sesion, carrito))

    # --- HU-29: Recalcular subtotales con promociones y volumen ---

    def actualizarCantidad(
        self, sesion: Session, usuario: UsuarioAutenticado, itemId: int, datos: ActualizarCantidadEntrada
    ) -> dict:
        """HU-29: cambia la cantidad y retorna el desglose con RN-07, RN-05, RN-08 y RN-02."""
        validarCantidadActualizar(datos.cantidad)
        mensajeErrorBd = "No fue posible recalcular los subtotales"
        with manejarErroresBd(mensajeErrorBd):
            item = self.repositorio.obtenerItemDeUsuario(sesion, itemId, usuario.id)
        if item is None:
            raise ErrorAplicacion(404, MENSAJE_ITEM_NO_EXISTE)

        contrato = self.clienteCatalogo.obtenerJuego(sesion, item.juegoId)
        validarJuegoVendible(contrato)
        self._validarReglasCantidad(sesion, usuario.id, item.juegoId, contrato["estado"], datos.cantidad)

        with manejarErroresBd(mensajeErrorBd):
            item = self.repositorio.actualizarCantidad(sesion, item, datos.cantidad)
        desglose = calcularDesglose(
            float(contrato["precioFinal"]), float(contrato["precioMinimo"]), item.cantidad, contrato["estado"]
        )
        return respuesta(
            "Subtotales recalculados",
            {
                "itemId": item.id,
                "juegoId": item.juegoId,
                "cantidad": item.cantidad,
                **desglose,
                "moneda": configuracion.MONEDA_BASE,
            },
        )

    # --- HU-30: Vaciar carrito de compras (código ya fusionado en Development, con la convención) ---

    def vaciarCarrito(self, sesion: Session, usuario: UsuarioAutenticado) -> dict:
        """HU-30 (FUN-04.1.5 / PRO-04.1.5): Elimina todos los ítems del carrito activo del usuario."""
        with manejarErroresBd("No fue posible vaciar el carrito de compras"):
            carrito = self._obtenerOCrearCarrito(sesion, usuario.id)
            carrito = self.repositorio.vaciarCarrito(sesion, carrito)
        return respuesta("Carrito vaciado exitosamente", self._armarCarrito(sesion, carrito))
