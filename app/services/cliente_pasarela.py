"""
PLACEHOLDER – Cliente de la API externa de Pagos (pasarela simulada).

El cobro se envía con Idempotency-Key = ordenId y la pasarela responde el resultado de forma
asíncrona por notificación de la pasarela (HU-37 / HU-38). Este cliente simula el acuse de recibo inmediato.
"""
COBROS_SIMULADOS: dict[str, dict] = {}


class PasarelaSinRespuesta(Exception):
    """La API de Pagos superó el tiempo de espera."""


class ClientePasarelaPagos:
    simularTimeout: bool = False

    def enviarCobro(self, payload: dict, claveIdempotencia: str) -> dict:
        if self.simularTimeout:
            raise PasarelaSinRespuesta("La pasarela de pagos no respondió")
        if claveIdempotencia not in COBROS_SIMULADOS:
            COBROS_SIMULADOS[claveIdempotencia] = {"payload": payload, "estado": "RECIBIDO"}
        return {"claveIdempotencia": claveIdempotencia, "estado": "RECIBIDO"}
