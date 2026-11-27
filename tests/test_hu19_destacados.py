"""Pruebas de HU-19: Listar juegos destacados y novedades (GET /api/v1/catalogo/juegos/destacados)."""
from datetime import date

from sqlalchemy.exc import OperationalError

from app.repositories.repositorio_catalogo import RepositorioCatalogo

URL = "/api/v1/catalogo/juegos/destacados"


def test_flujoExitoso(cliente, crearJuego):
    juego = crearJuego(destacado=True)
    respuesta = cliente.get(URL, params={"limite": 10})
    assert respuesta.status_code == 200
    assert respuesta.json() == {
        "message": "Consulta de destacados exitosa",
        "data": [{"juegoId": juego.id, "titulo": "Aurora Quest", "genero": "RPG",
                  "plataformas": ["PC", "CONSOLA"], "estado": "ACTIVO"}],
        "success": True,
    }


def test_criterioDestacadoYOrdenPorLanzamiento(cliente, crearJuego):
    crearJuego(titulo="Normal", destacado=False, estado="ACTIVO")
    crearJuego(titulo="Destacado", destacado=True, fechaLanzamiento=date(2025, 1, 1))
    crearJuego(titulo="Estreno", estado="ESTRENO", fechaLanzamiento=date(2026, 6, 1))
    crearJuego(titulo="Preventa", estado="PREVENTA", fechaLanzamiento=date(2026, 12, 1))
    crearJuego(titulo="Inactivo destacado", estado="INACTIVO", destacado=True)
    titulos = [j["titulo"] for j in cliente.get(URL).json()["data"]]
    assert titulos == ["Preventa", "Estreno", "Destacado"]


def test_limitePorDefecto10YPersonalizado(cliente, crearJuego):
    for indice in range(12):
        crearJuego(titulo=f"J{indice}", destacado=True)
    assert len(cliente.get(URL).json()["data"]) == 10
    assert len(cliente.get(URL, params={"limite": 3}).json()["data"]) == 3
    assert len(cliente.get(URL, params={"limite": 20}).json()["data"]) == 12


def test_estructuraDelContrato(cliente, crearJuego):
    crearJuego(destacado=True)
    cuerpo = cliente.get(URL).json()
    assert set(cuerpo) == {"message", "data", "success"}
    assert isinstance(cuerpo["data"], list)


def test_sinDatos(cliente, crearJuego):
    crearJuego(destacado=False)
    respuesta = cliente.get(URL)
    assert respuesta.status_code == 200
    assert respuesta.json() == {"message": "No existen juegos destacados", "data": [], "success": False}


def test_error400LimiteFueraDeRango(cliente):
    for limite in (50, 0):
        respuesta = cliente.get(URL, params={"limite": limite})
        assert respuesta.status_code == 400
        assert respuesta.json() == {"message": "limite debe estar entre 1 y 20", "data": None, "success": False}


def test_error503BaseDeDatos(cliente, monkeypatch):
    def _falla(*_args, **_kwargs):
        raise OperationalError("SELECT", {}, Exception("BD caída"))

    monkeypatch.setattr(RepositorioCatalogo, "listarDestacados", _falla)
    respuesta = cliente.get(URL)
    assert respuesta.status_code == 503
    assert respuesta.json() == {"message": "No fue posible consultar los destacados", "data": None, "success": False}
