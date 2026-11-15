from sqlalchemy import Column, Integer, String, Float, Boolean
from pydantic import BaseModel, Field, field_validator
from app.core.database import Base

# =====================================================================
# 1. ENTIDADES DE DOMINIO (Mapeo de tablas para SQLite)
# =====================================================================

class Moneda(Base):
    """Representa las monedas aceptadas en BitArcade (HU-01, HU-02)."""
    __tablename__ = "monedas"

    id = Column(Integer, primary_key=True, index=True)
    codigo_iso = Column(String(3), unique=True, index=True, nullable=False)  # Ej: COP, USD
    nombre = Column(String(50), nullable=False)                              # Ej: Peso Colombiano
    tasa_cambio_usd = Column(Float, nullable=False, default=1.0)             # Referencia para COM-03
    estado = Column(String(20), nullable=False, default="Activo")            # "Activo" o "Inactivo"


class ConfiguracionFinanciera(Base):
    """Centraliza IVA, margen de ganancia (markup) y moneda base (HU-03, HU-04, COM-01, COM-02)."""
    __tablename__ = "configuracion_financiera"

    id = Column(Integer, primary_key=True, index=True)
    tasa_iva = Column(Float, nullable=False, default=19.0)         # Porcentaje entre 0 y 100 (PRO-00.1.3)
    margen_ganancia = Column(Float, nullable=False, default=25.0)  # Porcentaje > 0 (PRO-00.1.4)
    moneda_base = Column(String(3), nullable=False, default="COP") # Moneda vigente para COM-02


class MetodoPago(Base):
    """Representa los medios de pago habilitados en la tienda (HU-05)."""
    __tablename__ = "metodos_pago"

    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String(50), unique=True, nullable=False)       # Ej: Tarjeta Crédito, PSE, Nequi
    estado = Column(String(20), nullable=False, default="Activo")  # "Activo" o "Inactivo" (borrado lógico)


# =====================================================================
# 2. ESQUEMAS DE VALIDACIÓN Y REGLAS DE DOMINIO (Pydantic DTOs)
# =====================================================================

class MonedaCreate(BaseModel):
    """Contrato de entrada para HU-01 (FUN-00.1.1: Registrar nueva moneda)."""
    codigo_iso: str = Field(..., min_length=3, max_length=3, examples=["USD"])
    nombre: str = Field(..., min_length=3, max_length=50, examples=["Dólar Estadounidense"])
    tasa_cambio_usd: float = Field(default=1.0, gt=0, examples=[1.0])

    @field_validator("codigo_iso")
    @classmethod
    def normalizar_codigo_iso(cls, v: str) -> str:
        if not v.isalpha():
            raise ValueError("El código ISO debe contener únicamente 3 letras (ej. COP, USD).")
        return v.upper()


class MonedaResponse(BaseModel):
    """Contrato de salida para HU-01 y HU-02."""
    id: int
    codigo_iso: str
    nombre: str
    tasa_cambio_usd: float
    estado: str

    class Config:
        from_attributes = True


class ActualizarIvaRequest(BaseModel):
    """Contrato de entrada para HU-03 (PRO-00.1.3: Validar IVA entre 0 y 100)."""
    tasa_iva: float = Field(..., ge=0, le=100, examples=[19.0])


class ActualizarMargenRequest(BaseModel):
    """Contrato de entrada para HU-04 (PRO-00.1.4: Validar markup > 0 y proteger RN-02)."""
    margen_ganancia: float = Field(..., gt=0, examples=[25.0])


class MetodoPagoCreate(BaseModel):
    """Contrato de entrada auxiliar para crear métodos de pago de prueba."""
    nombre: str = Field(..., min_length=2, max_length=50, examples=["PSE"])


class MetodoPagoResponse(BaseModel):
    """Contrato de salida para HU-05 (Inactivación lógica de método de pago)."""
    id: int
    nombre: str
    estado: str

    class Config:
        from_attributes = True