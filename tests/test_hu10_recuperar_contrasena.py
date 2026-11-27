"""Pruebas de HU-10: Restablecer contraseña mediante código."""
from datetime import timedelta

import pytest
from sqlalchemy.exc import OperationalError

from app.domain.usuarios import CodigoVerificacion
from app.repositories.repositorio_usuarios import RepositorioUsuarios
from app.services.cliente_notificaciones import ENVIOS_SIMULADOS
from tests.apoyo_modulos import crearUsuario, limpiarSimulaciones

URL_SOLICITAR = "/api/v1/usuarios/autenticacion/recuperacion/solicitar"
URL_CONFIRMAR = "/api/v1/usuarios/autenticacion/recuperacion/confirmar"
URL_INICIO_SESION = "/api/v1/usuarios/autenticacion/inicio-sesion"
MENSAJE = "Si el correo está registrado, se envió un código de recuperación"


@pytest.fixture(autouse=True)
def _limpiar():
    limpiarSimulaciones()


def _solicitarCodigo(cliente) -> str:
    cliente.post(URL_SOLICITAR, json={"correo": "jugador@correo.com"})
    return ENVIOS_SIMULADOS[-1]["datos"]["codigo"]


def test_respuestaIdenticaExistaONoElCorreo(cliente, sesion):
    crearUsuario(sesion)
    existe = cliente.post(URL_SOLICITAR, json={"correo": "jugador@correo.com"})
    noExiste = cliente.post(URL_SOLICITAR, json={"correo": "nadie@correo.com"})
    assert existe.status_code == noExiste.status_code == 200
    assert existe.json() == noExiste.json() == {"message": MENSAJE, "data": {"estadoEnvio": "SIMULADO"}, "success": True}
    assert len(ENVIOS_SIMULADOS) == 1


def test_flujoExitosoActualizaLaContrasena(cliente, sesion):
    crearUsuario(sesion)
    codigo = _solicitarCodigo(cliente)
    respuesta = cliente.post(URL_CONFIRMAR, json={"correo": "jugador@correo.com", "codigo": codigo,
                                                  "nuevaContrasena": "NuevaClave#2026"})
    assert respuesta.status_code == 200
    assert respuesta.json() == {"message": "Contraseña actualizada exitosamente", "data": None, "success": True}
    assert cliente.post(URL_INICIO_SESION, json={"correo": "jugador@correo.com", "contrasena": "NuevaClave#2026"}).status_code == 200


def test_codigoEsDeUnSoloUso(cliente, sesion):
    crearUsuario(sesion)
    codigo = _solicitarCodigo(cliente)
    datos = {"correo": "jugador@correo.com", "codigo": codigo, "nuevaContrasena": "NuevaClave#2026"}
    cliente.post(URL_CONFIRMAR, json=datos)
    respuesta = cliente.post(URL_CONFIRMAR, json=datos)
    assert respuesta.status_code == 400
    assert respuesta.json()["message"] == "El código es inválido o expiró"


def test_codigoExpirado(cliente, sesion):
    crearUsuario(sesion)
    codigo = _solicitarCodigo(cliente)
    registro = sesion.query(CodigoVerificacion).one()
    registro.expiraEn = registro.expiraEn - timedelta(minutes=16)
    sesion.commit()
    respuesta = cliente.post(URL_CONFIRMAR, json={"correo": "jugador@correo.com", "codigo": codigo,
                                                  "nuevaContrasena": "NuevaClave#2026"})
    assert respuesta.status_code == 400


def test_maximoCincoIntentos(cliente, sesion):
    crearUsuario(sesion)
    codigo = _solicitarCodigo(cliente)
    for _ in range(5):
        cliente.post(URL_CONFIRMAR, json={"correo": "jugador@correo.com", "codigo": "999999x",
                                          "nuevaContrasena": "NuevaClave#2026"})
    respuesta = cliente.post(URL_CONFIRMAR, json={"correo": "jugador@correo.com", "codigo": codigo,
                                                  "nuevaContrasena": "NuevaClave#2026"})
    assert respuesta.status_code == 400


def test_error400NuevaContrasenaCorta(cliente, sesion):
    crearUsuario(sesion)
    codigo = _solicitarCodigo(cliente)
    respuesta = cliente.post(URL_CONFIRMAR, json={"correo": "jugador@correo.com", "codigo": codigo, "nuevaContrasena": "123"})
    assert respuesta.status_code == 400
    assert respuesta.json()["message"] == "La contraseña debe tener mínimo 8 caracteres"


def test_error503BaseDeDatos(cliente, monkeypatch):
    def _falla(*_args, **_kwargs):
        raise OperationalError("SELECT", {}, Exception("BD caída"))

    monkeypatch.setattr(RepositorioUsuarios, "obtenerPorCorreo", _falla)
    respuesta = cliente.post(URL_SOLICITAR, json={"correo": "jugador@correo.com"})
    assert respuesta.status_code == 503
    assert respuesta.json()["message"] == "No fue posible procesar la recuperación de contraseña"
