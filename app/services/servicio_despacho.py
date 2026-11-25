"""
Servicio de aplicación para MOD-06 Despacho y Biblioteca (HU-41 a HU-43).
"""
import uuid
from datetime import datetime, timezone
from typing import Any, Optional, Protocol

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.respuestas import ErrorAplicacion
from app.domain.despacho import (
    INSTRUCCION_ACTIVACION_ESTANDAR,
    DespachoOrden,
    EstadoDespacho,
    LicenciaUsuario,
    ReglasDespacho,
    SolicitudDespachoCOM10,
)
from app.domain.inventario import KeyLicencia
from app.domain.orden import Orden
from app.repositories.repositorio_despacho import RepositorioDespacho
from app.services.servicio_orden import ServicioOrden


class AdaptadorOrdenYInventarioDespacho(Protocol):
    def validar_y_confirmar_keys(
        self, solicitud: SolicitudDespachoCOM10
    ) -> list[dict[str, Any]]:
        """
        Verifica que la orden exista en estado PAGADA y confirma la entrega de las
        licencias en inventario (RESERVADA -> VENDIDA), retornando metadatos por ítem.
        """
        ...


class AdaptadorOrdenesCOM09(Protocol):
    def marcar_orden_entregada(
        self, orden_id: int, entregada_en: datetime
    ) -> dict[str, Any]:
        """
        Invoca COM-09 (PATCH /interno/v1/ordenes/{ordenId}/estado) en MOD-04
        para transicionar la orden de PAGADA a ENTREGADA (HU-42).
        """
        ...


class AdaptadorOrdenesLocalCOM09:
    """Adaptador interno de MOD-06 hacia MOD-04 (COM-09) para HU-42."""

    def __init__(self, db: Session, servicio_orden: Optional[ServicioOrden] = None):
        self.db = db
        self.servicio_orden = servicio_orden or ServicioOrden()

    def marcar_orden_entregada(
        self, orden_id: int, entregada_en: datetime
    ) -> dict[str, Any]:
        return self.servicio_orden.marcar_orden_como_entregada(
            sesion=self.db,
            orden_id=orden_id,
            entregada_en=entregada_en,
        )


class AdaptadorOrdenYInventarioLocal:
    """Adaptador local hacia MOD-04 (Orden) e Inventario (KeyLicencia) para HU-41."""

    def __init__(self, db: Session):
        self.db = db

    @staticmethod
    def _extraer_fecha_expiracion(instancia: Any) -> datetime | None:
        for col in instancia.__table__.columns:
            if "expir" in col.name or "hasta" in col.name:
                valor = getattr(instancia, col.name, None)
                if isinstance(valor, datetime):
                    return valor
        return None

    def validar_y_confirmar_keys(
        self, solicitud: SolicitudDespachoCOM10
    ) -> list[dict[str, Any]]:
        try:
            orden = self.db.query(Orden).filter(Orden.id == solicitud.ordenId).first()
            if orden is None or orden.usuario_id != solicitud.usuarioId:
                raise ErrorAplicacion(404, "La orden indicada no existe")

            ReglasDespacho.validar_orden_elegible_despacho(orden.estado)

            ahora = datetime.now(timezone.utc)
            expira_orden = self._extraer_fecha_expiracion(orden)
            if expira_orden is not None:
                expira_utc = (
                    expira_orden.replace(tzinfo=timezone.utc)
                    if expira_orden.tzinfo is None
                    else expira_orden
                )
                if expira_utc < ahora:
                    raise ErrorAplicacion(
                        409,
                        "La reserva de inventario expiró; el despacho requiere revisión manual",
                    )

            resultados: list[dict[str, Any]] = []
            tiene_col_orden_id = hasattr(KeyLicencia, "orden_id")

            for item in solicitud.items:
                consulta = self.db.query(KeyLicencia).filter(
                    KeyLicencia.juego_id == item.juegoId,
                    KeyLicencia.estado == "RESERVADA",
                )
                if tiene_col_orden_id:
                    consulta_orden = consulta.filter(
                        KeyLicencia.orden_id == solicitud.ordenId
                    ).first()
                    key_obj = consulta_orden or consulta.first()
                else:
                    key_obj = consulta.first()

                if key_obj is None:
                    key_obj = (
                        self.db.query(KeyLicencia)
                        .filter(
                            KeyLicencia.juego_id == item.juegoId,
                            KeyLicencia.estado == "DISPONIBLE",
                        )
                        .first()
                    )

                if key_obj is None:
                    self.db.rollback()
                    raise ErrorAplicacion(
                        409,
                        "No hay claves reservadas disponibles para despachar la orden",
                    )

                expira_key = self._extraer_fecha_expiracion(key_obj)
                if expira_key is not None:
                    expira_key_utc = (
                        expira_key.replace(tzinfo=timezone.utc)
                        if expira_key.tzinfo is None
                        else expira_key
                    )
                    if expira_key_utc < ahora:
                        self.db.rollback()
                        raise ErrorAplicacion(
                            409,
                            "La reserva de inventario expiró; el despacho requiere revisión manual",
                        )

                key_obj.estado = "VENDIDA"
                resultados.append(
                    {
                        "juegoId": item.juegoId,
                        "titulo": item.titulo,
                        "reservaId": item.reservaId,
                        "keyInventarioId": key_obj.id,
                        "plataforma": getattr(key_obj, "plataforma", "PC") or "PC",
                    }
                )

            self.db.flush()
            return resultados
        except ErrorAplicacion:
            raise
        except SQLAlchemyError as error:
            self.db.rollback()
            raise ErrorAplicacion(
                503, "No fue posible procesar el despacho de la orden"
            ) from error


