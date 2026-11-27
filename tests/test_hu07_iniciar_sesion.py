"""Pruebas de HU-07: Iniciar sesión y generación de JWT (POST /api/v1/usuarios/autenticacion/inicio-sesion)."""
import jwt
from sqlalchemy.exc import OperationalError

from app.core.configuracion import configuracion
from app.core.seguridad import decodificarToken
from app.domain.usuarios import ESTADO_PENDIENTE_CONFIRMACION
from app.repositories.repositorio_usuarios import RepositorioUsuarios
from tests.apoyo_modulos import crearUsuario

URL = "/api/v1/usuarios/autenticacion/inicio-sesion"


def test_flujoExitosoEmiteJwt(cliente, sesion):
    usuario = crearUsuario(sesion)
    respuesta = cliente.post(URL, json={"correo": "jugador@correo.com", "contrasena": "Clave#2026"})
    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["message"] == "Inicio de sesión exitoso" and cuerpo["success"] is True
    datos = cuerpo["data"]
    assert datos["tipo"] == "Bearer" and datos["cuentaConfirmada"] is True
    assert datos["expiraEn"] == configuracion.MINUTOS_EXPIRACION_TOKEN * 60
    claims = jwt.decode(datos["token"], configuracion.CLAVE_SECRETA, algorithms=["HS256"])
    assert claims["sub"] == str(usuario.id) and claims["rol"] == "CLIENTE"
    assert {"iat", "exp", "cuentaConfirmada"} <= set(claims)


def test_otrosModulosValidanElTokenLocalmente(cliente, sesion):
    usuario = crearUsuario(sesion)
    token = cliente.post(URL, json={"correo": "jugador@correo.com", "contrasena": "Clave#2026"}).json()["data"]["token"]
    assert decodificarToken(token).id == usuario.id


def test_cuentaSinConfirmarPuedeIniciarSesion(cliente, sesion):
    crearUsuario(sesion, estado=ESTADO_PENDIENTE_CONFIRMACION)
    datos = cliente.post(URL, json={"correo": "jugador@correo.com", "contrasena": "Clave#2026"}).json()["data"]
    assert datos["cuentaConfirmada"] is False


def test_error401MismoMensajeParaContrasenaOCorreoIncorrecto(cliente, sesion):
    crearUsuario(sesion)
    contrasenaIncorrecta = cliente.post(URL, json={"correo": "jugador@correo.com", "contrasena": "Otra#2026"})
    correoMalo = cliente.post(URL, json={"correo": "nadie@correo.com", "contrasena": "Clave#2026"})
    assert contrasenaIncorrecta.status_code == correoMalo.status_code == 401
    assert contrasenaIncorrecta.json() == correoMalo.json() == {"message": "Credenciales inválidas", "data": None, "success": False}


def test_error503BaseDeDatos(cliente, monkeypatch):
    def _falla(*_args, **_kwargs):
        raise OperationalError("SELECT", {}, Exception("BD caída"))

    monkeypatch.setattr(RepositorioUsuarios, "obtenerPorCorreo", _falla)
    respuesta = cliente.post(URL, json={"correo": "jugador@correo.com", "contrasena": "Clave#2026"})
    assert respuesta.status_code == 503
    assert respuesta.json()["message"] == "No fue posible iniciar sesión"
