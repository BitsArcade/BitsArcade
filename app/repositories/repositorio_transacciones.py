"""
Repositorio de persistencia para MOD-05 Transacciones.
"""
from typing import Optional

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.respuestas import ErrorAplicacion
from app.domain.transacciones import (
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

    def obtener_por_orden_id(self, orden_id: int) -> Optional[Transaccion]:
        try:
            registro = (
                self.db.query(TransaccionORM)
                .filter(TransaccionORM.orden_id == orden_id)
                .first()
            )
            return self._a_dominio(registro) if registro else None
        except SQLAlchemyError as error:
            raise ErrorAplicacion(503, "No fue posible iniciar el pago") from error

    def guardar(self, transaccion: Transaccion) -> Transaccion:
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
            raise ErrorAplicacion(503, "No fue posible iniciar el pago") from error