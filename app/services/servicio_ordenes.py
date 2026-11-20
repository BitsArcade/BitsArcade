from sqlalchemy.orm import Session

from app.core.respuestas import ErrorAplicacion, manejar_errores_bd, respuesta
from app.core.seguridad import UsuarioAutenticado
from app.domain.carrito import (
    calcular_desglose,
    validar_juego_vendible,
    validar_limite_preventa,
    validar_stock_suficiente,
)
from app.domain.ordenes import (
    ESTADO_ORDEN_PENDIENTE,
    ActualizarEstadoOrdenEntrada,
    CancelarOrdenEntrada,
    OrdenCompra,
    calcularLiquidacionOrden,
    validarOrdenPendiente,
    validarTransicionEstadoCom09,
)
from app.repositories.repositorio_carrito import RepositorioCarrito
from app.repositories.repositorio_ordenes import RepositorioOrdenes
from app.services.cliente_inventario import (
    MENSAJE_COM12_NO_DISPONIBLE,
    ClienteInventario,
    InventarioNoDisponible,
)
from app.services.servicio_catalogo import ServicioCatalogo
from app.services.servicio_parametros import ServicioParametros


class ServicioOrdenes:
    """
    Capa Application / Service de MOD-04 (SUB-04.2):
    Orquesta HU-31 a HU-35 y los contratos internos COM-08 y COM-09.
    """

    def __init__(self):
        self.repositorioOrdenes = RepositorioOrdenes()
        self.repositorioCarrito = RepositorioCarrito()
        self.servicioCatalogo = ServicioCatalogo()
        self.clienteInventario = ClienteInventario()
        self.servicioParametros = ServicioParametros()

    def _serializarOrden(self, orden: OrdenCompra) -> dict:
        """Convierte una entidad OrdenCompra en diccionario limpio en camelCase."""
        return {
            "id": orden.id,
            "usuarioId": orden.usuarioId,
            "estado": orden.estado,
            "moneda": orden.moneda,
            "tasaCambioCongelada": orden.tasaCambioCongelada,
            "subtotalBase": orden.subtotalBase,
            "descuentoAplicado": orden.descuentoAplicado,
            "montoIva": orden.montoIva,
            "totalPagar": orden.totalPagar,
            "motivoCancelacion": orden.motivoCancelacion,
            "fechaCreacion": orden.fechaCreacion,
            "fechaExpiracionReserva": orden.fechaExpiracionReserva,
            "detalles": [
                {
                    "juegoId": detalle.juegoId,
                    "tituloJuego": detalle.tituloJuego,
                    "cantidad": detalle.cantidad,
                    "precioUnitario": detalle.precioUnitario,
                    "descuentoVolumen": detalle.descuentoVolumen,
                    "subtotal": detalle.subtotal,
                }
                for detalle in orden.detalles
            ],
        }

    # --- HU-31: Consolidar orden de compra ---

    def consolidarOrden(self, sesion: Session, usuario: UsuarioAutenticado) -> dict:
        """
        HU-31 (FUN-04.2.1 / PRO-04.2.1):
        Consolida el carrito activo en una orden PENDIENTE, reserva las keys por 15 min (RN-04),
        congela moneda/tasa de cambio (RN-09) y vacía el carrito.
        """
        with manejar_errores_bd("No fue posible consultar el carrito para consolidar la orden"):
            carrito = self.repositorioCarrito.obtener_carrito_activo(sesion, usuario.id)

        if not carrito or not carrito.items:
            raise ErrorAplicacion(400, "No es posible consolidar la orden porque el carrito está vacío.")

        # 1. Obtener parámetros financieros vigentes desde MOD-00 (COM-02 y COM-03)
        contratoCom02 = self.servicioParametros.obtener_contrato_com02(sesion)
        tasaIvaDecimal = float(contratoCom02["taxRate"])
        monedaVigente = contratoCom02["currency"]
        contratoCom03 = self.servicioParametros.obtener_contrato_com03(sesion, monedaVigente)
        tasaCambioCongelada = float(contratoCom03["exchangeRate"])

        # 2. Validar catálogo (COM-11), stock (COM-12) y calcular precios por ítem
        itemsCalculados = []
        for itemCarrito in carrito.items:
            contratoJuego = self.servicioCatalogo.obtener_contrato_com11(sesion, itemCarrito.juego_id)
            validar_juego_vendible(contratoJuego)
            validar_limite_preventa(contratoJuego["status"], itemCarrito.cantidad, 0)

            try:
                disponibles = self.clienteInventario.contar_disponibles(sesion, itemCarrito.juego_id)
            except InventarioNoDisponible as error:
                raise ErrorAplicacion(503, MENSAJE_COM12_NO_DISPONIBLE) from error

            validar_stock_suficiente(itemCarrito.cantidad, disponibles)

            desgloseItem = calcular_desglose(
                float(contratoJuego["finalPrice"]),
                float(contratoJuego["floorPrice"]),
                itemCarrito.cantidad,
                contratoJuego["status"],
            )
            itemsCalculados.append(
                {
                    "juegoId": itemCarrito.juego_id,
                    "tituloJuego": contratoJuego.get("title") or f"Juego #{itemCarrito.juego_id}",
                    "cantidad": itemCarrito.cantidad,
                    "precioUnitario": desgloseItem["precioUnitario"],
                    "descuentoVolumen": desgloseItem["descuentoVolumen"],
                    "subtotal": desgloseItem["subtotal"],
                }
            )

        # 3. Liquidar totales de la orden (HU-32)
        liquidacion = calcularLiquidacionOrden(itemsCalculados, tasaIvaDecimal)

        # 4. Reservar keys atómicamente (RN-04), guardar orden y vaciar carrito
        with manejar_errores_bd("No fue posible consolidar la orden de compra"):
            keysReservadasTotales = []
            for itemCalc in itemsCalculados:
                keysReservadas = self.repositorioOrdenes.reservarKeysDisponibles(
                    sesion, itemCalc["juegoId"], itemCalc["cantidad"]
                )
                if len(keysReservadas) < itemCalc["cantidad"]:
                    sesion.rollback()
                    raise ErrorAplicacion(409, "Stock insuficiente al momento de reservar las licencias.")
                keysReservadasTotales.extend(keysReservadas)

            nuevaOrden = self.repositorioOrdenes.crearOrdenConDetalles(
                sesion=sesion,
                usuarioId=usuario.id,
                moneda=monedaVigente,
                tasaCambio=tasaCambioCongelada,
                liquidacion=liquidacion,
                itemsCalculados=itemsCalculados,
                keysReservadas=keysReservadasTotales,
            )
            self.repositorioCarrito.vaciarCarrito(sesion, carrito)

        return respuesta("Orden de compra consolidada exitosamente", self._serializarOrden(nuevaOrden))

    # --- HU-32: Calcular total con markup e impuesto (Liquidación financiera) ---

    def obtenerLiquidacionOrden(self, sesion: Session, usuario: UsuarioAutenticado, ordenId: int) -> dict:
        """HU-32 (FUN-04.2.2 / PRO-04.2.2): Retorna el desglose financiero completo de una orden."""
        with manejar_errores_bd("No fue posible consultar la liquidación de la orden"):
            orden = self.repositorioOrdenes.obtenerOrdenDeUsuario(sesion, ordenId, usuario.id)

        if not orden:
            raise ErrorAplicacion(404, f"No se encontró la orden con ID {ordenId} para tu usuario.")

        datosLiquidacion = {
            "ordenId": orden.id,
            "estado": orden.estado,
            "moneda": orden.moneda,
            "tasaCambioAplicada": orden.tasaCambioCongelada,
            "subtotalBase": orden.subtotalBase,
            "descuentoAplicado": orden.descuentoAplicado,
            "montoIva": orden.montoIva,
            "totalPagar": orden.totalPagar,
            "items": [
                {
                    "juegoId": detalle.juegoId,
                    "tituloJuego": detalle.tituloJuego,
                    "cantidad": detalle.cantidad,
                    "precioUnitario": detalle.precioUnitario,
                    "descuentoVolumen": detalle.descuentoVolumen,
                    "subtotal": detalle.subtotal,
                }
                for detalle in orden.detalles
            ],
        }
        return respuesta("Liquidación financiera de la orden obtenida", datosLiquidacion)

    # --- HU-33: Consultar órdenes pendientes ---

    def consultarOrdenesPendientes(self, sesion: Session, usuario: UsuarioAutenticado) -> dict:
        """HU-33 (FUN-04.2.3 / PRO-04.2.3): Lista las órdenes abiertas en estado PENDIENTE."""
        with manejar_errores_bd("No fue posible consultar las órdenes pendientes"):
            ordenes = self.repositorioOrdenes.listarOrdenesPendientesUsuario(sesion, usuario.id)

        listaOrdenes = [self._serializarOrden(orden) for orden in ordenes]
        if not listaOrdenes:
            return respuesta("No tienes órdenes pendientes de pago", [], False)
        return respuesta("Consulta de órdenes pendientes exitosa", listaOrdenes)

    # --- HU-34: Cancelar orden de compra ---

    def cancelarOrden(
        self, sesion: Session, usuario: UsuarioAutenticado, ordenId: int, datos: CancelarOrdenEntrada
    ) -> dict:
        """HU-34 (FUN-04.2.4 / PRO-04.2.4): Anula una orden PENDIENTE y libera sus keys reservadas."""
        with manejar_errores_bd("No fue posible consultar la orden a cancelar"):
            orden = self.repositorioOrdenes.obtenerOrdenDeUsuario(sesion, ordenId, usuario.id)

        if not orden:
            raise ErrorAplicacion(404, f"No se encontró la orden con ID {ordenId} para tu usuario.")

        validarOrdenPendiente(orden.estado, "cancelar")

        with manejar_errores_bd("No fue posible cancelar la orden de compra"):
            ordenCancelada = self.repositorioOrdenes.cancelarOrden(sesion, orden, datos.motivo)

        return respuesta("Orden cancelada y stock liberado correctamente", self._serializarOrden(ordenCancelada))

    # --- HU-35: Cambiar estado a PROCESANDO ---

    def bloquearOrdenProcesando(self, sesion: Session, usuario: UsuarioAutenticado, ordenId: int) -> dict:
        """HU-35 (FUN-04.2.5 / PRO-04.2.5): Bloquea la orden en estado PROCESANDO al iniciar el cobro."""
        with manejar_errores_bd("No fue posible consultar la orden para iniciar pago"):
            orden = self.repositorioOrdenes.obtenerOrdenDeUsuario(sesion, ordenId, usuario.id)

        if not orden:
            raise ErrorAplicacion(404, f"No se encontró la orden con ID {ordenId} para tu usuario.")

        validarOrdenPendiente(orden.estado, "pasar a PROCESANDO")

        with manejar_errores_bd("No fue posible actualizar el estado de la orden a PROCESANDO"):
            ordenBloqueada = self.repositorioOrdenes.cambiarEstadoProcesando(sesion, orden)

        return respuesta(
            "Orden bloqueada en estado PROCESANDO para cobro",
            self._serializarOrden(ordenBloqueada),
        )

    # --- CONTRATOS INTERNOS ENTRE MICROSERVICIOS (Tabla 10 del Informe) ---

    def obtenerContratoCom08(self, sesion: Session, ordenId: int) -> dict:
        """COM-08 (Para MOD-05 Transacciones): Entrega {ordenId, usuarioId, moneda, total, items} de orden a cobrar."""
        orden = self.repositorioOrdenes.obtenerOrdenPorId(sesion, ordenId)
        if not orden:
            raise ErrorAplicacion(404, f"La orden {ordenId} no existe.")
        if orden.estado not in (ESTADO_ORDEN_PENDIENTE, "PROCESANDO"):
            raise ErrorAplicacion(409, f"La orden {ordenId} no está disponible para cobro (estado: {orden.estado}).")

        return {
            "ordenId": orden.id,
            "usuarioId": orden.usuarioId,
            "moneda": orden.moneda,
            "total": orden.totalPagar,
            "items": [
                {
                    "juegoId": detalle.juegoId,
                    "tituloJuego": detalle.tituloJuego,
                    "cantidad": detalle.cantidad,
                    "subtotal": detalle.subtotal,
                }
                for detalle in orden.detalles
            ],
        }

    def procesarContratoCom09(self, sesion: Session, datos: ActualizarEstadoOrdenEntrada) -> dict:
        """COM-09 (Para MOD-05 Transacciones): Actualiza estado tras cobro (PAGADA / CANCELADA - RN-06)."""
        orden = self.repositorioOrdenes.obtenerOrdenPorId(sesion, datos.ordenId)
        if not orden:
            raise ErrorAplicacion(404, f"La orden {datos.ordenId} no existe.")

        estadoDestino = datos.estado.upper()
        validarTransicionEstadoCom09(orden.estado, estadoDestino)

        with manejar_errores_bd("No fue posible actualizar el estado de la orden vía COM-09"):
            self.repositorioOrdenes.actualizarEstadoCom09(sesion, orden, estadoDestino)

        return {"confirmado": True, "ordenId": orden.id, "estado": estadoDestino}