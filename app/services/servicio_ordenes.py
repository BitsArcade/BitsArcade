import logging
from datetime import datetime, timedelta

from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.fechas import aIsoZ, ahoraUtc
from app.core.respuestas import ErrorAplicacion, manejarErroresBd, respuesta
from app.core.seguridad import UsuarioAutenticado
from app.domain.carrito import calcularDesglose, validarJuegoVendible
from app.domain.inventario import LiberarReservasEntrada, ReservarClavesEntrada
from app.domain.ordenes import (
    ESTADO_ORDEN_CANCELADA,
    ESTADO_ORDEN_ENTREGADA,
    ESTADO_ORDEN_PENDIENTE,
    ESTADO_ORDEN_PROCESANDO,
    MENSAJE_CARRITO_VACIO,
    MENSAJE_CUENTA_NO_CONFIRMADA,
    MENSAJE_IDEMPOTENCIA_OBLIGATORIA,
    MENSAJE_MONEDA_NO_HABILITADA,
    MENSAJE_ORDEN_EXPIRADA,
    MENSAJE_ORDEN_NO_EXISTE,
    MENSAJE_SOLO_PENDIENTE,
    MENSAJE_STOCK_INSUFICIENTE_ORDEN,
    MINUTOS_EXPIRACION_ORDEN,
    MOTIVO_EXPIRACION,
    CrearOrdenEntrada,
    LineaOrden,
    Orden,
    ReservaOrden,
    calcularLiquidacion,
    convertirDesdeCop,
    validarEstadoConsulta,
    validarSolicitante,
    validarTransicion,
)
from app.domain.parametros import MONEDA_BASE
from app.repositories.repositorio_carrito import RepositorioCarrito
from app.repositories.repositorio_ordenes import RepositorioOrdenes
from app.services.cliente_usuarios import ClienteUsuarios
from app.services.servicio_carrito import ClienteCatalogo
from app.services.servicio_inventario import ServicioInventario
from app.services.servicio_parametros import ServicioParametros

registro = logging.getLogger("bitarcade.ordenes")


class ReservaNoDisponible(Exception):
    """COM-13 (liberar reservas) no respondió."""


