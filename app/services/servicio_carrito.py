from sqlalchemy.orm import Session

from app.core.configuracion import settings
from app.core.respuestas import ErrorAplicacion, manejar_errores_bd, respuesta
from app.core.seguridad import UsuarioAutenticado
from app.domain.carrito import (
    AgregarItemEntrada,
    Carrito,
    validar_cantidad_agregar,
    validar_juego_vendible,
    validar_limite_preventa,
    validar_stock_suficiente,
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
    Adaptador del contrato COM-11 (proveedor MOD-02): {exists, title, status, finalPrice, floorPrice}.
    MOD-04 consume el precio calculado por el Catálogo y NO recalcula RN-01.
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
    """
    Consulta de licencias en órdenes previas NO canceladas del usuario (RN-05).

    Las órdenes de compra se crean en HU-31 (aún no implementada). Mientras tanto se retorna 0;
    cuando exista la entidad Orden basta con implementar este método sin tocar el resto del flujo.
    """

    def contar_licencias_no_canceladas(self, sesion: Session, usuario_id: int, juego_id: int) -> int:
        return 0


class ServicioCarrito:
    """Capa Application / Service de MOD-04: casos de uso del carrito (HU-26 a HU-29)."""

    def __init__(self):
        self.repositorio = RepositorioCarrito()
        self.cliente_catalogo = ClienteCatalogo()
        self.cliente_inventario = ClienteInventario()
        self.cliente_ordenes = ClienteOrdenes()

    # --- Utilidades internas ---

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
        """RN-05 (preventa) y stock suficiente vía COM-12 (solo consulta, la reserva es HU-31)."""
        licencias_ordenes = self.cliente_ordenes.contar_licencias_no_canceladas(sesion, usuario_id, juego_id)
        validar_limite_preventa(estado_juego, cantidad_total, licencias_ordenes)
        validar_stock_suficiente(cantidad_total, self._contar_disponibles(sesion, juego_id))

    def _armar_carrito(self, sesion: Session, carrito: Carrito) -> dict:
        """Lista los ítems con precios vigentes de COM-11 y el subtotal preliminar (sin descuentos)."""
        items = []
        subtotal = 0.0
        for item in carrito.items:
            contrato = self.cliente_catalogo.obtener_juego(sesion, item.juego_id)
            if not contrato.get("exists"):
                continue
            precio_unitario = float(contrato["finalPrice"])
            subtotal += precio_unitario * item.cantidad
            items.append(
                {
                    "itemId": item.id,
                    "gameId": item.juego_id,
                    "titulo": contrato.get("title"),
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
        """HU-26: valida juego (COM-11), RN-05 y stock (COM-12); guarda o acumula el ítem."""
        validar_cantidad_agregar(datos.cantidad)
        contrato = self.cliente_catalogo.obtener_juego(sesion, datos.gameId)
        validar_juego_vendible(contrato)

        mensaje_error_bd = "No fue posible agregar el juego al carrito"
        with manejar_errores_bd(mensaje_error_bd):
            carrito = self._obtener_o_crear_carrito(sesion, usuario.id)
            existente = self.repositorio.obtener_item_por_juego(sesion, carrito.id, datos.gameId)
        cantidad_total = (existente.cantidad if existente else 0) + datos.cantidad

        self._validar_reglas_cantidad(sesion, usuario.id, datos.gameId, contrato["status"], cantidad_total)

        with manejar_errores_bd(mensaje_error_bd):
            self.repositorio.guardar_item(sesion, carrito, datos.gameId, cantidad_total)
        return respuesta("Juego agregado al carrito", self._armar_carrito(sesion, carrito))
