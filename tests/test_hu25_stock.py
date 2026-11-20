"""Pruebas de HU-25: Verificar disponibilidad de stock (GET /api/v1/catalogo/juegos/{gameId}/stock)."""
from sqlalchemy.exc import OperationalError

from app.domain.catalogo import determinar_estado_stock
from app.domain.inventario import KeyLicencia
from app.repositories.repositorio_catalogo import RepositorioCatalogo
from app.services.cliente_inventario import ClienteInventario, InventarioNoDisponible


def _agregar_keys(sesion, juego_id, disponibles=0, vendidas=0, reservadas=0):
    for estado, cantidad in (("DISPONIBLE", disponibles), ("VENDIDA", vendidas), ("RESERVADA", reservadas)):
        sesion.add_all([KeyLicencia(juego_id=juego_id, estado=estado) for _ in range(cantidad)])
    sesion.commit()


def test_flujo_exitoso_disponible(cliente, sesion, crear_juego):
    juego = crear_juego()
    _agregar_keys(sesion, juego.id, disponibles=7)
    respuesta = cliente.get(f"/api/v1/catalogo/juegos/{juego.id}/stock")
    assert respuesta.status_code == 200
    assert respuesta.json() == {
        "message": "Consulta de stock exitosa",
        "data": {"gameId": juego.id, "estado": "DISPONIBLE"},
        "success": True,
    }


def test_agotado_cuando_no_hay_keys_disponibles(cliente, sesion, crear_juego):
    juego = crear_juego()
    _agregar_keys(sesion, juego.id, vendidas=3, reservadas=2)
    datos = cliente.get(f"/api/v1/catalogo/juegos/{juego.id}/stock").json()["data"]
    assert datos == {"gameId": juego.id, "estado": "AGOTADO"}


def test_no_expone_conteo_exacto(cliente, sesion, crear_juego):
    juego = crear_juego()
    _agregar_keys(sesion, juego.id, disponibles=7)
    datos = cliente.get(f"/api/v1/catalogo/juegos/{juego.id}/stock").json()["data"]
    assert set(datos) == {"gameId", "estado"}


def test_dominio_estado_stock():
    assert determinar_estado_stock(1) == "DISPONIBLE"
    assert determinar_estado_stock(0) == "AGOTADO"


def test_error_404_juego_inexistente(cliente):
    respuesta = cliente.get("/api/v1/catalogo/juegos/9999/stock")
    assert respuesta.status_code == 404
    assert respuesta.json() == {"message": "El juego indicado no existe", "data": None, "success": False}


def test_error_503_com12_no_responde_nunca_asume_disponible(cliente, crear_juego, monkeypatch):
    juego = crear_juego()

    def _falla(self, sesion, juego_id):
        raise InventarioNoDisponible("MOD-03 caído")

    monkeypatch.setattr(ClienteInventario, "contar_disponibles", _falla)
    respuesta = cliente.get(f"/api/v1/catalogo/juegos/{juego.id}/stock")
    assert respuesta.status_code == 503
    assert respuesta.json() == {"message": "No fue posible verificar la disponibilidad", "data": None, "success": False}


def test_error_503_base_de_datos(cliente, monkeypatch):
    def _falla(*_args, **_kwargs):
        raise OperationalError("SELECT", {}, Exception("BD caída"))

    monkeypatch.setattr(RepositorioCatalogo, "obtener_publicado_por_id", _falla)
    respuesta = cliente.get("/api/v1/catalogo/juegos/1/stock")
    assert respuesta.status_code == 503
    assert respuesta.json() == {"message": "No fue posible verificar el stock", "data": None, "success": False}
