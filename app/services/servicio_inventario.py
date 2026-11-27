import logging
import uuid
from datetime import timedelta

from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.cifrado import (
    cifrarClave,
    descifrarClave,
    hashClave,
)
from app.core.fechas import (
    aIsoZ,
    ahoraUtc,
)
from app.core.respuestas import (
    ErrorAplicacion,
    manejarErroresBd,
    respuesta,
)
from app.domain.inventario import (
    CONTADORES_POR_ESTADO,
    ESTADO_CLAVE_DISPONIBLE,
    ESTADO_CLAVE_RESERVADA,
    ESTADO_CLAVE_VENDIDA,
    ESTADO_RESERVA_ACTIVA,
    ESTADO_RESERVA_EXPIRADA,
    ESTADO_RESERVA_LIBERADA,
    ESTADO_RESERVA_VENDIDA,
    ESTADOS_CLAVE,
    MINUTOS_RESERVA,
    MOTIVO_DUPLICADA,
    MOTIVO_FORMATO_INVALIDO,
    AlertaStock,
    CargaLoteEntrada,
    ClaveLicencia,
    LiberarReservasEntrada,
    ReservaClave,
    ReservarClavesEntrada,
    claveConFormatoValido,
    normalizarClave,
    totalesVacios,
    validarCantidadReserva,
    validarJuegoIdConsulta,
    validarLote,
)
from app.repositories.repositorio_inventario import RepositorioInventario

registro = logging.getLogger("bitarcade.inventario")


