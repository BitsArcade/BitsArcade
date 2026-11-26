"""
Dominio, modelos ORM, esquemas Pydantic y reglas de negocio de MOD-06 Despacho (HU-41 a HU-50).
"""
import hashlib
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field
from sqlalchemy import Boolean, Column, DateTime, Float, Integer, String

from app.core.base_datos import Base
from app.core.respuestas import ErrorAplicacion

INSTRUCCION_ACTIVACION_ESTANDAR = (
    "Copia esta clave y actívala en tu cuenta de Steam/Epic antes de compartir pantalla"
)


class EstadoDespacho(str, Enum):
    ACTIVADO = "ACTIVADO"
    ENTREGADO = "ENTREGADO"
    ENTREGADA = "ENTREGADA"
    REQUIERE_REVISION = "REQUIERE_REVISION"


# ==============================================================================
# MODELOS ORM (Base de Datos)
# ==============================================================================
class DespachoOrdenORM(Base):
    """Registro maestro del despacho y compra ejecutada para una orden pagada (COM-10 / HU-41 / HU-47)."""

    __tablename__ = "despachos_ordenes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    despacho_id = Column(String(32), unique=True, nullable=False, index=True)
    orden_id = Column(Integer, unique=True, nullable=False, index=True)
    usuario_id = Column(Integer, nullable=False, index=True)
    transaccion_id = Column(String(32), unique=True, nullable=False, index=True)
    moneda = Column(String(3), nullable=False, default="COP")
    tasa_cambio = Column(Float, nullable=False, default=1.0)
    total = Column(Float, nullable=False, default=0.0)
    estado = Column(String(30), nullable=False, default=EstadoDespacho.ACTIVADO.value)
    notificado_externo = Column(Boolean, nullable=False, default=False)
    creado_en = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    actualizado_en = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class LicenciaUsuarioORM(Base):
    """
    Licencia digital asignada de forma única e inmutable al perfil del usuario (HU-41 / HU-45).
    Restricción única en BD sobre reserva_id, key_inventario_id, clave_digital y huella_clave (RN-10).
    """

    __tablename__ = "licencias_usuario"

    id = Column(Integer, primary_key=True, autoincrement=True)
    licencia_id = Column(String(32), unique=True, nullable=False, index=True)
    despacho_id = Column(String(32), nullable=False, index=True)
    orden_id = Column(Integer, nullable=False, index=True)
    usuario_id = Column(Integer, nullable=False, index=True)
    juego_id = Column(Integer, nullable=False, index=True)
    titulo_juego = Column(String(180), nullable=False)
    plataforma = Column(String(60), nullable=False, default="PC")
    precio_unitario = Column(Float, nullable=False, default=0.0)
    reserva_id = Column(String(64), unique=True, nullable=True, index=True)
    key_inventario_id = Column(Integer, unique=True, nullable=True, index=True)
    clave_digital = Column(String(64), unique=True, nullable=False)
    clave_enmascarada = Column(String(32), nullable=False)
    huella_clave = Column(String(64), unique=True, nullable=False)
    revelada = Column(Boolean, nullable=False, default=False)
    revelada_en = Column(DateTime(timezone=True), nullable=True)
    asignada_en = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


# ==============================================================================
# ENTIDADES Y REGLAS DE DOMINIO (Despacho.Dominio)
# ==============================================================================
@dataclass(frozen=True)
class LicenciaUsuario:
    """Entidad inmutable de licencia digital asignada al usuario (HU-41 / RN-10)."""

    licencia_id: str
    despacho_id: str
    orden_id: int
    usuario_id: int
    juego_id: int
    titulo_juego: str
    plataforma: str
    reserva_id: Optional[str]
    key_inventario_id: Optional[int]
    clave_digital: str
    clave_enmascarada: str
    revelada: bool
    revelada_en: Optional[datetime]
    asignada_en: datetime
    precio_unitario: float = 0.0


