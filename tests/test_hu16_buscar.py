"""Pruebas de HU-16: Buscar videojuegos por nombre (GET /api/v1/catalogo/juegos/buscar)."""
from sqlalchemy.exc import OperationalError

from app.domain.catalogo import validarTextoBusqueda
from app.core.respuestas import ErrorAplicacion
from app.repositories.repositorio_catalogo import RepositorioCatalogo

URL = "/api/v1/catalogo/juegos/buscar"


def test_flujoExitosoCoincidenciaParcialSinMayusculas(cliente, crearJuego):
    juego = crearJuego(titulo="Aurora Quest")
    crearJuego(titulo="Space Racer")
    respuesta = cliente.get(URL, params={"texto": "AURO"})
    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["success"] is True
    assert cuerpo["message"] == "Búsqueda exitosa"
    assert cuerpo["data"] == {
        "items": [{"juegoId": juego.id, "titulo": "Aurora Quest", "genero": "RPG",
                   "plataformas": ["PC", "CONSOLA"], "estado": "ACTIVO"}],
        "pagina": 0, "tamano": 20, "total": 1,
    }


def test_coincidenciaEnMedioDelTitulo(cliente, crearJuego):
    crearJuego(titulo="Aurora Quest")
    assert cliente.get(URL, params={"texto": "quest"}).json()["data"]["total"] == 1


def test_soloJuegosPublicados(cliente, crearJuego):
    crearJuego(titulo="Aurora Quest", estado="INACTIVO")
    crearJuego(titulo="Aurora Rising", estado="PREVENTA")
    datos = cliente.get(URL, params={"texto": "aurora"}).json()["data"]
    assert [i["titulo"] for i in datos["items"]] == ["Aurora Rising"]


def test_comodinesSqlSeTratanComoTexto(cliente, crearJuego):
    crearJuego(titulo="Aurora Quest")
    assert cliente.get(URL, params={"texto": "%%"}).json()["data"]["total"] == 0


def test_estructuraDelContrato(cliente, crearJuego):
    crearJuego()
    cuerpo = cliente.get(URL, params={"texto": "aurora"}).json()
    assert set(cuerpo) == {"message", "data", "success"}
    assert set(cuerpo["data"]) == {"items", "pagina", "tamano", "total"}


def test_sinResultados(cliente, crearJuego):
    crearJuego()
    respuesta = cliente.get(URL, params={"texto": "zelda"})
    assert respuesta.status_code == 200
    assert respuesta.json() == {
        "message": "No se encontraron juegos para la búsqueda",
        "data": {"items": [], "pagina": 0, "tamano": 20, "total": 0},
        "success": False,
    }


def test_error400MinimoDosCaracteres(cliente):
    for texto in ("a", " a ", ""):
        respuesta = cliente.get(URL, params={"texto": texto})
        assert respuesta.status_code == 400
        assert respuesta.json() == {
            "message": "El texto de búsqueda debe tener al menos 2 caracteres", "data": None, "success": False,
        }


def test_dominioValidaLongitud():
    assert validarTextoBusqueda("  ab ") == "ab"
    try:
        validarTextoBusqueda("a")
        assert False
    except ErrorAplicacion as error:
        assert error.codigoHttp == 400


def test_error503BaseDeDatos(cliente, monkeypatch):
    def _falla(*_args, **_kwargs):
        raise OperationalError("SELECT", {}, Exception("BD caída"))

    monkeypatch.setattr(RepositorioCatalogo, "buscarPorTitulo", _falla)
    respuesta = cliente.get(URL, params={"texto": "aurora"})
    assert respuesta.status_code == 503
    assert respuesta.json() == {"message": "No fue posible realizar la búsqueda", "data": None, "success": False}
