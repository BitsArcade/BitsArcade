"""
Servicio de aplicación para MOD-05 Transacciones (HU-36, HU-37, HU-38, HU-39 y HU-40).
"""
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, Optional, Protocol

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.configuracion import settings
from app.core.respuestas import ErrorAplicacion
from app.domain.orden import Orden
from app.domain.transacciones import (
    Comprobante,
    EstadoTransaccion,
    OrdenParaCobro,
    ReglasTransaccion,
    SolicitudNotificacionPasarela,
    Transaccion,
)
from app.repositories.repositorio_transacciones import RepositorioTransacciones


class ErrorReservaExpiradaDespacho(Exception):
    """Indica que la reserva expiró al intentar activar el despacho COM-10 (P-02)."""


class AdaptadorOrdenesCOM(Protocol):
    async def obtener_orden_com08(self, orden_id: int) -> Optional[OrdenParaCobro]:
        """Contrato COM-08: obtiene datos congelados de la orden en MOD-04."""
        ...

    async def marcar_orden_procesando_com09(self, orden_id: int) -> bool:
        """Contrato COM-09: cambia estado de la orden a PROCESANDO."""
        ...

    async def notificar_resultado_com09(
        self, orden_id: int, nuevo_estado: str, transaccion_id: str
    ) -> bool:
        """Contrato COM-09 (HU-40): cambia orden a PAGADA o CANCELADA."""
        ...


