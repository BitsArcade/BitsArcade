"""Pruebas de HU-19: Listar juegos destacados y novedades (GET /api/v1/catalogo/juegos/destacados)."""
from datetime import date

from sqlalchemy.exc import OperationalError

from app.repositories.repositorio_catalogo import RepositorioCatalogo

URL = "/api/v1/catalogo/juegos/destacados"


def test_flujo_exitoso(cliente, crear_juego):
    juego = crear_juego(destacado=True)
    respuesta = cliente.get(URL, params={"limite": 10})
    assert respuesta.status_code == 200
    assert respuesta.json() == {
        "message": "Consulta de destacados exitosa",
        "data": [{"gameId": juego.id, "titulo": "Aurora Quest", "genero": "RPG",
                  "plataformas": ["PC", "CONSOLA"], "estado": "ACTIVO"}],
        "success": True,
    }


def test_criterio_destacado_y_orden_por_lanzamiento(cliente, crear_juego):
    crear_juego(titulo="Normal", destacado=False, estado="ACTIVO")
    crear_juego(titulo="Destacado", destacado=True, fecha_lanzamiento=date(2025, 1, 1))
    crear_juego(titulo="Estreno", estado="ESTRENO", fecha_lanzamiento=date(2026, 6, 1))
    crear_juego(titulo="Preventa", estado="PREVENTA", fecha_lanzamiento=date(2026, 12, 1))
    crear_juego(titulo="Inactivo destacado", estado="INACTIVO", destacado=True)
    titulos = [j["titulo"] for j in cliente.get(URL).json()["data"]]
    assert titulos == ["Preventa", "Estreno", "Destacado"]


def test_limite_por_defecto_10_y_personalizado(cliente, crear_juego):
    for indice in range(12):
        crear_juego(titulo=f"J{indice}", destacado=True)
    assert len(cliente.get(URL).json()["data"]) == 10
    assert len(cliente.get(URL, params={"limite": 3}).json()["data"]) == 3
    assert len(cliente.get(URL, params={"limite": 20}).json()["data"]) == 12


def test_estructura_del_contrato(cliente, crear_juego):
    crear_juego(destacado=True)
    cuerpo = cliente.get(URL).json()
    assert set(cuerpo) == {"message", "data", "success"}
    assert isinstance(cuerpo["data"], list)


def test_sin_datos(cliente, crear_juego):
    crear_juego(destacado=False)
    respuesta = cliente.get(URL)
    assert respuesta.status_code == 200
    assert respuesta.json() == {"message": "No existen juegos destacados", "data": [], "success": False}


def test_error_400_limite_fuera_de_rango(cliente):
    for limite in (50, 0):
        respuesta = cliente.get(URL, params={"limite": limite})
        assert respuesta.status_code == 400
        assert respuesta.json() == {"message": "limite debe estar entre 1 y 20", "data": None, "success": False}


def test_error_503_base_de_datos(cliente, monkeypatch):
    def _falla(*_args, **_kwargs):
        raise OperationalError("SELECT", {}, Exception("BD caída"))

    monkeypatch.setattr(RepositorioCatalogo, "listar_destacados", _falla)
    respuesta = cliente.get(URL)
    assert respuesta.status_code == 503
    assert respuesta.json() == {"message": "No fue posible consultar los destacados", "data": None, "success": False}
