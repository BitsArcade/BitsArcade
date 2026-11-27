from collections import Counter
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.cifrado import descifrarClave
from app.core.fechas import ZONA_BOGOTA, aIsoZ, ahoraUtc
from app.core.respuestas import ErrorAplicacion, manejarErroresBd, respuesta
from app.core.seguridad import UsuarioAutenticado
from app.domain.despacho import (
    EMISOR_COMPROBANTE,
    MENSAJE_FECHA_INVALIDA,
    MENSAJE_RANGO_INVALIDO,
    AsignacionLicencia,
    enmascararClave,
    formatearClave,
)
from app.repositories.repositorio_despacho import RepositorioDespacho

MENSAJE_COMPRA_NO_EXISTE = "La compra indicada no existe"


class ServicioBiblioteca:
    """Capa Application / Service de MOD-06: biblioteca e historial del cliente (HU-43, HU-46 a HU-50)."""

    def __init__(self):
        self.repositorio = RepositorioDespacho()

    def _claveEnmascarada(self, asignacion: AsignacionLicencia) -> str:
        """Las claves siempre salen enmascaradas; solo HU-43 las revela (RN-11)."""
        return enmascararClave(formatearClave(descifrarClave(asignacion.claveCifrada)))

    def _obtenerCompraPropia(self, sesion: Session, usuario: UsuarioAutenticado, ordenId: int, mensaje503: str):
        with manejarErroresBd(mensaje503):
            compra = self.repositorio.obtenerRegistroCompra(sesion, ordenId)
            if compra is None or compra.usuarioId != usuario.id:
                raise ErrorAplicacion(404, MENSAJE_COMPRA_NO_EXISTE)
            return compra, self.repositorio.listarAsignacionesOrden(sesion, ordenId)

    # ===== HU-43: Formateo y visualización segura de la clave =====

    def revelarClave(self, sesion: Session, usuario: UsuarioAutenticado, licenciaId: str) -> dict:
        """
        HU-43 (RN-11): valida propiedad, descifra y formatea la clave. El primer revelado fija
        reveladaEn (no se modifica después) y la licencia deja de ser reembolsable.
        """
        with manejarErroresBd("No fue posible revelar la clave"):
            asignacion = self.repositorio.obtenerAsignacion(sesion, licenciaId)
            if asignacion is None or asignacion.usuarioId != usuario.id:
                raise ErrorAplicacion(404, "La licencia indicada no existe")
            if not asignacion.revelada:
                asignacion.revelada = True
                asignacion.reveladaEn = ahoraUtc()
                self.repositorio.guardar(sesion, asignacion)
        return respuesta(
            "Clave revelada exitosamente",
            {
                "licenciaId": asignacion.licenciaId,
                "juegoId": asignacion.juegoId,
                "claveLicencia": formatearClave(descifrarClave(asignacion.claveCifrada)),
                "reveladaEn": aIsoZ(asignacion.reveladaEn),
                "reembolsable": False,
            },
        )

    # ===== HU-46: Consultar biblioteca personal de juegos =====

    def consultarBiblioteca(self, sesion: Session, usuario: UsuarioAutenticado) -> dict:
        """HU-46: licencias del propio usuario, agrupadas por título y con la clave enmascarada."""
        with manejarErroresBd("No fue posible consultar la biblioteca"):
            asignaciones = self.repositorio.listarAsignacionesUsuario(sesion, usuario.id)
        if not asignaciones:
            return respuesta("Aún no tienes licencias en tu biblioteca", [], False)
        return respuesta(
            "Consulta de biblioteca exitosa",
            [
                {
                    "licenciaId": a.licenciaId,
                    "juegoId": a.juegoId,
                    "titulo": a.titulo,
                    "plataforma": a.plataforma,
                    "entregadaEn": aIsoZ(a.entregadaEn),
                    "claveLicencia": self._claveEnmascarada(a),
                    "revelada": bool(a.revelada),
                }
                for a in asignaciones
            ],
        )

    # ===== HU-47: Consultar detalle de compra pasada =====

    def consultarCompra(self, sesion: Session, usuario: UsuarioAutenticado, ordenId: int) -> dict:
        """HU-47: detalle desde el registro propio de MOD-06 (sin COM hacia MOD-04/05)."""
        compra, asignaciones = self._obtenerCompraPropia(sesion, usuario, ordenId, "No fue posible consultar la compra")
        return respuesta(
            "Consulta de compra exitosa",
            {
                "ordenId": compra.ordenId,
                "fecha": aIsoZ(compra.fecha),
                "moneda": compra.moneda,
                "total": compra.total,
                "tasaCambio": compra.tasaCambio,
                "transaccionId": compra.transaccionId,
                "estadoOrden": compra.estadoOrden,
                "items": [
                    {
                        "juegoId": a.juegoId,
                        "titulo": a.titulo,
                        "precioUnitario": a.precioUnitarioFinal,
                        "claveLicencia": self._claveEnmascarada(a),
                    }
                    for a in asignaciones
                ],
            },
        )

    # ===== HU-48: Descargar comprobante digital de compra =====

    def generarComprobante(self, sesion: Session, usuario: UsuarioAutenticado, ordenId: int) -> dict:
        """HU-48: comprobante digital simulado (no es factura electrónica) con base, IVA y total."""
        compra, asignaciones = self._obtenerCompraPropia(sesion, usuario, ordenId, "No fue posible generar el comprobante")
        cantidades = Counter(a.titulo for a in asignaciones)
        return respuesta(
            "Comprobante generado",
            {
                "numero": f"CMP-{compra.ordenId}",
                "emisor": EMISOR_COMPROBANTE,
                "comprador": {"nombre": compra.nombre, "correo": compra.correo},
                "fecha": aIsoZ(compra.fecha),
                "moneda": compra.moneda,
                "desglose": {"baseGravable": compra.baseGravable, "valorIva": compra.iva, "total": compra.total},
                "tasaCambio": compra.tasaCambio,
                "transaccionId": compra.transaccionId,
                "items": [{"titulo": titulo, "cantidad": cantidad} for titulo, cantidad in cantidades.items()],
            },
        )

    # ===== HU-49: Consultar estado de licencias =====

    def consultarEstadoLicencias(self, sesion: Session, usuario: UsuarioAutenticado) -> dict:
        """HU-49: las claves no vencen; reembolsable es informativo (RN-11): true mientras no se revele."""
        with manejarErroresBd("No fue posible consultar el estado de las licencias"):
            asignaciones = self.repositorio.listarAsignacionesUsuario(sesion, usuario.id)
        if not asignaciones:
            return respuesta("No tienes licencias registradas", [], False)
        return respuesta(
            "Consulta de estado de licencias exitosa",
            [
                {
                    "licenciaId": a.licenciaId,
                    "juegoId": a.juegoId,
                    "estado": a.estado,
                    "revelada": bool(a.revelada),
                    "reveladaEn": aIsoZ(a.reveladaEn),
                    "reembolsable": not a.revelada,
                }
                for a in asignaciones
            ],
        )

    # ===== HU-50: Filtrar historial por fechas =====

    @staticmethod
    def _convertirFecha(valor: str | None) -> date | None:
        if valor is None or valor == "":
            return None
        try:
            if len(valor) != 10:
                raise ValueError
            return datetime.strptime(valor, "%Y-%m-%d").date()
        except ValueError as error:
            raise ErrorAplicacion(400, MENSAJE_FECHA_INVALIDA) from error

    @staticmethod
    def _inicioDiaBogotaEnUtc(dia: date) -> datetime:
        return datetime.combine(dia, time.min, tzinfo=ZONA_BOGOTA).astimezone(timezone.utc).replace(tzinfo=None)

    def filtrarHistorial(
        self, sesion: Session, usuario: UsuarioAutenticado, desde: str | None, hasta: str | None, orden: str | None
    ) -> dict:
        """HU-50: rango inclusivo en zona America/Bogota; orden descendente por defecto (orden=asc|desc)."""
        fechaDesde = self._convertirFecha(desde)
        fechaHasta = self._convertirFecha(hasta)
        if fechaDesde and fechaHasta and fechaDesde > fechaHasta:
            raise ErrorAplicacion(400, MENSAJE_RANGO_INVALIDO)
        sentido = (orden or "desc").lower()
        if sentido not in ("asc", "desc"):
            raise ErrorAplicacion(400, "El parámetro orden debe ser asc o desc")
        limiteInferior = self._inicioDiaBogotaEnUtc(fechaDesde) if fechaDesde else None
        limiteSuperior = self._inicioDiaBogotaEnUtc(fechaHasta + timedelta(days=1)) if fechaHasta else None
        with manejarErroresBd("No fue posible consultar el historial"):
            compras = self.repositorio.listarComprasUsuario(
                sesion, usuario.id, limiteInferior, limiteSuperior, sentido == "asc"
            )
        if not compras:
            return respuesta("No existen compras en el rango indicado", [], False)
        return respuesta(
            "Consulta de historial exitosa",
            [{"ordenId": c.ordenId, "fecha": aIsoZ(c.fecha), "total": c.total, "moneda": c.moneda} for c in compras],
        )
