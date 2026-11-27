"""Pruebas de HU-25: Verificar disponibilidad de stock (GET /api/v1/catalogo/juegos/{juegoId}/stock)."""
from sqlalchemy.exc import OperationalError

from app.domain.catalogo import determinarEstadoStock
from app.domain.inventario import ClaveLicencia
from app.repositories.repositorio_catalogo import RepositorioCatalogo
from app.services.cliente_inventario import ClienteInventario, InventarioNoDisponible


def _agregarClaves(sesion, juegoId, disponibles=0, vendidas=0, reservadas=0):
    for estado, cantidad in (("DISPONIBLE", disponibles), ("VENDIDA", vendidas), ("RESERVADA", reservadas)):
        sesion.add_all([ClaveLicencia(juegoId=juegoId, estado=estado) for _ in range(cantidad)])
    sesion.commit()


def test_flujoExitosoDisponible(cliente, sesion, crearJuego):
    juego = crearJuego()
    _agregarClaves(sesion, juego.id, disponibles=7)
    respuesta = cliente.get(f"/api/v1/catalogo/juegos/{juego.id}/stock")
    assert respuesta.status_code == 200
    assert respuesta.json() == {
        "message": "Consulta de stock exitosa",
        "data": {"juegoId": juego.id, "estadoStock": "DISPONIBLE"},
        "success": True,
    }


def test_agotadoCuandoNoHayClavesDisponibles(cliente, sesion, crearJuego):
    juego = crearJuego()
    _agregarClaves(sesion, juego.id, vendidas=3, reservadas=2)
    datos = cliente.get(f"/api/v1/catalogo/juegos/{juego.id}/stock").json()["data"]
    assert datos == {"juegoId": juego.id, "estadoStock": "AGOTADO"}


def test_noExponeConteoExacto(cliente, sesion, crearJuego):
    juego = crearJuego()
    _agregarClaves(sesion, juego.id, disponibles=7)
    datos = cliente.get(f"/api/v1/catalogo/juegos/{juego.id}/stock").json()["data"]
    assert set(datos) == {"juegoId", "estadoStock"}


def test_dominioEstadoStock():
    assert determinarEstadoStock(1) == "DISPONIBLE"
    assert determinarEstadoStock(0) == "AGOTADO"


def test_error404JuegoInexistente(cliente):
    respuesta = cliente.get("/api/v1/catalogo/juegos/9999/stock")
    assert respuesta.status_code == 404
    assert respuesta.json() == {"message": "El juego indicado no existe", "data": None, "success": False}


def test_error503Com12NoRespondeNuncaAsumeDisponible(cliente, crearJuego, monkeypatch):
    juego = crearJuego()

    def _falla(self, sesion, juegoId):
        raise InventarioNoDisponible("MOD-03 caído")

    monkeypatch.setattr(ClienteInventario, "contarDisponibles", _falla)
    respuesta = cliente.get(f"/api/v1/catalogo/juegos/{juego.id}/stock")
    assert respuesta.status_code == 503
    assert respuesta.json() == {"message": "No fue posible verificar la disponibilidad", "data": None, "success": False}


def test_error503BaseDeDatos(cliente, monkeypatch):
    def _falla(*_args, **_kwargs):
        raise OperationalError("SELECT", {}, Exception("BD caída"))

    monkeypatch.setattr(RepositorioCatalogo, "obtenerPublicadoPorId", _falla)
    respuesta = cliente.get("/api/v1/catalogo/juegos/1/stock")
    assert respuesta.status_code == 503
    assert respuesta.json() == {"message": "No fue posible verificar el stock", "data": None, "success": False}