class ClientePasarelaPagos(Protocol):
    async def transmitir_cobro(self, payload: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
        """API externa de Pagos simulada con Idempotency-Key = ordenId."""
        ...


class AdaptadorDespachoCOM10(Protocol):
    async def activar_despacho_com10(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Contrato COM-10 ampliado hacia MOD-06 Despacho."""
        ...


class AdaptadorOrdenesLocal:
    """Implementación sobre MOD-04 (COM-08 / COM-09 / HU-40)."""

    def __init__(self, db: Session):
        self.db = db

    async def obtener_orden_com08(self, orden_id: int) -> Optional[OrdenParaCobro]:
        try:
            orden = self.db.query(Orden).filter(Orden.id == orden_id).first()
            if orden is None:
                return None

            items_serializados = [
                {
                    "juegoId": getattr(item, "juego_id", None),
                    "titulo": getattr(item, "titulo", f"Juego #{getattr(item, 'juego_id', '')}"),
                    "reservaId": getattr(item, "reserva_id", None),
                    "precioUnitario": float(getattr(item, "precio_unitario", 0.0)),
                }
                for item in getattr(orden, "items", [])
            ]

            tasa = getattr(
                orden,
                "tasa_cambio_congelada",
                getattr(orden, "tasa_cambio", 1.0),
            )
            expira = getattr(
                orden,
                "fecha_expiracion_reserva",
                getattr(orden, "expira_en", None),
            )

            return OrdenParaCobro(
                orden_id=orden.id,
                usuario_id=orden.usuario_id,
                estado=orden.estado,
                total=float(orden.total),
                moneda=orden.moneda,
                tasa_cambio=float(tasa),
                expira_en=expira,
                items=items_serializados,
            )
        except SQLAlchemyError as error:
            raise ErrorAplicacion(503, "No fue posible iniciar el pago") from error

    async def marcar_orden_procesando_com09(self, orden_id: int) -> bool:
        try:
            orden = self.db.query(Orden).filter(Orden.id == orden_id).first()
            if orden is None or orden.estado != "PENDIENTE":
                return False
            orden.estado = "PROCESANDO"
            self.db.commit()
            return True
        except SQLAlchemyError as error:
            self.db.rollback()
            raise ErrorAplicacion(503, "No fue posible iniciar el pago") from error

    async def notificar_resultado_com09(
        self, orden_id: int, nuevo_estado: str, transaccion_id: str
    ) -> bool:
        """
        HU-40 / COM-09: Actualiza la orden a PAGADA o CANCELADA de forma idempotente,
        delegando a ServicioOrden.actualizar_estado_interno cuando está disponible
        para liberar claves reservadas en inventario al cancelar.
        """
        mensaje_bd = (
            "No fue posible procesar el rechazo del pago"
            if nuevo_estado == "CANCELADA"
            else "No fue posible procesar la aprobación del pago"
        )
        try:
            orden = self.db.query(Orden).filter(Orden.id == orden_id).first()
            if orden is None:
                return False

            debe_transicionar = ReglasTransaccion.validar_transicion_orden_com09(
                orden.estado, nuevo_estado
            )
            if not debe_transicionar:
                return True

            # Delegar a MOD-04 (ServicioOrden.actualizar_estado_interno) si está disponible
            try:
                from app.services.servicio_orden import ServicioOrden

                entrada = SimpleNamespace(
                    estado=nuevo_estado,
                    nuevoEstado=nuevo_estado,
                    transaccionId=transaccion_id,
                )
                ServicioOrden.actualizar_estado_interno(self.db, orden_id, entrada)
                return True
            except (ImportError, TypeError, AttributeError):
                orden.estado = nuevo_estado
                self.db.commit()
                return True
        except ErrorAplicacion:
            raise
        except SQLAlchemyError as error:
            self.db.rollback()
            raise ErrorAplicacion(503, mensaje_bd) from error


class ClientePasarelaSimulada:
    """Cliente simulado de la API externa de Pagos."""

    async def transmitir_cobro(
        self, payload: dict[str, Any], idempotency_key: str
    ) -> dict[str, Any]:
        return {
            "recibido": True,
            "idempotencyKey": idempotency_key,
            "transaccionId": payload["transaccionId"],
            "estado": "EN_PROCESO",
        }


class AdaptadorDespachoLocal:
    """Adaptador COM-10 hacia MOD-06 Despacho."""

    async def activar_despacho_com10(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "ordenId": payload["ordenId"],
            "estadoDespacho": "ACTIVADO",
        }


class ServicioTransacciones:
    def __init__(
        self,
        repositorio: RepositorioTransacciones,
        adaptador_ordenes: AdaptadorOrdenesCOM,
        cliente_pasarela: ClientePasarelaPagos,
        adaptador_despacho: Optional[AdaptadorDespachoCOM10] = None,
        secreto_webhook: Optional[str] = None,
    ):
        self.repositorio = repositorio
        self.adaptador_ordenes = adaptador_ordenes
        self.cliente_pasarela = cliente_pasarela
        self.adaptador_despacho = adaptador_despacho or AdaptadorDespachoLocal()
        self.secreto_webhook = secreto_webhook or getattr(
            settings, "PASARELA_WEBHOOK_SECRET", settings.SECRET_KEY
        )

    @staticmethod
    def _serializar_comprobante(comprobante: Comprobante) -> dict[str, Any]:
        fecha_utc = (
            comprobante.fecha.replace(tzinfo=timezone.utc)
            if comprobante.fecha.tzinfo is None
            else comprobante.fecha
        )
        return {
            "comprobanteId": comprobante.comprobante_id,
            "transaccionId": comprobante.transaccion_id,
            "ordenId": comprobante.orden_id,
            "fecha": fecha_utc.isoformat(),
            "monto": comprobante.monto,
            "moneda": comprobante.moneda,
            "tasaCambio": comprobante.tasa_cambio,
            "referenciaPasarela": comprobante.referencia_pasarela,
        }

    async def iniciar_cobro(
        self,
        orden_id: int,
        metodo_pago_id: int,
        usuario_id: int,
    ) -> Transaccion:
        # 1. Idempotencia: si ya existe transacción para este ordenId, validar dueño y retornar
        existente = self.repositorio.obtener_por_orden_id(orden_id)
        if existente is not None:
            if existente.usuario_id != usuario_id:
                raise ErrorAplicacion(404, "La orden indicada no existe")
            return existente

        # 2. Obtener datos congelados de la orden vía COM-08
        orden = await self.adaptador_ordenes.obtener_orden_com08(orden_id)
        if orden is None:
            raise ErrorAplicacion(404, "La orden indicada no existe")

        # 3. Validar dueño, estado PENDIENTE y vigencia >= 2 minutos
        ReglasTransaccion.validar_orden_cobrable(orden, usuario_id)

        # 4. Cambiar estado de la orden a PROCESANDO vía COM-09 (HU-35)
        actualizada = await self.adaptador_ordenes.marcar_orden_procesando_com09(orden_id)
        if not actualizada:
            raise ErrorAplicacion(409, "La orden no está disponible para pago")

        # 5. Construir payload con tasa congelada (RN-09) y enviar con Idempotency-Key = ordenId
        transaccion_id = f"TX-{uuid.uuid4().hex[:8].upper()}"
        payload = ReglasTransaccion.construir_payload_pasarela(
            transaccion_id=transaccion_id,
            orden=orden,
            metodo_pago_id=metodo_pago_id,
        )

        try:
            await self.cliente_pasarela.transmitir_cobro(
                payload=payload,
                idempotency_key=str(orden_id),
            )
        except TimeoutError as error:
            raise ErrorAplicacion(504, "La pasarela de pagos no respondió") from error
        except ErrorAplicacion:
            raise
        except Exception as error:
            raise ErrorAplicacion(503, "No fue posible iniciar el pago") from error

        # 6. Registrar transacción EN_PROCESO
        nueva_transaccion = Transaccion(
            transaccion_id=transaccion_id,
            orden_id=orden.orden_id,
            usuario_id=usuario_id,
            metodo_pago_id=metodo_pago_id,
            monto=orden.total,
            moneda=orden.moneda,
            tasa_cambio=orden.tasa_cambio,
            estado=EstadoTransaccion.EN_PROCESO,
        )
        return self.repositorio.guardar(nueva_transaccion)

    async def procesar_notificacion_pasarela(
        self,
        cuerpo_crudo: bytes,
        firma_hmac: Optional[str],
        notificacion: SolicitudNotificacionPasarela,
    ) -> tuple[str, dict[str, Any]]:
        estado_entrante = notificacion.estado.strip().upper()
        if estado_entrante == "APROBADO":
            datos = await self.procesar_aprobacion_pasarela(
                cuerpo_crudo=cuerpo_crudo,
                firma_hmac=firma_hmac,
                notificacion=notificacion,
            )
            return "Pago aprobado procesado", datos

        if estado_entrante in ReglasTransaccion.MAPEO_ESTADOS_NO_EXITOSOS:
            return await self.procesar_rechazo_pasarela(
                cuerpo_crudo=cuerpo_crudo,
                firma_hmac=firma_hmac,
                notificacion=notificacion,
            )

        ReglasTransaccion.verificar_firma_hmac(
            cuerpo_crudo=cuerpo_crudo,
            firma_recibida=firma_hmac,
            secreto=self.secreto_webhook,
        )
        raise ErrorAplicacion(400, "Estado de notificación de pasarela no soportado")

    async def procesar_aprobacion_pasarela(
        self,
        cuerpo_crudo: bytes,
        firma_hmac: Optional[str],
        notificacion: SolicitudNotificacionPasarela,
    ) -> dict[str, str]:
        # 1. Validar firma HMAC en X-Signature (401 si es inválida o ausente)
        ReglasTransaccion.verificar_firma_hmac(
            cuerpo_crudo=cuerpo_crudo,
            firma_recibida=firma_hmac,
            secreto=self.secreto_webhook,
        )

        # 2. Consultar transacción (404 si transaccionId es desconocido)
        transaccion = self.repositorio.obtener_por_transaccion_id(
            notificacion.transaccionId,
            mensaje_error_bd="No fue posible procesar la aprobación del pago",
        )
        if transaccion is None:
            raise ErrorAplicacion(404, "La transacción indicada no existe")

        # 3. Idempotencia: si ya está APROBADA, retornar resultado consistente sin duplicar
        if transaccion.estado == EstadoTransaccion.APROBADA:
            return {
                "transaccionId": transaccion.transaccion_id,
                "estado": EstadoTransaccion.APROBADA.value,
                "estadoOrden": "PAGADA",
                "estadoDespacho": "ACTIVADO",
            }

        # 4. Validar estado previo y coincidencia de monto y moneda (409)
        ReglasTransaccion.validar_aprobacion_pasarela(
            transaccion=transaccion,
            monto_notificado=notificacion.monto,
            moneda_notificada=notificacion.moneda,
        )

        # 5. Actualizar transacción a APROBADA
        transaccion_aprobada = self.repositorio.actualizar_estado(
            transaccion_id=transaccion.transaccion_id,
            nuevo_estado=EstadoTransaccion.APROBADA,
            referencia_pasarela=notificacion.referenciaPasarela,
            mensaje_error_bd="No fue posible procesar la aprobación del pago",
        )

        # 6. Generar comprobante digital inmutable (HU-39, único por transacción)
        comprobante = Comprobante(
            comprobante_id=f"CMP-{uuid.uuid4().hex[:8].upper()}",
            transaccion_id=transaccion_aprobada.transaccion_id,
            orden_id=transaccion_aprobada.orden_id,
            usuario_id=transaccion_aprobada.usuario_id,
            fecha=datetime.now(timezone.utc),
            monto=transaccion_aprobada.monto,
            moneda=transaccion_aprobada.moneda,
            tasa_cambio=transaccion_aprobada.tasa_cambio,
            referencia_pasarela=transaccion_aprobada.referencia_pasarela,
        )
        self.repositorio.crear_o_obtener_comprobante(
            comprobante,
            mensaje_error_bd="No fue posible procesar la aprobación del pago",
        )

        # 7. Delegar a HU-40 actualización de la orden a PAGADA (COM-09)
        await self.adaptador_ordenes.notificar_resultado_com09(
            orden_id=transaccion_aprobada.orden_id,
            nuevo_estado="PAGADA",
            transaccion_id=transaccion_aprobada.transaccion_id,
        )

        # 8. Activar despacho con COM-10 (si la reserva expiró, marcar REQUIERE_REVISION - P-02)
        orden = await self.adaptador_ordenes.obtener_orden_com08(transaccion_aprobada.orden_id)
        items_orden = orden.items if orden is not None else []
        orden_para_com10 = OrdenParaCobro(
            orden_id=transaccion_aprobada.orden_id,
            usuario_id=transaccion_aprobada.usuario_id,
            estado="PAGADA",
            total=transaccion_aprobada.monto,
            moneda=transaccion_aprobada.moneda,
            tasa_cambio=transaccion_aprobada.tasa_cambio,
            expira_en=datetime.now(timezone.utc),
            items=items_orden,
        )
        payload_com10 = ReglasTransaccion.construir_payload_com10(
            transaccion=transaccion_aprobada,
            orden=orden_para_com10,
        )

        try:
            await self.adaptador_despacho.activar_despacho_com10(payload_com10)
            return {
                "transaccionId": transaccion_aprobada.transaccion_id,
                "estado": EstadoTransaccion.APROBADA.value,
                "estadoOrden": "PAGADA",
                "estadoDespacho": "ACTIVADO",
            }
        except ErrorReservaExpiradaDespacho:
            self.repositorio.actualizar_estado(
                transaccion_id=transaccion_aprobada.transaccion_id,
                nuevo_estado=EstadoTransaccion.REQUIERE_REVISION,
                mensaje_usuario="Pago aprobado pero la reserva expiró; requiere revisión manual (P-02).",
                mensaje_error_bd="No fue posible procesar la aprobación del pago",
            )
            return {
                "transaccionId": transaccion_aprobada.transaccion_id,
                "estado": EstadoTransaccion.REQUIERE_REVISION.value,
                "estadoOrden": "PAGADA",
                "estadoDespacho": "REQUIERE_REVISION",
            }

    async def procesar_rechazo_pasarela(
        self,
        cuerpo_crudo: bytes,
        firma_hmac: Optional[str],
        notificacion: SolicitudNotificacionPasarela,
    ) -> tuple[str, dict[str, str]]:
        # 1. Validar firma HMAC en X-Signature (401 si es inválida o ausente)
        ReglasTransaccion.verificar_firma_hmac(
            cuerpo_crudo=cuerpo_crudo,
            firma_recibida=firma_hmac,
            secreto=self.secreto_webhook,
        )

        # 2. Mapear estado no exitoso (RECHAZADO/FALLIDO -> FALLIDA, EXPIRADO -> EXPIRADA)
        estado_destino, mensaje_respuesta, mensaje_usuario = (
            ReglasTransaccion.mapear_rechazo_pasarela(notificacion.estado)
        )

        # 3. Consultar transacción (404 si transaccionId es desconocido)
        transaccion = self.repositorio.obtener_por_transaccion_id(
            notificacion.transaccionId,
            mensaje_error_bd="No fue posible procesar el rechazo del pago",
        )
        if transaccion is None:
            raise ErrorAplicacion(404, "La transacción indicada no existe")

        # 4. Idempotencia si ya fue resuelta con el mismo estado terminal
        if transaccion.estado == estado_destino:
            return mensaje_respuesta, {
                "transaccionId": transaccion.transaccion_id,
                "estado": estado_destino.value,
                "estadoOrden": "CANCELADA",
                "mensajeUsuario": transaccion.mensaje_usuario or mensaje_usuario,
            }

        # 5. Si ya fue resuelta con otro estado (ej. APROBADA), lanzar 409
        if transaccion.estado != EstadoTransaccion.EN_PROCESO:
            raise ErrorAplicacion(409, "La transacción ya fue resuelta con otro estado")

        # 6. Registrar transacción FALLIDA o EXPIRADA
        transaccion_actualizada = self.repositorio.actualizar_estado(
            transaccion_id=transaccion.transaccion_id,
            nuevo_estado=estado_destino,
            referencia_pasarela=notificacion.referenciaPasarela,
            mensaje_usuario=mensaje_usuario,
            mensaje_error_bd="No fue posible procesar el rechazo del pago",
        )

        # 7. Delegar a HU-40 la cancelación de la orden (COM-09 CANCELADA; MOD-04 libera claves)
        await self.adaptador_ordenes.notificar_resultado_com09(
            orden_id=transaccion_actualizada.orden_id,
            nuevo_estado="CANCELADA",
            transaccion_id=transaccion_actualizada.transaccion_id,
        )

        return mensaje_respuesta, {
            "transaccionId": transaccion_actualizada.transaccion_id,
            "estado": estado_destino.value,
            "estadoOrden": "CANCELADA",
            "mensajeUsuario": mensaje_usuario,
        }

    def consultar_estado_transaccion(
        self,
        transaccion_id: str,
        usuario_id: int,
    ) -> dict[str, Any]:
        transaccion = self.repositorio.obtener_por_transaccion_id(
            transaccion_id,
            mensaje_error_bd="No fue posible consultar el estado del pago",
        )
        if transaccion is None or transaccion.usuario_id != usuario_id:
            raise ErrorAplicacion(404, "La transacción indicada no existe")

        return {
            "transaccionId": transaccion.transaccion_id,
            "ordenId": transaccion.orden_id,
            "estado": transaccion.estado.value,
            "mensajeUsuario": ReglasTransaccion.obtener_mensaje_usuario(transaccion),
        }

    def consultar_comprobante_por_transaccion(
        self,
        transaccion_id: str,
        usuario_id: int,
    ) -> dict[str, Any]:
        """HU-39: Consulta el comprobante digital inmutable asociado a una transacción aprobada."""
        transaccion = self.repositorio.obtener_por_transaccion_id(
            transaccion_id,
            mensaje_error_bd="No fue posible consultar el comprobante",
        )
        if transaccion is None or transaccion.usuario_id != usuario_id:
            raise ErrorAplicacion(404, "La transacción indicada no existe")

        ReglasTransaccion.validar_comprobante_disponible(transaccion)

        comprobante = self.repositorio.obtener_comprobante_por_transaccion_id(
            transaccion_id,
            mensaje_error_bd="No fue posible consultar el comprobante",
        )
        if comprobante is None:
            raise ErrorAplicacion(404, "El comprobante indicado no existe")

        return self._serializar_comprobante(comprobante)

    def consultar_comprobante_por_id(
        self,
        comprobante_id: str,
        usuario_id: int,
    ) -> dict[str, Any]:
        """HU-39: Consulta un comprobante digital directamente por su comprobanteId."""
        comprobante = self.repositorio.obtener_comprobante_por_id(
            comprobante_id,
            mensaje_error_bd="No fue posible consultar el comprobante",
        )
        if comprobante is None or comprobante.usuario_id != usuario_id:
            raise ErrorAplicacion(404, "El comprobante indicado no existe")

        return self._serializar_comprobante(comprobante)

    async def sincronizar_estado_final_orden(
        self,
        transaccion_id: str,
        usuario_id: int,
    ) -> dict[str, Any]:
        """
        HU-40: Sincroniza de forma idempotente el estado final de la orden (PAGADA o CANCELADA)
        vía COM-09 según el resultado terminal registrado en la transacción.
        """
        transaccion = self.repositorio.obtener_por_transaccion_id(
            transaccion_id,
            mensaje_error_bd="No fue posible actualizar el estado final de la orden",
        )
        if transaccion is None or transaccion.usuario_id != usuario_id:
            raise ErrorAplicacion(404, "La transacción indicada no existe")

        estado_orden_destino = ReglasTransaccion.mapear_estado_final_orden(transaccion.estado)

        actualizada = await self.adaptador_ordenes.notificar_resultado_com09(
            orden_id=transaccion.orden_id,
            nuevo_estado=estado_orden_destino,
            transaccion_id=transaccion.transaccion_id,
        )
        if not actualizada:
            raise ErrorAplicacion(404, "La orden indicada no existe")

        return {
            "transaccionId": transaccion.transaccion_id,
            "ordenId": transaccion.orden_id,
            "estadoTransaccion": transaccion.estado.value,
            "estadoOrden": estado_orden_destino,
            "sincronizado": True,
        }