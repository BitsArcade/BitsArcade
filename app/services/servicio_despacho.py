import logging
import uuid

from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.cifrado import cifrarClave, hashClave
from app.core.configuracion import configuracion
from app.core.fechas import ahoraUtc
from app.core.respuestas import ErrorAplicacion, manejarErroresBd, respuesta
from app.domain.despacho import (
    DESPACHO_ENTREGADO,
    DESPACHO_PENDIENTE_REINTENTO,
    ESTADO_ASIGNACION_ENTREGADA,
    MAXIMO_REINTENTOS_NOTIFICACION,
    PLANTILLA_DESPACHO,
    AsignacionLicencia,
    DespachoEntrada,
    NotificacionDespacho,
    RegistroCompra,
    calcularDesgloseIva,
)
from app.domain.inventario import normalizarClave
from app.repositories.repositorio_despacho import RepositorioDespacho
from app.services.cliente_notificaciones import ClienteNotificaciones, NotificacionesNoDisponible
from app.services.cliente_ordenes import (
    ESTADO_ORDEN_ENTREGADA,
    ClienteOrdenes,
    OrdenesNoDisponible,
    TransicionNoPermitida,
)
from app.services.clientes_despacho import ClienteInventarioVenta, ClienteUsuarios, InventarioVentaNoDisponible
from app.services.servicio_parametros import ServicioParametros

registro = logging.getLogger("bitarcade.despacho")

MENSAJE_YA_ENTREGADA = "La licencia ya fue entregada y no puede reasignarse"


