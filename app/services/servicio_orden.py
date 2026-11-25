from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.core.configuracion import settings
from app.core.respuestas import ErrorAplicacion, manejar_errores_bd, respuesta
from app.core.seguridad import UsuarioAutenticado
from app.domain.carrito import (
    MENSAJE_STOCK_INSUFICIENTE,
    calcular_desglose,
    validar_juego_vendible,
    validar_limite_preventa,
)
from app.domain.orden import (
    ESTADO_ORDEN_CANCELADA,
    ESTADO_ORDEN_ENTREGADA,
    ESTADO_ORDEN_PENDIENTE,
    ESTADO_ORDEN_PROCESANDO,
    MENSAJE_CARRITO_VACIO_ORDEN,
    MENSAJE_ORDEN_NO_EXISTE,
    ActualizarEstadoOrdenEntrada,
    EstadoOrdenInternoSalida,
    ItemOrden,
    Orden,
    validar_cancelacion_orden,
    validar_estado_consulta_orden,
    validar_transicion_estado_interno,
)
from app.repositories.repositorio_carrito import RepositorioCarrito
from app.repositories.repositorio_orden import RepositorioOrden
from app.services.cliente_inventario import (
    MENSAJE_COM12_NO_DISPONIBLE,
    ClienteInventario,
    InventarioNoDisponible,
    StockInsuficienteInventario,
)
from app.services.servicio_carrito import ClienteCatalogo, _extraer_usuario_id
from app.services.servicio_parametros import ServicioParametros


