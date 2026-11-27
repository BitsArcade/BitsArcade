from sqlalchemy.orm import Session

from app.core.configuracion import configuracion
from app.core.fechas import aIsoZ
from app.core.respuestas import ErrorAplicacion, manejarErroresBd, respuesta
from app.domain.parametros import (
    ESTADO_ACTIVO,
    ESTADO_INACTIVO,
    MONEDA_BASE,
    NOMBRE_IMPUESTO_IVA,
    PARAMETRO_MARGEN_GANANCIA,
    CrearMonedaEntrada,
    validarFiltroEstado,
    validarMargenGanancia,
    validarMoneda,
    validarTasaIva,
)
from app.repositories.repositorio_parametros import RepositorioParametros
from app.services.cliente_divisas import ClienteDivisas, DivisasNoDisponible

METODOS_PAGO_SEMILLA = ("PSE", "Tarjeta de crédito", "Nequi")
MENSAJE_TASA_NO_DISPONIBLE = "No fue posible obtener la tasa de cambio vigente"


class ServicioParametros:
    """Capa Application / Service de MOD-00: HU-01 a HU-05 y contratos COM-01, COM-02 y COM-03."""

    def __init__(self):
        self.repositorio = RepositorioParametros()
        self.clienteDivisas = ClienteDivisas()

    # ===== TT-02: datos base =====

    def asegurarDatosBase(self, sesion: Session) -> None:
        """TT-02: moneda COP, IVA, margen de ganancia y métodos de pago semilla (idempotente)."""
        if self.repositorio.obtenerMonedaPorCodigo(sesion, MONEDA_BASE) is None:
            self.repositorio.crearMoneda(sesion, "Peso colombiano", MONEDA_BASE)
        if self.repositorio.obtenerImpuestoPorNombre(sesion, NOMBRE_IMPUESTO_IVA) is None:
            self.repositorio.crearImpuesto(sesion, NOMBRE_IMPUESTO_IVA, float(configuracion.TASA_IVA))
        if self.repositorio.obtenerMargen(sesion) is None:
            self.repositorio.guardarMargen(sesion, float(configuracion.MARGEN_GANANCIA))
        for nombre in METODOS_PAGO_SEMILLA:
            if self.repositorio.obtenerMetodoPagoPorNombre(sesion, nombre) is None:
                self.repositorio.crearMetodoPago(sesion, nombre)

    # ===== HU-01: Registrar nueva moneda habilitada =====

    def registrarMoneda(self, sesion: Session, datos: CrearMonedaEntrada) -> dict:
        nombre, codigoIso = validarMoneda(datos.nombre, datos.codigoIso)
        with manejarErroresBd("No fue posible registrar la moneda"):
            if self.repositorio.obtenerMonedaPorCodigo(sesion, codigoIso) is not None:
                raise ErrorAplicacion(409, f"La moneda con código ISO {codigoIso} ya existe")
            moneda = self.repositorio.crearMoneda(sesion, nombre, codigoIso)
        return respuesta(
            "Moneda registrada exitosamente",
            {"monedaId": moneda.id, "nombre": moneda.nombre, "codigoIso": moneda.codigoIso, "estado": moneda.estado},
        )

    # ===== HU-02: Consultar monedas activas =====

    def consultarMonedas(self, sesion: Session, estado: str | None) -> dict:
        filtro = validarFiltroEstado(estado)
        with manejarErroresBd("No fue posible consultar las monedas"):
            self.asegurarDatosBase(sesion)
            monedas = self.repositorio.listarMonedasPorEstado(sesion, filtro)
        if not monedas:
            mensaje = "No existen monedas activas" if filtro == ESTADO_ACTIVO else "No existen monedas inactivas"
            return respuesta(mensaje, [], False)
        return respuesta("Consulta de monedas exitosa", [{"codigoIso": m.codigoIso, "nombre": m.nombre} for m in monedas])

    def monedaHabilitada(self, sesion: Session, codigoIso: str) -> bool:
        """Usado por HU-31: la moneda de cobro debe existir y estar ACTIVO."""
        self.asegurarDatosBase(sesion)
        moneda = self.repositorio.obtenerMonedaPorCodigo(sesion, codigoIso)
        return moneda is not None and moneda.estado == ESTADO_ACTIVO

    # ===== HU-03: Actualizar porcentaje de impuesto IVA =====

    def actualizarTasaIva(self, sesion: Session, impuestoId: int, tasaIva) -> dict:
        valor = validarTasaIva(tasaIva)
        with manejarErroresBd("No fue posible actualizar la tasa de impuesto"):
            self.asegurarDatosBase(sesion)
            impuesto = self.repositorio.obtenerImpuesto(sesion, impuestoId)
            if impuesto is None:
                raise ErrorAplicacion(404, "El impuesto indicado no existe")
            impuesto = self.repositorio.actualizarTasaIva(sesion, impuesto, valor)
        return respuesta(
            "Tasa de IVA actualizada exitosamente",
            {
                "impuestoId": impuesto.id,
                "nombre": impuesto.nombre,
                "tasaIva": float(impuesto.tasaIva),
                "actualizadoEn": aIsoZ(impuesto.actualizadoEn),
            },
        )

    # ===== HU-04: Configurar margen de ganancia =====

    def configurarMargenGanancia(self, sesion: Session, margenGanancia) -> dict:
        valor = validarMargenGanancia(margenGanancia)
        with manejarErroresBd("No fue posible actualizar el margen de ganancia"):
            parametro = self.repositorio.guardarMargen(sesion, valor)
        return respuesta(
            "Margen de ganancia actualizado exitosamente",
            {
                "parametro": PARAMETRO_MARGEN_GANANCIA,
                "margenGanancia": float(parametro.margenGanancia),
                "actualizadoEn": aIsoZ(parametro.actualizadoEn),
            },
        )

    # ===== HU-05: Inactivar método de pago =====

    def inactivarMetodoPago(self, sesion: Session, metodoPagoId: int) -> dict:
        with manejarErroresBd("No fue posible inactivar el método de pago"):
            self.asegurarDatosBase(sesion)
            metodo = self.repositorio.obtenerMetodoPago(sesion, metodoPagoId)
            if metodo is None:
                raise ErrorAplicacion(404, "El método de pago indicado no existe")
            if metodo.estado == ESTADO_INACTIVO:
                raise ErrorAplicacion(409, "El método de pago ya se encuentra inactivo")
            metodo = self.repositorio.inactivarMetodoPago(sesion, metodo)
        return respuesta(
            "Método de pago inactivado exitosamente",
            {"metodoPagoId": metodo.id, "nombre": metodo.nombre, "estado": metodo.estado},
        )

    # ===== Contratos internos =====

    def obtenerContratoCom01(self, sesion: Session) -> dict:
        """COM-01 / COM-02: {tasaIva, margenGanancia, monedaBase}; porcentajes de 0 a 100."""
        self.asegurarDatosBase(sesion)
        impuesto = self.repositorio.obtenerImpuestoPorNombre(sesion, NOMBRE_IMPUESTO_IVA)
        margen = self.repositorio.obtenerMargen(sesion)
        return {
            "tasaIva": float(impuesto.tasaIva),
            "margenGanancia": float(margen.margenGanancia),
            "monedaBase": MONEDA_BASE,
        }

    def obtenerContratoCom03(self, sesion: Session, codigoIso: str) -> dict:
        """
        COM-03: {codigoIso, tasaCambio, consultadaEn} en COP por 1 unidad de la moneda.
        COP retorna 1 sin consultar la API de Divisas; otra moneda debe estar habilitada (ACTIVO).
        """
        codigo = (codigoIso or "").upper()
        if codigo == MONEDA_BASE:
            from app.core.fechas import ahoraUtc

            return {"codigoIso": MONEDA_BASE, "tasaCambio": 1.0, "consultadaEn": ahoraUtc()}
        if not self.monedaHabilitada(sesion, codigo):
            raise ErrorAplicacion(409, "La moneda indicada no está habilitada")
        try:
            return self.clienteDivisas.consultarTasa(codigo)
        except DivisasNoDisponible as error:
            raise ErrorAplicacion(503, MENSAJE_TASA_NO_DISPONIBLE) from error
