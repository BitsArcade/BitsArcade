"""Pruebas de HU-06: Registro de nuevos clientes (POST /api/v1/usuarios/autenticacion/registro)."""
import pytest
from sqlalchemy.exc import OperationalError

from app.domain.usuarios import ESTADO_CONFIRMADA, ESTADO_PENDIENTE_CONFIRMACION, Usuario
from app.repositories.repositorio_usuarios import RepositorioUsuarios
from app.services.cliente_notificaciones import ENVIOS_SIMULADOS
from tests.apoyo_modulos import limpiarSimulaciones

URL = "/api/v1/usuarios/autenticacion/registro"
URL_CONFIRMAR = "/api/v1/usuarios/autenticacion/registro/confirmar"
PETICION = {"correo": "jugador@correo.com", "contrasena": "Clave#2026", "nombre": "Ana Pérez"}


@pytest.fixture(autouse=True)
def _limpiar():
    limpiarSimulaciones()


def test_flujoExitosoCreaCuentaPendiente(cliente, sesion):
    respuesta = cliente.post(URL, json=PETICION)
    assert respuesta.status_code == 201
    cuerpo = respuesta.json()
    assert cuerpo["success"] is True and cuerpo["message"] == "Cuenta creada exitosamente"
    assert cuerpo["data"] == {"usuarioId": cuerpo["data"]["usuarioId"], "correo": "jugador@correo.com",
                              "nombre": "Ana Pérez", "rol": "CLIENTE", "cuentaConfirmada": False}
    usuario = sesion.query(Usuario).one()
    assert usuario.estado == ESTADO_PENDIENTE_CONFIRMACION
    assert usuario.contrasenaHash.startswith("$2") and "Clave#2026" not in usuario.contrasenaHash


def test_codigoSeEnviaPorNotificacionesYConfirmaCuenta(cliente, sesion):
    cliente.post(URL, json=PETICION)
    codigo = ENVIOS_SIMULADOS[-1]["datos"]["codigo"]
    respuesta = cliente.post(URL_CONFIRMAR, json={"correo": "JUGADOR@correo.com", "codigo": codigo})
    assert respuesta.status_code == 200
    assert respuesta.json() == {"message": "Cuenta confirmada exitosamente",
                                "data": {"usuarioId": respuesta.json()["data"]["usuarioId"], "cuentaConfirmada": True},
                                "success": True}
    sesion.expire_all()
    assert sesion.query(Usuario).one().estado == ESTADO_CONFIRMADA


def test_error400CorreoInvalido(cliente):
    respuesta = cliente.post(URL, json={**PETICION, "correo": "ana@"})
    assert respuesta.status_code == 400
    assert respuesta.json() == {"message": "Formato de correo inválido", "data": None, "success": False}


def test_error400ContrasenaCorta(cliente):
    respuesta = cliente.post(URL, json={**PETICION, "contrasena": "123"})
    assert respuesta.status_code == 400
    assert respuesta.json()["message"] == "La contraseña debe tener mínimo 8 caracteres"


def test_error409CorreoDuplicadoSinDistinguirMayusculas(cliente):
    cliente.post(URL, json=PETICION)
    respuesta = cliente.post(URL, json={**PETICION, "correo": "Jugador@Correo.com"})
    assert respuesta.status_code == 409
    assert respuesta.json()["message"] == "El correo ya se encuentra registrado"


def test_error400CodigoIncorrecto(cliente):
    cliente.post(URL, json=PETICION)
    respuesta = cliente.post(URL_CONFIRMAR, json={"correo": PETICION["correo"], "codigo": "000000x"})
    assert respuesta.status_code == 400
    assert respuesta.json()["message"] == "Código de confirmación inválido o expirado"


def test_fallaDeNotificacionesNoRevierteRegistro(cliente, sesion, monkeypatch):
    from app.api.usuarios import servicioUsuarios

    monkeypatch.setattr(servicioUsuarios.clienteNotificaciones, "disponible", False)
    assert cliente.post(URL, json=PETICION).status_code == 201
    assert sesion.query(Usuario).count() == 1


def test_error503BaseDeDatos(cliente, monkeypatch):
    def _falla(*_args, **_kwargs):
        raise OperationalError("SELECT", {}, Exception("BD caída"))

    monkeypatch.setattr(RepositorioUsuarios, "obtenerPorCorreo", _falla)
    respuesta = cliente.post(URL, json=PETICION)
    assert respuesta.status_code == 503
    assert respuesta.json() == {"message": "No fue posible registrar el usuario", "data": None, "success": False}
