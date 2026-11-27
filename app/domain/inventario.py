"""
Modelo PROVISIONAL de inventario de keys (MOD-03) usado por el contrato COM-12.

MOD-03 (HU-11 a HU-15) es responsabilidad de otro desarrollador. Este modelo mínimo solo
existe para que MOD-02 (HU-25) y MOD-04 (HU-26, HU-29) puedan consultar el stock disponible
mientras MOD-03 no esté integrado. Cuando MOD-03 publique su entidad definitiva, basta con
adaptar `ClienteInventario` (app/services/cliente_inventario.py) y retirar este archivo.
Nunca se almacena ni se expone aquí el valor de la key.
"""
from sqlalchemy import Column, ForeignKey, Integer, String
from sqlalchemy.orm import synonym

from app.core.base_datos import Base

ESTADO_KEY_DISPONIBLE = "DISPONIBLE"
ESTADO_KEY_RESERVADA = "RESERVADA"
ESTADO_KEY_VENDIDA = "VENDIDA"


class KeyLicencia(Base):
    """Licencia digital de un juego con su estado de inventario (DISPONIBLE, RESERVADA, VENDIDA)."""
    __tablename__ = "keys_licencia"

    id = Column(Integer, primary_key=True, index=True)
    juego_id = Column(Integer, ForeignKey("juegos.id"), nullable=False, index=True)
    plataforma = Column(String(20), nullable=True)
    estado = Column(String(20), nullable=False, default=ESTADO_KEY_DISPONIBLE)

    # Nombre de atributo según la convención actualizada (camelCase); la columna física se conserva.
    juegoId = synonym("juego_id")


# ===== Nombres según la convención actualizada (HU ajustadas): "clave" en lugar de "key" =====
ESTADO_CLAVE_DISPONIBLE = ESTADO_KEY_DISPONIBLE
ESTADO_CLAVE_RESERVADA = ESTADO_KEY_RESERVADA
ESTADO_CLAVE_VENDIDA = ESTADO_KEY_VENDIDA
ESTADOS_CLAVE = (ESTADO_CLAVE_DISPONIBLE, ESTADO_CLAVE_RESERVADA, ESTADO_CLAVE_VENDIDA)
ClaveLicencia = KeyLicencia
