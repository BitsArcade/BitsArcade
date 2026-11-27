"""Pruebas de HU-24: Calcular y consultar precio final público (+ contrato COM-11)."""
import pytest
from sqlalchemy.exc import OperationalError

from app.core.respuestas import ErrorAplicacion
from app.domain.catalogo import calcularPrecioFinal, calcularPrecioPiso
from app.repositories.repositorio_catalogo import RepositorioCatalogo
from app.services.servicio_catalogo import ClienteParametrosFinancieros
from tests.conftest import configurarParametros


# --- Pruebas unitarias de dominio (RN-01 / RN-02) ---

def test_rn01FormulaPrecioFinal():
    # C_A=160000, M=25%, IVA=19% -> 160000 × 1.25 × 1.19 = 238000
    assert calcularPrecioFinal(160000, 25, 19) == 238000


def test_rn02MargenNegativoSimuladoRetorna409():
    with pytest.raises(ErrorAplicacion) as error:
        calcularPrecioFinal(160000, -50, 19)
    assert error.value.codigoHttp == 409
    assert error.value.mensaje == "El precio calculado viola la política de margen mínimo (RN-02)"


def test_precioPiso():
    assert calcularPrecioPiso(40, 19) == 47.6


# --- Pruebas funcionales del endpoint ---

def test_flujoExitoso(cliente, crearJuego):
    juego = crearJuego(costoAdquisicion=160000)
    respuesta = cliente.get(f"/api/v1/catalogo/juegos/{juego.id}/precio")
    assert respuesta.status_code == 200
    assert respuesta.json() == {
        "message": "Consulta de precio exitosa",
        "data": {"juegoId": juego.id, "moneda": "COP", "tasaIva": 19.0, "precioFinal": 238000},
        "success": True,
    }


def test_usaParametrosVigentesDeMod00(cliente, crearJuego):
    juego = crearJuego(costoAdquisicion=100000)
    configurarParametros(cliente, tasaIva=10, margenGanancia=50)
    datos = cliente.get(f"/api/v1/catalogo/juegos/{juego.id}/precio").json()["data"]
    assert datos["tasaIva"] == 10.0
    assert datos["precioFinal"] == 165000  # 100000 × 1.5 × 1.1


def test_unaSolaLlamadaACom01(cliente, crearJuego, monkeypatch):
    juego = crearJuego()
    llamadas = []
    original = ClienteParametrosFinancieros.obtenerContratoCom01

    def _contar(self, sesion):
        llamadas.append(1)
        return original(self, sesion)

    monkeypatch.setattr(ClienteParametrosFinancieros, "obtenerContratoCom01", _contar)
    cliente.get(f"/api/v1/catalogo/juegos/{juego.id}/precio")
    assert len(llamadas) == 1


def test_noExponeCostoNiMargen(cliente, crearJuego):
    juego = crearJuego(costoAdquisicion=160000)
    datos = cliente.get(f"/api/v1/catalogo/juegos/{juego.id}/precio").json()["data"]
    assert set(datos) == {"juegoId", "moneda", "tasaIva", "precioFinal"}


def test_error404JuegoInexistente(cliente):
    respuesta = cliente.get("/api/v1/catalogo/juegos/9999/precio")
    assert respuesta.status_code == 404
    assert respuesta.json() == {"message": "El juego indicado no existe", "data": None, "success": False}


def test_error409Rn02(cliente, crearJuego, monkeypatch):
    juego = crearJuego()
    monkeypatch.setattr(ClienteParametrosFinancieros, "obtenerContratoCom01",
                        lambda self, sesion: {"tasaIva": 19, "margenGanancia": -50, "monedaBase": "COP"})
    respuesta = cliente.get(f"/api/v1/catalogo/juegos/{juego.id}/precio")
    assert respuesta.status_code == 409
    assert respuesta.json()["message"] == "El precio calculado viola la política de margen mínimo (RN-02)"
    assert respuesta.json()["success"] is False


def test_error503Com01NoResponde(cliente, crearJuego, monkeypatch):
    juego = crearJuego()

    def _falla(self, sesion):
        raise ConnectionError("MOD-00 caído")

    monkeypatch.setattr(ClienteParametrosFinancieros, "obtenerContratoCom01", _falla)
    respuesta = cliente.get(f"/api/v1/catalogo/juegos/{juego.id}/precio")
    assert respuesta.status_code == 503
    assert respuesta.json() == {
        "message": "No fue posible obtener los parámetros financieros", "data": None, "success": False,
    }


def test_error503BaseDeDatos(cliente, monkeypatch):
    def _falla(*_args, **_kwargs):
        raise OperationalError("SELECT", {}, Exception("BD caída"))

    monkeypatch.setattr(RepositorioCatalogo, "obtenerPublicadoPorId", _falla)
    respuesta = cliente.get("/api/v1/catalogo/juegos/1/precio")
    assert respuesta.status_code == 503
    assert respuesta.json() == {"message": "No fue posible calcular el precio", "data": None, "success": False}


# --- Contrato COM-11 ---

def test_com11JuegoExistente(cliente, crearJuego):
    juego = crearJuego(costoAdquisicion=160000, estado="PREVENTA")
    respuesta = cliente.get(f"/interno/v1/catalogo/juegos/{juego.id}")
    assert respuesta.status_code == 200
    assert respuesta.json() == {
        "message": "Consulta de juego exitosa",
        "data": {"juegoId": juego.id, "existe": True, "titulo": "Aurora Quest", "estado": "PREVENTA",
                 "precioFinal": 238000, "precioMinimo": 190400},
        "success": True,
    }


def test_com11SinTokenDeServicioRetorna401(clienteSinTokenServicio, crearJuego):
    juego = crearJuego()
    respuesta = clienteSinTokenServicio.get(f"/interno/v1/catalogo/juegos/{juego.id}")
    assert respuesta.status_code == 401
    assert respuesta.json() == {"message": "Token de servicio inválido o ausente", "data": None, "success": False}


def test_com11JuegoInexistente(cliente):
    assert cliente.get("/interno/v1/catalogo/juegos/9999").json() == {
        "message": "Consulta de juego exitosa",
        "data": {"juegoId": 9999, "existe": False, "titulo": None, "estado": None, "precioFinal": None,
                 "precioMinimo": None},
        "success": True,
    }
