"""Pruebas de HU-17: Filtrar catálogo por plataforma (GET /api/v1/catalogo/juegos?plataforma=PC)."""
from sqlalchemy.exc import OperationalError

from app.repositories.repositorio_catalogo import RepositorioCatalogo

URL = "/api/v1/catalogo/juegos"


def test_flujo_exitoso(cliente, crear_juego):
    juego = crear_juego(titulo="Aurora Quest", plataformas=("PC", "CONSOLA"))
    crear_juego(titulo="Solo Consola", plataformas=("CONSOLA",))
    respuesta = cliente.get(URL, params={"plataforma": "PC"})
    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["success"] is True
    assert cuerpo["message"] == "Filtrado por plataforma exitoso"
    assert cuerpo["data"] == {
        "items": [{"gameId": juego.id, "titulo": "Aurora Quest", "genero": "RPG",
                   "plataformas": ["PC", "CONSOLA"], "estado": "ACTIVO"}],
        "page": 0, "size": 20, "total": 1,
    }


def test_orden_alfabetico_por_titulo(cliente, crear_juego):
    for titulo in ("Zeta", "Alfa", "Media"):
        crear_juego(titulo=titulo, plataformas=("CONSOLA",))
    datos = cliente.get(URL, params={"plataforma": "CONSOLA"}).json()["data"]
    assert [i["titulo"] for i in datos["items"]] == ["Alfa", "Media", "Zeta"]


def test_excluye_inactivos(cliente, crear_juego):
    crear_juego(titulo="Inactivo", plataformas=("PC",), estado="INACTIVO")
    respuesta = cliente.get(URL, params={"plataforma": "PC"})
    assert respuesta.json()["data"]["total"] == 0


def test_estructura_del_contrato(cliente, crear_juego):
    crear_juego()
    cuerpo = cliente.get(URL, params={"plataforma": "pc"}).json()
    assert set(cuerpo) == {"message", "data", "success"}
    assert set(cuerpo["data"]) == {"items", "page", "size", "total"}


def test_sin_datos(cliente, crear_juego):
    crear_juego(plataformas=("CONSOLA",))
    respuesta = cliente.get(URL, params={"plataforma": "PC"})
    assert respuesta.status_code == 200
    assert respuesta.json() == {
        "message": "No existen juegos para la plataforma indicada",
        "data": {"items": [], "page": 0, "size": 20, "total": 0},
        "success": False,
    }


def test_error_400_plataforma_invalida(cliente):
    respuesta = cliente.get(URL, params={"plataforma": "XBOX360"})
    assert respuesta.status_code == 400
    assert respuesta.json() == {"message": "Plataforma no válida. Use PC o CONSOLA", "data": None, "success": False}


def test_error_503_base_de_datos(cliente, monkeypatch):
    def _falla(*_args, **_kwargs):
        raise OperationalError("SELECT", {}, Exception("BD caída"))

    monkeypatch.setattr(RepositorioCatalogo, "filtrar_por_plataforma", _falla)
    respuesta = cliente.get(URL, params={"plataforma": "PC"})
    assert respuesta.status_code == 503
    assert respuesta.json() == {"message": "No fue posible filtrar el catálogo", "data": None, "success": False}
