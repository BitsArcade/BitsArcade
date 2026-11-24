from sqlalchemy.orm import Session

from app.core.configuracion import settings
from app.core.respuestas import ErrorAplicacion, manejar_errores_bd, respuesta
from app.core.seguridad import UsuarioAutenticado
from app.domain.carrito import (
    MENSAJE_ITEM_NO_EXISTE,
    AgregarItemEntrada,
    ActualizarCantidadEntrada,
    Carrito,
    calcular_desglose,
    validar_cantidad_actualizar,
    validar_cantidad_agregar,
    validar_juego_vendible,
    validar_limite_preventa,
    validar_stock_suficiente,
)
from app.repositories.repositorio_carrito import RepositorioCarrito
from app.repositories.repositorio_orden import RepositorioOrden
from app.services.cliente_inventario import (
    MENSAJE_COM12_NO_DISPONIBLE,
    ClienteInventario,
    InventarioNoDisponible,
)
from app.services.servicio_catalogo import ServicioCatalogo

MENSAJE_COM11_NO_DISPONIBLE = "No fue posible obtener los precios vigentes"


class ClienteCatalogo:
    """
    Adaptador del contrato COM-11 (proveedor MOD-02): {existe, titulo, estado, precioFinal, precioPiso}.
    """

    def __init__(self, servicio_catalogo: ServicioCatalogo | None = None):
        self.servicio_catalogo = servicio_catalogo or ServicioCatalogo()

    def obtener_juego(self, sesion: Session, juego_id: int) -> dict:
        try:
            return self.servicio_catalogo.obtener_contrato_com11(sesion, juego_id)
        except ErrorAplicacion as error:
            if error.status_code == 503:
                raise ErrorAplicacion(503, MENSAJE_COM11_NO_DISPONIBLE) from error
            raise
        except Exception as error:
            raise ErrorAplicacion(503, MENSAJE_COM11_NO_DISPONIBLE) from error


class ClienteOrdenes:
    """Consulta de licencias en órdenes previas NO canceladas del usuario (RN-05)."""

    def __init__(self):
        self.repo_orden = RepositorioOrden()

    def contar_licencias_no_canceladas(self, sesion: Session, usuario_id: int, juego_id: int) -> int:
        return self.repo_orden.contar_licencias_no_canceladas(sesion, usuario_id, juego_id)


