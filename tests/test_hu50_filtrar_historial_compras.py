from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.base_datos import Base, get_db
from app.core.respuestas import ErrorAplicacion
from app.core.seguridad import UsuarioAutenticado, obtener_usuario_autenticado
from app.domain.despacho import DespachoOrdenORM, ReglasDespacho
from main import app


def crearSesionMemoria():
    motor = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=motor)
    Sesion = sessionmaker(autocommit=False, autoflush=False, bind=motor)
    return Sesion()


def insertarCompra(
    sesion,
    ordenId: int,
    usuarioId: int,
    fecha: datetime,
):
    sesion.add(
        DespachoOrdenORM(
            despacho_id=f"DSP-{ordenId}",
            orden_id=ordenId,
            usuario_id=usuarioId,
            transaccion_id=f"TX-{ordenId}",
            moneda="COP",
            tasa_cambio=1,
            total=238000,
            estado="ENTREGADA",
            notificado_externo=True,
            creado_en=fecha,
        )
    )


@pytest.fixture(autouse=True)
def limpiarDependencias():
    app.dependency_overrides.clear()
    yield
    app.dependency_overrides.clear()


def prepararConsulta(sesion, usuarioId: int = 77):
    app.dependency_overrides[get_db] = lambda: sesion
    app.dependency_overrides[obtener_usuario_autenticado] = lambda: UsuarioAutenticado(
        id=usuarioId,
        rol="CLIENTE",
    )


def test_hu50_regla_convierte_rango_inclusivo_de_bogota_a_utc():
    desde, hastaExclusiva = ReglasDespacho.validarRangoFechasHistorial(
        "2026-10-25", "2026-10-25"
    )

    assert desde == datetime(2026, 10, 25, 5, 0, tzinfo=timezone.utc)
    assert hastaExclusiva == datetime(2026, 10, 26, 5, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    ("desde", "hasta", "mensaje"),
    [
        (
            "25-10-2026",
            "2026-10-31",
            "Formato de fecha no válido. Debe ser YYYY-MM-DD",
        ),
        (
            "2026-02-30",
            "2026-10-31",
            "Formato de fecha no válido. Debe ser YYYY-MM-DD",
        ),
        (
            "2026-10-26",
            "2026-10-25",
            "La fecha 'desde' no puede ser posterior a 'hasta'",
        ),
    ],
)
def test_hu50_reglas_rechazan_fechas_no_validas(desde, hasta, mensaje):
    with pytest.raises(ErrorAplicacion) as error:
        ReglasDespacho.validarRangoFechasHistorial(desde, hasta)

    assert error.value.status_code == 400
    assert error.value.message == mensaje


def test_hu50_consulta_historial_inclusivo_aislado_y_ordenado():
    sesion = crearSesionMemoria()
    try:
        insertarCompra(
            sesion,
            5001,
            77,
            datetime(2026, 10, 25, 10, 3, tzinfo=timezone.utc),
        )
        insertarCompra(
            sesion,
            5002,
            77,
            datetime(2026, 10, 25, 15, 3, tzinfo=timezone.utc),
        )
        insertarCompra(
            sesion,
            5003,
            77,
            datetime(2026, 10, 25, 5, 0, tzinfo=timezone.utc),
        )
        insertarCompra(
            sesion,
            5004,
            77,
            datetime(2026, 10, 26, 4, 59, 59, tzinfo=timezone.utc),
        )
        insertarCompra(
            sesion,
            5005,
            77,
            datetime(2026, 10, 25, 4, 59, 59, tzinfo=timezone.utc),
        )
        insertarCompra(
            sesion,
            5006,
            77,
            datetime(2026, 10, 26, 5, 0, tzinfo=timezone.utc),
        )
        insertarCompra(
            sesion,
            5007,
            88,
            datetime(2026, 10, 25, 10, 3, tzinfo=timezone.utc),
        )
        sesion.commit()
        prepararConsulta(sesion)
        cliente = TestClient(app)

        respuesta = cliente.get(
            "/api/v1/biblioteca/compras",
            params={"desde": "2026-10-25", "hasta": "2026-10-25"},
        )

        assert respuesta.status_code == 200
        cuerpo = respuesta.json()
        assert set(cuerpo) == {"message", "data", "success"}
        assert cuerpo["message"] == "Consulta de historial exitosa"
        assert cuerpo["success"] is True
        assert [compra["orderId"] for compra in cuerpo["data"]] == [
            5004,
            5002,
            5001,
            5003,
        ]
        assert all(
            set(compra) == {"orderId", "fecha", "total", "moneda"}
            for compra in cuerpo["data"]
        )
        assert cuerpo["data"][0] == {
            "orderId": 5004,
            "fecha": "2026-10-26T04:59:59Z",
            "total": 238000,
            "moneda": "COP",
        }
        assert cliente.get(
            "/api/v1/biblioteca/compras",
            params={
                "desde": "2026-10-25",
                "hasta": "2026-10-25",
                "orden": "asc",
            },
        ).json()["data"][0]["orderId"] == 5003
    finally:
        sesion.close()


