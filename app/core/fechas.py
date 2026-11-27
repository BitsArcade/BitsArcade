"""
Utilidades de fecha y hora compartidas por MOD-01, MOD-03, MOD-05 y MOD-06.

Las fechas se guardan en SQLite como UTC sin zona horaria y se exponen en ISO-8601 con sufijo "Z".
"""
from datetime import datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo

    ZONA_BOGOTA = ZoneInfo("America/Bogota")
except Exception:  # pragma: no cover - entornos sin base de datos de zonas horarias
    ZONA_BOGOTA = timezone(timedelta(hours=-5))


def ahoraUtc() -> datetime:
    """Instante actual en UTC (naive) para persistir en la base de datos."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def aIsoZ(fecha: datetime | None) -> str | None:
    """Convierte una fecha UTC naive al formato 2026-10-25T10:03:00Z."""
    if fecha is None:
        return None
    return fecha.replace(microsecond=0).isoformat() + "Z"