class ServicioDespacho:
    def __init__(
        self,
        repositorio: RepositorioDespacho,
        adaptador_inventario: Optional[AdaptadorOrdenYInventarioDespacho] = None,
        adaptador_ordenes: Optional[AdaptadorOrdenesCOM09] = None,
    ):
        self.repositorio = repositorio
        self.adaptador_inventario = adaptador_inventario
        if adaptador_ordenes is not None:
            self.adaptador_ordenes = adaptador_ordenes
        elif adaptador_inventario is not None and hasattr(adaptador_inventario, "db"):
            self.adaptador_ordenes = AdaptadorOrdenesLocalCOM09(adaptador_inventario.db)
        else:
            self.adaptador_ordenes = None

    @staticmethod
    def _serializar_despacho(despacho: DespachoOrden) -> dict[str, Any]:
        return {
            "despachoId": despacho.despacho_id,
            "ordenId": despacho.orden_id,
            "usuarioId": despacho.usuario_id,
            "transaccionId": despacho.transaccion_id,
            "estadoDespacho": despacho.estado.value,
            "licenciasAsignadas": [
                {
                    "licenciaId": lic.licencia_id,
                    "juegoId": lic.juego_id,
                    "titulo": lic.titulo_juego,
                    "plataforma": lic.plataforma,
                    "claveEnmascarada": lic.clave_enmascarada,
                    "revelada": lic.revelada,
                    "asignadaEn": lic.asignada_en.isoformat(),
                }
                for lic in despacho.licencias
            ],
        }

    def marcar_orden_como_entregada(
        self,
        orden_id: int,
        entregada_en: Optional[datetime] = None,
    ) -> dict[str, Any]:
        """
        HU-42 / COM-09: Notifica a MOD-04 que las licencias fueron asignadas y
        cierra formalmente la orden en estado ENTREGADA.
        """
        if self.adaptador_ordenes is None:
            raise ErrorAplicacion(
                503, "No fue posible marcar la orden como entregada"
            )
        fecha_entrega = entregada_en or datetime.now(timezone.utc)
        return self.adaptador_ordenes.marcar_orden_entregada(
            orden_id=orden_id,
            entregada_en=fecha_entrega,
        )

    def ejecutar_despacho_com10(
        self, solicitud: SolicitudDespachoCOM10
    ) -> dict[str, Any]:
        """
        HU-41 / COM-10 + HU-42 / COM-09: Asigna de forma idempotente e inmutable una
        licencia digital al perfil del usuario por cada ítem de la orden pagada y
        cierra la orden como ENTREGADA.
        """
        existente = self.repositorio.obtener_despacho_por_orden_id(solicitud.ordenId)
        if existente is not None:
            return self._serializar_despacho(existente)

        if self.adaptador_inventario is None:
            raise ErrorAplicacion(
                503, "No fue posible procesar el despacho de la orden"
            )

        items_confirmados = self.adaptador_inventario.validar_y_confirmar_keys(solicitud)

        ahora = datetime.now(timezone.utc)
        despacho_id = f"DSP-{uuid.uuid4().hex[:8].upper()}"
        licencias: list[LicenciaUsuario] = []

        for idx, item_conf in enumerate(items_confirmados, start=1):
            clave_plana, clave_enmascarada, _ = ReglasDespacho.generar_clave_digital(
                orden_id=solicitud.ordenId,
                juego_id=item_conf["juegoId"],
                indice=idx,
            )
            licencias.append(
                LicenciaUsuario(
                    licencia_id=f"LIC-{uuid.uuid4().hex[:8].upper()}",
                    despacho_id=despacho_id,
                    orden_id=solicitud.ordenId,
                    usuario_id=solicitud.usuarioId,
                    juego_id=item_conf["juegoId"],
                    titulo_juego=item_conf["titulo"],
                    plataforma=item_conf["plataforma"],
                    reserva_id=item_conf["reservaId"],
                    key_inventario_id=item_conf["keyInventarioId"],
                    clave_digital=clave_plana,
                    clave_enmascarada=clave_enmascarada,
                    revelada=False,
                    revelada_en=None,
                    asignada_en=ahora,
                )
            )

        nuevo_despacho = DespachoOrden(
            despacho_id=despacho_id,
            orden_id=solicitud.ordenId,
            usuario_id=solicitud.usuarioId,
            transaccion_id=solicitud.transaccionId,
            estado=EstadoDespacho.ACTIVADO,
            notificado_externo=False,
            creado_en=ahora,
            licencias=licencias,
        )
        guardado = self.repositorio.guardar_despacho_con_licencias(nuevo_despacho)

        # HU-42: Tras asignar las licencias de la orden pagada, cerrarla como ENTREGADA vía COM-09
        if self.adaptador_ordenes is not None:
            self.marcar_orden_como_entregada(
                orden_id=solicitud.ordenId,
                entregada_en=ahora,
            )

        return self._serializar_despacho(guardado)

    def revelar_clave_licencia(
        self,
        licencia_id: str,
        usuario_id: int,
    ) -> dict[str, Any]:
        """
        HU-43: Revela de forma segura la clave digital de una licencia perteneciente
        al usuario autenticado, formateada en grupos de 4 caracteres con guiones,
        registrando auditoría de visualización (reveladaEn).
        """
        licencia = self.repositorio.obtener_licencia_por_id(licencia_id)
        licencia_validada = ReglasDespacho.validar_propiedad_licencia(
            licencia=licencia,
            usuario_id=usuario_id,
        )

        clave_formateada = ReglasDespacho.formatear_clave_legible(
            licencia_validada.clave_digital
        )

        ahora = datetime.now(timezone.utc)
        actualizada = self.repositorio.registrar_revelacion_licencia(
            licencia_id=licencia_validada.licencia_id,
            fecha_revelacion=ahora,
        )
        licencia_final = actualizada or licencia_validada
        fecha_iso = (
            licencia_final.revelada_en.isoformat()
            if licencia_final.revelada_en is not None
            else ahora.isoformat()
        )

        return {
            "licenciaId": licencia_final.licencia_id,
            "juegoId": licencia_final.juego_id,
            "claveFormateada": clave_formateada,
            "instruccionActivacion": INSTRUCCION_ACTIVACION_ESTANDAR,
            "reveladaEn": fecha_iso,
        }