from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from app.core.configuracion import configuracion

# Motor de conexión hacia la base de datos SQLite definida en .env
motor = create_engine(
    configuracion.URL_BASE_DATOS,
    connect_args={"check_same_thread": False}
)

# Fábrica de sesiones transaccionales por cada petición HTTP
SesionLocal = sessionmaker(autocommit=False, autoflush=False, bind=motor)

# Clase base de la que heredarán todos nuestros modelos/tablas ORM
Base = declarative_base()

# Generador de sesión segura mediante Inyección de Dependencias
def obtenerSesionBd():
    sesionBd = SesionLocal()
    try:
        yield sesionBd
    finally:
        sesionBd.close()

# ===== Compatibilidad temporal con los módulos que aún usan los nombres anteriores =====
# `get_db` es el MISMO objeto que `obtenerSesionBd`, así una sola sobreescritura de dependencia
# (pruebas) aplica a ambos.
engine = motor
SessionLocal = SesionLocal
get_db = obtenerSesionBd
