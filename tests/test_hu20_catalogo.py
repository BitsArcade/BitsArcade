"""Pruebas de HU-20: Consultar catálogo completo (GET /api/v1/catalogo/juegos)."""
from sqlalchemy.exc import OperationalError

from app.repositories.repositorio_catalogo import RepositorioCatalogo

URL = "/api/v1/catalogo/juegos"


def test_flujoExitosoListaJuegosPublicados(cliente, crearJuego):
    juego = crearJuego()
    respuesta = cliente.get(URL, params={"pagina": 0, "tamano": 20})
    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["success"] is True
    assert cuerpo["message"] == "Consulta de catálogo exitosa"
    assert cuerpo["data"] == {
        "items": [
            {
                "juegoId": juego.id,
                "titulo": "Aurora Quest",
                "genero": "RPG",
                "plataformas": ["PC", "CONSOLA"],
                "estado": "ACTIVO",
            }
        ],
        "pagina": 0,
        "tamano": 20,
        "total": 1,
    }


def test_estructuraDelContrato(cliente, crearJuego):
    crearJuego()
    cuerpo = cliente.get(URL).json()
    assert set(cuerpo) == {"message", "data", "success"}
    assert set(cuerpo["data"]) == {"items", "pagina", "tamano", "total"}
    assert set(cuerpo["data"]["items"][0]) == {"juegoId", "titulo", "genero", "plataformas", "estado"}


def test_excluyeInactivosEIncluyePreventaYEstreno(cliente, crearJuego):
    crearJuego(titulo="A Activo", estado="ACTIVO")
    crearJuego(titulo="B Preventa", estado="PREVENTA")
    crearJuego(titulo="C Estreno", estado="ESTRENO")
    crearJuego(titulo="D Inactivo", estado="INACTIVO")
    datos = cliente.get(URL).json()["data"]
    assert datos["total"] == 3
    assert [i["estado"] for i in datos["items"]] == ["ACTIVO", "PREVENTA", "ESTRENO"]


def test_noExponeCostoNiPrecio(cliente, crearJuego):
    crearJuego()
    texto = cliente.get(URL).text
    for campo in ("costo", "precio", "margen", "160000"):
        assert campo not in texto


def test_paginacion(cliente, crearJuego):
    for indice in range(5):
        crearJuego(titulo=f"Juego {indice}")
    datos = cliente.get(URL, params={"pagina": 1, "tamano": 2}).json()["data"]
    assert datos["pagina"] == 1 and datos["tamano"] == 2 and datos["total"] == 5
    assert [i["titulo"] for i in datos["items"]] == ["Juego 2", "Juego 3"]


def test_sinDatos(cliente):
    respuesta = cliente.get(URL)
    assert respuesta.status_code == 200
    assert respuesta.json() == {
        "message": "No existen juegos publicados",
        "data": {"items": [], "pagina": 0, "tamano": 20, "total": 0},
        "success": False,
    }


def test_error400TamanoInvalido(cliente):
    respuesta = cliente.get(URL, params={"tamano": 500})
    assert respuesta.status_code == 400
    assert respuesta.json() == {"message": "tamano debe estar entre 1 y 100", "data": None, "success": False}


def test_error503BaseDeDatos(cliente, monkeypatch):
    def _falla(*_args, **_kwargs):
        raise OperationalError("SELECT", {}, Exception("BD caída"))

    monkeypatch.setattr(RepositorioCatalogo, "listarPublicados", _falla)
    respuesta = cliente.get(URL)
    assert respuesta.status_code == 503
    assert respuesta.json() == {"message": "No fue posible consultar el catálogo", "data": None, "success": False}