class ServicioOrdenes:
    """Capa Application / Service de MOD-04: órdenes de compra (HU-31 a HU-35, COM-08, COM-09)."""

    def __init__(self):
        self.repositorio = RepositorioOrdenes()
        self.repositorioCarrito = RepositorioCarrito()
        self.clienteCatalogo = ClienteCatalogo()
        self.clienteUsuarios = ClienteUsuarios()
        self.servicioInventario = ServicioInventario()
        self.servicioParametros = ServicioParametros()

    # --- Utilidades internas ---

    @staticmethod
    def _total(orden: Orden) -> float:
        return convertirDesdeCop(orden.totalCop, orden.tasaCambio, orden.moneda)

    def _salidaOrden(self, orden: Orden) -> dict:
        return {
            "ordenId": orden.id,
            "estado": orden.estado,
            "moneda": orden.moneda,
            "tasaCambio": orden.tasaCambio,
            "total": self._total(orden),
            "expiraEn": aIsoZ(orden.expiraEn),
        }

    def _liberarReservas(self, sesion: Session, reservaIds: list[str]) -> int:
        """COM-13: POST /interno/v1/inventario/reservas/liberar (idempotente)."""
        if not reservaIds:
            return 0
        try:
            resultado = self.servicioInventario.liberarReservas(sesion, LiberarReservasEntrada(reservaIds=reservaIds))
            return int(resultado["data"]["liberadas"])
        except Exception as error:
            raise ReservaNoDisponible(str(error)) from error

    # ===== HU-31: Consolidar orden de compra pendiente =====

    def crearOrden(
        self, sesion: Session, usuario: UsuarioAutenticado, datos: CrearOrdenEntrada, claveIdempotencia: str | None
    ) -> dict:
        """
        HU-31: carrito no vacío, usuario confirmado (COM-04, RN-12), moneda habilitada, IVA (COM-02) y
        tasa (COP = 1; otra moneda vía COM-03). Reserva atómica de todas las líneas (COM-06, RN-04);
        si una falla se liberan las ya reservadas (COM-13). Congela precios, IVA y tasa (RN-09),
        liquida (HU-32) y vacía el carrito. Idempotente por Idempotency-Key.
        """
        if not claveIdempotencia or not claveIdempotencia.strip():
            raise ErrorAplicacion(400, MENSAJE_IDEMPOTENCIA_OBLIGATORIA)
        claveIdempotencia = claveIdempotencia.strip()
        moneda = str(datos.moneda or MONEDA_BASE).strip().upper()
        mensaje503 = "No fue posible generar la orden"

        with manejarErroresBd(mensaje503):
            existente = self.repositorio.obtenerPorIdempotencia(sesion, usuario.id, claveIdempotencia)
            if existente is not None:
                return respuesta("Orden generada exitosamente", self._salidaOrden(existente))
            carrito = self.repositorioCarrito.obtenerCarritoActivo(sesion, usuario.id)
            items = list(carrito.items) if carrito else []
        if not items:
            raise ErrorAplicacion(409, MENSAJE_CARRITO_VACIO)

        with manejarErroresBd(mensaje503):
            validacion = self.clienteUsuarios.validarUsuario(sesion, usuario.id)  # COM-04
        if not validacion["valido"] or not validacion["cuentaConfirmada"]:
            raise ErrorAplicacion(403, MENSAJE_CUENTA_NO_CONFIRMADA)

        with manejarErroresBd(mensaje503):
            if not self.servicioParametros.monedaHabilitada(sesion, moneda):
                raise ErrorAplicacion(409, MENSAJE_MONEDA_NO_HABILITADA)
            tasaIva = float(self.servicioParametros.obtenerContratoCom01(sesion)["tasaIva"])  # COM-02
        tasaCambio = float(self.servicioParametros.obtenerContratoCom03(sesion, moneda)["tasaCambio"])  # COM-03

        lineas = []
        for item in items:
            contrato = self.clienteCatalogo.obtenerJuego(sesion, item.juegoId)  # COM-11
            validarJuegoVendible(contrato)
            desglose = calcularDesglose(
                float(contrato["precioFinal"]), float(contrato["precioMinimo"]), item.cantidad, contrato["estado"]
            )
            lineas.append((item, contrato, desglose))

        subtotalCop = round(sum(d["precioUnitario"] * i.cantidad for i, _, d in lineas), 2)
        descuentosCop = round(sum(d["descuentoVolumen"] for _, _, d in lineas), 2)
        ahora = ahoraUtc()
        orden = Orden(
            usuarioId=usuario.id,
            estado=ESTADO_ORDEN_PENDIENTE,
            moneda=moneda,
            tasaCambio=tasaCambio,
            tasaIva=tasaIva,
            subtotalCop=subtotalCop,
            descuentosCop=descuentosCop,
            totalCop=round(subtotalCop - descuentosCop, 2),
            claveIdempotencia=claveIdempotencia,
            expiraEn=ahora + timedelta(minutes=MINUTOS_EXPIRACION_ORDEN),
            creadaEn=ahora,
            actualizadaEn=ahora,
        )
        orden.lineas = [
            LineaOrden(
                juegoId=i.juegoId,
                titulo=c.get("titulo"),
                cantidad=i.cantidad,
                precioUnitarioCop=d["precioUnitario"],
                descuentoCop=d["descuentoVolumen"],
            )
            for i, c, d in lineas
        ]
        try:
            self.repositorio.guardar(sesion, orden)
        except IntegrityError:  # Dos peticiones simultáneas con la misma Idempotency-Key
            sesion.rollback()
            existente = self.repositorio.obtenerPorIdempotencia(sesion, usuario.id, claveIdempotencia)
            if existente is None:
                raise ErrorAplicacion(503, mensaje503)
            return respuesta("Orden generada exitosamente", self._salidaOrden(existente))
        except SQLAlchemyError as error:
            sesion.rollback()
            raise ErrorAplicacion(503, mensaje503) from error

        # COM-06: reserva atómica de todas las líneas (todo o nada).
        reservadas: list[ReservaOrden] = []
        try:
            for item, contrato, desglose in lineas:
                resultado = self.servicioInventario.reservarClaves(
                    sesion, ReservarClavesEntrada(ordenId=orden.id, juegoId=item.juegoId, cantidad=item.cantidad)
                )
                netoUnitario = round(desglose["subtotal"] / item.cantidad, 2)
                for reservaId in resultado["data"]["reservaIds"]:
                    reservadas.append(
                        ReservaOrden(
                            ordenId=orden.id,
                            juegoId=item.juegoId,
                            titulo=contrato.get("titulo"),
                            reservaId=reservaId,
                            precioUnitarioCop=netoUnitario,
                        )
                    )
        except ErrorAplicacion as error:
            try:
                self._liberarReservas(sesion, [r.reservaId for r in reservadas])
            except ReservaNoDisponible:
                registro.error("No se pudieron liberar reservas de la orden fallida %s", orden.id)
            self.repositorio.eliminar(sesion, orden)
            if error.codigoHttp == 409:
                raise ErrorAplicacion(409, MENSAJE_STOCK_INSUFICIENTE_ORDEN) from error
            raise ErrorAplicacion(503, mensaje503) from error

        with manejarErroresBd(mensaje503):
            self.repositorio.guardar(sesion, *reservadas)
            sesion.refresh(orden)
            carrito = self.repositorioCarrito.obtenerCarritoActivo(sesion, usuario.id)
            if carrito is not None:
                self.repositorioCarrito.vaciarCarrito(sesion, carrito)
        return respuesta("Orden generada exitosamente", self._salidaOrden(orden))

    # ===== HU-32: Liquidación financiera de la orden =====

    def liquidar(self, orden: Orden) -> dict:
        """HU-32: desglose con los valores congelados (no consulta MOD-00, RN-09)."""
        return {
            "ordenId": orden.id,
            "moneda": orden.moneda,
            "tasaCambio": orden.tasaCambio,
            "desglose": calcularLiquidacion(
                orden.subtotalCop, orden.descuentosCop, orden.tasaIva, orden.tasaCambio, orden.moneda
            ),
            "lineas": [
                {
                    "juegoId": linea.juegoId,
                    "cantidad": linea.cantidad,
                    "precioUnitario": convertirDesdeCop(linea.precioUnitarioCop, orden.tasaCambio, orden.moneda),
                }
                for linea in orden.lineas
            ],
        }

    def consultarLiquidacion(self, sesion: Session, usuario: UsuarioAutenticado, ordenId: int) -> dict:
        with manejarErroresBd("No fue posible obtener la liquidación"):
            orden = self.repositorio.obtenerDeUsuario(sesion, ordenId, usuario.id)
            if orden is None:
                raise ErrorAplicacion(404, MENSAJE_ORDEN_NO_EXISTE)
            datos = self.liquidar(orden)
        return respuesta("Liquidación obtenida exitosamente", datos)

    # ===== HU-33: Consultar órdenes pendientes =====

    def consultarOrdenes(self, sesion: Session, usuario: UsuarioAutenticado, estado: str | None) -> dict:
        filtro = validarEstadoConsulta(estado)
        with manejarErroresBd("No fue posible consultar las órdenes"):
            self.cancelarOrdenesExpiradas(sesion, usuario.id)
            ordenes = self.repositorio.listarPorEstado(sesion, usuario.id, filtro)
        pendientes = filtro == ESTADO_ORDEN_PENDIENTE
        if not ordenes:
            return respuesta("No tienes órdenes pendientes" if pendientes else "No tienes órdenes en el estado indicado", [], False)
        return respuesta(
            "Consulta de órdenes pendientes exitosa" if pendientes else "Consulta de órdenes exitosa",
            [
                {"ordenId": o.id, "total": self._total(o), "moneda": o.moneda, "expiraEn": aIsoZ(o.expiraEn)}
                for o in ordenes
            ],
        )

    # ===== HU-34: Cancelar orden de compra y liberar stock =====

    def _cancelar(self, sesion: Session, orden: Orden, motivo: str | None) -> None:
        """Libera las reservas (COM-13) y solo entonces pasa la orden a CANCELADA (irreversible)."""
        self._liberarReservas(sesion, [r.reservaId for r in orden.reservas])
        orden.estado = ESTADO_ORDEN_CANCELADA
        orden.motivoCancelacion = (motivo or "").strip()[:200] or None
        orden.actualizadaEn = ahoraUtc()
        sesion.commit()

    def cancelarOrden(self, sesion: Session, usuario: UsuarioAutenticado, ordenId: int, motivo: str | None) -> dict:
        mensaje503 = "No fue posible cancelar la orden"
        with manejarErroresBd(mensaje503):
            orden = self.repositorio.obtenerDeUsuario(sesion, ordenId, usuario.id)
            if orden is None:
                raise ErrorAplicacion(404, MENSAJE_ORDEN_NO_EXISTE)
            if orden.estado == ESTADO_ORDEN_CANCELADA:  # Idempotente
                return respuesta("Orden cancelada exitosamente", {"ordenId": orden.id, "estado": orden.estado})
            if orden.estado != ESTADO_ORDEN_PENDIENTE:
                raise ErrorAplicacion(409, MENSAJE_SOLO_PENDIENTE)
            try:
                self._cancelar(sesion, orden, motivo)
            except ReservaNoDisponible as error:
                sesion.rollback()
                raise ErrorAplicacion(503, "No fue posible liberar el stock reservado") from error
        return respuesta("Orden cancelada exitosamente", {"ordenId": orden.id, "estado": orden.estado})

    def cancelarOrdenesExpiradas(self, sesion: Session, usuarioId: int | None = None) -> int:
        """Job de HU-34: cancela las órdenes PENDIENTE con expiraEn vencido (si COM-13 falla, reintenta luego)."""
        canceladas = 0
        for orden in self.repositorio.listarPendientesVencidas(sesion, ahoraUtc(), usuarioId):
            try:
                self._cancelar(sesion, orden, MOTIVO_EXPIRACION)
                canceladas += 1
            except ReservaNoDisponible:
                sesion.rollback()
                registro.warning("COM-13 no respondió; la orden %s se reintentará", orden.id)
        return canceladas

    # ===== HU-35 / COM-09: actualizar estado de la orden =====

    def actualizarEstado(
        self,
        sesion: Session,
        ordenId: int,
        estado: str,
        transaccionId: str | None = None,
        entregadaEn: datetime | None = None,
        solicitante: str | None = None,
    ) -> dict:
        """
        COM-09 (PATCH /interno/v1/ordenes/{ordenId}/estado), usado por HU-35 (PROCESANDO), HU-40
        (PAGADA / CANCELADA) y HU-42 (ENTREGADA). Repetir el mismo estado es idempotente.
        Al pasar a CANCELADA, MOD-04 libera las reservas con COM-13 (RN-06).
        """
        nuevo = str(estado or "").upper()
        mensaje503 = "No fue posible actualizar el estado de la orden"
        with manejarErroresBd(mensaje503):
            orden = self.repositorio.obtenerPorId(sesion, ordenId)
            if orden is None:
                raise ErrorAplicacion(404, MENSAJE_ORDEN_NO_EXISTE)
            if orden.estado == nuevo:
                return respuesta("Estado de la orden actualizado", {"ordenId": orden.id, "estado": orden.estado, "confirmado": True})
            validarSolicitante(nuevo, solicitante)
            validarTransicion(orden.estado, nuevo)
            if nuevo == ESTADO_ORDEN_PROCESANDO and orden.expiraEn < ahoraUtc():
                raise ErrorAplicacion(409, MENSAJE_ORDEN_EXPIRADA)
            if transaccionId:
                orden.transaccionId = transaccionId
            if nuevo == ESTADO_ORDEN_CANCELADA:
                try:
                    self._cancelar(sesion, orden, "Pago no aprobado")
                except ReservaNoDisponible as error:
                    sesion.rollback()
                    raise ErrorAplicacion(503, "No fue posible liberar el stock reservado") from error
            else:
                orden.estado = nuevo
                if nuevo == ESTADO_ORDEN_ENTREGADA:
                    orden.entregadaEn = entregadaEn or ahoraUtc()
                orden.actualizadaEn = ahoraUtc()
                sesion.commit()
        return respuesta("Estado de la orden actualizado", {"ordenId": orden.id, "estado": orden.estado, "confirmado": True})

    # ===== COM-08: datos de la orden para MOD-05 =====

    def obtenerContratoCom08(self, sesion: Session, ordenId: int) -> dict | None:
        """COM-08 ampliado: {ordenId, usuarioId, estado, moneda, tasaCambio, total, expiraEn, items[...]}."""
        orden = self.repositorio.obtenerPorId(sesion, ordenId)
        if orden is None:
            return None
        return {
            "ordenId": orden.id,
            "usuarioId": orden.usuarioId,
            "estado": orden.estado,
            "moneda": orden.moneda,
            "tasaCambio": orden.tasaCambio,
            "tasaIva": orden.tasaIva,
            "total": self._total(orden),
            "expiraEn": orden.expiraEn,
            "items": [
                {
                    "juegoId": r.juegoId,
                    "titulo": r.titulo,
                    "reservaId": r.reservaId,
                    "precioUnitario": convertirDesdeCop(r.precioUnitarioCop, orden.tasaCambio, orden.moneda),
                }
                for r in orden.reservas
            ],
        }

    def contarLicenciasNoCanceladas(self, sesion: Session, usuarioId: int, juegoId: int) -> int:
        """HU-31 / RN-05: licencias en órdenes no canceladas (lo consume el carrito en HU-26 y HU-29)."""
        return self.repositorio.contarLicenciasNoCanceladas(sesion, usuarioId, juegoId)