class ServicioOrden:
    """Capa Application / Service de MOD-04: casos de uso de Órdenes (HU-31 a HU-35 y HU-42)."""

    def __init__(self):
        self.repo_carrito = RepositorioCarrito()
        self.repo_orden = RepositorioOrden()
        self.cliente_catalogo = ClienteCatalogo()
        self.cliente_inventario = ClienteInventario()
        self.servicio_parametros = ServicioParametros()

    @staticmethod
    def _orden_a_salida(orden: Orden) -> dict:
        return {
            "ordenId": orden.id,
            "estado": orden.estado,
            "moneda": orden.moneda,
            "subtotalBruto": round(orden.subtotal_bruto, 2),
            "descuentoTotal": round(orden.descuento_total, 2),
            "total": round(orden.total, 2),
            "items": [
                {
                    "juegoId": item.juego_id,
                    "titulo": item.titulo,
                    "cantidad": item.cantidad,
                    "precioUnitario": round(item.precio_unitario, 2),
                    "descuentoVolumen": round(item.descuento_volumen, 2),
                    "subtotal": round(item.subtotal, 2),
                }
                for item in orden.items
            ],
        }

    # --- HU-31: Consolidar orden de compra pendiente ---

    def consolidar_orden(self, sesion: Session, usuario: UsuarioAutenticado | int) -> dict:
        usuario_id = _extraer_usuario_id(usuario)
        with manejar_errores_bd("No fue posible consolidar la orden"):
            carrito = self.repo_carrito.obtener_carrito_activo(sesion, usuario_id)

        if carrito is None or not carrito.items:
            raise ErrorAplicacion(400, MENSAJE_CARRITO_VACIO_ORDEN)

        items_orden: list[ItemOrden] = []
        subtotal_bruto = 0.0
        descuento_total = 0.0
        total_final = 0.0

        for item_carrito in carrito.items:
            contrato = self.cliente_catalogo.obtener_juego(sesion, item_carrito.juego_id)
            validar_juego_vendible(contrato)

            with manejar_errores_bd("No fue posible consolidar la orden"):
                licencias_previas = self.repo_orden.contar_licencias_no_canceladas(
                    sesion, usuario_id, item_carrito.juego_id
                )
            validar_limite_preventa(contrato["estado"], item_carrito.cantidad, licencias_previas)

            desglose = calcular_desglose(
                precio_unitario=float(contrato["precioFinal"]),
                precio_piso=float(contrato["precioPiso"]),
                cantidad=item_carrito.cantidad,
                estado_juego=contrato["estado"],
            )

            bruto_item = round(desglose["precioUnitario"] * item_carrito.cantidad, 2)
            subtotal_bruto += bruto_item
            descuento_total += desglose["descuentoVolumen"]
            total_final += desglose["subtotal"]

            items_orden.append(
                ItemOrden(
                    juego_id=item_carrito.juego_id,
                    titulo=contrato["titulo"],
                    cantidad=item_carrito.cantidad,
                    precio_unitario=desglose["precioUnitario"],
                    descuento_volumen=desglose["descuentoVolumen"],
                    subtotal=desglose["subtotal"],
                )
            )

        # Reserva atómica en inventario (COM-12) antes de confirmar la orden
        try:
            for item_carrito in carrito.items:
                self.cliente_inventario.reservar_keys(sesion, item_carrito.juego_id, item_carrito.cantidad)
        except StockInsuficienteInventario as error:
            sesion.rollback()
            raise ErrorAplicacion(409, MENSAJE_STOCK_INSUFICIENTE) from error
        except InventarioNoDisponible as error:
            sesion.rollback()
            raise ErrorAplicacion(503, MENSAJE_COM12_NO_DISPONIBLE) from error

        with manejar_errores_bd("No fue posible consolidar la orden"):
            nueva_orden = Orden(
                usuario_id=usuario_id,
                estado=ESTADO_ORDEN_PENDIENTE,
                moneda=settings.DEFAULT_CURRENCY,
                subtotal_bruto=round(subtotal_bruto, 2),
                descuento_total=round(descuento_total, 2),
                total=round(total_final, 2),
                items=items_orden,
            )
            orden_creada = self.repo_orden.crear_orden(sesion, nueva_orden)
            self.repo_carrito.vaciar_carrito(sesion, carrito)

        return respuesta("Orden de compra consolidada exitosamente", self._orden_a_salida(orden_creada))

    # --- HU-32: Liquidación financiera de la orden ---

    def consultar_liquidacion(
        self, sesion: Session, usuario: UsuarioAutenticado | int, orden_id: int
    ) -> dict:
        usuario_id = _extraer_usuario_id(usuario)
        with manejar_errores_bd("No fue posible consultar la liquidación"):
            orden = self.repo_orden.obtener_por_id_y_usuario(sesion, orden_id, usuario_id)

        if orden is None:
            raise ErrorAplicacion(404, MENSAJE_ORDEN_NO_EXISTE)

        try:
            contrato_com01 = self.servicio_parametros.obtener_contrato_com01(sesion)
            tasa_iva = float(contrato_com01["taxRate"])
        except Exception as error:
            raise ErrorAplicacion(503, "No fue posible obtener los parámetros financieros") from error

        total_pagar = round(orden.total, 2)
        base_gravable = round(total_pagar / (1 + tasa_iva), 2)
        valor_iva = round(total_pagar - base_gravable, 2)

        return respuesta(
            "Liquidación financiera de la orden obtenida",
            {
                "ordenId": orden.id,
                "estado": orden.estado,
                "moneda": orden.moneda,
                "tasaIvaPorcentaje": round(tasa_iva * 100, 2),
                "subtotalBruto": round(orden.subtotal_bruto, 2),
                "descuentoVolumenTotal": round(orden.descuento_total, 2),
                "baseGravable": base_gravable,
                "valorIva": valor_iva,
                "totalPagar": total_pagar,
            },
        )

    # --- HU-33: Consultar órdenes pendientes / historial ---

    def listar_ordenes(
        self, sesion: Session, usuario: UsuarioAutenticado | int, estado: str | None = None
    ) -> dict:
        usuario_id = _extraer_usuario_id(usuario)
        estado_filtrado = validar_estado_consulta_orden(estado)
        with manejar_errores_bd("No fue posible consultar las órdenes"):
            ordenes = self.repo_orden.listar_por_usuario(sesion, usuario_id, estado_filtrado)

        if not ordenes:
            return respuesta("No se encontraron órdenes para los criterios indicados", [], False)

        return respuesta(
            "Consulta de órdenes exitosa",
            [self._orden_a_salida(o) for o in ordenes],
        )

    # --- HU-34: Cancelar orden de compra y liberar stock ---

    def cancelar_orden(
        self, sesion: Session, usuario: UsuarioAutenticado | int, orden_id: int
    ) -> dict:
        usuario_id = _extraer_usuario_id(usuario)
        with manejar_errores_bd("No fue posible cancelar la orden"):
            orden = self.repo_orden.obtener_por_id_y_usuario(sesion, orden_id, usuario_id)

        if orden is None:
            raise ErrorAplicacion(404, MENSAJE_ORDEN_NO_EXISTE)

        validar_cancelacion_orden(orden.estado)

        licencias_liberadas = 0
        try:
            for item in orden.items:
                licencias_liberadas += self.cliente_inventario.liberar_keys(
                    sesion, item.juego_id, item.cantidad
                )
        except InventarioNoDisponible as error:
            sesion.rollback()
            raise ErrorAplicacion(503, MENSAJE_COM12_NO_DISPONIBLE) from error

        with manejar_errores_bd("No fue posible cancelar la orden"):
            self.repo_orden.actualizar_estado(sesion, orden, ESTADO_ORDEN_CANCELADA)

        return respuesta(
            "Orden cancelada y stock liberado exitosamente",
            {
                "ordenId": orden.id,
                "estado": ESTADO_ORDEN_CANCELADA,
                "licenciasLiberadas": licencias_liberadas,
            },
        )

    # --- HU-35 y HU-42: Actualizar estado interno vía COM-09 (MOD-05 y MOD-06) ---

    def actualizar_estado_interno(
        self,
        sesion: Session,
        orden_id: int,
        nuevo_estado: str | ActualizarEstadoOrdenEntrada,
        entregada_en: Optional[datetime] = None,
    ) -> EstadoOrdenInternoSalida:
        if hasattr(nuevo_estado, "estado"):
            estado_solicitado = nuevo_estado.estado
            fecha_entrega = getattr(nuevo_estado, "entregadaEn", None) or entregada_en
        else:
            estado_solicitado = nuevo_estado
            fecha_entrega = entregada_en

        mensaje_error_bd = (
            "No fue posible marcar la orden como entregada"
            if (estado_solicitado or "").strip().upper() == ESTADO_ORDEN_ENTREGADA
            else "No fue posible actualizar el estado de la orden"
        )

        with manejar_errores_bd(mensaje_error_bd):
            orden = self.repo_orden.obtener_por_id(sesion, orden_id)

        if orden is None:
            raise ErrorAplicacion(404, MENSAJE_ORDEN_NO_EXISTE)

        estado_anterior = orden.estado
        estado_destino = validar_transicion_estado_interno(
            estado_anterior,
            estado_solicitado,
            entregada_en=fecha_entrega,
        )

        if estado_destino == ESTADO_ORDEN_CANCELADA:
            try:
                for item in orden.items:
                    self.cliente_inventario.liberar_keys(sesion, item.juego_id, item.cantidad)
            except InventarioNoDisponible as error:
                sesion.rollback()
                raise ErrorAplicacion(503, MENSAJE_COM12_NO_DISPONIBLE) from error

        with manejar_errores_bd(mensaje_error_bd):
            self.repo_orden.actualizar_estado(
                sesion,
                orden,
                estado_destino,
                entregada_en=fecha_entrega,
            )

        return EstadoOrdenInternoSalida(
            ordenId=orden.id,
            estadoAnterior=estado_anterior,
            estadoActual=estado_destino,
            bloqueada=(estado_destino == ESTADO_ORDEN_PROCESANDO),
        )

    def marcar_orden_como_entregada(
        self,
        sesion: Session,
        orden_id: int,
        entregada_en: Optional[datetime],
    ) -> dict:
        """HU-42: Cierra formalmente una orden PAGADA pasándola a ENTREGADA vía COM-09."""
        salida = self.actualizar_estado_interno(
            sesion=sesion,
            orden_id=orden_id,
            nuevo_estado=ESTADO_ORDEN_ENTREGADA,
            entregada_en=entregada_en,
        )
        return respuesta(
            "Orden cerrada como entregada",
            {
                "ordenId": salida.ordenId,
                "estado": salida.estadoActual,
                "confirmado": True,
            },
        )