@dataclass(frozen=True)
class DespachoOrden:
    """Entidad de despacho y registro propio de compra de una orden en MOD-06."""

    despacho_id: str
    orden_id: int
    usuario_id: int
    transaccion_id: str
    estado: EstadoDespacho
    notificado_externo: bool
    creado_en: datetime
    licencias: list[LicenciaUsuario]
    moneda: str = "COP"
    tasa_cambio: float = 1.0
    total: float = 0.0


class ReglasDespacho:
    @staticmethod
    def validar_orden_elegible_despacho(estado_orden: str) -> None:
        """Solo una orden en estado PAGADA puede recibir asignación de licencias (HU-41)."""
        if estado_orden.strip().upper() != "PAGADA":
            raise ErrorAplicacion(
                409, "La orden no está en estado PAGADA y no es elegible para despacho"
            )

    @staticmethod
    def generar_clave_digital(orden_id: int, juego_id: int, indice: int) -> tuple[str, str, str]:
        """
        Genera una clave digital única de 16 caracteres (XXXX-XXXX-XXXX-XXXX),
        su versión enmascarada (XXXX-XXXX-XXXX-****) y su huella SHA-256.
        """
        alfabeto = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
        bloques = [
            "".join(secrets.choice(alfabeto) for _ in range(4))
            for _ in range(4)
        ]
        clave_plana = "-".join(bloques)
        clave_enmascarada = f"{bloques[0]}-{bloques[1]}-{bloques[2]}-****"
        semilla = f"{orden_id}:{juego_id}:{indice}:{clave_plana}".encode("utf-8")
        huella = hashlib.sha256(semilla).hexdigest()
        return clave_plana, clave_enmascarada, huella

    @staticmethod
    def formatear_clave_legible(clave_cruda: str) -> str:
        """
        HU-43: Formatea la clave digital en grupos legibles de 4 caracteres
        separados por guiones (XXXX-XXXX-XXXX-XXXX).
        """
        limpia = re.sub(r"[^A-Za-z0-9]", "", (clave_cruda or "").strip().upper())
        if not limpia:
            raise ErrorAplicacion(503, "No fue posible revelar la clave digital")
        grupos = [limpia[i : i + 4] for i in range(0, len(limpia), 4)]
        return "-".join(grupos)

    @staticmethod
    def validar_propiedad_licencia(
        licencia: Optional[LicenciaUsuario], usuario_id: int
    ) -> LicenciaUsuario:
        """
        HU-43: Verifica que la licencia exista y pertenezca al usuario autenticado.
        Si no existe o es de otro usuario, responde 404 para evitar enumeración.
        """
        if licencia is None or licencia.usuario_id != usuario_id:
            raise ErrorAplicacion(404, "La licencia indicada no existe")
        return licencia

    @staticmethod
    def calcularEstadoLicencia(licencia: LicenciaUsuario) -> dict[str, Any]:
        """HU-49: calcula el estado y la elegibilidad informativa de reembolso."""
        revelada = licencia.revelada or licencia.revelada_en is not None
        return {
            "licenciaId": licencia.licencia_id,
            "juegoId": licencia.juego_id,
            "estado": "REVELADA" if revelada else "ENTREGADA",
            "revelada": revelada,
            "reveladaEn": (
                licencia.revelada_en.isoformat()
                if licencia.revelada_en is not None
                else None
            ),
            "reembolsable": not revelada,
        }

    @staticmethod
    def validar_propiedad_compra(
        compra: Optional[DespachoOrden], usuario_id: int
    ) -> DespachoOrden:
        """
        HU-47: Verifica que el registro de compra exista en MOD-06 y pertenezca
        al usuario autenticado; en caso contrario responde 404.
        """
        if compra is None or compra.usuario_id != usuario_id:
            raise ErrorAplicacion(404, "La compra indicada no existe")
        return compra

    @staticmethod
    def validarCuadreComprobante(
        base_gravable: float, valor_iva: float, total: float
    ) -> None:
        """HU-48: verifica que la base más el IVA coincidan con el total cobrado."""
        if round(base_gravable + valor_iva, 2) != round(total, 2):
            raise ErrorAplicacion(
                409,
                "El desglose financiero de la compra no coincide con el total registrado",
            )

    @staticmethod
    def normalizar_estado_orden_compra(estado_despacho: EstadoDespacho) -> str:
        """Mapea el estado interno del despacho al estado de orden entregado en el historial."""
        if estado_despacho in (
            EstadoDespacho.ACTIVADO,
            EstadoDespacho.ENTREGADO,
            EstadoDespacho.ENTREGADA,
        ):
            return "ENTREGADA"
        return estado_despacho.value

    @staticmethod
    def filtrar_biblioteca_usuario(
        licencias: list[LicenciaUsuario],
        usuario_id: int,
        titulo: Optional[str] = None,
        plataforma: Optional[str] = None,
    ) -> list[LicenciaUsuario]:
        """
        HU-46: Garantiza aislamiento por usuario autenticado y aplica filtros
        opcionales por título y plataforma sin exponer la clave en texto plano.
        """
        termino_titulo = (titulo or "").strip().lower()
        termino_plataforma = (plataforma or "").strip().lower()

        resultado: list[LicenciaUsuario] = []
        for lic in licencias:
            if lic.usuario_id != usuario_id:
                continue
            if termino_titulo and termino_titulo not in lic.titulo_juego.lower():
                continue
            if termino_plataforma and termino_plataforma != lic.plataforma.strip().lower():
                continue
            resultado.append(lic)
        return resultado

    @staticmethod
    def validar_elegibilidad_entrega(
        orden_id: int,
        reserva_ids: list[str],
        asignaciones_existentes: list[LicenciaUsuario],
        usuario_id: Optional[int] = None,
    ) -> dict[str, Any]:
        """
        HU-45 (RN-10): Valida unicidad e inmutabilidad de entrega.
        - Si alguna reserva o clave ya fue asignada a otra orden o usuario -> 409.
        - Si todas las asignaciones pertenecen a la misma orden -> idempotente (200).
        - Si no existen entregas previas -> autoriza el despacho (200, entregada=False).
        """
        for asignacion in asignaciones_existentes:
            if asignacion.orden_id != orden_id or (
                usuario_id is not None and asignacion.usuario_id != usuario_id
            ):
                raise ErrorAplicacion(
                    409, "La licencia ya fue entregada y no puede reasignarse"
                )

        entregadas_por_reserva = {
            asignacion.reserva_id: True
            for asignacion in asignaciones_existentes
            if asignacion.reserva_id
        }

        if reserva_ids:
            items = [
                {
                    "reservaId": rid,
                    "entregada": entregadas_por_reserva.get(rid, False),
                }
                for rid in reserva_ids
            ]
        else:
            items = [
                {
                    "reservaId": asignacion.reserva_id or asignacion.licencia_id,
                    "entregada": True,
                }
                for asignacion in asignaciones_existentes
            ]

        return {
            "ordenId": orden_id,
            "autorizado": True,
            "items": items,
        }


