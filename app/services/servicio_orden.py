from sqlalchemy.orm import Session

from app.core.respuestas import ErrorAplicacion, manejar_errores_bd, respuesta
from app.core.seguridad import UsuarioAutenticado
from app.domain.carrito import (
    calcular_desglose,
    validar_juego_vendible,
    validar_limite_preventa,
    validar_stock_suficiente,
)
from app.domain.orden import (
    ESTADO_ORDEN_CANCELADA,
    ESTADO_ORDEN_PENDIENTE,
    MENSAJE_CARRITO_VACIO,
    MENSAJE_ORDEN_NO_EXISTE,
    ItemOrden,
    Orden,
    validar_cancelacion_orden,
    validar_estado_consulta,
)
from app.repositories.repositorio_carrito import RepositorioCarrito
from app.repositories.repositorio_orden import RepositorioOrden
from app.services.cliente_inventario import (
    MENSAJE_COM12_NO_DISPONIBLE,
    ClienteInventario,
    InventarioNoDisponible,
    StockInsuficienteInventario,
)
from app.services.servicio_carrito import ClienteCatalogo
from app.services.servicio_parametros import ServicioParametros

MENSAJE_COM02_NO_DISPONIBLE = "No fue posible obtener la configuración tributaria de la orden"


class ClienteParametrosOrden:
    """Adaptador del contrato COM-02 (proveedor MOD-00): {tasaIva, moneda}."""

    def __init__(self, servicio_parametros: ServicioParametros | None = None):
        self.servicio_parametros = servicio_parametros or ServicioParametros()

    def obtener(self, sesion: Session) -> dict:
        try:
            return self.servicio_parametros.obtener_contrato_com02(sesion)
        except Exception as error:
            raise ErrorAplicacion(503, MENSAJE_COM02_NO_DISPONIBLE) from error


def _orden_a_dict(orden: Orden) -> dict:
    return {
        "ordenId": orden.id,
        "usuarioId": orden.usuario_id,
        "estado": orden.estado,
        "moneda": orden.moneda,
        "subtotalBruto": orden.subtotal_bruto,
        "descuentoTotal": orden.descuento_total,
        "subtotalNeto": orden.subtotal_neto,
        "valorIva": orden.valor_iva,
        "total": orden.total,
        "fechaCreacion": orden.fecha_creacion,
        "items": [
            {
                "itemOrdenId": item.id,
                "juegoId": item.juego_id,
                "titulo": item.titulo_juego,
                "cantidad": item.cantidad,
                "precioUnitario": item.precio_unitario,
                "descuentoVolumen": item.descuento_volumen,
                "subtotal": item.subtotal,
            }
            for item in orden.items
        ],
    }


