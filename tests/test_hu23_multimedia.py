"""Pruebas de HU-23: Visualizar galería y trailers (GET /api/v1/catalogo/juegos/{juegoId}/multimedia)."""
from sqlalchemy.exc import OperationalError

from app.domain.catalogo import MultimediaJuego
from app.repositories.repositorio_catalogo import RepositorioCatalogo


def test_flujoExitosoAgrupaImagenesYVideos(cliente, sesion, crearJuego):
    juego = crearJuego()
    sesion.add_all([
        MultimediaJuego(juegoId=juego.id, tipo="IMAGEN", url="https://cdn.bitarcade.test/101/2.jpg", orden=2),
        MultimediaJuego(juegoId=juego.id, tipo="VIDEO", url="https://cdn.bitarcade.test/101/trailer.mp4", orden=1),
        MultimediaJuego(juegoId=juego.id, tipo="IMAGEN", url="https://cdn.bitarcade.test/101/1.jpg", orden=1),
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


def test_sinMaterialMultimedia(cliente, crearJuego):
    juego = crearJuego()
    respuesta = cliente.get(f"/api/v1/catalogo/juegos/{juego.id}/multimedia")
    assert respuesta.status_code == 200
    assert respuesta.json() == {
        "message": "El juego no tiene material multimedia",
        "data": {"imagenes": [], "videos": []},
        "success": False,
    }


def test_error404JuegoInexistente(cliente):
    respuesta = cliente.get("/api/v1/catalogo/juegos/9999/multimedia")
    assert respuesta.status_code == 404
    assert respuesta.json() == {"message": "El juego indicado no existe", "data": None, "success": False}


def test_error503BaseDeDatos(cliente, crearJuego, monkeypatch):
    juego = crearJuego()

    def _falla(*_args, **_kwargs):
        raise OperationalError("SELECT", {}, Exception("BD caída"))

    monkeypatch.setattr(RepositorioCatalogo, "listarMultimedia", _falla)
    respuesta = cliente.get(f"/api/v1/catalogo/juegos/{juego.id}/multimedia")
    assert respuesta.status_code == 503
    assert respuesta.json() == {
        "message": "No fue posible consultar el material multimedia", "data": None, "success": False,
    }