class ServicioInventario:
    """Capa Application / Service de MOD-03: casos de uso del inventario de claves (HU-11 a HU-15)."""

    def __init__(self):
        self.repositorio = RepositorioInventario()

    # ===== HU-11: Carga masiva de claves al vault =====

    def cargarLote(self, sesion: Session, datos: CargaLoteEntrada) -> dict:
        """HU-11 (RN-03): normaliza, valida formato y unicidad, guarda cifradas en DISPONIBLE."""
        validarLote(datos.juegoId, datos.plataforma, datos.claves)
        plataforma = datos.plataforma.strip().upper()
        rechazadas, candidatas, vistos = [], [], set()
        for indice, valor in enumerate(datos.claves):
            registroClave = normalizarClave(valor)
            if not claveConFormatoValido(registroClave):
                rechazadas.append({"indice": indice, "motivo": MOTIVO_FORMATO_INVALIDO})
                continue
            huella = hashClave(registroClave)
            if huella in vistos:
                rechazadas.append({"indice": indice, "motivo": MOTIVO_DUPLICADA})
                continue
            vistos.add(huella)
            candidatas.append((indice, registroClave, huella))

        with manejarErroresBd("No fue posible cargar las claves"):
            existentes = self.repositorio.obtenerHashesExistentes(
                sesion, datos.juegoId, plataforma, [huella for _, _, huella in candidatas]
            )
            nuevas = []
            for indice, registroClave, huella in candidatas:
                if huella in existentes:
                    rechazadas.append({"indice": indice, "motivo": MOTIVO_DUPLICADA})
                    continue
                nuevas.append(
                    ClaveLicencia(
                        juegoId=datos.juegoId,
                        plataforma=plataforma,
                        estado=ESTADO_CLAVE_DISPONIBLE,
                        claveCifrada=cifrarClave(registroClave),
                        claveHash=huella,
                    )
                )
            try:
                self.repositorio.guardarClaves(sesion, nuevas)
            except IntegrityError as error:  # Carga concurrente del mismo lote
                sesion.rollback()
                raise ErrorAplicacion(409, "El lote contiene claves ya registradas") from error
            if nuevas:
                self.cerrarAlertaSiRepuesto(sesion, datos.juegoId, plataforma)  # HU-15

        return respuesta(
            "Carga de claves finalizada",
            {
                "juegoId": datos.juegoId,
                "plataforma": plataforma,
                "recibidas": len(datos.claves),
                "cargadas": len(nuevas),
                "rechazadas": sorted(rechazadas, key=lambda r: r["indice"]),
            },
        )

    # ===== HU-12: Consultar y auditar inventario de claves =====

    def consultarMetricas(self, sesion: Session, juegoId: str | None) -> dict:
        """HU-12: cuenta claves por juego, plataforma y estado (sin exponer valores)."""
        juegoId = validarJuegoIdConsulta(juegoId)
        with manejarErroresBd("No fue posible consultar el inventario"):
            filas = self.repositorio.contarPorJuegoYEstado(sesion, juegoId)
        porJuego: dict[tuple, dict] = {}
        totales = totalesVacios()
        for filaJuego, filaPlataforma, estado, cantidad in filas:
            if estado not in ESTADOS_CLAVE:
                continue
            grupo = porJuego.setdefault(
                (filaJuego, filaPlataforma),
                {"juegoId": filaJuego, "plataforma": filaPlataforma, **totalesVacios()},
            )
            contador = CONTADORES_POR_ESTADO[estado]
            grupo[contador] += cantidad
            totales[contador] += cantidad
        if not porJuego:
            return respuesta("No existen claves registradas", {"porJuego": [], "totales": totales}, False)
        return respuesta("Consulta de inventario exitosa", {"porJuego": list(porJuego.values()), "totales": totales})

    # ===== HU-13: Reservar clave temporalmente =====

    def reservarClaves(self, sesion: Session, datos: ReservarClavesEntrada) -> dict:
        """HU-13 (COM-06, RN-04): reserva atómica de N claves por 15 minutos."""
        cantidad = validarCantidadReserva(datos.cantidad)
        if datos.ordenId is None or datos.juegoId is None:
            raise ErrorAplicacion(400, "ordenId y juegoId son obligatorios")
        mensaje503 = "No fue posible reservar las claves"
        try:
            ids = self.repositorio.obtenerIdsDisponibles(sesion, datos.juegoId, cantidad)
            if len(ids) < cantidad:
                raise ErrorAplicacion(409, "Stock insuficiente para el juego solicitado")
            expiraEn = ahoraUtc() + timedelta(minutes=MINUTOS_RESERVA)
            reservas = []
            for claveId in ids:
                if not self.repositorio.marcarReservadaSiDisponible(sesion, claveId):
                    # Otra transacción tomó la clave: se revierte todo (todo o nada).
                    raise ErrorAplicacion(409, "Stock insuficiente para el juego solicitado")
                reservas.append(
                    ReservaClave(
                        reservaId=f"res-{uuid.uuid4().hex[:12]}",
                        claveId=claveId,
                        ordenId=datos.ordenId,
                        juegoId=datos.juegoId,
                        estado=ESTADO_RESERVA_ACTIVA,
                        expiraEn=expiraEn,
                    )
                )
            sesion.add_all(reservas)
            sesion.commit()
        except ErrorAplicacion:
            sesion.rollback()
            raise
        except SQLAlchemyError as error:
            sesion.rollback()
            raise ErrorAplicacion(503, mensaje503) from error
        return respuesta(
            "Claves reservadas exitosamente",
            {"reservaIds": [r.reservaId for r in reservas], "expiraEn": aIsoZ(expiraEn)},
        )

    def _devolverADisponible(self, sesion: Session, reserva: ReservaClave, nuevoEstado: str) -> None:
        registroClave = self.repositorio.obtenerClave(sesion, reserva.claveId)
        if registroClave is not None and registroClave.estado == ESTADO_CLAVE_RESERVADA:
            registroClave.estado = ESTADO_CLAVE_DISPONIBLE
        reserva.estado = nuevoEstado

    def liberarReservas(self, sesion: Session, datos: LiberarReservasEntrada) -> dict:
        """COM-13: libera reservas ACTIVAS (idempotente: repetir no cambia nada y retorna 0)."""
        with manejarErroresBd("No fue posible liberar las reservas"):
            liberadas = 0
            for reserva in self.repositorio.obtenerReservas(sesion, list(dict.fromkeys(datos.reservaIds))):
                if reserva.estado == ESTADO_RESERVA_ACTIVA:
                    self._devolverADisponible(sesion, reserva, ESTADO_RESERVA_LIBERADA)
                    liberadas += 1
            sesion.commit()
        return respuesta("Reservas liberadas exitosamente", {"liberadas": liberadas})

    def liberarReservasVencidas(self, sesion: Session) -> int:
        """TT-04 (RN-04): devuelve a DISPONIBLE las reservas con expiraEn < ahora."""
        vencidas = self.repositorio.obtenerReservasVencidas(sesion, ahoraUtc())
        for reserva in vencidas:
            self._devolverADisponible(sesion, reserva, ESTADO_RESERVA_EXPIRADA)
        sesion.commit()
        return len(vencidas)

    def consultarStock(self, sesion: Session, juegoId: int) -> dict:
        """COM-12: {juegoId, available} (uso interno entre módulos)."""
        with manejarErroresBd("No fue posible verificar la disponibilidad"):
            disponibles = self.repositorio.contarDisponibles(sesion, juegoId)
        return respuesta("Consulta de stock exitosa", {"juegoId": juegoId, "cantidadDisponible": disponibles})

    # ===== HU-14: Actualizar estado de clave a vendida =====

    def confirmarVentaInterna(self, sesion: Session, reservaId: str) -> tuple[ReservaClave, ClaveLicencia]:
        """COM-07: valida la reserva vigente y la marca VENDIDA. Idempotente por reservaId."""
        with manejarErroresBd("No fue posible confirmar la venta de la clave"):
            reserva = self.repositorio.obtenerReserva(sesion, reservaId)
            if reserva is None:
                raise ErrorAplicacion(404, "La reserva indicada no existe")
            registroClave = self.repositorio.obtenerClave(sesion, reserva.claveId)
            if reserva.estado == ESTADO_RESERVA_VENDIDA:
                return reserva, registroClave
            if reserva.estado != ESTADO_RESERVA_ACTIVA or reserva.expiraEn < ahoraUtc():
                raise ErrorAplicacion(409, "La reserva expiró o fue liberada")
            registroClave.estado = ESTADO_CLAVE_VENDIDA
            reserva.estado = ESTADO_RESERVA_VENDIDA
            reserva.vendidaEn = ahoraUtc()
            sesion.commit()
            return reserva, registroClave

    def confirmarVenta(self, sesion: Session, reservaId: str) -> dict:
        """HU-14: retorna el valor descifrado de la clave (nunca se registra en logs)."""
        reserva, registroClave = self.confirmarVentaInterna(sesion, reservaId)
        return respuesta(
            "Clave confirmada como vendida",
            {
                "reservaId": reserva.reservaId,
                "estado": ESTADO_CLAVE_VENDIDA,
                "claveLicencia": descifrarClave(registroClave.claveCifrada),
            },
        )

    # ===== HU-15: Reportar y alertar llaves agotadas =====

    def cerrarAlertaSiRepuesto(self, sesion: Session, juegoId: int, plataforma: str | None) -> None:
        """La alerta se cierra al reponerse stock (HU-11)."""
        alerta = self.repositorio.obtenerAlertaActiva(sesion, juegoId, plataforma)
        if alerta is not None:
            alerta.activa = False
            alerta.cerradaEn = ahoraUtc()
            sesion.commit()

    def evaluarStockAgotado(self, sesion: Session, emitirAlerta=None) -> list[AlertaStock]:
        """
        TT-04: identifica (juego, plataforma) con 0 claves DISPONIBLE y registra una alerta
        idempotente (no se duplica). Cierra las alertas cuyo stock ya se repuso.
        """
        nuevas = []
        for juegoId, plataforma, disponibles in self.repositorio.disponiblesPorJuegoYPlataforma(sesion):
            alerta = self.repositorio.obtenerAlertaActiva(sesion, juegoId, plataforma)
            if (disponibles or 0) == 0 and alerta is None:
                alerta = AlertaStock(juegoId=juegoId, plataforma=plataforma, activa=True)
                sesion.add(alerta)
                nuevas.append(alerta)
            elif (disponibles or 0) > 0 and alerta is not None:
                alerta.activa = False
                alerta.cerradaEn = ahoraUtc()
        sesion.commit()
        for alerta in nuevas:
            registro.warning("Stock agotado: juego %s plataforma %s", alerta.juegoId, alerta.plataforma)
            if emitirAlerta:
                emitirAlerta(alerta)  # Emisión asíncrona (cola/notificación) a cargo de TT-04
        return nuevas

    def consultarAgotadas(self, sesion: Session) -> dict:
        """HU-15: lista los títulos con alerta de stock agotado abierta."""
        with manejarErroresBd("No fue posible consultar las llaves agotadas"):
            alertas = self.repositorio.listarAlertasActivas(sesion)
        if not alertas:
            return respuesta("No existen títulos con stock agotado", [], False)
        return respuesta(
            "Consulta de llaves agotadas exitosa",
            [
                {"juegoId": a.juegoId, "plataforma": a.plataforma, "alertaDesde": aIsoZ(a.alertaDesde)}
                for a in alertas
            ],
        )