def test_hu50_sin_compras_retorna_lista_vacia():
    sesion = crearSesionMemoria()
    try:
        prepararConsulta(sesion)
        respuesta = TestClient(app).get(
            "/api/v1/biblioteca/compras",
            params={"desde": "2026-10-01", "hasta": "2026-10-31"},
        )

        assert respuesta.status_code == 200
        assert respuesta.json() == {
            "message": "No existen compras en el rango indicado",
            "data": [],
            "success": False,
        }
    finally:
        sesion.close()


@pytest.mark.parametrize(
    ("desde", "hasta", "mensaje"),
    [
        (
            "25-10-2026",
            "2026-10-31",
            "Formato de fecha no válido. Debe ser YYYY-MM-DD",
        ),
        (
            "2026-10-26",
            "2026-10-25",
            "La fecha 'desde' no puede ser posterior a 'hasta'",
        ),
    ],
)
def test_hu50_api_retorna_400_para_fechas_invalidas(desde, hasta, mensaje):
    prepararConsulta(None)
    respuesta = TestClient(app).get(
        "/api/v1/biblioteca/compras",
        params={"desde": desde, "hasta": hasta},
    )

    assert respuesta.status_code == 400
    assert respuesta.json() == {
        "message": mensaje,
        "data": None,
        "success": False,
    }


def test_hu50_api_rechaza_orden_no_permitido():
    prepararConsulta(None)
    respuesta = TestClient(app).get(
        "/api/v1/biblioteca/compras",
        params={
            "desde": "2026-10-01",
            "hasta": "2026-10-31",
            "orden": "ascendente",
        },
    )

    assert respuesta.status_code == 400
    assert respuesta.json() == {
        "message": "El orden debe ser 'asc' o 'desc'",
        "data": None,
        "success": False,
    }


@pytest.mark.parametrize(
    "encabezados",
    [{}, {"Authorization": "Bearer token-invalido"}],
)
def test_hu50_requiere_token_valido(encabezados):
    respuesta = TestClient(app).get(
        "/api/v1/biblioteca/compras",
        params={"desde": "2026-10-01", "hasta": "2026-10-31"},
        headers=encabezados,
    )

    assert respuesta.status_code == 401
    assert respuesta.json() == {
        "message": "Token inválido, expirado o ausente",
        "data": None,
        "success": False,
    }


def test_hu50_fallo_de_base_de_datos_retorna_503():
    sesion = MagicMock()
    sesion.query.side_effect = OperationalError(
        "SELECT",
        {},
        Exception("Base de datos no disponible"),
    )
    prepararConsulta(sesion)

    respuesta = TestClient(app).get(
        "/api/v1/biblioteca/compras",
        params={"desde": "2026-10-01", "hasta": "2026-10-31"},
    )

    assert respuesta.status_code == 503
    assert respuesta.json() == {
        "message": "No fue posible consultar el historial",
        "data": None,
        "success": False,
    }