class ServicioOrden:
    """Capa Application / Service de MOD-04: gestión de órdenes (HU-31 a HU-35)."""

    def __init__(self):
        self.repositorio = RepositorioOrden()
        self.repo_carrito = RepositorioCarrito()
        self.cliente_catalogo = ClienteCatalogo()
        self.cliente_inventario = ClienteInventario()
        self.cliente_parametros = ClienteParametrosOrden()

    # --- HU-31: Consolidar orden de compra pendiente ---

    def consolidar_orden(self, sesion: Session, usuario: UsuarioAutenticado) -> dict:
        with manejar_errores_bd("No fue posible consultar el carrito para generar la orden"):
            carrito = self.repo_carrito.obtener_carrito_activo(sesion, usuario.id)

        if carrito is None or not carrito.items:
            raise ErrorAplicacion(400, MENSAJE_CARRITO_VACIO)

        config_com02 = self.cliente_parametros.obtener(sesion)
        tasa_iva = float(config_com02["tasaIva"])
        moneda = config_com02["moneda"]

        items_orden: list[ItemOrden] = []
        subtotal_bruto = 0.0
        descuento_total = 0.0
        total_con_iva = 0.0

        for item in carrito.items:
            contrato = self.cliente_catalogo.obtener_juego(sesion, item.juego_id)
            validar_juego_vendible(contrato)

            licencias_previas = self.repositorio.contar_licencias_no_canceladas(sesion, usuario.id, item.juego_id)
            validar_limite_preventa(contrato["estado"], item.cantidad, licencias_previas)

            try:
                disponibles = self.cliente_inventario.contar_disponibles(sesion, item.juego_id)
            except InventarioNoDisponible as error:
                raise ErrorAplicacion(503, MENSAJE_COM12_NO_DISPONIBLE) from error
            validar_stock_suficiente(item.cantidad, disponibles)

            desglose = calcular_desglose(
                float(contrato["precioFinal"]),
                float(contrato["precioPiso"]),
                item.cantidad,
                contrato["estado"],
            )
            bruto_item = round(desglose["precioUnitario"] * item.cantidad, 2)
            subtotal_bruto += bruto_item
            descuento_total += desglose["descuentoVolumen"]
            total_con_iva += desglose["subtotal"]

            items_orden.append(
                ItemOrden(
                    juego_id=item.juego_id,
                    titulo_juego=contrato.get("titulo") or f"Juego #{item.juego_id}",
                    cantidad=item.cantidad,
                    precio_unitario=desglose["precioUnitario"],
                    descuento_volumen=desglose["descuentoVolumen"],
                    subtotal=desglose["subtotal"],
                )
            )

        total_redondeado = round(total_con_iva, 2)
        base_gravable = round(total_redondeado / (1 + tasa_iva), 2) if tasa_iva > 0 else total_redondeado
        valor_iva = round(total_redondeado - base_gravable, 2)

        try:
            for item_orden in items_orden:
                self.cliente_inventario.reservar_keys(sesion, item_orden.juego_id, item_orden.cantidad)

            nueva_orden = Orden(
                usuario_id=usuario.id,
                estado=ESTADO_ORDEN_PENDIENTE,
                moneda=moneda,
                tasa_iva=tasa_iva,
                subtotal_bruto=round(subtotal_bruto, 2),
                descuento_total=round(descuento_total, 2),
                subtotal_neto=base_gravable,
                valor_iva=valor_iva,
                total=total_redondeado,
                items=items_orden,
            )
            sesion.add(nueva_orden)
            for item_carrito in list(carrito.items):
                sesion.delete(item_carrito)
            sesion.commit()
            sesion.refresh(nueva_orden)
        except StockInsuficienteInventario as error:
            sesion.rollback()
            raise ErrorAplicacion(409, str(error)) from error
        except InventarioNoDisponible as error:
            sesion.rollback()
            raise ErrorAplicacion(503, MENSAJE_COM12_NO_DISPONIBLE) from error
        except Exception as error:
            sesion.rollback()
            raise ErrorAplicacion(503, "No fue posible consolidar la orden de compra") from error

        return respuesta("Orden de compra consolidada exitosamente", _orden_a_dict(nueva_orden))

    # --- HU-32: Liquidación financiera de la orden ---

    def consultar_liquidacion(self, sesion: Session, usuario: UsuarioAutenticado, orden_id: int) -> dict:
        with manejar_errores_bd("No fue posible consultar la liquidación de la orden"):
            orden = self.repositorio.obtener_por_id_y_usuario(sesion, orden_id, usuario.id)
        if orden is None:
            raise ErrorAplicacion(404, MENSAJE_ORDEN_NO_EXISTE)

        datos = {
            "ordenId": orden.id,
            "estado": orden.estado,
            "moneda": orden.moneda,
            "tasaIvaPorcentaje": round(orden.tasa_iva * 100, 2),
            "subtotalBruto": orden.subtotal_bruto,
            "descuentoVolumenTotal": orden.descuento_total,
            "baseGravable": orden.subtotal_neto,
            "valorIva": orden.valor_iva,
            "totalPagar": orden.total,
        }
        return respuesta("Liquidación financiera de la orden obtenida", datos)

    # --- HU-33: Consultar órdenes pendientes (o filtradas por estado) ---

    def listar_ordenes(self, sesion: Session, usuario: UsuarioAutenticado, estado: str | None = None) -> dict:
        estado_valido = validar_estado_consulta(estado)
        with manejar_errores_bd("No fue posible consultar las órdenes del usuario"):
            ordenes = self.repositorio.listar_por_usuario(sesion, usuario.id, estado_valido)
        datos = [_orden_a_dict(o) for o in ordenes]
        if not datos:
            return respuesta("No se encontraron órdenes para los criterios indicados", [], False)
        return respuesta("Consulta de órdenes exitosa", datos)

    # --- HU-34: Cancelar orden de compra y liberar stock ---

    def cancelar_orden(self, sesion: Session, usuario: UsuarioAutenticado, orden_id: int) -> dict:
        with manejar_errores_bd("No fue posible consultar la orden para cancelarla"):
            orden = self.repositorio.obtener_por_id_y_usuario(sesion, orden_id, usuario.id)
        if orden is None:
            raise ErrorAplicacion(404, MENSAJE_ORDEN_NO_EXISTE)

        validar_cancelacion_orden(orden.estado)

        total_liberadas = 0
        try:
            for item in orden.items:
                total_liberadas += self.cliente_inventario.liberar_keys(sesion, item.juego_id, item.cantidad)
            orden.estado = ESTADO_ORDEN_CANCELADA
            sesion.commit()
            sesion.refresh(orden)
        except InventarioNoDisponible as error:
            sesion.rollback()
            raise ErrorAplicacion(503, MENSAJE_COM12_NO_DISPONIBLE) from error
        except Exception as error:
            sesion.rollback()
            raise ErrorAplicacion(503, "No fue posible cancelar la orden de compra") from error

        return respuesta(
            "Orden cancelada y stock liberado exitosamente",
            {
                "ordenId": orden.id,
                "estado": orden.estado,
                "licenciasLiberadas": total_liberadas,
            },
        )