from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.base_datos import Base
from app.core.seguridad import UsuarioAutenticado
from app.domain.ordenes import (
    ESTADO_ORDEN_CANCELADA,
    ESTADO_ORDEN_PENDIENTE,
    OrdenCompra,
)
from app.services.servicio_ordenes import ServicioOrdenes


def crearSesionPrueba():
    motor = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=motor)
    FabricaSesion = sessionmaker(autocommit=False, autoflush=False, bind=motor)
    return FabricaSesion()


def testConsultarSoloOrdenesPendientesDelUsuario():
    """HU-33: Verifica que solo se listen las órdenes en estado PENDIENTE del usuario autenticado."""
    sesion = crearSesionPrueba()
    usuarioPrueba = UsuarioAutenticado(id=10, email="dumar@bitsarcade.com", rol="CLIENTE")
    servicio = ServicioOrdenes()

    ordenPendiente = OrdenCompra(
        usuarioId=10,
        estado=ESTADO_ORDEN_PENDIENTE,
        moneda="COP",
        tasaCambioCongelada=4200.0,
        subtotalBase=100000.0,
        descuentoAplicado=0.0,
        montoIva=19000.0,
        totalPagar=119000.0,
    )
    ordenCancelada = OrdenCompra(
        usuarioId=10,
        estado=ESTADO_ORDEN_CANCELADA,
        moneda="COP",
        tasaCambioCongelada=4200.0,
        subtotalBase=50000.0,
        descuentoAplicado=0.0,
        montoIva=9500.0,
        totalPagar=59500.0,
    )
    ordenOtroUsuario = OrdenCompra(
        usuarioId=99,
        estado=ESTADO_ORDEN_PENDIENTE,
        moneda="COP",
        tasaCambioCongelada=4200.0,
        subtotalBase=80000.0,
        descuentoAplicado=0.0,
        montoIva=15200.0,
        totalPagar=95200.0,
    )
    sesion.add_all([ordenPendiente, ordenCancelada, ordenOtroUsuario])
    sesion.commit()

    respuestaServicio = servicio.consultarOrdenesPendientes(sesion, usuarioPrueba)

    assert respuestaServicio["success"] is True
    assert len(respuestaServicio["data"]) == 1
    assert respuestaServicio["data"][0]["id"] == ordenPendiente.id
    assert respuestaServicio["data"][0]["estado"] == ESTADO_ORDEN_PENDIENTE