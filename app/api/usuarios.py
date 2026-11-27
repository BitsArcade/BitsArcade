from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.base_datos import obtenerSesionBd
from app.core.respuestas import Respuesta
from app.domain.usuarios import (
    ConfirmacionSalida,
    ConfirmarRegistroEntrada,
    InicioSesionEntrada,
    InicioSesionSalida,
    RegistroEntrada,
    RegistroSalida,
)
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
