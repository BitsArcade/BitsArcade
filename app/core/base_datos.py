from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from app.core.configuracion import settings

# Motor de conexión hacia la base de datos SQLite definida en .env
engine = create_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False}
)

# Fábrica de sesiones transaccionales por cada petición HTTP
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Clase base de la que heredarán todos nuestros modelos/tablas ORM
Base = declarative_base()

# Generador de sesión segura mediante Inyección de Dependencias
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()