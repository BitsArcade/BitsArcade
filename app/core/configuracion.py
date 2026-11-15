from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    APP_NAME: str = "BitArcade Backend API"
    APP_ENV: str = "development"
    APP_DEBUG: bool = True
    APP_PORT: int = 8000
    DATABASE_URL: str = "sqlite:///./dev.db"
    SECRET_KEY: str = "bitarcade_uts"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    
    # Parámetros financieros globales (MOD-00)
    TAX_RATE: float = 0.19
    DEFAULT_MARGIN: float = 0.25
    DEFAULT_CURRENCY: str = "COP"

    class Config:
        env_file = ".env"

settings = Settings()