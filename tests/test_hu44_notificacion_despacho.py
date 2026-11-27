"""Pruebas de HU-44: Notificación automática de despacho (POST /externo/v1/notificaciones/despacho)."""
import pytest

from app.domain.despacho import NotificacionDespacho
from app.services.cliente_notificaciones import ENVIOS_SIMULADOS, ClienteNotificaciones
from app.services.servicio_despacho import ServicioDespacho
from tests.apoyo_modulos import crearUsuario, despacharOrden, limpiarSimulaciones


@pytest.fixture(autouse=True)
def _limpiar():
    limpiarSimulaciones()


def test_despachoEnviaPlantillaSinLaClave(cliente, sesion):
    usuario = crearUsuario(sesion)
    despacharOrden(cliente, sesion, usuario.id)
    envio = ENVIOS_SIMULADOS[-1]
    assert envio["plantilla"] == "DESPACHO_CONFIRMADO" and envio["destinatario"] == "jugador@correo.com"
    assert envio["datos"] == {"ordenId": 5001, "juegos": ["Aurora Quest"]}
    assert "AAAAA" not in str(envio)
    assert sesion.query(NotificacionDespacho).one().estado == "ENVIADA"


def test_apiExternaSimuladaResponde202(cliente):
    respuesta = cliente.post("/externo/v1/notificaciones/despacho", json={
        "destinatario": "jugador@correo.com", "plantilla": "DESPACHO_CONFIRMADO",
        "datos": {"ordenId": 5001, "juegos": ["Aurora Quest"]}})
    assert respuesta.status_code == 202
    assert respuesta.json()["message"] == "Notificación de despacho enviada"
    assert respuesta.json()["data"]["estado"] == "ENVIADA"


def test_fallaNoRevierteEntregaYReintentaTresVeces(cliente, sesion, monkeypatch):
    usuario = crearUsuario(sesion)
    monkeypatch.setattr(ClienteNotificaciones, "disponible", False)
    respuesta, _ = despacharOrden(cliente, sesion, usuario.id)
    assert respuesta.status_code == 201                       # La entrega no se revierte
    notificacion = sesion.query(NotificacionDespacho).one()
    assert notificacion.estado == "FALLIDA" and notificacion.intentos == 3
    resultado = ServicioDespacho().notificarDespacho(sesion, 5001)
    assert resultado == {"message": "El servicio de notificaciones no está disponible", "data": None, "success": False}


def test_apiExternaCaidaResponde503(cliente, monkeypatch):
    monkeypatch.setattr(ClienteNotificaciones, "disponible", False)
    respuesta = cliente.post("/externo/v1/notificaciones/despacho", json={"destinatario": "a@b.co"})
    assert respuesta.status_code == 503
    assert respuesta.json()["message"] == "El servicio de notificaciones no está disponible"
