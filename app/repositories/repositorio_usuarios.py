from datetime import timedelta

from sqlalchemy.orm import Session

from app.core.fechas import ahoraUtc
from app.domain.usuarios import (
    ESTADO_PENDIENTE_CONFIRMACION,
    MINUTOS_VIGENCIA_CODIGO,
    ROL_CLIENTE,
    CodigoVerificacion,
    Usuario,
)


class RepositorioUsuarios:
    """Capa Repository de MOD-01: acceso a datos de usuarios y códigos temporales."""

    # ===== COMÚN MOD-01: consultas de usuario =====

    def obtenerPorCorreo(self, sesion: Session, correo: str) -> Usuario | None:
        return sesion.query(Usuario).filter(Usuario.correo == correo.lower()).first()

    def obtenerPorId(self, sesion: Session, usuarioId: int) -> Usuario | None:
        return sesion.get(Usuario, usuarioId)

    def crearCodigo(self, sesion: Session, usuarioId: int, tipo: str, codigoHash: str) -> CodigoVerificacion:
        """Invalida los códigos previos del mismo tipo y registra uno nuevo con vigencia de 15 minutos."""
        sesion.query(CodigoVerificacion).filter(
            CodigoVerificacion.usuarioId == usuarioId,
            CodigoVerificacion.tipo == tipo,
            CodigoVerificacion.usado.is_(False),
        ).update({CodigoVerificacion.usado: True}, synchronize_session=False)
        codigo = CodigoVerificacion(
            usuarioId=usuarioId,
            tipo=tipo,
            codigoHash=codigoHash,
            expiraEn=ahoraUtc() + timedelta(minutes=MINUTOS_VIGENCIA_CODIGO),
        )
        sesion.add(codigo)
        sesion.commit()
        return codigo

    def obtenerCodigoActivo(self, sesion: Session, usuarioId: int, tipo: str) -> CodigoVerificacion | None:
        return (
            sesion.query(CodigoVerificacion)
            .filter(
                CodigoVerificacion.usuarioId == usuarioId,
                CodigoVerificacion.tipo == tipo,
                CodigoVerificacion.usado.is_(False),
            )
            .order_by(CodigoVerificacion.id.desc())
            .first()
        )

    def guardar(self, sesion: Session, *entidades) -> None:
        for entidad in entidades:
            sesion.add(entidad)
        sesion.commit()
        for entidad in entidades:
            sesion.refresh(entidad)

    # ===== HU-06: Registro de nuevos clientes =====

    def crearUsuario(self, sesion: Session, correo: str, nombre: str, contrasenaHash: str) -> Usuario:
        usuario = Usuario(
            correo=correo,
            nombre=nombre,
            contrasenaHash=contrasenaHash,
            rol=ROL_CLIENTE,
            estado=ESTADO_PENDIENTE_CONFIRMACION,
        )
        sesion.add(usuario)
        sesion.commit()
        sesion.refresh(usuario)
        return usuario
