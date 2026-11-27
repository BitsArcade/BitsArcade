"""Pruebas de HU-09: Actualizar datos personales (PUT /api/v1/usuarios/perfil)."""
from sqlalchemy.exc import OperationalError

from app.repositories.repositorio_usuarios import RepositorioUsuarios
from tests.apoyo_modulos import crearUsuario
from tests.conftest import encabezadoAuth

URL = "/api/v1/usuarios/perfil"


def test_flujoExitoso(cliente, sesion):
    usuario = crearUsuario(sesion)
    respuesta = cliente.put(URL, json={"nombre": "Ana María Pérez", "telefono": "3001234567"},
                            headers=encabezadoAuth(usuario.id))
    assert respuesta.status_code == 200
    assert respuesta.json() == {
        "message": "Datos personales actualizados exitosamente",
        "data": {"usuarioId": usuario.id, "nombre": "Ana María Pérez", "telefono": "3001234567"},
        "success": True,
    }


def test_correoYRolNoSonEditables(cliente, sesion):
    usuario = crearUsuario(sesion)
    cliente.put(URL, json={"nombre": "Ana", "correo": "otro@correo.com", "rol": "ADMIN"},
                headers=encabezadoAuth(usuario.id))
    sesion.refresh(usuario)
    assert usuario.correo == "jugador@correo.com" and usuario.rol == "CLIENTE"


def test_error400TelefonoInvalido(cliente, sesion):
    usuario = crearUsuario(sesion)
    respuesta = cliente.put(URL, json={"nombre": "Ana", "telefono": "abc"}, headers=encabezadoAuth(usuario.id))
    assert respuesta.status_code == 400
    assert respuesta.json() == {"message": "El teléfono debe contener entre 7 y 15 dígitos", "data": None, "success": False}


def test_error400NombreFueraDeRango(cliente, sesion):
    usuario = crearUsuario(sesion)
    respuesta = cliente.put(URL, json={"nombre": "A"}, headers=encabezadoAuth(usuario.id))
    assert respuesta.status_code == 400


def test_error401SinToken(cliente):
    assert cliente.put(URL, json={"nombre": "Ana"}).status_code == 401


def test_error503BaseDeDatos(cliente, monkeypatch):
    def _falla(*_args, **_kwargs):
        raise OperationalError("SELECT", {}, Exception("BD caída"))

    monkeypatch.setattr(RepositorioUsuarios, "obtenerPorId", _falla)
    respuesta = cliente.put(URL, json={"nombre": "Ana"}, headers=encabezadoAuth(1))
    assert respuesta.status_code == 503
    assert respuesta.json()["message"] == "No fue posible actualizar los datos personales"
