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
from app.domain.despacho import (
    DespachoOrden,
    DespachoOrdenORM,
    EstadoDespacho,
    LicenciaUsuario,
    LicenciaUsuarioORM,
    ReglasDespacho,
)
from app.repositories.repositorio_despacho import RepositorioDespacho
from app.services.servicio_despacho import ServicioDespacho
from main import app


def _crear_sesion_memoria():
    motor = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=motor)
    Sesion = sessionmaker(autocommit=False, autoflush=False, bind=motor)
    return Sesion()


def _insertar_compra(
    db,
    *,
    orden_id: int = 5001,
    usuario_id: int = 77,
    transaccion_id: str = "TX-9001",
    moneda: str = "COP",
    tasa_cambio: float = 1.0,
    total: float = 238000.0,
    estado: str = "ENTREGADA",
    fecha: datetime | None = None,
    items: list[dict] | None = None,
):
    fecha_compra = fecha or datetime(2026, 10, 25, 10, 3, 0, tzinfo=timezone.utc)
    despacho = DespachoOrdenORM(
        despacho_id=f"DSP-{orden_id}",
        orden_id=orden_id,
        usuario_id=usuario_id,
        transaccion_id=transaccion_id,
        moneda=moneda,
        tasa_cambio=tasa_cambio,
        total=total,
        estado=estado,
        notificado_externo=True,
        creado_en=fecha_compra,
    )
    db.add(despacho)

    lista_items = items or [
        {
            "licencia_id": f"LIC-{orden_id}-1",
            "juego_id": 101,
            "titulo": "Aurora Quest",
            "plataforma": "PC",
            "precio_unitario": 238000.0,
            "clave_digital": "AAAAA-BBBBB-CCCCC",
            "clave_enmascarada": "*****-*****-*****",
        }
    ]

    for idx, item in enumerate(lista_items, start=1):
        lic = LicenciaUsuarioORM(
            licencia_id=item["licencia_id"],
            despacho_id=f"DSP-{orden_id}",
            orden_id=orden_id,
            usuario_id=usuario_id,
            juego_id=item["juego_id"],
            titulo_juego=item["titulo"],
            plataforma=item.get("plataforma", "PC"),
            precio_unitario=item.get("precio_unitario", 238000.0),
            reserva_id=f"res-{orden_id}-{idx}",
            key_inventario_id=None,
            clave_digital=item["clave_digital"],
            clave_enmascarada=item["clave_enmascarada"],
            huella_clave=f"huella-{orden_id}-{idx}",
            revelada=False,
            revelada_en=None,
            asignada_en=fecha_compra,
        )
        db.add(lic)

    db.commit()


# =====================================================================
# 1. PRUEBAS UNITARIAS DE DOMINIO (HU-47)
# =====================================================================


def test_hu47_dominio_valida_propiedad_compra_aislamiento_usuario():
    ahora = datetime(2026, 10, 25, 10, 3, 0, tzinfo=timezone.utc)
    compra = DespachoOrden(
        despacho_id="DSP-5001",
        orden_id=5001,
        usuario_id=77,
        transaccion_id="TX-9001",
        estado=EstadoDespacho.ENTREGADA,
        notificado_externo=True,
        creado_en=ahora,
        licencias=[
            LicenciaUsuario(
                licencia_id="LIC-1",
                despacho_id="DSP-5001",
                orden_id=5001,
                usuario_id=77,
                juego_id=101,
                titulo_juego="Aurora Quest",
                plataforma="PC",
                reserva_id="res-9f1",
                key_inventario_id=1,
                clave_digital="AAAAA-BBBBB-CCCCC",
                clave_enmascarada="*****-*****-*****",
                revelada=False,
                revelada_en=None,
                asignada_en=ahora,
                precio_unitario=238000.0,
            )
        ],
        moneda="COP",
        tasa_cambio=1.0,
        total=238000.0,
    )

    validada = ReglasDespacho.validar_propiedad_compra(compra=compra, usuario_id=77)
    assert validada.orden_id == 5001

    with pytest.raises(ErrorAplicacion) as exc_ajena:
        ReglasDespacho.validar_propiedad_compra(compra=compra, usuario_id=99)
    assert exc_ajena.value.status_code == 404
    assert exc_ajena.value.message == "La compra indicada no existe"

    with pytest.raises(ErrorAplicacion) as exc_none:
        ReglasDespacho.validar_propiedad_compra(compra=None, usuario_id=77)
    assert exc_none.value.status_code == 404
    assert exc_none.value.message == "La compra indicada no existe"


