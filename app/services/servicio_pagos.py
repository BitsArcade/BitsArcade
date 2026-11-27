import json
import logging
import time
import uuid
from datetime import timedelta

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.configuracion import configuracion
from app.core.fechas import aIsoZ, ahoraUtc
from app.core.respuestas import ErrorAplicacion, manejarErroresBd, respuesta
from app.core.seguridad import UsuarioAutenticado
from app.domain.pagos import (
    ESTADO_PASARELA_APROBADO,
    ESTADO_TX_APROBADA,
    ESTADO_TX_EN_PROCESO,
    ESTADO_TX_EXPIRADA,
    ESTADO_TX_FALLIDA,
    ESTADO_TX_REQUIERE_REVISION,
    ESTADOS_PASARELA_RECHAZO,
    MAXIMO_REINTENTOS_COM09,
    MENSAJES_USUARIO,
    MENSAJES_USUARIO_POR_ESTADO,
    MINUTOS_MINIMOS_VIGENCIA,
    Comprobante,
    IniciarPagoEntrada,
    NotificacionOrden,
    Transaccion,
    NotificacionPasarelaEntrada,
    firmaValida,
    montosCoinciden,
)
from app.repositories.repositorio_pagos import RepositorioPagos
from app.services.cliente_despacho import ClienteDespacho
from app.services.cliente_ordenes import (
    ESTADO_ORDEN_CANCELADA,
    ESTADO_ORDEN_PAGADA,
    ESTADO_ORDEN_PENDIENTE,
    ESTADO_ORDEN_PROCESANDO,
    ClienteOrdenes,
    OrdenesNoDisponible,
    TransicionNoPermitida,
)
from app.services.cliente_pasarela import ClientePasarelaPagos, PasarelaSinRespuesta

registro = logging.getLogger("bitarcade.pagos")

MENSAJE_FIRMA_INVALIDA = "Firma de la notificación de la pasarela inválida"
MENSAJE_TX_NO_EXISTE = "La transacción indicada no existe"
MENSAJE_TX_RESUELTA = "La transacción ya fue resuelta con otro estado"


