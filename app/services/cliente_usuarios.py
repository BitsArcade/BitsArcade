"""
Adaptadores hacia MOD-01 (Usuarios), resueltos en proceso:

- COM-04: GET /interno/v1/usuarios/{usuarioId}/validacion → {valido, cuentaConfirmada} (HU-31, RN-12).
- COM-05: GET /interno/v1/usuarios/{usuarioId}/comprador → {usuarioId, correo, nombre} (HU-41).
"""
from sqlalchemy.orm import Session

from app.domain.usuarios import ESTADO_CONFIRMADA
from app.repositories.repositorio_usuarios import RepositorioUsuarios


class ClienteUsuarios:
    def __init__(self):
        self.repositorio = RepositorioUsuarios()

    def validarUsuario(self, sesion: Session, usuarioId: int) -> dict:
        usuario = self.repositorio.obtenerPorId(sesion, usuarioId)
        if usuario is None:
            return {"valido": False, "cuentaConfirmada": False}
        return {"valido": True, "cuentaConfirmada": usuario.estado == ESTADO_CONFIRMADA}

    def obtenerComprador(self, sesion: Session, usuarioId: int) -> dict | None:
        usuario = self.repositorio.obtenerPorId(sesion, usuarioId)
        if usuario is None:
            return None
        return {"usuarioId": usuario.id, "correo": usuario.correo, "nombre": usuario.nombre}