class ServicioCarrito:
    """Capa Application / Service de MOD-04: casos de uso del carrito (HU-26 a HU-30)."""

    def __init__(self):
        self.repositorio = RepositorioCarrito()
        self.cliente_catalogo = ClienteCatalogo()
        self.cliente_inventario = ClienteInventario()
        self.cliente_ordenes = ClienteOrdenes()

    def _obtener_o_crear_carrito(self, sesion: Session, usuario_id: int) -> Carrito:
        carrito = self.repositorio.obtener_carrito_activo(sesion, usuario_id)
        return carrito or self.repositorio.crear_carrito(sesion, usuario_id)

    def _contar_disponibles(self, sesion: Session, juego_id: int) -> int:
        try:
            return self.cliente_inventario.contar_disponibles(sesion, juego_id)
        except InventarioNoDisponible as error:
            raise ErrorAplicacion(503, MENSAJE_COM12_NO_DISPONIBLE) from error

    def _validar_reglas_cantidad(
        self, sesion: Session, usuario_id: int, juego_id: int, estado_juego: str, cantidad_total: int
    ) -> None:
        licencias_ordenes = self.cliente_ordenes.contar_licencias_no_canceladas(sesion, usuario_id, juego_id)
        validar_limite_preventa(estado_juego, cantidad_total, licencias_ordenes)
        validar_stock_suficiente(cantidad_total, self._contar_disponibles(sesion, juego_id))

    def _armar_carrito(self, sesion: Session, carrito: Carrito) -> dict:
        items = []
        subtotal = 0.0
        for item in carrito.items:
            contrato = self.cliente_catalogo.obtener_juego(sesion, item.juego_id)
            if not contrato.get("existe"):
                continue
            precio_unitario = float(contrato["precioFinal"])
            subtotal += precio_unitario * item.cantidad
            items.append(
                {
                    "itemId": item.id,
                    "juegoId": item.juego_id,
                    "titulo": contrato.get("titulo"),
                    "cantidad": item.cantidad,
                    "precioUnitario": precio_unitario,
                }
            )
        return {
            "carritoId": carrito.id,
            "items": items,
            "subtotal": round(subtotal, 2),
            "moneda": settings.DEFAULT_CURRENCY,
        }

    # --- HU-26: Agregar juego al carrito ---

    def agregar_item(self, sesion: Session, usuario: UsuarioAutenticado, datos: AgregarItemEntrada) -> dict:
        validar_cantidad_agregar(datos.cantidad)
        contrato = self.cliente_catalogo.obtener_juego(sesion, datos.juegoId)
        validar_juego_vendible(contrato)

        mensaje_error_bd = "No fue posible agregar el juego al carrito"
        with manejar_errores_bd(mensaje_error_bd):
            carrito = self._obtener_o_crear_carrito(sesion, usuario.id)
            existente = self.repositorio.obtener_item_por_juego(sesion, carrito.id, datos.juegoId)
        cantidad_total = (existente.cantidad if existente else 0) + datos.cantidad

        self._validar_reglas_cantidad(sesion, usuario.id, datos.juegoId, contrato["estado"], cantidad_total)

        with manejar_errores_bd(mensaje_error_bd):
            self.repositorio.guardar_item(sesion, carrito, datos.juegoId, cantidad_total)
        return respuesta("Juego agregado al carrito", self._armar_carrito(sesion, carrito))

    # --- HU-27: Consultar ítems del carrito activo ---

    def consultar_carrito(self, sesion: Session, usuario: UsuarioAutenticado) -> dict:
        with manejar_errores_bd("No fue posible consultar el carrito"):
            carrito = self._obtener_o_crear_carrito(sesion, usuario.id)
        datos = self._armar_carrito(sesion, carrito)
        if not datos["items"]:
            return respuesta("El carrito está vacío", datos, False)
        return respuesta("Consulta de carrito exitosa", datos)

    # --- HU-28: Eliminar ítem del carrito ---

    def eliminar_item(self, sesion: Session, usuario: UsuarioAutenticado, item_id: int) -> dict:
        with manejar_errores_bd("No fue posible eliminar el ítem"):
            item = self.repositorio.obtener_item_de_usuario(sesion, item_id, usuario.id)
            if item is None:
                raise ErrorAplicacion(404, MENSAJE_ITEM_NO_EXISTE)
            carrito = self.repositorio.eliminar_item(sesion, item)
        return respuesta("Ítem eliminado del carrito", self._armar_carrito(sesion, carrito))

    # --- HU-29: Recalcular subtotales con promociones y volumen ---

    def actualizar_cantidad(
        self, sesion: Session, usuario: UsuarioAutenticado, item_id: int, datos: ActualizarCantidadEntrada
    ) -> dict:
        validar_cantidad_actualizar(datos.cantidad)
        mensaje_error_bd = "No fue posible recalcular los subtotales"
        with manejar_errores_bd(mensaje_error_bd):
            item = self.repositorio.obtener_item_de_usuario(sesion, item_id, usuario.id)
        if item is None:
            raise ErrorAplicacion(404, MENSAJE_ITEM_NO_EXISTE)

        contrato = self.cliente_catalogo.obtener_juego(sesion, item.juego_id)
        validar_juego_vendible(contrato)
        self._validar_reglas_cantidad(sesion, usuario.id, item.juego_id, contrato["estado"], datos.cantidad)

        with manejar_errores_bd(mensaje_error_bd):
            item = self.repositorio.actualizar_cantidad(sesion, item, datos.cantidad)
        desglose = calcular_desglose(
            float(contrato["precioFinal"]), float(contrato["precioPiso"]), item.cantidad, contrato["estado"]
        )
        return respuesta(
            "Subtotales recalculados",
            {
                "itemId": item.id,
                "juegoId": item.juego_id,
                "cantidad": item.cantidad,
                **desglose,
                "moneda": settings.DEFAULT_CURRENCY,
            },
        )

    # --- HU-30: Vaciar carrito de compras ---

    def vaciar_carrito(self, sesion: Session, usuario: UsuarioAutenticado) -> dict:
        with manejar_errores_bd("No fue posible vaciar el carrito"):
            carrito = self._obtener_o_crear_carrito(sesion, usuario.id)
            for item in list(carrito.items):
                sesion.delete(item)
            sesion.commit()
            sesion.refresh(carrito)
        return respuesta("Carrito vaciado exitosamente", self._armar_carrito(sesion, carrito))