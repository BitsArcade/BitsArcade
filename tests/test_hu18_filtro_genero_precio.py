"""Pruebas de HU-18: Filtrado combinado por género y precio (GET /api/v1/catalogo/juegos/filtrar)."""
from sqlalchemy.exc import OperationalError

from app.domain.catalogo import convertirRangoPrecioACosto
from app.repositories.repositorio_catalogo import RepositorioCatalogo
from app.services.servicio_catalogo import ClienteParametrosFinancieros

URL = "/api/v1/catalogo/juegos/filtrar"


def test_flujoExitoso(cliente, crearJuego):
    juego = crearJuego(genero="RPG", costoAdquisicion=160000)  # precio final 238000
    respuesta = cliente.get(URL, params={"genero": "RPG", "precioMin": 100000, "precioMax": 300000})
    assert respuesta.status_code == 200
    assert respuesta.json() == {
        "message": "Filtrado exitoso",
        "data": {
            "items": [{"juegoId": juego.id, "titulo": "Aurora Quest", "genero": "RPG",
                       "plataformas": ["PC", "CONSOLA"], "estado": "ACTIVO",
                       "precioFinal": 238000, "moneda": "COP"}],
            "pagina": 0, "tamano": 20, "total": 1,
        },
        "success": True,
    }


def test_filtroOperaSobrePrecioFinalYNoSobreCosto(cliente, crearJuego):
    # Costo 90000 está dentro de [100000, 300000] pero su precio final (133875) también;
    # costo 250000 está dentro del rango como costo, pero su precio final (371875) NO.
    crearJuego(titulo="Barato", costoAdquisicion=90000)
    crearJuego(titulo="Caro", costoAdquisicion=250000)
    titulos = [i["titulo"] for i in cliente.get(
        URL, params={"precioMin": 100000, "precioMax": 300000}).json()["data"]["items"]]
    assert titulos == ["Barato"]


def test_limitesExactosIncluidos(cliente, crearJuego):
    crearJuego(costoAdquisicion=160000)
    datos = cliente.get(URL, params={"precioMin": 238000, "precioMax": 238000}).json()["data"]
    assert datos["total"] == 1


def test_combinaGenero(cliente, crearJuego):
    crearJuego(titulo="RPG", genero="RPG")
    crearJuego(titulo="Accion", genero="Acción")
    titulos = [i["titulo"] for i in cliente.get(URL, params={"genero": "rpg"}).json()["data"]["items"]]
    assert titulos == ["RPG"]


def test_excluyeInactivos(cliente, crearJuego):
    crearJuego(estado="INACTIVO")
    assert cliente.get(URL, params={"genero": "RPG"}).json()["data"]["total"] == 0


def test_unaSolaLlamadaACom01(cliente, crearJuego, monkeypatch):
    for indice in range(3):
        crearJuego(titulo=f"J{indice}")
    llamadas = []
    original = ClienteParametrosFinancieros.obtenerContratoCom01

    def _contar(self, sesion):
        llamadas.append(1)
        return original(self, sesion)

    monkeypatch.setattr(ClienteParametrosFinancieros, "obtenerContratoCom01", _contar)
    assert cliente.get(URL, params={"genero": "RPG"}).json()["data"]["total"] == 3
    assert len(llamadas) == 1


def test_dominioConvierteRango():
    costoMin, costoMax = convertirRangoPrecioACosto(119000, 238000, 25, 19)
    assert round(costoMin) == 80000 and round(costoMax) == 160000


def test_sinDatos(cliente, crearJuego):
    crearJuego(genero="RPG")
    respuesta = cliente.get(URL, params={"genero": "Deportes"})
    assert respuesta.status_code == 200
    assert respuesta.json() == {
        "message": "No existen juegos con los filtros indicados",
        "data": {"items": [], "pagina": 0, "tamano": 20, "total": 0},
        "success": False,
    }


def test_error400PrecioMinMayorQueMax(cliente):
    respuesta = cliente.get(URL, params={"precioMin": 900000, "precioMax": 100000})
    assert respuesta.status_code == 400
    assert respuesta.json() == {
        "message": "precioMin no puede ser mayor que precioMax", "data": None, "success": False,
    }


def test_error503Com01NoResponde(cliente, monkeypatch):
    def _falla(self, sesion):
        raise ConnectionError("MOD-00 caído")

    monkeypatch.setattr(ClienteParametrosFinancieros, "obtenerContratoCom01", _falla)
    respuesta = cliente.get(URL, params={"genero": "RPG"})
    assert respuesta.status_code == 503
    assert respuesta.json() == {
        "message": "No fue posible obtener los parámetros financieros", "data": None, "success": False,
    }


def test_error503BaseDeDatos(cliente, monkeypatch):
    def _falla(*_args, **_kwargs):
        raise OperationalError("SELECT", {}, Exception("BD caída"))

    monkeypatch.setattr(RepositorioCatalogo, "filtrarPorGeneroYCosto", _falla)
    respuesta = cliente.get(URL, params={"genero": "RPG"})
    assert respuesta.status_code == 503
    assert respuesta.json() == {"message": "No fue posible filtrar el catálogo", "data": None, "success": False}
