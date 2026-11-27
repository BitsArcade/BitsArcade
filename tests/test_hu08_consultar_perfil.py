"""Pruebas de HU-08: Consultar perfil autenticado (GET /api/v1/usuarios/perfil)."""
from sqlalchemy.exc import OperationalError

from app.repositories.repositorio_usuarios import RepositorioUsuarios
from tests.apoyo_modulos import crearUsuario
from tests.conftest import encabezadoAuth

URL = "/api/v1/usuarios/perfil"


def test_flujoExitosoSinDatosSensibles(cliente, sesion):
    usuario = crearUsuario(sesion)
    respuesta = cliente.get(URL, headers=encabezadoAuth(usuario.id))
    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["message"] == "Consulta de perfil exitosa"
    assert set(cuerpo["data"]) == {"usuarioId", "correo", "nombre", "telefono", "rol", "creadoEn"}
    assert cuerpo["data"]["usuarioId"] == usuario.id and cuerpo["data"]["telefono"] is None
    assert cuerpo["data"]["creadoEn"].endswith("Z")
    assert "contrasena" not in respuesta.text.lower().replace("clave_", "")


def test_usuarioIdSaleDelToken(cliente, sesion):
    crearUsuario(sesion, correo="uno@correo.com")
    otro = crearUsuario(sesion, correo="dos@correo.com")
    datos = cliente.get(URL, headers=encabezadoAuth(otro.id)).json()["data"]
    assert datos["correo"] == "dos@correo.com"


def test_error404UsuarioEliminado(cliente):
    respuesta = cliente.get(URL, headers=encabezadoAuth(999))
    assert respuesta.status_code == 404
    assert respuesta.json() == {"message": "El usuario no existe", "data": None, "success": False}


def test_error401SinToken(cliente):
    respuesta = cliente.get(URL)
    assert respuesta.status_code == 401
    assert respuesta.json()["message"] == "Token inválido, expirado o ausente"


def test_error503BaseDeDatos(cliente, monkeypatch):
    def _falla(*_args, **_kwargs):
        raise OperationalError("SELECT", {}, Exception("BD caída"))

    monkeypatch.setattr(RepositorioUsuarios, "obtenerPorId", _falla)
    respuesta = cliente.get(URL, headers=encabezadoAuth(1))
    assert respuesta.status_code == 503
    assert respuesta.json()["message"] == "No fue posible consultar el perfil"
