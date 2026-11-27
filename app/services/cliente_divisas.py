"""
Cliente de la API externa de Divisas (simulada) usada por COM-03.

Devuelve la tasa vigente en COP por 1 unidad de la moneda solicitada. Si la API no responde se
lanza `DivisasNoDisponible`: el consumidor (HU-31) no crea la orden ni usa tasas anteriores.
"""
from app.core.fechas import ahoraUtc

TASAS_SIMULADAS: dict[str, float] = {"USD": 4000.0, "EUR": 4350.0}


class DivisasNoDisponible(Exception):
    """La API externa de Divisas no respondió o no tiene la moneda."""


class ClienteDivisas:
    disponible: bool = True

    def consultarTasa(self, codigoIso: str) -> dict:
        if not self.disponible or codigoIso not in TASAS_SIMULADAS:
            raise DivisasNoDisponible(f"Sin tasa para {codigoIso}")
        return {"codigoIso": codigoIso, "tasaCambio": TASAS_SIMULADAS[codigoIso], "consultadaEn": ahoraUtc()}
