"""Pruebas de HU-23: Visualizar galería y trailers (GET /api/v1/catalogo/juegos/{gameId}/multimedia)."""
from sqlalchemy.exc import OperationalError

from app.domain.catalogo import MultimediaJuego
from app.repositories.repositorio_catalogo import RepositorioCatalogo


def test_flujo_exitoso_agrupa_imagenes_y_videos(cliente, sesion, crear_juego):
    juego = crear_juego()
    sesion.add_all([
        MultimediaJuego(juego_id=juego.id, tipo="IMAGEN", url="https://cdn.bitarcade.test/101/2.jpg", orden=2),
        MultimediaJuego(juego_id=juego.id, tipo="VIDEO", url="https://cdn.bitarcade.test/101/trailer.mp4", orden=1),
        MultimediaJuego(juego_id=juego.id, tipo="IMAGEN", url="https://cdn.bitarcade.test/101/1.jpg", orden=1),
    ])
    sesion.commit()
    respuesta = cliente.get(f"/api/v1/catalogo/juegos/{juego.id}/multimedia")
    assert respuesta.status_code == 200
    assert respuesta.json() == {
        "message": "Consulta de multimedia exitosa",
        "data": {
            "imagenes": ["https://cdn.bitarcade.test/101/1.jpg", "https://cdn.bitarcade.test/101/2.jpg"],
            "videos": ["https://cdn.bitarcade.test/101/trailer.mp4"],
        },
        "success": True,
    }


def test_sin_material_multimedia(cliente, crear_juego):
    juego = crear_juego()
    respuesta = cliente.get(f"/api/v1/catalogo/juegos/{juego.id}/multimedia")
    assert respuesta.status_code == 200
    assert respuesta.json() == {
        "message": "El juego no tiene material multimedia",
        "data": {"imagenes": [], "videos": []},
        "success": False,
    }


def test_error_404_juego_inexistente(cliente):
    respuesta = cliente.get("/api/v1/catalogo/juegos/9999/multimedia")
    assert respuesta.status_code == 404
    assert respuesta.json() == {"message": "El juego indicado no existe", "data": None, "success": False}


def test_error_503_base_de_datos(cliente, crear_juego, monkeypatch):
    juego = crear_juego()

    def _falla(*_args, **_kwargs):
        raise OperationalError("SELECT", {}, Exception("BD caída"))

    monkeypatch.setattr(RepositorioCatalogo, "listar_multimedia", _falla)
    respuesta = cliente.get(f"/api/v1/catalogo/juegos/{juego.id}/multimedia")
    assert respuesta.status_code == 503
    assert respuesta.json() == {
        "message": "No fue posible consultar el material multimedia", "data": None, "success": False,
    }
