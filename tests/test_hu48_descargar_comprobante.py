from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.despacho import obtener_servicio_despacho
from app.core.base_datos import Base, get_db
from app.core.respuestas import ErrorAplicacion
from app.core.seguridad import UsuarioAutenticado, obtener_usuario_autenticado
from app.domain.despacho import (
    CompradorComprobanteSalida,
    DespachoOrdenORM,
    LicenciaUsuarioORM,
    ReglasDespacho,
)
from app.domain.orden import ItemOrden, Orden
from app.repositories.repositorio_despacho import RepositorioDespacho
from app.services.servicio_despacho import ServicioDespacho
from app.services.servicio_orden import ServicioOrden
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


def insertarCompra(sesion, ordenId: int = 5001, usuarioId: int = 77):
    fecha = datetime(2026, 10, 25, 10, 3, 0, tzinfo=timezone.utc)
    orden = Orden(
        id=ordenId,
        usuario_id=usuarioId,
        estado="ENTREGADA",
        moneda="COP",
        subtotal_bruto=238000,
        descuento_total=0,
        total=238000,
        items=[
            ItemOrden(
                juego_id=101,
                titulo="Aurora Quest",
                cantidad=1,
                precio_unitario=238000,
                descuento_volumen=0,
                subtotal=238000,
            )
        ],
    )
    despacho = DespachoOrdenORM(
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
    licencia = LicenciaUsuarioORM(
        licencia_id=f"LIC-{ordenId}",
        despacho_id=f"DSP-{ordenId}",
        orden_id=ordenId,
        usuario_id=usuarioId,
        juego_id=101,
        titulo_juego="Aurora Quest",
        plataforma="PC",
        precio_unitario=238000,
        reserva_id=f"res-{ordenId}",
        key_inventario_id=None,
        clave_digital="AAAA-BBBB-CCCC-DDDD",
        clave_enmascarada="AAAA-BBBB-CCCC-****",
        huella_clave=f"huella-{ordenId}",
        revelada=False,
        revelada_en=None,
        asignada_en=fecha,
    )
    sesion.add_all([orden, despacho, licencia])
    sesion.commit()


class AdaptadorPerfilCompradorPruebas:
    def obtenerPerfil(self, usuarioId: int) -> CompradorComprobanteSalida:
        assert usuarioId == 77
        return CompradorComprobanteSalida(
            nombre="Ana Pérez",
            correo="jugador@correo.com",
        )


@pytest.fixture(autouse=True)
def limpiarDependencias():
    yield
    app.dependency_overrides.clear()


def test_hu48_regla_valida_que_base_iva_y_total_cuadren():
    ReglasDespacho.validarCuadreComprobante(
        base_gravable=200000,
        valor_iva=38000,
        total=238000,
    )

    with pytest.raises(ErrorAplicacion) as error:
        ReglasDespacho.validarCuadreComprobante(
            base_gravable=200000,
            valor_iva=37999,
            total=238000,
        )

    assert error.value.status_code == 409


def test_hu48_descarga_comprobante_json_contrato_y_desglose():
    sesion = crearSesionMemoria()
    try:
        insertarCompra(sesion)
        app.dependency_overrides[get_db] = lambda: sesion
        app.dependency_overrides[obtener_usuario_autenticado] = lambda: UsuarioAutenticado(
            id=77,
            rol="CLIENTE",
        )
        app.dependency_overrides[obtener_servicio_despacho] = lambda: ServicioDespacho(
            repositorio=RepositorioDespacho(sesion),
            servicioOrden=ServicioOrden(),
            adaptadorPerfilComprador=AdaptadorPerfilCompradorPruebas(),
        )

        respuesta = TestClient(app).get(
            "/api/v1/biblioteca/compras/5001/comprobante"
        )

        assert respuesta.status_code == 200
        assert respuesta.headers["content-type"].startswith("application/json")
        assert respuesta.headers["content-disposition"] == (
            'attachment; filename="comprobante-CMP-5001.json"'
        )
        cuerpo = respuesta.json()
        assert set(cuerpo) == {"message", "data", "success"}
        assert cuerpo["message"] == "Comprobante generado"
        assert cuerpo["success"] is True
        assert cuerpo["data"] == {
            "numero": "CMP-5001",
            "emisor": "BitArcade",
            "comprador": {
                "nombre": "Ana Pérez",
                "correo": "jugador@correo.com",
            },
            "fecha": "2026-10-25T10:03:00+00:00",
            "moneda": "COP",
            "desglose": {
                "baseGravable": 200000,
                "valorIva": 38000,
                "total": 238000,
            },
            "tasaCambio": 1,
            "transaccionId": "TX-5001",
            "items": [{"titulo": "Aurora Quest", "cantidad": 1}],
        }
        assert "AAAA-BBBB-CCCC-DDDD" not in respuesta.text
    finally:
        sesion.close()


def test_hu48_rechaza_compra_ajena_con_404():
    sesion = crearSesionMemoria()
    try:
        insertarCompra(sesion, usuarioId=88)
        app.dependency_overrides[get_db] = lambda: sesion
        app.dependency_overrides[obtener_usuario_autenticado] = lambda: UsuarioAutenticado(
            id=77,
            rol="CLIENTE",
        )

        respuesta = TestClient(app).get(
            "/api/v1/biblioteca/compras/5001/comprobante"
        )

        assert respuesta.status_code == 404
        assert respuesta.json() == {
            "message": "La compra indicada no existe",
            "data": None,
            "success": False,
        }
    finally:
        sesion.close()


def test_hu48_requiere_token():
    respuesta = TestClient(app).get(
        "/api/v1/biblioteca/compras/5001/comprobante"
    )

    assert respuesta.status_code == 401
    assert respuesta.json()["message"] == "Token inválido, expirado o ausente"


def test_hu48_fallo_de_base_de_datos_retorna_503():
    sesion = MagicMock()
    sesion.query.side_effect = OperationalError(
        "SELECT",
        {},
        Exception("Base de datos no disponible"),
    )
    app.dependency_overrides[get_db] = lambda: sesion
    app.dependency_overrides[obtener_usuario_autenticado] = lambda: UsuarioAutenticado(
        id=77,
        rol="CLIENTE",
    )

    respuesta = TestClient(app).get(
        "/api/v1/biblioteca/compras/5001/comprobante"
    )

    assert respuesta.status_code == 503
    assert respuesta.json() == {
        "message": "No fue posible generar el comprobante",
        "data": None,
        "success": False,
    }
