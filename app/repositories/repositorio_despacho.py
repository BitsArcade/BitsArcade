"""
Repositorio de persistencia para MOD-06 Despacho (HU-41 a HU-50).
"""
import hashlib
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import or_
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
from app.domain.orden import Orden


class RepositorioDespacho:
    def __init__(self, db: Session):
        self.db = db

    @staticmethod
    def _licencia_a_dominio(modelo: LicenciaUsuarioORM) -> LicenciaUsuario:
        asignada_utc = (
            modelo.asignada_en.replace(tzinfo=timezone.utc)
            if modelo.asignada_en.tzinfo is None
            else modelo.asignada_en
        )
        revelada_utc = None
        if modelo.revelada_en is not None:
            revelada_utc = (
                modelo.revelada_en.replace(tzinfo=timezone.utc)
                if modelo.revelada_en.tzinfo is None
                else modelo.revelada_en
            )
        return LicenciaUsuario(
            licencia_id=modelo.licencia_id,
            despacho_id=modelo.despacho_id,
            orden_id=modelo.orden_id,
            usuario_id=modelo.usuario_id,
            juego_id=modelo.juego_id,
            titulo_juego=modelo.titulo_juego,
            plataforma=modelo.plataforma,
            reserva_id=modelo.reserva_id,
            key_inventario_id=modelo.key_inventario_id,
            clave_digital=modelo.clave_digital,
            clave_enmascarada=modelo.clave_enmascarada,
            revelada=modelo.revelada,
            revelada_en=revelada_utc,
            asignada_en=asignada_utc,
        )

    def _despacho_a_dominio(self, modelo: DespachoOrdenORM) -> DespachoOrden:
        creado_utc = (
            modelo.creado_en.replace(tzinfo=timezone.utc)
            if modelo.creado_en.tzinfo is None
            else modelo.creado_en
        )
        registros_licencias = (
            self.db.query(LicenciaUsuarioORM)
            .filter(LicenciaUsuarioORM.despacho_id == modelo.despacho_id)
            .order_by(LicenciaUsuarioORM.id.asc())
            .all()
        )
        return DespachoOrden(
            despacho_id=modelo.despacho_id,
            orden_id=modelo.orden_id,
            usuario_id=modelo.usuario_id,
            transaccion_id=modelo.transaccion_id,
            estado=EstadoDespacho(modelo.estado),
            notificado_externo=modelo.notificado_externo,
            creado_en=creado_utc,
            licencias=[self._licencia_a_dominio(lic) for lic in registros_licencias],
        )

    def obtener_despacho_por_orden_id(
        self,
        orden_id: int,
        mensaje_error_bd: str = "No fue posible procesar el despacho de la orden",
    ) -> Optional[DespachoOrden]:
        try:
            registro = (
                self.db.query(DespachoOrdenORM)
                .filter(DespachoOrdenORM.orden_id == orden_id)
                .first()
            )
            return self._despacho_a_dominio(registro) if registro else None
        except SQLAlchemyError as error:
            raise ErrorAplicacion(503, mensaje_error_bd) from error

    def guardar_despacho_con_licencias(
        self,
        despacho: DespachoOrden,
        mensaje_error_bd: str = "No fue posible procesar el despacho de la orden",
    ) -> DespachoOrden:
        try:
            existente = (
                self.db.query(DespachoOrdenORM)
                .filter(DespachoOrdenORM.orden_id == despacho.orden_id)
                .first()
            )
            if existente is not None:
                return self._despacho_a_dominio(existente)

            nuevo_despacho = DespachoOrdenORM(
                despacho_id=despacho.despacho_id,
                orden_id=despacho.orden_id,
                usuario_id=despacho.usuario_id,
                transaccion_id=despacho.transaccion_id,
                estado=despacho.estado.value,
                notificado_externo=despacho.notificado_externo,
                creado_en=despacho.creado_en,
            )
            self.db.add(nuevo_despacho)

            for lic in despacho.licencias:
                semilla_huella = (
                    f"{lic.orden_id}:{lic.juego_id}:{lic.licencia_id}:{lic.clave_digital}"
                )
                huella = hashlib.sha256(semilla_huella.encode("utf-8")).hexdigest()
                nueva_licencia = LicenciaUsuarioORM(
                    licencia_id=lic.licencia_id,
                    despacho_id=despacho.despacho_id,
                    orden_id=lic.orden_id,
                    usuario_id=lic.usuario_id,
                    juego_id=lic.juego_id,
                    titulo_juego=lic.titulo_juego,
                    plataforma=lic.plataforma,
                    reserva_id=lic.reserva_id,
                    key_inventario_id=lic.key_inventario_id,
                    clave_digital=lic.clave_digital,
                    clave_enmascarada=lic.clave_enmascarada,
                    huella_clave=huella,
                    revelada=lic.revelada,
                    revelada_en=lic.revelada_en,
                    asignada_en=lic.asignada_en,
                )
                self.db.add(nueva_licencia)

            self.db.commit()
            self.db.refresh(nuevo_despacho)
            return self._despacho_a_dominio(nuevo_despacho)
        except IntegrityError as error:
            self.db.rollback()
            raise ErrorAplicacion(
                409, "La licencia ya fue entregada y no puede reasignarse"
            ) from error
        except SQLAlchemyError as error:
            self.db.rollback()
            raise ErrorAplicacion(503, mensaje_error_bd) from error

    def obtener_licencia_por_id(
        self,
        licencia_id: str,
        mensaje_error_bd: str = "No fue posible revelar la clave digital",
    ) -> Optional[LicenciaUsuario]:
        """HU-43: Consulta una licencia asignada por su identificador público (licenciaId)."""
        try:
            registro = (
                self.db.query(LicenciaUsuarioORM)
                .filter(LicenciaUsuarioORM.licencia_id == licencia_id)
                .first()
            )
            return self._licencia_a_dominio(registro) if registro else None
        except SQLAlchemyError as error:
            raise ErrorAplicacion(503, mensaje_error_bd) from error

    def registrar_revelacion_licencia(
        self,
        licencia_id: str,
        fecha_revelacion: datetime,
        mensaje_error_bd: str = "No fue posible revelar la clave digital",
    ) -> Optional[LicenciaUsuario]:
        """
        HU-43: Registra auditoría de visualización (revelada=True, revelada_en)
        sin modificar la clave digital inmutable.
        """
        try:
            registro = (
                self.db.query(LicenciaUsuarioORM)
                .filter(LicenciaUsuarioORM.licencia_id == licencia_id)
                .first()
            )
            if registro is None:
                return None

            registro.revelada = True
            registro.revelada_en = fecha_revelacion
            self.db.commit()
            self.db.refresh(registro)
            return self._licencia_a_dominio(registro)
        except SQLAlchemyError as error:
            self.db.rollback()
            raise ErrorAplicacion(503, mensaje_error_bd) from error

    def listar_licencias_por_usuario(
        self,
        usuario_id: int,
        mensaje_error_bd: str = "No fue posible consultar la biblioteca de licencias",
    ) -> list[LicenciaUsuario]:
        """Lista todas las licencias digitales asignadas al usuario autenticado."""
        try:
            registros = (
                self.db.query(LicenciaUsuarioORM)
                .filter(LicenciaUsuarioORM.usuario_id == usuario_id)
                .order_by(LicenciaUsuarioORM.asignada_en.desc(), LicenciaUsuarioORM.id.desc())
                .all()
            )
            return [self._licencia_a_dominio(reg) for reg in registros]
        except SQLAlchemyError as error:
            raise ErrorAplicacion(503, mensaje_error_bd) from error

    def obtener_reservas_y_keys_de_orden(
        self,
        orden_id: int,
        mensaje_error_bd: str = "No fue posible validar la entrega",
    ) -> tuple[list[str], list[int]]:
        """
        HU-45: Obtiene los reservaId y key_inventario_id vinculados a una orden
        consultando tanto asignaciones previas como reservas en inventario/orden.
        """
        try:
            reserva_ids: list[str] = []
            key_ids: list[int] = []

            def _agregar_reserva(valor: Optional[str]) -> None:
                if valor and valor not in reserva_ids:
                    reserva_ids.append(valor)

            def _agregar_key(valor: Optional[int]) -> None:
                if isinstance(valor, int) and valor not in key_ids:
                    key_ids.append(valor)

            # 1. Asignaciones ya registradas en MOD-06 para esta orden
            asignaciones_orden = (
                self.db.query(LicenciaUsuarioORM)
                .filter(LicenciaUsuarioORM.orden_id == orden_id)
                .order_by(LicenciaUsuarioORM.id.asc())
                .all()
            )
            for asig in asignaciones_orden:
                _agregar_reserva(asig.reserva_id)
                _agregar_key(asig.key_inventario_id)

            # 2. Claves reservadas en MOD-03 asociadas a esta orden
            if hasattr(KeyLicencia, "orden_id"):
                keys_orden = (
                    self.db.query(KeyLicencia)
                    .filter(KeyLicencia.orden_id == orden_id)
                    .order_by(KeyLicencia.id.asc())
                    .all()
                )
                for key_obj in keys_orden:
                    _agregar_key(getattr(key_obj, "id", None))
                    _agregar_reserva(
                        getattr(key_obj, "reserva_id", None)
                        or getattr(key_obj, "codigo_reserva", None)
                    )

            # 3. Líneas/ítems de la orden en MOD-04 si tienen reserva_id
            orden_obj = self.db.query(Orden).filter(Orden.id == orden_id).first()
            if orden_obj is not None:
                for attr_relacion in ("items", "detalles", "lineas"):
                    coleccion = getattr(orden_obj, attr_relacion, None)
                    if isinstance(coleccion, list):
                        for linea in coleccion:
                            _agregar_reserva(getattr(linea, "reserva_id", None))

            return reserva_ids, key_ids
        except SQLAlchemyError as error:
            raise ErrorAplicacion(503, mensaje_error_bd) from error

    def consultar_asignaciones_previas(
        self,
        orden_id: int,
        reserva_ids: list[str],
        key_ids: Optional[list[int]] = None,
        mensaje_error_bd: str = "No fue posible validar la entrega",
    ) -> list[LicenciaUsuario]:
        """
        HU-45: Busca en licencias_usuario cualquier entrega previa asociada a la orden,
        a alguno de los reservaId o a alguna key_inventario_id.
        """
        try:
            condiciones = [LicenciaUsuarioORM.orden_id == orden_id]
            if reserva_ids:
                condiciones.append(LicenciaUsuarioORM.reserva_id.in_(reserva_ids))
            if key_ids:
                condiciones.append(LicenciaUsuarioORM.key_inventario_id.in_(key_ids))

            registros = (
                self.db.query(LicenciaUsuarioORM)
                .filter(or_(*condiciones))
                .order_by(LicenciaUsuarioORM.id.asc())
                .all()
            )
            return [self._licencia_a_dominio(reg) for reg in registros]
        except SQLAlchemyError as error:
            raise ErrorAplicacion(503, mensaje_error_bd) from error