# ==============================================================================
# ESQUEMAS PYDANTIC (Contratos COM y API español camelCase)
# ==============================================================================
class ItemDespachoCOM10(BaseModel):
    juegoId: int = Field(..., gt=0)
    titulo: str = Field(..., min_length=1)
    reservaId: Optional[str] = None
    precioUnitario: float = Field(..., ge=0)


class SolicitudDespachoCOM10(BaseModel):
    ordenId: int = Field(..., gt=0)
    usuarioId: int = Field(..., gt=0)
    transaccionId: str = Field(..., min_length=1)
    moneda: str = Field(..., min_length=3, max_length=3)
    tasaCambio: float = Field(..., gt=0)
    total: float = Field(..., ge=0)
    items: list[ItemDespachoCOM10] = Field(..., min_length=1)


class LicenciaAsignadaSalida(BaseModel):
    licenciaId: str
    juegoId: int
    titulo: str
    plataforma: str
    claveEnmascarada: str
    revelada: bool
    asignadaEn: str


class DatosDespachoCOM10(BaseModel):
    despachoId: str
    ordenId: int
    usuarioId: int
    transaccionId: str
    estadoDespacho: str
    licenciasAsignadas: list[LicenciaAsignadaSalida]


class RespuestaDespachoCOM10(BaseModel):
    message: str
    data: Optional[DatosDespachoCOM10] = None
    success: bool


