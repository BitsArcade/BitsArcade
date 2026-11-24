from sqlalchemy.orm import Session

from app.core.configuracion import settings
from app.core.respuestas import ErrorAplicacion, manejar_errores_bd, respuesta
from app.core.seguridad import UsuarioAutenticado
from app.domain.carrito import (
    MENSAJE_ITEM_NO_EXISTE,
    ActualizarCantidadEntrada,
    AgregarItemEntrada,
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


def _extraer_usuario_id(usuario: UsuarioAutenticado | int) -> int:
    return usuario.id if hasattr(usuario, "id") else int(usuario)


class ClienteCatalogo:
    """
    Adaptador del contrato COM-11 (proveedor MOD-02) hacia el dominio de MOD-04.
    Traduce las llaves del catálogo al español interno de Carrito y Órdenes.
    """

    def __init__(self, servicio_catalogo: ServicioCatalogo | None = None):
        self.servicio_catalogo = servicio_catalogo or ServicioCatalogo()

    def obtener_juego(self, sesion: Session, juego_id: int) -> dict:
        try:
            crudo = self.servicio_catalogo.obtener_contrato_com11(sesion, juego_id)
            return {
                "existe": bool(crudo.get("exists", crudo.get("existe", False))),
                "titulo": crudo.get("title", crudo.get("titulo")),
                "estado": crudo.get("status", crudo.get("estado")),
                "precioFinal": crudo.get("finalPrice", crudo.get("precioFinal")),
                "precioPiso": crudo.get("floorPrice", crudo.get("precioPiso")),
            }
        except ErrorAplicacion as error:
            if error.status_code == 503:
                raise ErrorAplicacion(503, MENSAJE_COM11_NO_DISPONIBLE) from error
            raise
        except Exception as error:
            raise ErrorAplicacion(503, MENSAJE_COM11_NO_DISPONIBLE) from error


class ClienteOrdenes:
    """Adaptador interno de Órdenes (MOD-04) para validar límite de preventa (RN-05)."""

    def __init__(self, repo_orden: RepositorioOrden | None = None):
        self.repo_orden = repo_orden or RepositorioOrden()

    def contar_licencias_no_canceladas(self, sesion: Session, usuario_id: int, juego_id: int) -> int:
        return self.repo_orden.contar_licencias_no_canceladas(sesion, usuario_id, juego_id)


class ServicioCarrito:
    """Capa Application / Service de MOD-04: casos de uso del carrito (HU-26 a HU-30)."""

    def __init__(self):
        self.repositorio = RepositorioCarrito()
        self.cliente_ordenes = ClienteOrdenes()
        self.cliente_catalogo = ClienteCatalogo()
        self.cliente_inventario = ClienteInventario()

    def _construir_carrito_salida(self, sesion: Session, carrito: Carrito) -> dict:
        items_salida = []
        subtotal = 0.0
        for item in carrito.items:
            contrato = self.cliente_catalogo.obtener_juego(sesion, item.juego_id)
            precio_unitario = float(contrato["precioFinal"] or 0.0)
            subtotal += precio_unitario * item.cantidad
            items_salida.append(
                {
                    "itemId": item.id,
                    "juegoId": item.juego_id,
                    "titulo": contrato["titulo"],
                    "cantidad": item.cantidad,
                    "precioUnitario": round(precio_unitario, 2),
                }
            )
        return {
            "carritoId": carrito.id,
            "items": items_salida,
            "subtotal": round(subtotal, 2),
            "moneda": settings.DEFAULT_CURRENCY,
        }

    # --- HU-26: Agregar juego al carrito ---

    def agregar_item(self, sesion: Session, usuario: UsuarioAutenticado | int, datos: AgregarItemEntrada) -> dict:
        usuario_id = _extraer_usuario_id(usuario)
        validar_cantidad_agregar(datos.cantidad)
        contrato = self.cliente_catalogo.obtener_juego(sesion, datos.juegoId)
        validar_juego_vendible(contrato)

        try:
            disponibles = self.cliente_inventario.contar_disponibles(sesion, datos.juegoId)
        except InventarioNoDisponible as error:
            raise ErrorAplicacion(503, MENSAJE_COM12_NO_DISPONIBLE) from error

        with manejar_errores_bd("No fue posible agregar el juego al carrito"):
            carrito = self.repositorio.obtener_o_crear_carrito(sesion, usuario_id)
            item_existente = self.repositorio.obtener_item_por_juego(sesion, carrito.id, datos.juegoId)
            cantidad_actual = item_existente.cantidad if item_existente else 0
            nueva_cantidad = cantidad_actual + datos.cantidad

            licencias_ordenes = self.cliente_ordenes.contar_licencias_no_canceladas(
                sesion, usuario_id, datos.juegoId
            )

        validar_limite_preventa(contrato["estado"], nueva_cantidad, licencias_ordenes)
        validar_stock_suficiente(nueva_cantidad, disponibles)

        with manejar_errores_bd("No fue posible agregar el juego al carrito"):
            if item_existente:
                self.repositorio.actualizar_cantidad_item(sesion, item_existente, nueva_cantidad)
            else:
                self.repositorio.agregar_item(sesion, carrito.id, datos.juegoId, datos.cantidad)
            sesion.refresh(carrito)

        return respuesta("Juego agregado al carrito", self._construir_carrito_salida(sesion, carrito))

    # --- HU-27: Consultar carrito de compras ---

    def consultar_carrito(self, sesion: Session, usuario: UsuarioAutenticado | int) -> dict:
        usuario_id = _extraer_usuario_id(usuario)
        with manejar_errores_bd("No fue posible consultar el carrito"):
            carrito = self.repositorio.obtener_carrito_activo(sesion, usuario_id)

        if carrito is None or not carrito.items:
            carrito_id = carrito.id if carrito else 0
            return respuesta(
                "El carrito está vacío",
                {"carritoId": carrito_id, "items": [], "subtotal": 0.0, "moneda": settings.DEFAULT_CURRENCY},
                False,
            )

        return respuesta("Consulta de carrito exitosa", self._construir_carrito_salida(sesion, carrito))

    # --- HU-28: Eliminar ítem del carrito ---

    def eliminar_item(self, sesion: Session, usuario: UsuarioAutenticado | int, item_id: int) -> dict:
        usuario_id = _extraer_usuario_id(usuario)
        with manejar_errores_bd("No fue posible eliminar el ítem"):
            item = self.repositorio.obtener_item_de_usuario(sesion, item_id, usuario_id)
            if item is None:
                raise ErrorAplicacion(404, MENSAJE_ITEM_NO_EXISTE)
            carrito = item.carrito
            self.repositorio.eliminar_item(sesion, item)
            sesion.refresh(carrito)

        return respuesta("Ítem eliminado del carrito", self._construir_carrito_salida(sesion, carrito))

    # --- HU-29: Recalcular subtotales con promociones y volumen ---

    def actualizar_cantidad(
        self, sesion: Session, usuario: UsuarioAutenticado | int, item_id: int, datos: ActualizarCantidadEntrada
    ) -> dict:
        usuario_id = _extraer_usuario_id(usuario)
        validar_cantidad_actualizar(datos.cantidad)

        with manejar_errores_bd("No fue posible recalcular los subtotales"):
            item = self.repositorio.obtener_item_de_usuario(sesion, item_id, usuario_id)
            if item is None:
                raise ErrorAplicacion(404, MENSAJE_ITEM_NO_EXISTE)
            licencias_ordenes = self.cliente_ordenes.contar_licencias_no_canceladas(
                sesion, usuario_id, item.juego_id
            )

        contrato = self.cliente_catalogo.obtener_juego(sesion, item.juego_id)
        validar_juego_vendible(contrato)
        validar_limite_preventa(contrato["estado"], datos.cantidad, licencias_ordenes)

        try:
            disponibles = self.cliente_inventario.contar_disponibles(sesion, item.juego_id)
        except InventarioNoDisponible as error:
            raise ErrorAplicacion(503, MENSAJE_COM12_NO_DISPONIBLE) from error

        validar_stock_suficiente(datos.cantidad, disponibles)

        with manejar_errores_bd("No fue posible recalcular los subtotales"):
            self.repositorio.actualizar_cantidad_item(sesion, item, datos.cantidad)

        desglose = calcular_desglose(
            precio_unitario=float(contrato["precioFinal"]),
            precio_piso=float(contrato["precioPiso"]),
            cantidad=datos.cantidad,
            estado_juego=contrato["estado"],
        )

        return respuesta(
            "Subtotales recalculados",
            {
                "itemId": item.id,
                "juegoId": item.juego_id,
                "cantidad": datos.cantidad,
                **desglose,
                "moneda": settings.DEFAULT_CURRENCY,
            },
        )

    # --- HU-30: Vaciar carrito de compras ---

    def vaciar_carrito(self, sesion: Session, usuario: UsuarioAutenticado | int) -> dict:
        usuario_id = _extraer_usuario_id(usuario)
        with manejar_errores_bd("No fue posible vaciar el carrito"):
            carrito = self.repositorio.obtener_carrito_activo(sesion, usuario_id)
            if carrito is None:
                return respuesta(
                    "Carrito vaciado exitosamente",
                    {"carritoId": 0, "items": [], "subtotal": 0.0, "moneda": settings.DEFAULT_CURRENCY},
                )
            self.repositorio.vaciar_carrito(sesion, carrito)

        return respuesta(
            "Carrito vaciado exitosamente",
            {"carritoId": carrito.id, "items": [], "subtotal": 0.0, "moneda": settings.DEFAULT_CURRENCY},
        )