# =====================================================================
# 2. PRUEBAS FUNCIONALES DEL ENDPOINT GET /api/v1/biblioteca/compras/{ordenId}
# =====================================================================


def test_hu47_caso1_y_caso2_consulta_compra_exitosa_y_contrato():
    db = _crear_sesion_memoria()
    try:
        _insertar_compra(db, orden_id=5001, usuario_id=77)

        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides[obtener_usuario_autenticado] = lambda: UsuarioAutenticado(
            id=77, rol="CLIENTE"
        )

        cliente = TestClient(app)
        respuesta = cliente.get("/api/v1/biblioteca/compras/5001")

        assert respuesta.status_code == 200
        cuerpo = respuesta.json()
        assert set(cuerpo.keys()) == {"message", "data", "success"}
        assert cuerpo["success"] is True
        assert cuerpo["message"] == "Consulta de compra exitosa"

        data = cuerpo["data"]
        assert set(data.keys()) == {
            "ordenId",
            "fecha",
            "moneda",
            "total",
            "tasaCambio",
            "transaccionId",
            "estadoOrden",
            "items",
        }
        assert data["ordenId"] == 5001
        assert data["moneda"] == "COP"
        assert data["total"] == 238000
        assert data["tasaCambio"] == 1
        assert data["transaccionId"] == "TX-9001"
        assert data["estadoOrden"] == "ENTREGADA"

        assert len(data["items"]) == 1
        item = data["items"][0]
        assert set(item.keys()) == {
            "juegoId",
            "titulo",
            "precioUnitario",
            "claveLicencia",
        }
        assert item["juegoId"] == 101
        assert item["titulo"] == "Aurora Quest"
        assert item["precioUnitario"] == 238000
        assert item["claveLicencia"] == "*****-*****-*****"
        assert "AAAAA-BBBBB-CCCCC" not in respuesta.text
    finally:
        app.dependency_overrides.clear()
        db.close()


def test_hu47_caso3_error_404_orden_ajena_o_inexistente():
    db = _crear_sesion_memoria()
    try:
        _insertar_compra(db, orden_id=5001, usuario_id=88)

        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides[obtener_usuario_autenticado] = lambda: UsuarioAutenticado(
            id=77, rol="CLIENTE"
        )

        cliente = TestClient(app)
        resp_ajena = cliente.get("/api/v1/biblioteca/compras/5001")
        assert resp_ajena.status_code == 404
        assert resp_ajena.json() == {
            "message": "La compra indicada no existe",
            "data": None,
            "success": False,
        }

        resp_inexistente = cliente.get("/api/v1/biblioteca/compras/9999")
        assert resp_inexistente.status_code == 404
        assert resp_inexistente.json()["message"] == "La compra indicada no existe"
    finally:
        app.dependency_overrides.clear()
        db.close()


def test_hu47_caso4_error_401_sin_token():
    app.dependency_overrides.clear()
    cliente = TestClient(app)
    respuesta = cliente.get("/api/v1/biblioteca/compras/5001")
    assert respuesta.status_code == 401


def test_hu47_caso5_error_503_fallo_base_datos():
    sesion_mock = MagicMock()
    sesion_mock.query.side_effect = OperationalError("SELECT 1", {}, Exception("DB caída"))

    repo = RepositorioDespacho(sesion_mock)
    servicio = ServicioDespacho(repositorio=repo)

    with pytest.raises(ErrorAplicacion) as exc:
        servicio.consultar_detalle_compra_pasada(orden_id=5001, usuario_id=77)

    assert exc.value.status_code == 503
    assert exc.value.message == "No fue posible consultar la compra"