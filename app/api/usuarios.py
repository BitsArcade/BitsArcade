from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.base_datos import obtenerSesionBd
from app.core.respuestas import (
    ErrorAplicacion,
    Respuesta,
    manejarErroresBd,
    respuesta,
)
from app.core.seguridad import (
    UsuarioAutenticado,
    obtenerUsuarioAutenticado,
    validarTokenServicio,
)
from app.domain.usuarios import (
    ActualizarPerfilEntrada,
    ConfirmacionSalida,
    ConfirmarRecuperacionEntrada,
    ConfirmarRegistroEntrada,
    EstadoEnvioSalida,
    InicioSesionEntrada,
    InicioSesionSalida,
    PerfilActualizadoSalida,
    PerfilSalida,
    RegistroEntrada,
    RegistroSalida,
    SolicitarRecuperacionEntrada,
)
from app.services.cliente_usuarios import ClienteUsuarios
from app.services.servicio_usuarios import ServicioUsuarios

enrutadorUsuarios = APIRouter(
    prefix="/api/v1/usuarios",
    tags=["MOD-01: Usuarios y Autenticación (HU-06 a HU-10)"],
)

servicioUsuarios = ServicioUsuarios()

ERROR_401 = {"description": "Token inválido, expirado o ausente"}


# ===== HU-06: Registro de nuevos clientes =====

@enrutadorUsuarios.post(
    "/autenticacion/registro",
    response_model=Respuesta[RegistroSalida],
    status_code=status.HTTP_201_CREATED,
    responses={
        400: {"description": "Formato de correo inválido / La contraseña debe tener mínimo 8 caracteres"},
        409: {"description": "El correo ya se encuentra registrado"},
        503: {"description": "No fue posible registrar el usuario"},
    },
)
def registrarNuevoCliente(datos: RegistroEntrada, sesion: Session = Depends(obtenerSesionBd)):
    """HU-06: registro público; el usuario nace en PENDIENTE_CONFIRMACION y recibe un código por correo."""
    return servicioUsuarios.registrarUsuario(sesion, datos)


@enrutadorUsuarios.post(
    "/autenticacion/registro/confirmar",
    response_model=Respuesta[ConfirmacionSalida],
    responses={400: {"description": "Código de confirmación inválido o expirado"}},
)
def confirmarCuenta(datos: ConfirmarRegistroEntrada, sesion: Session = Depends(obtenerSesionBd)):
    """HU-06 (RN-12): confirma la cuenta con correo + código; pasa a CONFIRMADA."""
    return servicioUsuarios.confirmarRegistro(sesion, datos)


# ===== HU-07: Iniciar sesión y generación de JWT =====

@enrutadorUsuarios.post(
    "/autenticacion/inicio-sesion",
    response_model=Respuesta[InicioSesionSalida],
    responses={
        401: {"description": "Credenciales inválidas"},
        503: {"description": "No fue posible iniciar sesión"},
    },
)
def iniciarSesion(datos: InicioSesionEntrada, sesion: Session = Depends(obtenerSesionBd)):
    """HU-07: valida credenciales y emite el JWT (sub, rol, cuentaConfirmada, iat, exp)."""
    return servicioUsuarios.iniciarSesion(sesion, datos)


# ===== HU-08: Consultar perfil autenticado =====

@enrutadorUsuarios.get(
    "/perfil",
    response_model=Respuesta[PerfilSalida],
    responses={
        401: ERROR_401,
        404: {"description": "El usuario no existe"},
        503: {"description": "No fue posible consultar el perfil"},
    },
)
def consultarPerfil(
    usuario: UsuarioAutenticado = Depends(obtenerUsuarioAutenticado),
    sesion: Session = Depends(obtenerSesionBd),
):
    """HU-08: retorna el perfil del usuario del JWT, sin hash ni clave."""
    return servicioUsuarios.consultarPerfil(sesion, usuario)


# ===== HU-09: Actualizar datos personales =====

@enrutadorUsuarios.put(
    "/perfil",
    response_model=Respuesta[PerfilActualizadoSalida],
    responses={
        400: {"description": "El teléfono debe contener entre 7 y 15 dígitos"},
        401: ERROR_401,
        503: {"description": "No fue posible actualizar los datos personales"},
    },
)
def actualizarDatosPersonales(
    datos: ActualizarPerfilEntrada,
    usuario: UsuarioAutenticado = Depends(obtenerUsuarioAutenticado),
    sesion: Session = Depends(obtenerSesionBd),
):
    """HU-09: edita nombre y teléfono del usuario del JWT."""
    return servicioUsuarios.actualizarPerfil(sesion, usuario, datos)


# ===== HU-10: Restablecer contraseña mediante código =====

@enrutadorUsuarios.post(
    "/autenticacion/recuperacion/solicitar",
    response_model=Respuesta[EstadoEnvioSalida],
    responses={503: {"description": "No fue posible procesar la recuperación de contraseña"}},
)
def solicitarRecuperacion(datos: SolicitarRecuperacionEntrada, sesion: Session = Depends(obtenerSesionBd)):
    """HU-10: genera y envía un código temporal; la respuesta es idéntica exista o no el correo."""
    return servicioUsuarios.solicitarRecuperacion(sesion, datos)


@enrutadorUsuarios.post(
    "/autenticacion/recuperacion/confirmar",
    response_model=Respuesta[None],
    responses={
        400: {"description": "El código es inválido o expiró / La contraseña debe tener mínimo 8 caracteres"},
        503: {"description": "No fue posible procesar la recuperación de contraseña"},
    },
)
def confirmarRecuperacion(datos: ConfirmarRecuperacionEntrada, sesion: Session = Depends(obtenerSesionBd)):
    """HU-10: valida el código (15 min, un uso, máx. 5 intentos) y actualiza el hash de la clave."""
    return servicioUsuarios.confirmarRecuperacion(sesion, datos)


# ===== Contratos internos de MOD-01 (COM-04 / COM-05) =====

enrutadorUsuariosInterno = APIRouter(
    prefix="/interno/v1/usuarios",
    tags=["MOD-01: Contratos internos (COM-04, COM-05)"],
    dependencies=[Depends(validarTokenServicio)],
)
clienteUsuarios = ClienteUsuarios()


@enrutadorUsuariosInterno.get("/{usuarioId}/validacion")
def validarUsuarioCom04(usuarioId: int, sesion: Session = Depends(obtenerSesionBd)):
    """COM-04: {valido, cuentaConfirmada} (RN-12, consumido por HU-31)."""
    with manejarErroresBd("No fue posible validar el usuario"):
        datos = clienteUsuarios.validarUsuario(sesion, usuarioId)
    if not datos["valido"]:
        raise ErrorAplicacion(404, "El usuario indicado no existe")
    return respuesta("Validación de usuario exitosa", datos)


@enrutadorUsuariosInterno.get("/{usuarioId}/comprador")
def obtenerCompradorCom05(usuarioId: int, sesion: Session = Depends(obtenerSesionBd)):
    """COM-05: {usuarioId, correo, nombre} del comprador (consumido por HU-41)."""
    with manejarErroresBd("No fue posible consultar el comprador"):
        datos = clienteUsuarios.obtenerComprador(sesion, usuarioId)
    if datos is None:
        raise ErrorAplicacion(404, "El usuario indicado no existe")
    return respuesta("Consulta de comprador exitosa", datos)
