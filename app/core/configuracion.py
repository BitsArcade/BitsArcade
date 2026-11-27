"""
Configuración global de BitArcade (pydantic-settings).

Los nombres de los campos están en español (UPPER_SNAKE). Para no romper los archivos .env
existentes se aceptan también los nombres anteriores en inglés (APP_NAME, DATABASE_URL,
SECRET_KEY, ACCESS_TOKEN_EXPIRE_MINUTES) como alias de lectura.
Los porcentajes (TASA_IVA, MARGEN_GANANCIA) se expresan de 0 a 100 (19 = 19 %).
"""
from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Configuracion(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    NOMBRE_APLICACION: str = Field("BitArcade Backend API", validation_alias=AliasChoices("NOMBRE_APLICACION", "APP_NAME"))
    ENTORNO: str = Field("development", validation_alias=AliasChoices("ENTORNO", "APP_ENV"))
    DEPURACION: bool = Field(True, validation_alias=AliasChoices("DEPURACION", "APP_DEBUG"))
    PUERTO: int = Field(8000, validation_alias=AliasChoices("PUERTO", "APP_PORT"))
    URL_BASE_DATOS: str = Field("sqlite:///./dev.db", validation_alias=AliasChoices("URL_BASE_DATOS", "DATABASE_URL"))
    CLAVE_SECRETA: str = Field("cambiar-en-env", validation_alias=AliasChoices("CLAVE_SECRETA", "SECRET_KEY"))
    MINUTOS_EXPIRACION_TOKEN: int = Field(
        30, validation_alias=AliasChoices("MINUTOS_EXPIRACION_TOKEN", "ACCESS_TOKEN_EXPIRE_MINUTES")
    )

    # Parámetros financieros iniciales (MOD-00, TT-02). Porcentajes de 0 a 100.
    TASA_IVA: float = 19.0
    MARGEN_GANANCIA: float = 25.0
    MONEDA_BASE: str = "COP"

    # Secreto HMAC compartido con la pasarela de pagos simulada (HU-37 / HU-38).
    SECRETO_PASARELA: str = "bitarcade-pasarela-simulada"
    # Token de servicio exigido en las rutas /interno/v1 (header X-Token-Servicio).
    TOKEN_SERVICIO: str = "bitarcade-token-servicio-local"


configuracion = Configuracion()


# ===== Compatibilidad temporal =====
# Los módulos que aún no migran a la convención (MOD-00 y MOD-04 órdenes) leen `settings` con los
# nombres anteriores en inglés y los porcentajes en decimal (0.19). Se conserva hasta que migren.
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    APP_NAME: str = "BitArcade Backend API"
    APP_ENV: str = "development"
    APP_DEBUG: bool = True
    APP_PORT: int = 8000
    DATABASE_URL: str = "sqlite:///./dev.db"
    SECRET_KEY: str = "cambiar-en-env"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    # Parámetros financieros globales (MOD-00)
    TAX_RATE: float = 0.19
    DEFAULT_MARGIN: float = 0.25
    DEFAULT_CURRENCY: str = "COP"


settings = Settings()
