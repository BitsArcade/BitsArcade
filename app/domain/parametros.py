from sqlalchemy import Column, Integer, String, Float
from pydantic import BaseModel, Field, field_validator
from app.core.base_datos import Base

# =====================================================================
# 1. ENTIDADES DE DOMINIO (Mapeo de tablas para SQLite)
# =====================================================================

class Moneda(Base):
    """Representa las monedas aceptadas en BitArcade (HU-01, HU-02)."""
    __tablename__ = "monedas"

    id = Column(Integer, primary_key=True, index=True)
    codigo_iso = Column(String(3), unique=True, index=True, nullable=False)
    nombre = Column(String(50), nullable=False)
    tasa_cambio_usd = Column(Float, nullable=False, default=1.0)
    estado = Column(String(20), nullable=False, default="Activo")


class ConfiguracionFinanciera(Base):
    """Centraliza IVA, margen de ganancia (markup) y moneda base (HU-03, HU-04, COM-01, COM-02)."""
    __tablename__ = "configuracion_financiera"

    id = Column(Integer, primary_key=True, index=True)
    tasa_iva = Column(Float, nullable=False, default=19.0)
    margen_ganancia = Column(Float, nullable=False, default=25.0)
    moneda_base = Column(String(3), nullable=False, default="COP")


class MetodoPago(Base):
    """Representa los medios de pago habilitados en la tienda (HU-05)."""
    __tablename__ = "metodos_pago"

    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String(50), unique=True, nullable=False)
    estado = Column(String(20), nullable=False, default="Activo")


# =====================================================================
# 2. ESQUEMAS DE VALIDACIÓN Y REGLAS DE DOMINIO (Pydantic DTOs)
# =====================================================================

class CrearMonedaEntrada(BaseModel):
    """Contrato de entrada para HU-01 (FUN-00.1.1: Registrar nueva moneda)."""
    codigo_iso: str = Field(..., min_length=3, max_length=3, examples=["EUR"])
    nombre: str = Field(..., min_length=3, max_length=50, examples=["Euro"])
    tasa_cambio_usd: float = Field(default=1.0, gt=0, examples=[0.92])

    @field_validator("codigo_iso")
    @classmethod
    def normalizar_codigo_iso(cls, valor: str) -> str:
        if not valor.isalpha():
            raise ValueError("El código ISO debe contener únicamente 3 letras (ej. COP, USD).")
        return valor.upper()


class MonedaSalida(BaseModel):
    """Contrato de salida para HU-01 y HU-02."""
    id: int
    codigo_iso: str
    nombre: str
    tasa_cambio_usd: float
    estado: str

    class Config:
        from_attributes = True


class ActualizarIvaEntrada(BaseModel):
    """Contrato de entrada para HU-03 (PRO-00.1.3: Validar IVA entre 0 y 100)."""
    tasa_iva: float = Field(..., ge=0, le=100, examples=[19.0])


class ActualizarMargenEntrada(BaseModel):
    """Contrato de entrada para HU-04 (PRO-00.1.4: Validar markup > 0 y proteger RN-02)."""
    margen_ganancia: float = Field(..., gt=0, examples=[25.0])


class CrearMetodoPagoEntrada(BaseModel):
    """Contrato de entrada auxiliar para crear métodos de pago."""
    nombre: str = Field(..., min_length=2, max_length=50, examples=["Efecty"])


class MetodoPagoSalida(BaseModel):
    """Contrato de salida para HU-05 (Inactivación lógica de método de pago)."""
    id: int
    nombre: str
    estado: str

    class Config:
        from_attributes = True