"""Pruebas de HU-17: Filtrar catálogo por plataforma (GET /api/v1/catalogo/juegos?plataforma=PC)."""
from sqlalchemy.exc import OperationalError

from app.repositories.repositorio_catalogo import RepositorioCatalogo

URL = "/api/v1/catalogo/juegos"


def test_flujoExitoso(cliente, crearJuego):
    juego = crearJuego(titulo="Aurora Quest", plataformas=("PC", "CONSOLA"))
    crearJuego(titulo="Solo Consola", plataformas=("CONSOLA",))
    respuesta = cliente.get(URL, params={"plataforma": "PC"})
    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["success"] is True
    assert cuerpo["message"] == "Filtrado por plataforma exitoso"
    assert cuerpo["data"] == {
        "items": [{"juegoId": juego.id, "titulo": "Aurora Quest", "genero": "RPG",
                   "plataformas": ["PC", "CONSOLA"], "estado": "ACTIVO"}],
        "pagina": 0, "tamano": 20, "total": 1,
    }


def test_ordenAlfabeticoPorTitulo(cliente, crearJuego):
    for titulo in ("Zeta", "Alfa", "Media"):
        crearJuego(titulo=titulo, plataformas=("CONSOLA",))
    datos = cliente.get(URL, params={"plataforma": "CONSOLA"}).json()["data"]
    assert [i["titulo"] for i in datos["items"]] == ["Alfa", "Media", "Zeta"]


def test_excluyeInactivos(cliente, crearJuego):
    crearJuego(titulo="Inactivo", plataformas=("PC",), estado="INACTIVO")
    respuesta = cliente.get(URL, params={"plataforma": "PC"})
    assert respuesta.json()["data"]["total"] == 0


def test_estructuraDelContrato(cliente, crearJuego):
    crearJuego()
    cuerpo = cliente.get(URL, params={"plataforma": "pc"}).json()
    assert set(cuerpo) == {"message", "data", "success"}
    assert set(cuerpo["data"]) == {"items", "pagina", "tamano", "total"}


def test_sinDatos(cliente, crearJuego):
    crearJuego(plataformas=("CONSOLA",))
    respuesta = cliente.get(URL, params={"plataforma": "PC"})
    assert respuesta.status_code == 200
    assert respuesta.json() == {
        "message": "No existen juegos para la plataforma indicada",
        "data": {"items": [], "pagina": 0, "tamano": 20, "total": 0},
        "success": False,
    }


def test_error400PlataformaInvalida(cliente):
    respuesta = cliente.get(URL, params={"plataforma": "XBOX360"})
    assert respuesta.status_code == 400
    assert respuesta.json() == {"message": "Plataforma no válida. Use PC o CONSOLA", "data": None, "success": False}


def test_error503BaseDeDatos(cliente, monkeypatch):
    def _falla(*_args, **_kwargs):
        raise OperationalError("SELECT", {}, Exception("BD caída"))

    monkeypatch.setattr(RepositorioCatalogo, "filtrarPorPlataforma", _falla)
    respuesta = cliente.get(URL, params={"plataforma": "PC"})
    assert respuesta.status_code == 503
    assert respuesta.json() == {"message": "No fue posible filtrar el catálogo", "data": None, "success": False}
