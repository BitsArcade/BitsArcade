"""Pruebas de HU-50: Filtrar historial por fechas (GET /api/v1/biblioteca/compras?desde=&hasta=)."""
from datetime import datetime

import pytest
from sqlalchemy.exc import OperationalError

from app.domain.despacho import RegistroCompra
from app.repositories.repositorio_despacho import RepositorioDespacho
from tests.conftest import encabezadoAuth

URL = "/api/v1/biblioteca/compras"


@pytest.fixture
def compras(sesion):
    # Fechas en UTC. 2026-10-01T03:00Z equivale al 30/09 22:00 en Bogotá (fuera del rango de octubre).
    for ordenId, fecha in [(5001, datetime(2026, 10, 25, 10, 3)), (5002, datetime(2026, 10, 1, 3, 0)),
                            (5003, datetime(2026, 11, 1, 4, 59)), (5004, datetime(2026, 10, 10, 12, 0))]:
        sesion.add(RegistroCompra(ordenId=ordenId, usuarioId=77, transaccionId=f"TX-{ordenId}", moneda="COP",
                                  total=238000, fecha=fecha, estadoDespacho="ENTREGADO"))
    sesion.add(RegistroCompra(ordenId=6000, usuarioId=88, transaccionId="TX-6000", moneda="COP", total=1,
                              fecha=datetime(2026, 10, 20), estadoDespacho="ENTREGADO"))
    sesion.commit()


def test_flujoExitosoRangoInclusivoBogotaDescendente(cliente, compras):
    respuesta = cliente.get(URL, params={"desde": "2026-10-01", "hasta": "2026-10-31"}, headers=encabezadoAuth(77))
    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["message"] == "Consulta de historial exitosa"
    assert [c["ordenId"] for c in cuerpo["data"]] == [5003, 5001, 5004]   # 5003 = 31/10 23:59 Bogotá
    assert cuerpo["data"][1] == {"ordenId": 5001, "fecha": "2026-10-25T10:03:00Z", "total": 238000, "moneda": "COP"}


def test_ordenAscendente(cliente, compras):
    datos = cliente.get(URL, params={"desde": "2026-10-01", "hasta": "2026-10-31", "orden": "asc"},
                        headers=encabezadoAuth(77)).json()["data"]
    assert [c["ordenId"] for c in datos] == [5004, 5001, 5003]


def test_sinComprasEnElRango(cliente, compras):
    respuesta = cliente.get(URL, params={"desde": "2025-01-01", "hasta": "2025-01-31"}, headers=encabezadoAuth(77))
    assert respuesta.json() == {"message": "No existen compras en el rango indicado", "data": [], "success": False}


def test_error400FormatoDeFecha(cliente):
    respuesta = cliente.get(URL, params={"desde": "25-10-2026", "hasta": "2026-10-31"}, headers=encabezadoAuth(77))
    assert respuesta.status_code == 400
    assert respuesta.json() == {"message": "Formato de fecha no válido. Debe ser YYYY-MM-DD", "data": None,
                                "success": False}


def test_error400DesdePosteriorAHasta(cliente):
    respuesta = cliente.get(URL, params={"desde": "2026-10-31", "hasta": "2026-10-01"}, headers=encabezadoAuth(77))
    assert respuesta.status_code == 400
    assert respuesta.json()["message"] == "La fecha 'desde' no puede ser posterior a 'hasta'"


def test_error401SinToken(cliente):
    assert cliente.get(URL).status_code == 401


def test_error503BaseDeDatos(cliente, monkeypatch):
    def _falla(*_args, **_kwargs):
        raise OperationalError("SELECT", {}, Exception("BD caída"))

    monkeypatch.setattr(RepositorioDespacho, "listarComprasUsuario", _falla)
    respuesta = cliente.get(URL, params={"desde": "2026-10-01", "hasta": "2026-10-31"}, headers=encabezadoAuth(77))
    assert respuesta.status_code == 503
    assert respuesta.json()["message"] == "No fue posible consultar el historial"
