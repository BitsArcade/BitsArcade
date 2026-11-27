from sqlalchemy.orm import Session

from app.core.fechas import ahoraUtc
from app.domain.parametros import (
    ESTADO_ACTIVO,
    ESTADO_INACTIVO,
    PARAMETRO_MARGEN_GANANCIA,
    Impuesto,
    MetodoPago,
    Moneda,
    ParametroFinanciero,
)


class RepositorioParametros:
    """Capa Repository de MOD-00: acceso a monedas, impuestos, parámetros y métodos de pago."""

    # --- Monedas (HU-01 / HU-02) ---
    def obtenerMonedaPorCodigo(self, sesion: Session, codigoIso: str) -> Moneda | None:
        return sesion.query(Moneda).filter(Moneda.codigoIso == codigoIso).first()

    def crearMoneda(self, sesion: Session, nombre: str, codigoIso: str) -> Moneda:
        moneda = Moneda(nombre=nombre, codigoIso=codigoIso, estado=ESTADO_ACTIVO)
        sesion.add(moneda)
        sesion.commit()
        sesion.refresh(moneda)
        return moneda

    def listarMonedasPorEstado(self, sesion: Session, estado: str) -> list[Moneda]:
        return sesion.query(Moneda).filter(Moneda.estado == estado).order_by(Moneda.codigoIso.desc()).all()

    # --- Impuestos (HU-03) ---
    def obtenerImpuesto(self, sesion: Session, impuestoId: int) -> Impuesto | None:
        return sesion.get(Impuesto, impuestoId)

    def obtenerImpuestoPorNombre(self, sesion: Session, nombre: str) -> Impuesto | None:
        return sesion.query(Impuesto).filter(Impuesto.nombre == nombre).first()

    def crearImpuesto(self, sesion: Session, nombre: str, tasaIva: float) -> Impuesto:
        impuesto = Impuesto(nombre=nombre, tasaIva=tasaIva, actualizadoEn=ahoraUtc())
        sesion.add(impuesto)
        sesion.commit()
        sesion.refresh(impuesto)
        return impuesto

    def actualizarTasaIva(self, sesion: Session, impuesto: Impuesto, tasaIva: float) -> Impuesto:
        impuesto.tasaIva = tasaIva
        impuesto.actualizadoEn = ahoraUtc()
        sesion.commit()
        sesion.refresh(impuesto)
        return impuesto

    # --- Margen de ganancia (HU-04) ---
    def obtenerMargen(self, sesion: Session) -> ParametroFinanciero | None:
        return sesion.query(ParametroFinanciero).filter(ParametroFinanciero.parametro == PARAMETRO_MARGEN_GANANCIA).first()

    def guardarMargen(self, sesion: Session, margenGanancia: float) -> ParametroFinanciero:
        parametro = self.obtenerMargen(sesion)
        if parametro is None:
            parametro = ParametroFinanciero(parametro=PARAMETRO_MARGEN_GANANCIA, margenGanancia=margenGanancia)
            sesion.add(parametro)
        parametro.margenGanancia = margenGanancia
        parametro.actualizadoEn = ahoraUtc()
        sesion.commit()
        sesion.refresh(parametro)
        return parametro

    # --- Métodos de pago (HU-05) ---
    def obtenerMetodoPago(self, sesion: Session, metodoPagoId: int) -> MetodoPago | None:
        return sesion.get(MetodoPago, metodoPagoId)

    def obtenerMetodoPagoPorNombre(self, sesion: Session, nombre: str) -> MetodoPago | None:
        return sesion.query(MetodoPago).filter(MetodoPago.nombre == nombre).first()

    def crearMetodoPago(self, sesion: Session, nombre: str) -> MetodoPago:
        metodo = MetodoPago(nombre=nombre, estado=ESTADO_ACTIVO)
        sesion.add(metodo)
        sesion.commit()
        sesion.refresh(metodo)
        return metodo

    def inactivarMetodoPago(self, sesion: Session, metodo: MetodoPago) -> MetodoPago:
        metodo.estado = ESTADO_INACTIVO
        sesion.commit()
        sesion.refresh(metodo)
        return metodo
