"""
Cliente del contrato COM-10 (MOD-05 → MOD-06 Despacho).

MOD-06 se ejecuta en el mismo proceso: se invoca su capa de servicio directamente. Si MOD-06 se
separa, este cliente se reemplaza por POST /interno/v1/despacho/ordenes manteniendo la firma.
"""
from sqlalchemy.orm import Session


class ClienteDespacho:
    def despachar(self, sesion: Session, payload: dict) -> dict:
        from app.domain.despacho import DespachoEntrada
        from app.services.servicio_despacho import ServicioDespacho

        return ServicioDespacho().asignarLicencias(sesion, DespachoEntrada(**payload))