class ServicioDespacho:
    """Capa Application / Service de MOD-06: despacho de licencias (HU-41, HU-42, HU-44, HU-45)."""

    def __init__(self):
        self.repositorio = RepositorioDespacho()
        self.clienteUsuarios = ClienteUsuarios()
        self.clienteInventario = ClienteInventarioVenta()
        self.clienteOrdenes = ClienteOrdenes("MOD-06")
        self.clienteNotificaciones = ClienteNotificaciones()
        self.servicioParametros = ServicioParametros()

    # ===== HU-41: Asignar clave digital al perfil del usuario =====

    def _salidaDespacho(self, ordenId: int, asignaciones: list[AsignacionLicencia]) -> dict:
        return respuesta(
            "Licencias asignadas exitosamente",
            {
                "ordenId": ordenId,
                "estadoDespacho": DESPACHO_ENTREGADO,
                "licencias": [{"licenciaId": a.licenciaId, "juegoId": a.juegoId} for a in asignaciones],
            },
        )

    def _tasaIvaVigente(self, sesion: Session, ordenId: int | None = None) -> float:
        """IVA congelado en la orden (RN-09); si no está disponible, el vigente de MOD-00 (COM-01)."""
        try:
            orden = self.clienteOrdenes.obtenerOrden(sesion, ordenId) if ordenId else None
            if orden and orden.get("tasaIva") is not None:
                return float(orden["tasaIva"])
        except OrdenesNoDisponible:
            pass
        try:
            return float(self.servicioParametros.obtenerContratoCom01(sesion)["tasaIva"])
        except Exception:
            return float(configuracion.TASA_IVA)

    def asignarLicencias(self, sesion: Session, datos: DespachoEntrada) -> dict:
        """
        HU-41 (COM-10): valida unicidad (HU-45), comprador (COM-05), obtiene cada clave (COM-07),
        la guarda cifrada en la asignación (ENTREGADA, revelada=false), registra la compra y dispara
        HU-42 y HU-44. Idempotente por ordenId. La respuesta nunca incluye valores de clave.
        """
        if not datos.items:
            raise ErrorAplicacion(400, "La orden no contiene ítems para despachar")
        mensaje503 = "No fue posible asignar la licencia"
        with manejarErroresBd(mensaje503):
            existente = self.repositorio.obtenerRegistroCompra(sesion, datos.ordenId)
            if existente is not None and existente.estadoDespacho == DESPACHO_ENTREGADO:
                return self._salidaDespacho(datos.ordenId, self.repositorio.listarAsignacionesOrden(sesion, datos.ordenId))

            self.validarElegibilidad(sesion, datos.ordenId, [i.reservaId for i in datos.items])  # HU-45
            comprador = self.clienteUsuarios.obtenerComprador(sesion, datos.usuarioId)
            if comprador is None:
                raise ErrorAplicacion(404, "El comprador no existe")

            registroCompra = existente or RegistroCompra(ordenId=datos.ordenId)
            base, iva = calcularDesgloseIva(datos.total, self._tasaIvaVigente(sesion, datos.ordenId), 0 if datos.moneda == "COP" else 2)
            registroCompra.usuarioId = datos.usuarioId
            registroCompra.correo = comprador["correo"]
            registroCompra.nombre = comprador["nombre"]
            registroCompra.transaccionId = datos.transaccionId
            registroCompra.moneda = datos.moneda
            registroCompra.tasaCambio = datos.tasaCambio
            registroCompra.total = datos.total
            registroCompra.baseGravable = base
            registroCompra.iva = iva
            registroCompra.estadoOrden = "PAGADA"

            yaEntregadas = {a.reservaId for a in self.repositorio.listarAsignacionesOrden(sesion, datos.ordenId)}
            nuevas = []
            for item in datos.items:
                if item.reservaId in yaEntregadas:
                    continue
                try:
                    venta = self.clienteInventario.confirmarVenta(sesion, item.reservaId)  # COM-07
                except InventarioVentaNoDisponible as error:
                    sesion.rollback()
                    registroCompra.estadoDespacho = DESPACHO_PENDIENTE_REINTENTO
                    self.repositorio.guardar(sesion, registroCompra)
                    raise ErrorAplicacion(503, "No fue posible obtener la clave del inventario") from error
                clave = normalizarClave(venta["claveLicencia"])
                nuevas.append(
                    AsignacionLicencia(
                        licenciaId=f"LIC-{uuid.uuid4().hex[:8].upper()}",
                        ordenId=datos.ordenId,
                        usuarioId=datos.usuarioId,
                        juegoId=item.juegoId,
                        titulo=item.titulo,
                        plataforma=venta.get("plataforma"),
                        reservaId=item.reservaId,
                        claveCifrada=cifrarClave(clave),
                        claveHash=hashClave(clave),
                        precioUnitarioFinal=float(item.precioUnitario or 0),
                        estado=ESTADO_ASIGNACION_ENTREGADA,
                        entregadaEn=ahoraUtc(),
                    )
                )
            registroCompra.estadoDespacho = DESPACHO_ENTREGADO
            registroCompra.entregadaEn = ahoraUtc()
            try:
                self.repositorio.guardar(sesion, registroCompra, *nuevas)
            except IntegrityError as error:  # RN-10: restricción única en BD
                sesion.rollback()
                raise ErrorAplicacion(409, MENSAJE_YA_ENTREGADA) from error

        self.marcarOrdenEntregada(sesion, datos.ordenId)   # HU-42
        self.notificarDespacho(sesion, datos.ordenId)       # HU-44
        return self._salidaDespacho(datos.ordenId, self.repositorio.listarAsignacionesOrden(sesion, datos.ordenId))

    # ===== HU-42: Marcar orden como entregada =====

    def marcarOrdenEntregada(self, sesion: Session, ordenId: int) -> dict:
        """
        HU-42: COM-09 con MOD-06 como solicitante (PATCH /interno/v1/ordenes/{ordenId}/estado),
        solo desde PAGADA, con fecha y hora exactas de despacho.
        """
        entregadaEn = ahoraUtc()
        try:
            self.clienteOrdenes.actualizarEstado(sesion, ordenId, ESTADO_ORDEN_ENTREGADA, entregadaEn=entregadaEn)
        except TransicionNoPermitida:
            registro.error("ALERTA COM-09: la orden %s no está PAGADA; no se marcó ENTREGADA", ordenId)
            return respuesta(
                "Transición de estado no permitida",
                {"ordenId": ordenId, "estado": ESTADO_ORDEN_ENTREGADA, "confirmado": False},
                False,
            )
        except OrdenesNoDisponible as error:
            raise ErrorAplicacion(503, "No fue posible marcar la orden como entregada") from error
        with manejarErroresBd("No fue posible marcar la orden como entregada"):
            registroCompra = self.repositorio.obtenerRegistroCompra(sesion, ordenId)
            if registroCompra is not None:
                registroCompra.estadoOrden = ESTADO_ORDEN_ENTREGADA
                registroCompra.entregadaEn = entregadaEn
                self.repositorio.guardar(sesion, registroCompra)
        return respuesta(
            "Orden cerrada como entregada",
            {"ordenId": ordenId, "estado": ESTADO_ORDEN_ENTREGADA, "confirmado": True},
        )

    # ===== HU-44: Notificación automática de despacho =====

    def notificarDespacho(self, sesion: Session, ordenId: int) -> dict:
        """
        HU-44: POST /external/notificaciones/despacho con la plantilla DESPACHO_CONFIRMADO.
        El correo NO contiene la clave; una falla no revierte la entrega (hasta 3 intentos).
        """
        try:
            registroCompra = self.repositorio.obtenerRegistroCompra(sesion, ordenId)
            juegos = [a.titulo for a in self.repositorio.listarAsignacionesOrden(sesion, ordenId) if a.titulo]
            notificacion = self.repositorio.obtenerNotificacion(sesion, ordenId) or NotificacionDespacho(
                ordenId=ordenId, estado="PENDIENTE", intentos=0
            )
        except SQLAlchemyError as error:
            raise ErrorAplicacion(503, "No fue posible enviar la notificación de despacho") from error
        if notificacion.estado == "ENVIADA":
            return respuesta(
                "Notificación de despacho enviada",
                {"notificacionId": notificacion.notificacionId, "estado": "ENVIADA"},
            )
        datos = {"ordenId": ordenId, "juegos": juegos}
        resultado = None
        for _ in range(MAXIMO_REINTENTOS_NOTIFICACION):
            notificacion.intentos += 1
            try:
                resultado = self.clienteNotificaciones.enviar(
                    registroCompra.correo if registroCompra else None, PLANTILLA_DESPACHO, datos
                )
                break
            except NotificacionesNoDisponible:
                continue
        notificacion.estado = "ENVIADA" if resultado else "FALLIDA"
        notificacion.notificacionId = resultado["notificacionId"] if resultado else None
        try:
            self.repositorio.guardar(sesion, notificacion)
        except SQLAlchemyError as error:
            sesion.rollback()
            raise ErrorAplicacion(503, "No fue posible enviar la notificación de despacho") from error
        if resultado is None:
            registro.warning("No fue posible notificar el despacho de la orden %s", ordenId)
            return respuesta("El servicio de notificaciones no está disponible", None, False)
        return respuesta("Notificación de despacho enviada", resultado)

    # ===== HU-45: Validar unicidad e inmutabilidad de entrega =====

    def validarElegibilidad(self, sesion: Session, ordenId: int, reservaIds: list[str]) -> dict:
        """
        HU-45 (RN-10): ninguna reserva de la orden puede figurar entregada a otra orden.
        Reintentar la misma orden es idempotente (sus ítems se informan como entregada=true).
        """
        with manejarErroresBd("No fue posible validar la entrega"):
            asignaciones = self.repositorio.obtenerAsignacionesPorReservas(sesion, reservaIds)
        porReserva = {a.reservaId: a for a in asignaciones}
        if any(a.ordenId != ordenId for a in asignaciones):
            raise ErrorAplicacion(409, MENSAJE_YA_ENTREGADA)
        return respuesta(
            "Entrega autorizada",
            {
                "ordenId": ordenId,
                "autorizado": True,
                "items": [{"reservaId": r, "entregada": r in porReserva} for r in dict.fromkeys(reservaIds)],
            },
        )
