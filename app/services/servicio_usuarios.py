import hashlib
import hmac
import logging
import secrets

import bcrypt
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.fechas import (
    aIsoZ,
    ahoraUtc,
)
from app.core.respuestas import (
    ErrorAplicacion,
    manejarErroresBd,
    respuesta,
)
from app.core.seguridad import (
    UsuarioAutenticado,
    emitirToken,
)
from app.domain.usuarios import (
    ESTADO_CONFIRMADA,
    MENSAJE_CODIGO_INVALIDO,
    TIPO_CODIGO_CONFIRMACION,
    TIPO_CODIGO_RECUPERACION,
    ActualizarPerfilEntrada,
    ConfirmarRecuperacionEntrada,
    ConfirmarRegistroEntrada,
    InicioSesionEntrada,
    RegistroEntrada,
    SolicitarRecuperacionEntrada,
    codigoVigente,
    normalizarCorreo,
    validarContrasena,
    validarCorreo,
    validarNombrePerfil,
    validarNombreRegistro,
    validarTelefono,
)
from app.repositories.repositorio_usuarios import RepositorioUsuarios
from app.services.cliente_notificaciones import (
    ClienteNotificaciones,
    NotificacionesNoDisponible,
)

registro = logging.getLogger("bitarcade.usuarios")


# ===== COMÚN MOD-01: utilidades de hash y códigos =====

