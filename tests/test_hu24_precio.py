"""Pruebas de HU-24: Calcular y consultar precio final público (+ contrato COM-11)."""
import pytest
from sqlalchemy.exc import OperationalError

from app.core.respuestas import ErrorAplicacion
from app.domain.catalogo import calcular_precio_final, calcular_precio_piso
from app.repositories.repositorio_catalogo import RepositorioCatalogo
from app.services.servicio_parametros import ServicioParametros


# --- Pruebas unitarias de dominio (RN-01 / RN-02) ---

def test_rn01_formula_precio_final():
    # C_A=160000, M=25%, IVA=19% -> 160000 × 1.25 × 1.19 = 238000
    assert calcular_precio_final(160000, 0.25, 0.19) == 238000


def test_rn02_margen_negativo_simulado_retorna_422():
    with pytest.raises(ErrorAplicacion) as error:
        calcular_precio_final(160000, -0.50, 0.19)
    assert error.value.status_code == 422
    assert error.value.message == "El precio calculado viola la política de margen mínimo (RN-02)"


def test_precio_piso():
    assert calcular_precio_piso(40, 0.19) == 47.6


# --- Pruebas funcionales del endpoint ---

def test_flujo_exitoso(cliente, crear_juego):
    juego = crear_juego(costo_adquisicion=160000)
    respuesta = cliente.get(f"/api/v1/catalogo/juegos/{juego.id}/precio")
    assert respuesta.status_code == 200
    assert respuesta.json() == {
        "message": "Consulta de precio exitosa",
        "data": {"gameId": juego.id, "moneda": "COP", "ivaPorcentaje": 19.0, "precioFinal": 238000},
        "success": True,
    }


def test_usa_parametros_vigentes_de_mod00(cliente, crear_juego):
    juego = crear_juego(costo_adquisicion=100000)
    cliente.put("/api/v1/parametros/impuesto-iva", json={"tasa_iva": 10})
    cliente.put("/api/v1/parametros/margen-ganancia", json={"margen_ganancia": 50})
    datos = cliente.get(f"/api/v1/catalogo/juegos/{juego.id}/precio").json()["data"]
    assert datos["ivaPorcentaje"] == 10.0
    assert datos["precioFinal"] == 165000  # 100000 × 1.5 × 1.1


def test_una_sola_llamada_a_com01(cliente, crear_juego, monkeypatch):
    juego = crear_juego()
    llamadas = []
    original = ServicioParametros.obtener_contrato_com01

    def _contar(self, sesion):
        llamadas.append(1)
        return original(self, sesion)

    monkeypatch.setattr(ServicioParametros, "obtener_contrato_com01", _contar)
    cliente.get(f"/api/v1/catalogo/juegos/{juego.id}/precio")
    assert len(llamadas) == 1


def test_no_expone_costo_ni_margen(cliente, crear_juego):
    juego = crear_juego(costo_adquisicion=160000)
    datos = cliente.get(f"/api/v1/catalogo/juegos/{juego.id}/precio").json()["data"]
    assert set(datos) == {"gameId", "moneda", "ivaPorcentaje", "precioFinal"}


def test_error_404_juego_inexistente(cliente):
    respuesta = cliente.get("/api/v1/catalogo/juegos/9999/precio")
    assert respuesta.status_code == 404
    assert respuesta.json() == {"message": "El juego indicado no existe", "data": None, "success": False}


def test_error_422_rn02(cliente, crear_juego, monkeypatch):
    juego = crear_juego()
    monkeypatch.setattr(ServicioParametros, "obtener_contrato_com01",
                        lambda self, sesion: {"taxRate": 0.19, "margin": -0.5})
    respuesta = cliente.get(f"/api/v1/catalogo/juegos/{juego.id}/precio")
    assert respuesta.status_code == 422
    assert respuesta.json()["message"] == "El precio calculado viola la política de margen mínimo (RN-02)"
    assert respuesta.json()["success"] is False


def test_error_503_com01_no_responde(cliente, crear_juego, monkeypatch):
    juego = crear_juego()

    def _falla(self, sesion):
        raise ConnectionError("MOD-00 caído")

    monkeypatch.setattr(ServicioParametros, "obtener_contrato_com01", _falla)
    respuesta = cliente.get(f"/api/v1/catalogo/juegos/{juego.id}/precio")
    assert respuesta.status_code == 503
    assert respuesta.json() == {
        "message": "No fue posible obtener los parámetros financieros", "data": None, "success": False,
    }


def test_error_503_base_de_datos(cliente, monkeypatch):
    def _falla(*_args, **_kwargs):
        raise OperationalError("SELECT", {}, Exception("BD caída"))

    monkeypatch.setattr(RepositorioCatalogo, "obtener_publicado_por_id", _falla)
    respuesta = cliente.get("/api/v1/catalogo/juegos/1/precio")
    assert respuesta.status_code == 503
    assert respuesta.json() == {"message": "No fue posible calcular el precio", "data": None, "success": False}


# --- Contrato COM-11 ---

def test_com11_juego_existente(cliente, crear_juego):
    juego = crear_juego(costo_adquisicion=160000, estado="PREVENTA")
    respuesta = cliente.get(f"/internal/v1/catalogo/juegos/{juego.id}")
    assert respuesta.status_code == 200
    assert respuesta.json() == {
        "exists": True, "title": "Aurora Quest", "status": "PREVENTA",
        "finalPrice": 238000, "floorPrice": 190400,
    }


def test_com11_juego_inexistente(cliente):
    assert cliente.get("/internal/v1/catalogo/juegos/9999").json() == {
        "exists": False, "title": None, "status": None, "finalPrice": None, "floorPrice": None,
    }
