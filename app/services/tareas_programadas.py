"""
Tareas periódicas del backend:

- TT-04 (MOD-03): expiración de reservas (HU-13, RN-04) y alertas de stock agotado (HU-15).
- HU-34 (MOD-04): cancelación de órdenes PENDIENTE con expiraEn vencido (libera reservas con COM-13).

Se ejecutan en un hilo de fondo solo si la variable de entorno INTERVALO_TAREAS_SEGUNDOS es > 0.
También pueden invocarse manualmente con `ejecutarCiclo()` (pruebas o cron externo).
"""
import logging
import os
import threading

from app.core.base_datos import SesionLocal

registro = logging.getLogger("bitarcade.tareas")
_detener = threading.Event()


def ejecutarCiclo(sesion=None) -> dict:
    from app.services.servicio_inventario import ServicioInventario
    from app.services.servicio_ordenes import ServicioOrdenes

    propia = sesion is None
    sesion = sesion or SesionLocal()
    try:
        ordenesCanceladas = ServicioOrdenes().cancelarOrdenesExpiradas(sesion)
        servicio = ServicioInventario()
        liberadas = servicio.liberarReservasVencidas(sesion)
        alertas = servicio.evaluarStockAgotado(sesion)
        return {"ordenesCanceladas": ordenesCanceladas, "reservasLiberadas": liberadas, "alertasNuevas": len(alertas)}
    finally:
        if propia:
            sesion.close()


def iniciarTareasProgramadas() -> threading.Thread | None:
    intervalo = int(os.getenv("INTERVALO_TAREAS_SEGUNDOS", "0") or 0)
    if intervalo <= 0:
        return None

    def _bucle():
        while not _detener.wait(intervalo):
            try:
                ejecutarCiclo()
            except Exception:  # Las tareas nunca deben detener la API
                registro.exception("Fallo en el ciclo de tareas programadas")

    hilo = threading.Thread(target=_bucle, name="tareas-programadas", daemon=True)
    hilo.start()
    return hilo
