"""Pruebas de HU-04: Configurar margen de ganancia (PUT /api/v1/parametrizacion/margenes/ganancia)."""
from sqlalchemy.exc import OperationalError

from app.repositories.repositorio_parametros import RepositorioParametros
from tests.conftest import encabezadoAuth

URL = "/api/v1/parametrizacion/margenes/ganancia"
ADMIN = encabezadoAuth(1, rol="ADMIN")


def test_flujoExitosoConfiguraMargen(cliente):
    respuesta = cliente.put(URL, json={"margenGanancia": 30}, headers=ADMIN)
    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["message"] == "Margen de ganancia actualizado exitosamente"
    assert cuerpo["data"]["parametro"] == "MARGEN_GANANCIA" and cuerpo["data"]["margenGanancia"] == 30.0


def test_elCatalogoUsaElNuevoMargen(cliente, crearJuego):
    juego = crearJuego(costoAdquisicion=100000)
    cliente.put(URL, json={"margenGanancia": 50}, headers=ADMIN)
    precio = cliente.get(f"/api/v1/catalogo/juegos/{juego.id}/precio").json()["data"]["precioFinal"]
    assert precio == 178500  # 100000 × 1.50 × 1.19


def test_error400MargenCero(cliente):
    respuesta = cliente.put(URL, json={"margenGanancia": 0}, headers=ADMIN)
    assert respuesta.status_code == 400
    assert respuesta.json() == {"message": "El margen de ganancia debe ser mayor a 0", "data": None, "success": False}


def test_error401Y403(cliente):
    assert cliente.put(URL, json={"margenGanancia": 25}).status_code == 401
    assert cliente.put(URL, json={"margenGanancia": 25}, headers=encabezadoAuth(5)).status_code == 403


def test_error503BaseDeDatos(cliente, monkeypatch):
    def _falla(*_args, **_kwargs):
        raise OperationalError("SELECT", {}, Exception("BD caída"))

    monkeypatch.setattr(RepositorioParametros, "guardarMargen", _falla)
    respuesta = cliente.put(URL, json={"margenGanancia": 25}, headers=ADMIN)
    assert respuesta.status_code == 503
    assert respuesta.json()["message"] == "No fue posible actualizar el margen de ganancia"