def generarHashContrasena(contrasena: str) -> str:
    return bcrypt.hashpw(contrasena.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verificarContrasena(contrasena: str, contrasenaHash: str) -> bool:
    try:
        return bcrypt.checkpw(contrasena.encode("utf-8"), contrasenaHash.encode("utf-8"))
    except ValueError:
        return False


def generarCodigo() -> str:
    """Código numérico de 6 dígitos."""
    return f"{secrets.randbelow(1_000_000):06d}"


def hashCodigo(codigo: str) -> str:
    return hashlib.sha256(codigo.strip().encode("utf-8")).hexdigest()


class ServicioUsuarios:
    """Capa Application / Service de MOD-01: casos de uso de usuarios (HU-06 a HU-10)."""

    def __init__(self):
        self.repositorio = RepositorioUsuarios()
        self.clienteNotificaciones = ClienteNotificaciones()

    def _enviarCodigo(self, correo: str, plantilla: str, codigo: str) -> str:
        """Envía el código por la API Notificaciones; una falla no revierte la operación."""
        try:
            self.clienteNotificaciones.enviar(correo, plantilla, {"codigo": codigo})
            return "SIMULADO"
        except NotificacionesNoDisponible:
            registro.warning("No fue posible enviar la plantilla %s", plantilla)
            return "FALLIDO"

    def _validarCodigo(self, sesion: Session, usuario, tipo: str, codigo: str | None, mensaje: str):
        """Valida vigencia, uso único e intentos (máx. 5). Cada intento fallido suma un intento."""
        registroCodigo = self.repositorio.obtenerCodigoActivo(sesion, usuario.id, tipo) if usuario else None
        if not codigoVigente(registroCodigo, ahoraUtc()):
            raise ErrorAplicacion(400, mensaje)
        if not hmac.compare_digest(registroCodigo.codigoHash, hashCodigo(codigo or "")):
            registroCodigo.intentos += 1
            sesion.commit()
            raise ErrorAplicacion(400, mensaje)
        return registroCodigo

    # ===== HU-06: Registro de nuevos clientes =====

    def registrarUsuario(self, sesion: Session, datos: RegistroEntrada) -> dict:
        """HU-06: valida, guarda con hash bcrypt en PENDIENTE_CONFIRMACION y envía el código."""
        correo = validarCorreo(datos.correo)
        contrasena = validarContrasena(datos.contrasena)
        nombre = validarNombreRegistro(datos.nombre)
        with manejarErroresBd("No fue posible registrar el usuario"):
            if self.repositorio.obtenerPorCorreo(sesion, correo):
                raise ErrorAplicacion(409, "El correo ya se encuentra registrado")
            try:
                usuario = self.repositorio.crearUsuario(sesion, correo, nombre, generarHashContrasena(contrasena))
            except IntegrityError as error:
                sesion.rollback()
                raise ErrorAplicacion(409, "El correo ya se encuentra registrado") from error
            codigo = generarCodigo()
            self.repositorio.crearCodigo(sesion, usuario.id, TIPO_CODIGO_CONFIRMACION, hashCodigo(codigo))
        self._enviarCodigo(usuario.correo, "CONFIRMACION_CUENTA", codigo)
        return respuesta(
            "Cuenta creada exitosamente",
            {
                "usuarioId": usuario.id,
                "correo": usuario.correo,
                "nombre": usuario.nombre,
                "rol": usuario.rol,
                "cuentaConfirmada": False,
            },
        )

    def confirmarRegistro(self, sesion: Session, datos: ConfirmarRegistroEntrada) -> dict:
        """HU-06 (RN-12): valida correo + código y cambia la cuenta a CONFIRMADA."""
        mensaje = "Código de confirmación inválido o expirado"
        with manejarErroresBd("No fue posible registrar el usuario"):
            usuario = self.repositorio.obtenerPorCorreo(sesion, normalizarCorreo(datos.correo))
            registroCodigo = self._validarCodigo(sesion, usuario, TIPO_CODIGO_CONFIRMACION, datos.codigo, mensaje)
            registroCodigo.usado = True
            usuario.estado = ESTADO_CONFIRMADA
            self.repositorio.guardar(sesion, usuario, registroCodigo)
        return respuesta("Cuenta confirmada exitosamente", {"usuarioId": usuario.id, "cuentaConfirmada": True})

    # ===== HU-07: Iniciar sesión y generación de JWT =====

    def iniciarSesion(self, sesion: Session, datos: InicioSesionEntrada) -> dict:
        """HU-07: mismo mensaje para correo inexistente o clave incorrecta."""
        with manejarErroresBd("No fue posible iniciar sesión"):
            usuario = self.repositorio.obtenerPorCorreo(sesion, normalizarCorreo(datos.correo))
        if usuario is None or not verificarContrasena(datos.contrasena or "", usuario.contrasenaHash):
            raise ErrorAplicacion(401, "Credenciales inválidas")
        cuentaConfirmada = usuario.estado == ESTADO_CONFIRMADA
        token, segundos = emitirToken(usuario.id, usuario.rol, cuentaConfirmada)
        return respuesta(
            "Inicio de sesión exitoso",
            {"token": token, "tipo": "Bearer", "expiraEn": segundos, "cuentaConfirmada": cuentaConfirmada},
        )

    # ===== HU-08: Consultar perfil autenticado =====

    def consultarPerfil(self, sesion: Session, usuarioToken: UsuarioAutenticado) -> dict:
        """HU-08: el usuarioId sale del token; nunca se retorna el hash de la clave."""
        with manejarErroresBd("No fue posible consultar el perfil"):
            usuario = self.repositorio.obtenerPorId(sesion, usuarioToken.id)
        if usuario is None:
            raise ErrorAplicacion(404, "El usuario no existe")
        return respuesta(
            "Consulta de perfil exitosa",
            {
                "usuarioId": usuario.id,
                "correo": usuario.correo,
                "nombre": usuario.nombre,
                "telefono": usuario.telefono,
                "rol": usuario.rol,
                "creadoEn": aIsoZ(usuario.creadoEn),
            },
        )

    # ===== HU-09: Actualizar datos personales =====

    def actualizarPerfil(
        self, sesion: Session, usuarioToken: UsuarioAutenticado, datos: ActualizarPerfilEntrada
    ) -> dict:
        """HU-09: actualiza nombre (2-80) y teléfono (opcional, 7-15 dígitos). Correo y rol no se editan."""
        nombre = validarNombrePerfil(datos.nombre)
        telefono = validarTelefono(datos.telefono)
        with manejarErroresBd("No fue posible actualizar los datos personales"):
            usuario = self.repositorio.obtenerPorId(sesion, usuarioToken.id)
            if usuario is None:
                raise ErrorAplicacion(404, "El usuario no existe")
            usuario.nombre = nombre
            usuario.telefono = telefono
            self.repositorio.guardar(sesion, usuario)
        return respuesta(
            "Datos personales actualizados exitosamente",
            {"usuarioId": usuario.id, "nombre": usuario.nombre, "telefono": usuario.telefono},
        )

    # ===== HU-10: Restablecer contraseña mediante código =====

    def solicitarRecuperacion(self, sesion: Session, datos: SolicitarRecuperacionEntrada) -> dict:
        """HU-10: responde siempre igual, exista o no el correo (sin enumeración de usuarios)."""
        with manejarErroresBd("No fue posible procesar la recuperación de contraseña"):
            usuario = self.repositorio.obtenerPorCorreo(sesion, normalizarCorreo(datos.correo))
            if usuario is not None:
                codigo = generarCodigo()
                self.repositorio.crearCodigo(sesion, usuario.id, TIPO_CODIGO_RECUPERACION, hashCodigo(codigo))
                self._enviarCodigo(usuario.correo, "RECUPERACION_CLAVE", codigo)
        return respuesta(
            "Si el correo está registrado, se envió un código de recuperación",
            {"estadoEnvio": "SIMULADO"},
        )

    def confirmarRecuperacion(self, sesion: Session, datos: ConfirmarRecuperacionEntrada) -> dict:
        """HU-10: código de 15 minutos, un solo uso y máximo 5 intentos; la nueva clave cumple HU-06."""
        nuevaContrasena = validarContrasena(datos.nuevaContrasena)
        with manejarErroresBd("No fue posible procesar la recuperación de contraseña"):
            usuario = self.repositorio.obtenerPorCorreo(sesion, normalizarCorreo(datos.correo))
            registroCodigo = self._validarCodigo(
                sesion, usuario, TIPO_CODIGO_RECUPERACION, datos.codigo, MENSAJE_CODIGO_INVALIDO
            )
            registroCodigo.usado = True
            usuario.contrasenaHash = generarHashContrasena(nuevaContrasena)
            self.repositorio.guardar(sesion, usuario, registroCodigo)
        return respuesta("Contraseña actualizada exitosamente", None)