class ServicioPagos:
    """Capa Application / Service de MOD-05: casos de uso de pagos (HU-36 a HU-40)."""

    def __init__(self):
        self.repositorio = RepositorioPagos()
        self.clienteOrdenes = ClienteOrdenes("MOD-05")
        self.clientePasarela = ClientePasarelaPagos()
        self.clienteDespacho = ClienteDespacho()
        self.esperar = time.sleep

    def _salidaPagoEnProceso(self, transaccion: Transaccion) -> dict:
        return respuesta(
            "Pago en proceso",
            {"transaccionId": transaccion.transaccionId, "ordenId": transaccion.ordenId, "estado": transaccion.estado},
        )

    # ===== HU-36: Transmitir cobro a la pasarela de pago simulada =====

    def iniciarPago(self, sesion: Session, usuario: UsuarioAutenticado, datos: IniciarPagoEntrada) -> dict:
        """
        HU-36: obtiene la orden por COM-08 (tasa congelada, RN-09), valida dueño, estado y vigencia,
        pasa la orden a PROCESANDO (COM-09 / HU-35) y envía el cobro con Idempotency-Key = ordenId.
        """
        mensaje503 = "No fue posible iniciar el pago"
        with manejarErroresBd(mensaje503):
            existente = self.repositorio.obtenerTransaccionPorOrden(sesion, datos.ordenId)
        if existente is not None and existente.usuarioId == usuario.id:
            return self._salidaPagoEnProceso(existente)  # Idempotente por ordenId

        try:
            orden = self.clienteOrdenes.obtenerOrden(sesion, datos.ordenId)
        except OrdenesNoDisponible as error:
            raise ErrorAplicacion(503, mensaje503) from error
        if orden is None or orden["usuarioId"] != usuario.id:
            raise ErrorAplicacion(404, "La orden indicada no existe")
        if orden["estado"] not in (ESTADO_ORDEN_PENDIENTE, ESTADO_ORDEN_PROCESANDO):
            raise ErrorAplicacion(409, "La orden no está disponible para pago")
        if orden["expiraEn"] - ahoraUtc() < timedelta(minutes=MINUTOS_MINIMOS_VIGENCIA):
            raise ErrorAplicacion(409, "La orden está por expirar. Genera una nueva orden")

        try:
            self.clienteOrdenes.actualizarEstado(sesion, datos.ordenId, ESTADO_ORDEN_PROCESANDO)
        except TransicionNoPermitida as error:
            raise ErrorAplicacion(409, "La orden no está disponible para pago") from error
        except OrdenesNoDisponible as error:
            raise ErrorAplicacion(503, mensaje503) from error

        transaccion = Transaccion(
            transaccionId=f"TX-{uuid.uuid4().hex[:10].upper()}",
            ordenId=datos.ordenId,
            usuarioId=usuario.id,
            metodoPagoId=datos.metodoPagoId,
            monto=float(orden["total"]),
            moneda=orden["moneda"],
            tasaCambio=float(orden["tasaCambio"]),
            itemsJson=json.dumps(orden.get("items", [])),
            estado=ESTADO_TX_EN_PROCESO,
        )
        payload = {
            "transaccionId": transaccion.transaccionId,
            "ordenId": datos.ordenId,
            "metodoPagoId": datos.metodoPagoId,
            "total": transaccion.monto,
            "moneda": transaccion.moneda,
            "tasaCambio": transaccion.tasaCambio,
            "items": orden.get("items", []),
        }
        try:
            self.clientePasarela.enviarCobro(payload, claveIdempotencia=str(datos.ordenId))
        except PasarelaSinRespuesta as error:
            raise ErrorAplicacion(504, "La pasarela de pagos no respondió") from error

        with manejarErroresBd(mensaje503):
            self.repositorio.guardar(sesion, transaccion)
        return self._salidaPagoEnProceso(transaccion)

    # ===== HU-37: Recibir y procesar aprobación de pago =====

    def procesarNotificacion(self, sesion: Session, cuerpo: bytes, firma: str | None) -> dict:
        """Punto único del notificación de la pasarela: valida la firma HMAC y delega por estado (HU-37 / HU-38)."""
        if not firmaValida(cuerpo, firma, configuracion.SECRETO_PASARELA):
            raise ErrorAplicacion(401, MENSAJE_FIRMA_INVALIDA)
        try:
            datos = NotificacionPasarelaEntrada(**json.loads(cuerpo or b"{}"))
        except (ValueError, TypeError) as error:
            raise ErrorAplicacion(400, "El cuerpo de la notificación no es válido") from error
        estado = (datos.estado or "").upper()
        if estado == ESTADO_PASARELA_APROBADO:
            return self.procesarAprobacion(sesion, datos)
        if estado in ESTADOS_PASARELA_RECHAZO:
            return self.procesarRechazo(sesion, datos, estado)
        raise ErrorAplicacion(400, "El estado informado por la pasarela no es válido")

    def _salidaAprobacion(self, transaccion: Transaccion) -> dict:
        return respuesta(
            "Pago aprobado procesado",
            {
                "transaccionId": transaccion.transaccionId,
                "estado": transaccion.estado,
                "estadoOrden": transaccion.ordenEstado,
                "estadoDespacho": transaccion.estadoDespacho,
            },
        )

    def procesarAprobacion(self, sesion: Session, datos: NotificacionPasarelaEntrada) -> dict:
        """
        HU-37: valida monto y moneda contra la orden, registra APROBADA (idempotente), genera el
        comprobante (HU-39), notifica PAGADA (HU-40) y activa el despacho (COM-10).
        """
        mensaje503 = "No fue posible procesar la aprobación del pago"
        with manejarErroresBd(mensaje503):
            transaccion = self.repositorio.obtenerTransaccion(sesion, datos.transaccionId or "")
        if transaccion is None:
            raise ErrorAplicacion(404, MENSAJE_TX_NO_EXISTE)
        if transaccion.estado in (ESTADO_TX_APROBADA, ESTADO_TX_REQUIERE_REVISION):
            return self._salidaAprobacion(transaccion)
        if transaccion.estado != ESTADO_TX_EN_PROCESO:
            raise ErrorAplicacion(409, MENSAJE_TX_RESUELTA)

        try:
            orden = self.clienteOrdenes.obtenerOrden(sesion, transaccion.ordenId)
        except OrdenesNoDisponible as error:
            raise ErrorAplicacion(503, mensaje503) from error
        if orden is None or not montosCoinciden(datos.monto, datos.moneda, orden["total"], orden["moneda"]):
            raise ErrorAplicacion(409, "El monto o la moneda no coinciden con la orden")

        notificacion = self.notificarResultado(sesion, transaccion.ordenId, ESTADO_ORDEN_PAGADA, transaccion.transaccionId)
        confirmado = notificacion["data"]["confirmado"]

        with manejarErroresBd(mensaje503):
            transaccion.estado = ESTADO_TX_APROBADA
            transaccion.referenciaPasarela = datos.referenciaPasarela
            transaccion.resueltaEn = ahoraUtc()
            transaccion.ordenEstado = ESTADO_ORDEN_PAGADA if confirmado else None
            self.registrarComprobante(sesion, transaccion)  # HU-39 (mismo commit)
            self.repositorio.guardar(sesion, transaccion)

        if not confirmado:
            transaccion.estado = ESTADO_TX_REQUIERE_REVISION
            transaccion.estadoDespacho = "NO_ACTIVADO"
        else:
            transaccion.estadoDespacho = self._activarDespacho(sesion, transaccion, orden)
            if transaccion.estadoDespacho != "ACTIVADO":
                transaccion.estado = ESTADO_TX_REQUIERE_REVISION  # P-02
        with manejarErroresBd(mensaje503):
            self.repositorio.guardar(sesion, transaccion)
        return self._salidaAprobacion(transaccion)

    def _activarDespacho(self, sesion: Session, transaccion: Transaccion, orden: dict) -> str:
        """COM-10 ampliado hacia MOD-06. Si el despacho falla la transacción queda REQUIERE_REVISION."""
        payload = {
            "ordenId": transaccion.ordenId,
            "usuarioId": transaccion.usuarioId,
            "transaccionId": transaccion.transaccionId,
            "moneda": transaccion.moneda,
            "tasaCambio": transaccion.tasaCambio,
            "total": transaccion.monto,
            "items": [
                {
                    "juegoId": item["juegoId"],
                    "titulo": item.get("titulo"),
                    "reservaId": item["reservaId"],
                    "precioUnitario": item.get("precioUnitario"),
                }
                for item in orden.get("items", [])
            ],
        }
        try:
            self.clienteDespacho.despachar(sesion, payload)
            return "ACTIVADO"
        except Exception:  # Cualquier falla de MOD-06 deja la transacción para revisión
            sesion.rollback()
            registro.exception("Falló el despacho de la orden %s", transaccion.ordenId)
            return ESTADO_TX_REQUIERE_REVISION

    # ===== HU-38: Gestionar rechazo de pago y cancelación de orden =====

    def procesarRechazo(self, sesion: Session, datos: NotificacionPasarelaEntrada, estadoPasarela: str) -> dict:
        """
        HU-38: registra FALLIDA o EXPIRADA y delega en HU-40 la cancelación de la orden (COM-09).
        MOD-05 NO libera inventario: lo hace MOD-04 al cancelar (RN-06, COM-13).
        """
        mensaje503 = "No fue posible procesar el rechazo del pago"
        nuevoEstado = ESTADOS_PASARELA_RECHAZO[estadoPasarela]
        with manejarErroresBd(mensaje503):
            transaccion = self.repositorio.obtenerTransaccion(sesion, datos.transaccionId or "")
        if transaccion is None:
            raise ErrorAplicacion(404, MENSAJE_TX_NO_EXISTE)
        if transaccion.estado in (ESTADO_TX_APROBADA, ESTADO_TX_REQUIERE_REVISION) or (
            transaccion.estado in (ESTADO_TX_FALLIDA, ESTADO_TX_EXPIRADA) and transaccion.estado != nuevoEstado
        ):
            raise ErrorAplicacion(409, MENSAJE_TX_RESUELTA)

        if transaccion.estado == ESTADO_TX_EN_PROCESO:
            notificacion = self.notificarResultado(
                sesion, transaccion.ordenId, ESTADO_ORDEN_CANCELADA, transaccion.transaccionId
            )
            with manejarErroresBd(mensaje503):
                transaccion.estado = nuevoEstado
                transaccion.motivo = datos.motivo or estadoPasarela
                transaccion.resueltaEn = ahoraUtc()
                transaccion.ordenEstado = ESTADO_ORDEN_CANCELADA if notificacion["data"]["confirmado"] else None
                self.repositorio.guardar(sesion, transaccion)

        return respuesta(
            "Pago rechazado procesado",
            {
                "transaccionId": transaccion.transaccionId,
                "estado": transaccion.estado,
                "estadoOrden": transaccion.ordenEstado,
                "mensajeUsuario": MENSAJES_USUARIO.get(estadoPasarela, MENSAJES_USUARIO["RECHAZADO"]),
            },
        )

    def consultarEstado(self, sesion: Session, usuario: UsuarioAutenticado, transaccionId: str) -> dict:
        """HU-38: GET /pagos/{transaccionId}/estado para que el usuario conozca el resultado."""
        with manejarErroresBd("No fue posible consultar el estado del pago"):
            transaccion = self.repositorio.obtenerTransaccion(sesion, transaccionId)
        if transaccion is None or transaccion.usuarioId != usuario.id:
            raise ErrorAplicacion(404, MENSAJE_TX_NO_EXISTE)
        if transaccion.estado in (ESTADO_TX_FALLIDA, ESTADO_TX_EXPIRADA):
            clave = "EXPIRADO" if transaccion.estado == ESTADO_TX_EXPIRADA else (
                "FALLIDO" if transaccion.motivo == "FALLIDO" else "RECHAZADO"
            )
            mensajeUsuario = MENSAJES_USUARIO[clave]
        else:
            mensajeUsuario = MENSAJES_USUARIO_POR_ESTADO.get(transaccion.estado)
        return respuesta(
            "Consulta de estado de pago exitosa",
            {
                "transaccionId": transaccion.transaccionId,
                "ordenId": transaccion.ordenId,
                "estado": transaccion.estado,
                "estadoOrden": transaccion.ordenEstado,
                "mensajeUsuario": mensajeUsuario,
            },
        )

    # ===== HU-39: Registrar comprobante digital de transacción =====

    def registrarComprobante(self, sesion: Session, transaccion: Transaccion) -> Comprobante:
        """Generación automática desde HU-37: un solo comprobante por transacción APROBADA."""
        existente = self.repositorio.obtenerComprobante(sesion, transaccion.transaccionId)
        if existente is not None:
            return existente
        comprobante = Comprobante(
            comprobanteId=transaccion.transaccionId.replace("TX-", "CMP-", 1),
            transaccionId=transaccion.transaccionId,
            ordenId=transaccion.ordenId,
            usuarioId=transaccion.usuarioId,
            fecha=ahoraUtc(),
            monto=transaccion.monto,
            moneda=transaccion.moneda,
            tasaCambio=transaccion.tasaCambio,
            referenciaPasarela=transaccion.referenciaPasarela,
        )
        sesion.add(comprobante)
        return comprobante

    def consultarComprobante(self, sesion: Session, usuario: UsuarioAutenticado, transaccionId: str) -> dict:
        """HU-39: consulta del recibo en JSON (solo del propio usuario)."""
        with manejarErroresBd("No fue posible consultar el comprobante"):
            comprobante = self.repositorio.obtenerComprobante(sesion, transaccionId)
        if comprobante is None or comprobante.usuarioId != usuario.id:
            raise ErrorAplicacion(404, "No existe comprobante para la transacción indicada")
        return respuesta(
            "Consulta de comprobante exitosa",
            {
                "comprobanteId": comprobante.comprobanteId,
                "transaccionId": comprobante.transaccionId,
                "ordenId": comprobante.ordenId,
                "fecha": aIsoZ(comprobante.fecha),
                "monto": comprobante.monto,
                "moneda": comprobante.moneda,
                "tasaCambio": comprobante.tasaCambio,
                "referenciaPasarela": comprobante.referenciaPasarela,
            },
        )

    # ===== HU-40: Notificar resultado del cobro a Órdenes =====

    def notificarResultado(self, sesion: Session, ordenId: int, estado: str, transaccionId: str) -> dict:
        """
        HU-40: único punto de MOD-05 que llama a COM-09 (PATCH /interno/v1/ordenes/{ordenId}/estado).
        Idempotente por transaccionId, 3 reintentos con backoff; un 409 de MOD-04 se registra y alerta.
        """
        mensaje503 = "No fue posible notificar el resultado del cobro"
        try:
            notificacion = self.repositorio.obtenerNotificacion(sesion, transaccionId)
            if notificacion is not None and notificacion.confirmado:
                return respuesta(
                    "Resultado notificado a Órdenes",
                    {"ordenId": ordenId, "estado": notificacion.estado, "confirmado": True},
                )
            if notificacion is None:
                notificacion = NotificacionOrden(transaccionId=transaccionId, ordenId=ordenId, estado=estado)
                sesion.add(notificacion)
        except SQLAlchemyError as error:
            raise ErrorAplicacion(503, mensaje503) from error

        resultado = None
        for intento in range(1, MAXIMO_REINTENTOS_COM09 + 1):
            notificacion.intentos = (notificacion.intentos or 0) + 1
            try:
                self.clienteOrdenes.actualizarEstado(sesion, ordenId, estado, transaccionId=transaccionId)
                notificacion.confirmado, notificacion.detalle = True, None
                resultado = respuesta(
                    "Resultado notificado a Órdenes", {"ordenId": ordenId, "estado": estado, "confirmado": True}
                )
                break
            except TransicionNoPermitida:
                notificacion.confirmado, notificacion.detalle = False, "409 Transición de estado no permitida"
                registro.error("ALERTA COM-09: transición %s no permitida para la orden %s", estado, ordenId)
                resultado = respuesta(
                    "Transición de estado no permitida",
                    {"ordenId": ordenId, "estado": estado, "confirmado": False},
                    False,
                )
                break
            except OrdenesNoDisponible:
                notificacion.detalle = "MOD-04 no disponible"
                if intento < MAXIMO_REINTENTOS_COM09:
                    self.esperar(0.2 * (2 ** (intento - 1)))  # backoff exponencial: 0.2s, 0.4s
        notificacion.actualizadaEn = ahoraUtc()
        try:
            sesion.commit()
        except SQLAlchemyError as error:
            sesion.rollback()
            raise ErrorAplicacion(503, mensaje503) from error
        if resultado is None:
            raise ErrorAplicacion(503, "MOD-04 no disponible tras los reintentos")
        return resultado
