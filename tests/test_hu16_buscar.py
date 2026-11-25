"""Pruebas de HU-16: Buscar videojuegos por nombre (GET /api/v1/catalogo/juegos/buscar)."""
from sqlalchemy.exc import OperationalError

from app.domain.catalogo import validar_texto_busqueda
from app.core.respuestas import ErrorAplicacion
from app.repositories.repositorio_catalogo import RepositorioCatalogo

URL = "/api/v1/catalogo/juegos/buscar"


def test_flujo_exitoso_coincidencia_parcial_sin_mayusculas(cliente, crear_juego):
    juego = crear_juego(titulo="Aurora Quest")
    crear_juego(titulo="Space Racer")
    respuesta = cliente.get(URL, params={"q": "AURO"})
    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["success"] is True
    assert cuerpo["message"] == "Búsqueda exitosa"
    assert cuerpo["data"] == {
        "items": [{"gameId": juego.id, "titulo": "Aurora Quest", "genero": "RPG",
                   "plataformas": ["PC", "CONSOLA"], "estado": "ACTIVO"}],
        "page": 0, "size": 20, "total": 1,
    }


def test_coincidencia_en_medio_del_titulo(cliente, crear_juego):
    crear_juego(titulo="Aurora Quest")
    assert cliente.get(URL, params={"q": "quest"}).json()["data"]["total"] == 1


def test_solo_juegos_publicados(cliente, crear_juego):
    crear_juego(titulo="Aurora Quest", estado="INACTIVO")
    crear_juego(titulo="Aurora Rising", estado="PREVENTA")
    datos = cliente.get(URL, params={"q": "aurora"}).json()["data"]
    assert [i["titulo"] for i in datos["items"]] == ["Aurora Rising"]


def test_comodines_sql_se_tratan_como_texto(cliente, crear_juego):
    crear_juego(titulo="Aurora Quest")
    assert cliente.get(URL, params={"q": "%%"}).json()["data"]["total"] == 0


def test_estructura_del_contrato(cliente, crear_juego):
    crear_juego()
    cuerpo = cliente.get(URL, params={"q": "aurora"}).json()
    assert set(cuerpo) == {"message", "data", "success"}
    assert set(cuerpo["data"]) == {"items", "page", "size", "total"}


def test_sin_resultados(cliente, crear_juego):
    crear_juego()
    respuesta = cliente.get(URL, params={"q": "zelda"})
    assert respuesta.status_code == 200
    assert respuesta.json() == {
        "message": "No se encontraron juegos para la búsqueda",
        "data": {"items": [], "page": 0, "size": 20, "total": 0},
        "success": False,
    }


def test_error_400_minimo_dos_caracteres(cliente):
    for texto in ("a", " a ", ""):
        respuesta = cliente.get(URL, params={"q": texto})
        assert respuesta.status_code == 400
        assert respuesta.json() == {
            "message": "El texto de búsqueda debe tener al menos 2 caracteres", "data": None, "success": False,
        }


def test_dominio_valida_longitud():
    assert validar_texto_busqueda("  ab ") == "ab"
    try:
        validar_texto_busqueda("a")
        assert False
    except ErrorAplicacion as error:
        assert error.status_code == 400


def test_error_503_base_de_datos(cliente, monkeypatch):
    def _falla(*_args, **_kwargs):
        raise OperationalError("SELECT", {}, Exception("BD caída"))

    monkeypatch.setattr(RepositorioCatalogo, "buscar_por_titulo", _falla)
    respuesta = cliente.get(URL, params={"q": "aurora"})
    assert respuesta.status_code == 503
    assert respuesta.json() == {"message": "No fue posible realizar la búsqueda", "data": None, "success": False}
