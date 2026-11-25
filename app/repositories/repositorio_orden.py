from datetime import datetime
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.domain.orden import (
    ESTADO_ORDEN_ENTREGADA,
    ESTADOS_ORDEN_ACTIVAS_PREVENTA,
    ItemOrden,
    Orden,
)


class RepositorioOrden:
    """Capa Repository de Órdenes (MOD-04)."""

    def crear_orden(self, sesion: Session, orden: Orden) -> Orden:
        sesion.add(orden)
        sesion.commit()
        sesion.refresh(orden)
        return orden

    def obtener_por_id(self, sesion: Session, orden_id: int) -> Orden | None:
        return sesion.query(Orden).filter(Orden.id == orden_id).first()

    def obtener_por_id_y_usuario(self, sesion: Session, orden_id: int, usuario_id: int) -> Orden | None:
        return (
            sesion.query(Orden)
            .filter(Orden.id == orden_id, Orden.usuario_id == usuario_id)
            .first()
        )

    def listar_por_usuario(self, sesion: Session, usuario_id: int, estado: str | None = None) -> list[Orden]:
        consulta = sesion.query(Orden).filter(Orden.usuario_id == usuario_id)
        if estado:
            consulta = consulta.filter(Orden.estado == estado)
        return consulta.order_by(Orden.id.desc()).all()

    def contar_licencias_no_canceladas(self, sesion: Session, usuario_id: int, juego_id: int) -> int:
        total = (
            sesion.query(func.coalesce(func.sum(ItemOrden.cantidad), 0))
            .join(Orden, Orden.id == ItemOrden.orden_id)
            .filter(
                Orden.usuario_id == usuario_id,
                Orden.estado.in_(ESTADOS_ORDEN_ACTIVAS_PREVENTA),
                ItemOrden.juego_id == juego_id,
            )
            .scalar()
        )
        return int(total or 0)

    def actualizar_estado(
        self,
        sesion: Session,
        orden: Orden,
        nuevo_estado: str,
        entregada_en: Optional[datetime] = None,
    ) -> Orden:
        orden.estado = nuevo_estado
        if nuevo_estado == ESTADO_ORDEN_ENTREGADA and entregada_en is not None:
            orden.entregada_en = entregada_en
        sesion.commit()
        sesion.refresh(orden)
        return orden