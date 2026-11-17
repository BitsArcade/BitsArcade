"""Pruebas de HU-21: Consultar detalles de ficha técnica (GET /api/v1/catalogo/juegos/{gameId})."""
from sqlalchemy.exc import OperationalError

from app.repositories.repositorio_catalogo import RepositorioCatalogo


def test_flujo_exitoso(cliente, crear_juego):
    juego = crear_juego()
    respuesta = cliente.get(f"/api/v1/catalogo/juegos/{juego.id}")
    assert respuesta.status_code == 200
    assert respuesta.json() == {
        "message": "Consulta de ficha técnica exitosa",
        "data": {
            "gameId": juego.id,
            "titulo": "Aurora Quest",
            "descripcion": "RPG de mundo abierto",
            "genero": "RPG",
            "plataformas": ["PC", "CONSOLA"],
            "desarrollador": "Nova Studio",
            "fechaLanzamiento": "2026-03-15",
            "estado": "ACTIVO",
        },
        "success": True,
    }


def test_no_expone_costo_margen_ni_precio(cliente, crear_juego):
    juego = crear_juego()
    texto = cliente.get(f"/api/v1/catalogo/juegos/{juego.id}").text
    for campo in ("costo", "margen", "precio", "160000"):
        assert campo not in texto


def test_rutas_estaticas_no_colisionan_con_game_id(cliente, crear_juego):
    crear_juego(destacado=True)
    assert cliente.get("/api/v1/catalogo/juegos/destacados").status_code == 200
    assert cliente.get("/api/v1/catalogo/juegos/buscar", params={"q": "aurora"}).status_code == 200


def test_error_404_juego_inexistente(cliente):
    respuesta = cliente.get("/api/v1/catalogo/juegos/9999")
    assert respuesta.status_code == 404
    assert respuesta.json() == {"message": "El juego indicado no existe", "data": None, "success": False}


def test_error_404_juego_inactivo(cliente, crear_juego):
    juego = crear_juego(estado="INACTIVO")
    assert cliente.get(f"/api/v1/catalogo/juegos/{juego.id}").status_code == 404


def test_error_503_base_de_datos(cliente, monkeypatch):
    def _falla(*_args, **_kwargs):
        raise OperationalError("SELECT", {}, Exception("BD caída"))

    monkeypatch.setattr(RepositorioCatalogo, "obtener_publicado_por_id", _falla)
    respuesta = cliente.get("/api/v1/catalogo/juegos/1")
    assert respuesta.status_code == 503
    assert respuesta.json() == {"message": "No fue posible consultar la ficha técnica", "data": None, "success": False}
