from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.core.respuestas import ErrorAplicacion
from app.domain.orden import (
    ESTADO_ORDEN_CANCELADA,
    ESTADO_ORDEN_ENTREGADA,
    ESTADO_ORDEN_PAGADA,
    ESTADO_ORDEN_PENDIENTE,
    ESTADO_ORDEN_PROCESANDO,
    MENSAJE_TRANSICION_NO_PERMITIDA,
    Orden,
    validar_transicion_estado_interno,
)
from app.services.servicio_despacho import (
    AdaptadorOrdenesLocalCOM09,
    ServicioDespacho,
)
from main import app

client = TestClient(app)


# =====================================================================
# 1. PRUEBAS UNITARIAS DE DOMINIO (HU-42)
# =====================================================================


def test_hu42_dominio_transicion_pagada_a_entregada_valida():
    fecha_entrega = datetime(2026, 10, 25, 10, 3, 5, tzinfo=timezone.utc)
    destino = validar_transicion_estado_interno(
        ESTADO_ORDEN_PAGADA,
        ESTADO_ORDEN_ENTREGADA,
        entregada_en=fecha_entrega,
    )
    assert destino == ESTADO_ORDEN_ENTREGADA


@pytest.mark.parametrize(
    "estado_origen",
    [
        ESTADO_ORDEN_PENDIENTE,
        ESTADO_ORDEN_PROCESANDO,
        ESTADO_ORDEN_CANCELADA,
        ESTADO_ORDEN_ENTREGADA,
    ],
)
def test_hu42_dominio_rechaza_transicion_a_entregada_si_no_esta_pagada(estado_origen):
    fecha_entrega = datetime(2026, 10, 25, 10, 3, 5, tzinfo=timezone.utc)
    with pytest.raises(ErrorAplicacion) as exc:
        validar_transicion_estado_interno(
            estado_origen,
            ESTADO_ORDEN_ENTREGADA,
            entregada_en=fecha_entrega,
        )
    assert exc.value.status_code == 409
    assert exc.value.message == MENSAJE_TRANSICION_NO_PERMITIDA


def test_hu42_dominio_exige_entregada_en_para_marcar_entregada():
    with pytest.raises(ErrorAplicacion) as exc:
        validar_transicion_estado_interno(
            ESTADO_ORDEN_PAGADA,
            ESTADO_ORDEN_ENTREGADA,
            entregada_en=None,
        )
    assert exc.value.status_code == 400


# =====================================================================
# 2. PRUEBAS FUNCIONALES DEL CONTRATO COM-09 Y SERVICIO DESPACHO (HU-42)
# =====================================================================


def test_hu42_caso1_y_caso2_cierre_exitoso_y_contrato_com09():
    sesion_mock = MagicMock()
    orden_pagada = Orden(
        id=5001,
        usuario_id=10,
        estado=ESTADO_ORDEN_PAGADA,
        moneda="COP",
        subtotal_bruto=120000.0,
        descuento_total=0.0,
        total=120000.0,
    )
    sesion_mock.query.return_value.filter.return_value.first.return_value = orden_pagada

    adaptador_com09 = AdaptadorOrdenesLocalCOM09(db=sesion_mock)
    servicio_despacho = ServicioDespacho(
        repositorio=MagicMock(),
        adaptador_inventario=MagicMock(),
        adaptador_ordenes=adaptador_com09,
    )

    fecha_entrega = datetime(2026, 10, 25, 10, 3, 5, tzinfo=timezone.utc)
    resultado = servicio_despacho.marcar_orden_como_entregada(
        orden_id=5001,
        entregada_en=fecha_entrega,
    )

    assert set(resultado.keys()) == {"message", "data", "success"}
    assert resultado["success"] is True
    assert resultado["message"] == "Orden cerrada como entregada"
    assert set(resultado["data"].keys()) == {"ordenId", "estado", "confirmado"}
    assert resultado["data"] == {
        "ordenId": 5001,
        "estado": "ENTREGADA",
        "confirmado": True,
    }
    assert orden_pagada.estado == ESTADO_ORDEN_ENTREGADA
    assert orden_pagada.entregada_en == fecha_entrega


def test_hu42_caso3_error_409_orden_no_pagada():
    sesion_mock = MagicMock()
    orden_pendiente = Orden(
        id=5001,
        usuario_id=10,
        estado=ESTADO_ORDEN_PENDIENTE,
        moneda="COP",
        subtotal_bruto=120000.0,
        descuento_total=0.0,
        total=120000.0,
    )
    sesion_mock.query.return_value.filter.return_value.first.return_value = orden_pendiente

    adaptador_com09 = AdaptadorOrdenesLocalCOM09(db=sesion_mock)
    servicio_despacho = ServicioDespacho(
        repositorio=MagicMock(),
        adaptador_inventario=MagicMock(),
        adaptador_ordenes=adaptador_com09,
    )

    with pytest.raises(ErrorAplicacion) as exc:
        servicio_despacho.marcar_orden_como_entregada(
            orden_id=5001,
            entregada_en=datetime(2026, 10, 25, 10, 3, 5, tzinfo=timezone.utc),
        )

    assert exc.value.status_code == 409
    assert exc.value.message == "Transición de estado no permitida"


def test_hu42_caso4_error_503_fallo_bd_al_marcar_entregada():
    sesion_mock = MagicMock()
    orden_pagada = Orden(
        id=5001,
        usuario_id=10,
        estado=ESTADO_ORDEN_PAGADA,
        moneda="COP",
        subtotal_bruto=120000.0,
        descuento_total=0.0,
        total=120000.0,
    )
    sesion_mock.query.return_value.filter.return_value.first.return_value = orden_pagada
    sesion_mock.commit.side_effect = OperationalError("SELECT 1", {}, Exception("DB caída"))

    adaptador_com09 = AdaptadorOrdenesLocalCOM09(db=sesion_mock)
    servicio_despacho = ServicioDespacho(
        repositorio=MagicMock(),
        adaptador_inventario=MagicMock(),
        adaptador_ordenes=adaptador_com09,
    )

    with pytest.raises(ErrorAplicacion) as exc:
        servicio_despacho.marcar_orden_como_entregada(
            orden_id=5001,
            entregada_en=datetime(2026, 10, 25, 10, 3, 5, tzinfo=timezone.utc),
        )

    assert exc.value.status_code == 503
    assert exc.value.message == "No fue posible marcar la orden como entregada"


def test_hu42_endpoint_com09_autoriza_mod06_y_rechaza_modulo_no_autorizado():
    respuesta_403 = client.patch(
        "/interno/v1/ordenes/5001/estado",
        headers={"X-Service-Module": "MOD-99"},
        json={"estado": "ENTREGADA", "entregadaEn": "2026-10-25T10:03:05Z"},
    )
    assert respuesta_403.status_code == 403
    cuerpo = respuesta_403.json()
    assert cuerpo["success"] is False