class ClaveReveladaSalida(BaseModel):
    """Contrato de salida de HU-43 al revelar de forma segura una clave digital."""

    licenciaId: str
    juegoId: int
    claveFormateada: str
    instruccionActivacion: str
    reveladaEn: str


class RespuestaRevelarClave(BaseModel):
    message: str
    data: Optional[ClaveReveladaSalida] = None
    success: bool


class LicenciaBibliotecaSalida(BaseModel):
    """Contrato de salida para cada licencia en la biblioteca del usuario (HU-46)."""

    licenciaId: str
    ordenId: int
    juegoId: int
    titulo: str
    plataforma: str
    claveEnmascarada: str
    revelada: bool
    reveladaEn: Optional[str] = None
    asignadaEn: str


class RespuestaBibliotecaLicencias(BaseModel):
    message: str
    data: list[LicenciaBibliotecaSalida]
    success: bool


class EstadoLicenciaSalida(BaseModel):
    licenciaId: str
    juegoId: int
    estado: str
    revelada: bool
    reveladaEn: Optional[str]
    reembolsable: bool


class RespuestaEstadoLicencias(BaseModel):
    message: str
    data: list[EstadoLicenciaSalida]
    success: bool


class ItemDetalleCompraSalida(BaseModel):
    """Ítem de compra histórica con clave enmascarada (HU-47)."""

    juegoId: int
    titulo: str
    precioUnitario: float
    claveLicencia: str


class DatosDetalleCompraSalida(BaseModel):
    """Contrato de salida de detalle de compra pasada en MOD-06 (HU-47)."""

    ordenId: int
    fecha: str
    moneda: str
    total: float
    tasaCambio: float
    transaccionId: str
    estadoOrden: str
    items: list[ItemDetalleCompraSalida]


class RespuestaDetalleCompra(BaseModel):
    """Contrato estándar de respuesta de HU-47."""

    message: str
    data: Optional[DatosDetalleCompraSalida] = None
    success: bool


class CompradorComprobanteSalida(BaseModel):
    nombre: str
    correo: str


class DesgloseComprobanteSalida(BaseModel):
    baseGravable: float
    valorIva: float
    total: float


class ItemComprobanteSalida(BaseModel):
    titulo: str
    cantidad: int


class DatosComprobanteCompraSalida(BaseModel):
    numero: str
    emisor: str
    comprador: CompradorComprobanteSalida
    fecha: str
    moneda: str
    desglose: DesgloseComprobanteSalida
    tasaCambio: float
    transaccionId: str
    items: list[ItemComprobanteSalida]


class RespuestaComprobanteCompra(BaseModel):
    """Contrato de salida de HU-48 para el comprobante descargable."""

    message: str
    data: Optional[DatosComprobanteCompraSalida] = None
    success: bool


class ItemElegibilidadEntregaSalida(BaseModel):
    """Ítem de verificación de elegibilidad de entrega en HU-45."""

    reservaId: str
    entregada: bool


class DatosElegibilidadEntrega(BaseModel):
    """Contrato de datos de salida de HU-45."""

    ordenId: int
    autorizado: bool
    items: list[ItemElegibilidadEntregaSalida]


class RespuestaElegibilidadEntrega(BaseModel):
    """Contrato estándar de respuesta de HU-45."""

    message: str
    data: Optional[DatosElegibilidadEntrega] = None
    success: bool