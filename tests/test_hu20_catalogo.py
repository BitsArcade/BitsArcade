"""Pruebas de HU-20: Consultar catálogo completo (GET /api/v1/catalogo/juegos)."""
from sqlalchemy.exc import OperationalError

from app.repositories.repositorio_catalogo import RepositorioCatalogo

URL = "/api/v1/catalogo/juegos"


def test_flujo_exitoso_lista_juegos_publicados(cliente, crear_juego):
    juego = crear_juego()
    respuesta = cliente.get(URL, params={"page": 0, "size": 20})
    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["success"] is True
    assert cuerpo["message"] == "Consulta de catálogo exitosa"
    assert cuerpo["data"] == {
        "items": [
            {
                "gameId": juego.id,
                "titulo": "Aurora Quest",
                "genero": "RPG",
                "plataformas": ["PC", "CONSOLA"],
                "estado": "ACTIVO",
            }
        ],
        "page": 0,
        "size": 20,
        "total": 1,
    }


def test_estructura_del_contrato(cliente, crear_juego):
    crear_juego()
    cuerpo = cliente.get(URL).json()
    assert set(cuerpo) == {"message", "data", "success"}
    assert set(cuerpo["data"]) == {"items", "page", "size", "total"}
    assert set(cuerpo["data"]["items"][0]) == {"gameId", "titulo", "genero", "plataformas", "estado"}


def test_excluye_inactivos_e_incluye_preventa_y_estreno(cliente, crear_juego):
    crear_juego(titulo="A Activo", estado="ACTIVO")
    crear_juego(titulo="B Preventa", estado="PREVENTA")
    crear_juego(titulo="C Estreno", estado="ESTRENO")
    crear_juego(titulo="D Inactivo", estado="INACTIVO")
    datos = cliente.get(URL).json()["data"]
    assert datos["total"] == 3
    assert [i["estado"] for i in datos["items"]] == ["ACTIVO", "PREVENTA", "ESTRENO"]


def test_no_expone_costo_ni_precio(cliente, crear_juego):
    crear_juego()
    texto = cliente.get(URL).text
    for campo in ("costo", "precio", "margen", "160000"):
        assert campo not in texto


def test_paginacion(cliente, crear_juego):
    for indice in range(5):
        crear_juego(titulo=f"Juego {indice}")
    datos = cliente.get(URL, params={"page": 1, "size": 2}).json()["data"]
    assert datos["page"] == 1 and datos["size"] == 2 and datos["total"] == 5
    assert [i["titulo"] for i in datos["items"]] == ["Juego 2", "Juego 3"]


def test_sin_datos(cliente):
    respuesta = cliente.get(URL)
    assert respuesta.status_code == 200
    assert respuesta.json() == {
        "message": "No existen juegos publicados",
        "data": {"items": [], "page": 0, "size": 20, "total": 0},
        "success": False,
    }


def test_error_400_size_invalido(cliente):
    respuesta = cliente.get(URL, params={"size": 500})
    assert respuesta.status_code == 400
    assert respuesta.json() == {"message": "size debe estar entre 1 y 100", "data": None, "success": False}


def test_error_503_base_de_datos(cliente, monkeypatch):
    def _falla(*_args, **_kwargs):
        raise OperationalError("SELECT", {}, Exception("BD caída"))

    monkeypatch.setattr(RepositorioCatalogo, "listar_publicados", _falla)
    respuesta = cliente.get(URL)
    assert respuesta.status_code == 503
    assert respuesta.json() == {"message": "No fue posible consultar el catálogo", "data": None, "success": False}
