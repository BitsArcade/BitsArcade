"""
Repositorio de persistencia para MOD-06 Despacho y Biblioteca (HU-41 a HU-50).
"""
import hashlib
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import asc, desc, or_
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.respuestas import ErrorAplicacion
from app.domain.despacho import (
    DespachoOrden,
    DespachoOrdenORM,
    EstadoDespacho,
    LicenciaUsuario,
    LicenciaUsuarioORM,
)
from app.domain.inventario import KeyLicencia


class RepositorioDespacho:
    def __init__(self, db: Session):
        self.db = db

    @staticmethod
    def _normalizar_fecha(valor: Optional[datetime]) -> Optional[datetime]:
        if valor is None:
            return None
        if valor.tzinfo is None:
            return valor.replace(tzinfo=timezone.utc)
        return valor

    @classmethod
    def _a_entidad_licencia(cls, orm: LicenciaUsuarioORM) -> LicenciaUsuario:
        return LicenciaUsuario(
            licencia_id=orm.licencia_id,
            despacho_id=orm.despacho_id,
            orden_id=orm.orden_id,
            usuario_id=orm.usuario_id,
            juego_id=orm.juego_id,
            titulo_juego=orm.titulo_juego,
            plataforma=orm.plataforma,
            reserva_id=orm.reserva_id,
            key_inventario_id=orm.key_inventario_id,
            clave_digital=orm.clave_digital,
            clave_enmascarada=orm.clave_enmascarada,
            revelada=bool(orm.revelada),
            revelada_en=cls._normalizar_fecha(orm.revelada_en),
            asignada_en=cls._normalizar_fecha(orm.asignada_en)
            or datetime.now(timezone.utc),
            precio_unitario=float(getattr(orm, "precio_unitario", 0.0) or 0.0),
        )

    @classmethod
    def _a_entidad_despacho(
        cls, orm: DespachoOrdenORM, licencias_orm: list[LicenciaUsuarioORM]
    ) -> DespachoOrden:
        try:
            estado = EstadoDespacho(orm.estado)
        except ValueError:
            estado = EstadoDespacho.ACTIVADO

        return DespachoOrden(
            despacho_id=orm.despacho_id,
            orden_id=orm.orden_id,
            usuario_id=orm.usuario_id,
            transaccion_id=orm.transaccion_id,
            estado=estado,
            notificado_externo=bool(orm.notificado_externo),
            creado_en=cls._normalizar_fecha(orm.creado_en)
            or datetime.now(timezone.utc),
            licencias=[cls._a_entidad_licencia(lic) for lic in licencias_orm],
            moneda=getattr(orm, "moneda", "COP") or "COP",
            tasa_cambio=float(getattr(orm, "tasa_cambio", 1.0) or 1.0),
            total=float(getattr(orm, "total", 0.0) or 0.0),
        )

    def obtener_despacho_por_orden_id(
        self,
        orden_id: int,
        mensaje_error_bd: str = "No fue posible procesar el despacho de la orden",
    ) -> Optional[DespachoOrden]:
        try:
            despacho_orm = (
                self.db.query(DespachoOrdenORM)
                .filter(DespachoOrdenORM.orden_id == orden_id)
                .first()
            )
            if despacho_orm is None:
                return None

            licencias_orm = (
                self.db.query(LicenciaUsuarioORM)
                .filter(LicenciaUsuarioORM.orden_id == orden_id)
                .order_by(LicenciaUsuarioORM.id.asc())
                .all()
            )
            return self._a_entidad_despacho(despacho_orm, licencias_orm)
        except SQLAlchemyError as error:
            raise ErrorAplicacion(503, mensaje_error_bd) from error

    def guardar_despacho_con_licencias(
        self, despacho: DespachoOrden
    ) -> DespachoOrden:
        try:
            despacho_orm = DespachoOrdenORM(
                despacho_id=despacho.despacho_id,
                orden_id=despacho.orden_id,
                usuario_id=despacho.usuario_id,
                transaccion_id=despacho.transaccion_id,
                moneda=despacho.moneda,
                tasa_cambio=despacho.tasa_cambio,
                total=despacho.total,
                estado=despacho.estado.value,
                notificado_externo=despacho.notificado_externo,
                creado_en=despacho.creado_en,
            )
            self.db.add(despacho_orm)

            licencias_orm: list[LicenciaUsuarioORM] = []
            for lic in despacho.licencias:
                huella = hashlib.sha256(
                    f"{lic.orden_id}:{lic.juego_id}:{lic.clave_digital}".encode("utf-8")
                ).hexdigest()
                lic_orm = LicenciaUsuarioORM(
                    licencia_id=lic.licencia_id,
                    despacho_id=lic.despacho_id,
                    orden_id=lic.orden_id,
                    usuario_id=lic.usuario_id,
                    juego_id=lic.juego_id,
                    titulo_juego=lic.titulo_juego,
                    plataforma=lic.plataforma,
                    precio_unitario=lic.precio_unitario,
                    reserva_id=lic.reserva_id,
                    key_inventario_id=lic.key_inventario_id,
                    clave_digital=lic.clave_digital,
                    clave_enmascarada=lic.clave_enmascarada,
                    huella_clave=huella,
                    revelada=lic.revelada,
                    revelada_en=lic.revelada_en,
                    asignada_en=lic.asignada_en,
                )
                self.db.add(lic_orm)
                licencias_orm.append(lic_orm)

            self.db.commit()
            self.db.refresh(despacho_orm)
            for item in licencias_orm:
                self.db.refresh(item)
            return self._a_entidad_despacho(despacho_orm, licencias_orm)
        except IntegrityError as error:
            self.db.rollback()
            raise ErrorAplicacion(
                409, "La licencia ya fue entregada y no puede reasignarse"
            ) from error
        except SQLAlchemyError as error:
            self.db.rollback()
            raise ErrorAplicacion(
                503, "No fue posible procesar el despacho de la orden"
            ) from error

    def obtener_licencia_por_id(
        self, licencia_id: str
    ) -> Optional[LicenciaUsuario]:
        try:
            lic_orm = (
                self.db.query(LicenciaUsuarioORM)
                .filter(LicenciaUsuarioORM.licencia_id == licencia_id)
                .first()
            )
            if lic_orm is None:
                return None
            return self._a_entidad_licencia(lic_orm)
        except SQLAlchemyError as error:
            raise ErrorAplicacion(
                503, "No fue posible revelar la clave digital"
            ) from error

    def registrar_revelacion_licencia(
        self, licencia_id: str, fecha_revelacion: datetime
    ) -> Optional[LicenciaUsuario]:
        try:
            lic_orm = (
                self.db.query(LicenciaUsuarioORM)
                .filter(LicenciaUsuarioORM.licencia_id == licencia_id)
                .first()
            )
            if lic_orm is None:
                return None

            if not lic_orm.revelada or lic_orm.revelada_en is None:
                lic_orm.revelada = True
                lic_orm.revelada_en = fecha_revelacion
                self.db.commit()
                self.db.refresh(lic_orm)

            return self._a_entidad_licencia(lic_orm)
        except SQLAlchemyError as error:
            self.db.rollback()
            raise ErrorAplicacion(
                503, "No fue posible revelar la clave digital"
            ) from error

    def listarComprasPorUsuarioYRango(
        self,
        usuarioId: int,
        fechaDesde: datetime,
        fechaHastaExclusiva: datetime,
        orden: str,
    ) -> list[DespachoOrden]:
        fechaDesdeUtc = fechaDesde.astimezone(timezone.utc).replace(tzinfo=None)
        fechaHastaUtc = (
            fechaHastaExclusiva.astimezone(timezone.utc).replace(tzinfo=None)
        )
        direccion = asc if orden == "asc" else desc
        try:
            filas = (
                self.db.query(DespachoOrdenORM)
                .filter(
                    DespachoOrdenORM.usuario_id == usuarioId,
                    DespachoOrdenORM.creado_en >= fechaDesdeUtc,
                    DespachoOrdenORM.creado_en < fechaHastaUtc,
                )
                .order_by(
                    direccion(DespachoOrdenORM.creado_en),
                    direccion(DespachoOrdenORM.orden_id),
                )
                .all()
            )
            return [self._a_entidad_despacho(fila, []) for fila in filas]
        except SQLAlchemyError as error:
            raise ErrorAplicacion(
                503, "No fue posible consultar el historial"
            ) from error

    def listar_licencias_por_usuario(
        self,
        usuario_id: int,
        mensajeErrorBd: str = "No fue posible consultar la biblioteca de licencias",
    ) -> list[LicenciaUsuario]:
        try:
            filas = (
                self.db.query(LicenciaUsuarioORM)
                .filter(LicenciaUsuarioORM.usuario_id == usuario_id)
                .order_by(
                    LicenciaUsuarioORM.asignada_en.desc(),
                    LicenciaUsuarioORM.id.desc(),
                )
                .all()
            )
            return [self._a_entidad_licencia(fila) for fila in filas]
        except SQLAlchemyError as error:
            raise ErrorAplicacion(503, mensajeErrorBd) from error

    def obtener_reservas_y_keys_de_orden(
        self,
        orden_id: int,
        mensaje_error_bd: str = "No fue posible validar la entrega",
    ) -> tuple[list[str], list[int]]:
        try:
            reservas: list[str] = []
            key_ids: list[int] = []

            asignaciones = (
                self.db.query(LicenciaUsuarioORM)
                .filter(LicenciaUsuarioORM.orden_id == orden_id)
                .all()
            )
            for asig in asignaciones:
                if asig.reserva_id and asig.reserva_id not in reservas:
                    reservas.append(asig.reserva_id)
                if asig.key_inventario_id and asig.key_inventario_id not in key_ids:
                    key_ids.append(asig.key_inventario_id)

            if hasattr(KeyLicencia, "orden_id"):
                keys = (
                    self.db.query(KeyLicencia)
                    .filter(KeyLicencia.orden_id == orden_id)
                    .all()
                )
                for key_obj in keys:
                    if key_obj.id and key_obj.id not in key_ids:
                        key_ids.append(key_obj.id)
                    reserva_key = getattr(key_obj, "reserva_id", None)
                    if reserva_key and reserva_key not in reservas:
                        reservas.append(reserva_key)

            return reservas, key_ids
        except SQLAlchemyError as error:
            raise ErrorAplicacion(503, mensaje_error_bd) from error

    def consultar_asignaciones_previas(
        self,
        orden_id: int,
        reserva_ids: Optional[list[str]] = None,
        key_ids: Optional[list[int]] = None,
        mensaje_error_bd: str = "No fue posible validar la entrega",
    ) -> list[LicenciaUsuario]:
        try:
            condiciones = [LicenciaUsuarioORM.orden_id == orden_id]
            if reserva_ids:
                condiciones.append(LicenciaUsuarioORM.reserva_id.in_(reserva_ids))
            if key_ids:
                condiciones.append(LicenciaUsuarioORM.key_inventario_id.in_(key_ids))

            filas = (
                self.db.query(LicenciaUsuarioORM)
                .filter(or_(*condiciones))
                .order_by(LicenciaUsuarioORM.id.asc())
                .all()
            )
            return [self._a_entidad_licencia(fila) for fila in filas]
        except SQLAlchemyError as error:
            raise ErrorAplicacion(503, mensaje_error_bd) from error