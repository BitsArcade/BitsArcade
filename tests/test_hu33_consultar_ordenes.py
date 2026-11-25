"""Pruebas de HU-33: Consultar órdenes pendientes (GET /api/v1/ordenes?estado=PENDIENTE)."""
from sqlalchemy.exc import OperationalError

from app.repositories.repositorio_orden import RepositorioOrden
from tests.conftest import encabezado_auth


def _crear_orden(cliente, juego_id, usuario_id=1) -> int:
    cliente.post(
        "/api/v1/carrito/items",
        json={"juegoId": juego_id, "cantidad": 1},
        headers=encabezado_auth(usuario_id),
    )
    resp = cliente.post("/api/v1/ordenes", headers=encabezado_auth(usuario_id))
    assert resp.status_code == 201
    return resp.json()["data"]["ordenId"]


def test_flujo_exitoso_filtrar_ordenes_pendientes(cliente, crear_juego, crear_keys):
    juego = crear_juego()
    crear_keys(juego.id, disponibles=10)
    orden_1 = _crear_orden(cliente, juego.id, usuario_id=1)
    orden_2 = _crear_orden(cliente, juego.id, usuario_id=1)

    # Cancelamos orden_1 para validar que el filtro estado=PENDIENTE solo trae orden_2
    cliente.post(f"/api/v1/ordenes/{orden_1}/cancelacion", headers=encabezado_auth(usuario_id=1))

    respuesta = cliente.get("/api/v1/ordenes?estado=PENDIENTE", headers=encabezado_auth(usuario_id=1))
    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["success"] is True
    assert len(cuerpo["data"]) == 1
    assert cuerpo["data"][0]["ordenId"] == orden_2
    assert cuerpo["data"][0]["estado"] == "PENDIENTE"


def test_sin_ordenes_retorna_200_success_false(cliente):
    respuesta = cliente.get("/api/v1/ordenes?estado=PENDIENTE", headers=encabezado_auth())
    assert respuesta.status_code == 200
    assert respuesta.json() == {
        "message": "No se encontraron órdenes para los criterios indicados",
        "data": [],
        "success": False,
    }


def test_error_400_estado_invalido(cliente):
    respuesta = cliente.get("/api/v1/ordenes?estado=INVENTADO", headers=encabezado_auth())
    assert respuesta.status_code == 400
    assert respuesta.json()["success"] is False


def test_error_401_sin_token(cliente):
    assert cliente.get("/api/v1/ordenes").status_code == 401


def test_error_503_base_de_datos(cliente, monkeypatch):
    def _falla(*_args, **_kwargs):
        raise OperationalError("SELECT", {}, Exception("BD caída"))

    monkeypatch.setattr(RepositorioOrden, "listar_por_usuario", _falla)
    assert cliente.get("/api/v1/ordenes", headers=encabezado_auth()).status_code == 503