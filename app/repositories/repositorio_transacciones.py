"""
Repositorio de persistencia para MOD-05 Transacciones (HU-36 a HU-40).
"""
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.respuestas import ErrorAplicacion
from app.domain.transacciones import (
    Comprobante,
    ComprobanteORM,
    EstadoTransaccion,
    Transaccion,
    TransaccionORM,
)


class RepositorioTransacciones:
    def __init__(self, db: Session):
        self.db = db

    @staticmethod
    def _a_dominio(modelo: TransaccionORM) -> Transaccion:
        return Transaccion(
            transaccion_id=modelo.transaccion_id,
            orden_id=modelo.orden_id,
            usuario_id=modelo.usuario_id,
            metodo_pago_id=modelo.metodo_pago_id,
            monto=modelo.monto,
            moneda=modelo.moneda,
            tasa_cambio=modelo.tasa_cambio,
            estado=EstadoTransaccion(modelo.estado),
            referencia_pasarela=modelo.referencia_pasarela,
            mensaje_usuario=modelo.mensaje_usuario,
            creado_en=modelo.creado_en,
            actualizado_en=modelo.actualizado_en,
        )

    @staticmethod
    def _comprobante_a_dominio(modelo: ComprobanteORM) -> Comprobante:
        return Comprobante(
            comprobante_id=modelo.comprobante_id,
            transaccion_id=modelo.transaccion_id,
            orden_id=modelo.orden_id,
            usuario_id=modelo.usuario_id,
            fecha=modelo.fecha,
            monto=modelo.monto,
            moneda=modelo.moneda,
            tasa_cambio=modelo.tasa_cambio,
            referencia_pasarela=modelo.referencia_pasarela,
        )

    def obtener_por_orden_id(
        self,
        orden_id: int,
        mensaje_error_bd: str = "No fue posible iniciar el pago",
    ) -> Optional[Transaccion]:
        try:
            registro = (
                self.db.query(TransaccionORM)
                .filter(TransaccionORM.orden_id == orden_id)
                .first()
            )
            return self._a_dominio(registro) if registro else None
        except SQLAlchemyError as error:
            raise ErrorAplicacion(503, mensaje_error_bd) from error

    def obtener_por_transaccion_id(
        self,
        transaccion_id: str,
        mensaje_error_bd: str = "No fue posible procesar la aprobación del pago",
    ) -> Optional[Transaccion]:
        try:
            registro = (
                self.db.query(TransaccionORM)
                .filter(TransaccionORM.transaccion_id == transaccion_id)
                .first()
            )
            return self._a_dominio(registro) if registro else None
        except SQLAlchemyError as error:
            raise ErrorAplicacion(503, mensaje_error_bd) from error

    def guardar(
        self,
        transaccion: Transaccion,
        mensaje_error_bd: str = "No fue posible iniciar el pago",
    ) -> Transaccion:
        try:
            registro = TransaccionORM(
                transaccion_id=transaccion.transaccion_id,
                orden_id=transaccion.orden_id,
                usuario_id=transaccion.usuario_id,
                metodo_pago_id=transaccion.metodo_pago_id,
                monto=transaccion.monto,
                moneda=transaccion.moneda,
                tasa_cambio=transaccion.tasa_cambio,
                estado=transaccion.estado.value,
                referencia_pasarela=transaccion.referencia_pasarela,
                mensaje_usuario=transaccion.mensaje_usuario,
            )
            self.db.add(registro)
            self.db.commit()
            self.db.refresh(registro)
            return self._a_dominio(registro)
        except SQLAlchemyError as error:
            self.db.rollback()
            raise ErrorAplicacion(503, mensaje_error_bd) from error

    def actualizar_estado(
        self,
        transaccion_id: str,
        nuevo_estado: EstadoTransaccion,
        referencia_pasarela: Optional[str] = None,
        mensaje_usuario: Optional[str] = None,
        mensaje_error_bd: str = "No fue posible procesar la aprobación del pago",
    ) -> Transaccion:
        try:
            registro = (
                self.db.query(TransaccionORM)
                .filter(TransaccionORM.transaccion_id == transaccion_id)
                .first()
            )
            if registro is None:
                raise ErrorAplicacion(404, "La transacción indicada no existe")

            registro.estado = nuevo_estado.value
            if referencia_pasarela is not None:
                registro.referencia_pasarela = referencia_pasarela
            if mensaje_usuario is not None:
                registro.mensaje_usuario = mensaje_usuario
            registro.actualizado_en = datetime.now(timezone.utc)

            self.db.commit()
            self.db.refresh(registro)
            return self._a_dominio(registro)
        except ErrorAplicacion:
            raise
        except SQLAlchemyError as error:
            self.db.rollback()
            raise ErrorAplicacion(503, mensaje_error_bd) from error

    def crear_o_obtener_comprobante(
        self,
        comprobante: Comprobante,
        mensaje_error_bd: str = "No fue posible procesar la aprobación del pago",
    ) -> Comprobante:
        try:
            existente = (
                self.db.query(ComprobanteORM)
                .filter(ComprobanteORM.transaccion_id == comprobante.transaccion_id)
                .first()
            )
            if existente is not None:
                return self._comprobante_a_dominio(existente)

            nuevo = ComprobanteORM(
                comprobante_id=comprobante.comprobante_id,
                transaccion_id=comprobante.transaccion_id,
                orden_id=comprobante.orden_id,
                usuario_id=comprobante.usuario_id,
                fecha=comprobante.fecha,
                monto=comprobante.monto,
                moneda=comprobante.moneda,
                tasa_cambio=comprobante.tasa_cambio,
                referencia_pasarela=comprobante.referencia_pasarela,
            )
            self.db.add(nuevo)
            self.db.commit()
            self.db.refresh(nuevo)
            return self._comprobante_a_dominio(nuevo)
        except SQLAlchemyError as error:
            self.db.rollback()
            raise ErrorAplicacion(503, mensaje_error_bd) from error