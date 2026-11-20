"""Pruebas de HU-18: Filtrado combinado por género y precio (GET /api/v1/catalogo/juegos/filtrar)."""
from sqlalchemy.exc import OperationalError

from app.domain.catalogo import convertir_rango_precio_a_costo
from app.repositories.repositorio_catalogo import RepositorioCatalogo
from app.services.servicio_parametros import ServicioParametros

URL = "/api/v1/catalogo/juegos/filtrar"


def test_flujo_exitoso(cliente, crear_juego):
    juego = crear_juego(genero="RPG", costo_adquisicion=160000)  # precio final 238000
    respuesta = cliente.get(URL, params={"genero": "RPG", "precioMin": 100000, "precioMax": 300000})
    assert respuesta.status_code == 200
    assert respuesta.json() == {
        "message": "Filtrado exitoso",
        "data": {
            "items": [{"gameId": juego.id, "titulo": "Aurora Quest", "genero": "RPG",
                       "plataformas": ["PC", "CONSOLA"], "estado": "ACTIVO",
                       "precioFinal": 238000, "moneda": "COP"}],
            "page": 0, "size": 20, "total": 1,
        },
        "success": True,
    }


def test_filtro_opera_sobre_precio_final_y_no_sobre_costo(cliente, crear_juego):
    # Costo 90000 está dentro de [100000, 300000] pero su precio final (133875) también;
    # costo 250000 está dentro del rango como costo, pero su precio final (371875) NO.
    crear_juego(titulo="Barato", costo_adquisicion=90000)
    crear_juego(titulo="Caro", costo_adquisicion=250000)
    titulos = [i["titulo"] for i in cliente.get(
        URL, params={"precioMin": 100000, "precioMax": 300000}).json()["data"]["items"]]
    assert titulos == ["Barato"]


def test_limites_exactos_incluidos(cliente, crear_juego):
    crear_juego(costo_adquisicion=160000)
    datos = cliente.get(URL, params={"precioMin": 238000, "precioMax": 238000}).json()["data"]
    assert datos["total"] == 1


def test_combina_genero(cliente, crear_juego):
    crear_juego(titulo="RPG", genero="RPG")
    crear_juego(titulo="Accion", genero="Acción")
    titulos = [i["titulo"] for i in cliente.get(URL, params={"genero": "rpg"}).json()["data"]["items"]]
    assert titulos == ["RPG"]


def test_excluye_inactivos(cliente, crear_juego):
    crear_juego(estado="INACTIVO")
    assert cliente.get(URL, params={"genero": "RPG"}).json()["data"]["total"] == 0


def test_una_sola_llamada_a_com01(cliente, crear_juego, monkeypatch):
    for indice in range(3):
        crear_juego(titulo=f"J{indice}")
    llamadas = []
    original = ServicioParametros.obtener_contrato_com01

    def _contar(self, sesion):
        llamadas.append(1)
        return original(self, sesion)

    monkeypatch.setattr(ServicioParametros, "obtener_contrato_com01", _contar)
    assert cliente.get(URL, params={"genero": "RPG"}).json()["data"]["total"] == 3
    assert len(llamadas) == 1


def test_dominio_convierte_rango():
    costo_min, costo_max = convertir_rango_precio_a_costo(119000, 238000, 0.25, 0.19)
    assert round(costo_min) == 80000 and round(costo_max) == 160000


def test_sin_datos(cliente, crear_juego):
    crear_juego(genero="RPG")
    respuesta = cliente.get(URL, params={"genero": "Deportes"})
    assert respuesta.status_code == 200
    assert respuesta.json() == {
        "message": "No existen juegos con los filtros indicados",
        "data": {"items": [], "page": 0, "size": 20, "total": 0},
        "success": False,
    }


def test_error_400_precio_min_mayor_que_max(cliente):
    respuesta = cliente.get(URL, params={"precioMin": 900000, "precioMax": 100000})
    assert respuesta.status_code == 400
    assert respuesta.json() == {
        "message": "precioMin no puede ser mayor que precioMax", "data": None, "success": False,
    }


def test_error_503_com01_no_responde(cliente, monkeypatch):
    def _falla(self, sesion):
        raise ConnectionError("MOD-00 caído")

    monkeypatch.setattr(ServicioParametros, "obtener_contrato_com01", _falla)
    respuesta = cliente.get(URL, params={"genero": "RPG"})
    assert respuesta.status_code == 503
    assert respuesta.json() == {
        "message": "No fue posible obtener los parámetros financieros", "data": None, "success": False,
    }


def test_error_503_base_de_datos(cliente, monkeypatch):
    def _falla(*_args, **_kwargs):
        raise OperationalError("SELECT", {}, Exception("BD caída"))

    monkeypatch.setattr(RepositorioCatalogo, "filtrar_por_genero_y_costo", _falla)
    respuesta = cliente.get(URL, params={"genero": "RPG"})
    assert respuesta.status_code == 503
    assert respuesta.json() == {"message": "No fue posible filtrar el catálogo", "data": None, "success": False}
