"""
Repositorio de persistencia para MOD-06 Despacho (HU-41 a HU-46).
"""
import hashlib
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.respuestas import ErrorAplicacion
from app.domain.despacho import (
    DespachoOrden,
    DespachoOrdenORM,
    EstadoDespacho,
    LicenciaUsuario,
    LicenciaUsuarioORM,
)


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
        """HU-44: Lista todas las licencias digitales asignadas al usuario autenticado."""
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