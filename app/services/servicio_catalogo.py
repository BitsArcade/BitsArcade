from sqlalchemy.orm import Session

from app.core.configuracion import configuracion

from app.core.respuestas import ErrorAplicacion, manejarErroresBd, respuesta
from app.domain.catalogo import (
    MENSAJE_JUEGO_NO_EXISTE,
    agruparMultimedia,
    calcularPrecioFinal,
    calcularPrecioPiso,
    convertirRangoPrecioACosto,
    determinarEstadoStock,
    formatearRequisitos,
    juegoAFichaTecnica,
    juegoAItem,
    validarLimiteDestacados,
    validarPaginacion,
    validarPlataforma,
    validarRangoPrecios,
    validarTextoBusqueda,
)
from app.repositories.repositorio_catalogo import RepositorioCatalogo
from app.services.cliente_inventario import (
    MENSAJE_COM12_NO_DISPONIBLE,
    ClienteInventario,
    InventarioNoDisponible,
)
from app.services.servicio_parametros import ServicioParametros

MENSAJE_COM01_NO_DISPONIBLE = "No fue posible obtener los parámetros financieros"


class ClienteParametrosFinancieros:
    """
    Adaptador del contrato COM-01 (proveedor MOD-00): {tasaIva, margenGanancia} en porcentaje (0-100).
    Hoy se resuelve en proceso con el servicio de MOD-00; si se separa en microservicios basta
    con reemplazar este adaptador por un cliente HTTP a GET /interno/v1/parametrizacion/financieros.
    """

    def __init__(self, servicioParametros: ServicioParametros | None = None):
        self.servicioParametros = servicioParametros or ServicioParametros()

    def obtenerContratoCom01(self, sesion: Session) -> dict:
        """
        Lee COM-01 de MOD-00 y lo entrega en porcentaje (0-100). Si MOD-00 aún expone el contrato
        anterior (`obtener_contrato_com01`, en decimal: taxRate=0.19), se convierte a porcentaje.
        """
        servicio = self.servicioParametros
        if hasattr(servicio, "obtenerContratoCom01"):
            return servicio.obtenerContratoCom01(sesion)
        contrato = servicio.obtener_contrato_com01(sesion)
        return {
            "tasaIva": round(float(contrato["taxRate"]) * 100, 4),
            "margenGanancia": round(float(contrato["margin"]) * 100, 4),
        }

    def obtener(self, sesion: Session) -> dict:
        try:
            contrato = self.obtenerContratoCom01(sesion)
            return {"tasaIva": float(contrato["tasaIva"]), "margenGanancia": float(contrato["margenGanancia"])}
        except Exception as error:  # Cualquier fallo de COM-01 se trata como no disponible.
            raise ErrorAplicacion(503, MENSAJE_COM01_NO_DISPONIBLE) from error


def _pagina(juegos, pagina: int, tamano: int, total: int) -> dict:
    return {"items": [juegoAItem(j) for j in juegos], "pagina": pagina, "tamano": tamano, "total": total}


class ServicioCatalogo:
    """Capa Application / Service de MOD-02: casos de uso del catálogo (HU-16 a HU-25)."""

    def __init__(self):
        self.repositorio = RepositorioCatalogo()
        self.clienteParametros = ClienteParametrosFinancieros()
        self.clienteInventario = ClienteInventario()

    def consultarCatalogo(self, sesion: Session, pagina: int, tamano: int) -> dict:
        """HU-20: listado paginado de juegos publicados (sin C_A ni precio)."""
        validarPaginacion(pagina, tamano)
        with manejarErroresBd("No fue posible consultar el catálogo"):
            juegos, total = self.repositorio.listarPublicados(sesion, pagina, tamano)
        if total == 0:
            return respuesta("No existen juegos publicados", _pagina([], pagina, tamano, 0), False)
        return respuesta("Consulta de catálogo exitosa", _pagina(juegos, pagina, tamano, total))

    def buscarPorNombre(self, sesion: Session, texto: str | None, pagina: int, tamano: int) -> dict:
        """HU-16: búsqueda parcial por título sobre juegos publicados."""
        textoLimpio = validarTextoBusqueda(texto)
        validarPaginacion(pagina, tamano)
        with manejarErroresBd("No fue posible realizar la búsqueda"):
            juegos, total = self.repositorio.buscarPorTitulo(sesion, textoLimpio, pagina, tamano)
        if total == 0:
            return respuesta("No se encontraron juegos para la búsqueda", _pagina([], pagina, tamano, 0), False)
        return respuesta("Búsqueda exitosa", _pagina(juegos, pagina, tamano, total))

    def filtrarPorPlataforma(self, sesion: Session, plataforma: str, pagina: int, tamano: int) -> dict:
        """HU-17: filtra el catálogo publicado por plataforma (PC / CONSOLA), orden alfabético."""
        plataformaValida = validarPlataforma(plataforma)
        validarPaginacion(pagina, tamano)
        with manejarErroresBd("No fue posible filtrar el catálogo"):
            juegos, total = self.repositorio.filtrarPorPlataforma(sesion, plataformaValida, pagina, tamano)
        if total == 0:
            return respuesta("No existen juegos para la plataforma indicada", _pagina([], pagina, tamano, 0), False)
        return respuesta("Filtrado por plataforma exitoso", _pagina(juegos, pagina, tamano, total))

    def listarDestacados(self, sesion: Session, limite: int) -> dict:
        """HU-19: destacados y novedades definidos solo con atributos del catálogo."""
        validarLimiteDestacados(limite)
        with manejarErroresBd("No fue posible consultar los destacados"):
            juegos = self.repositorio.listarDestacados(sesion, limite)
        if not juegos:
            return respuesta("No existen juegos destacados", [], False)
        return respuesta("Consulta de destacados exitosa", [juegoAItem(j) for j in juegos])

    def _obtenerJuegoPublicado(self, sesion: Session, juegoId: int, mensajeErrorBd: str):
        """Obtiene un juego publicado o lanza 404; los fallos de BD se traducen a 503."""
        with manejarErroresBd(mensajeErrorBd):
            juego = self.repositorio.obtenerPublicadoPorId(sesion, juegoId)
        if juego is None:
            raise ErrorAplicacion(404, MENSAJE_JUEGO_NO_EXISTE)
        return juego

    def consultarFichaTecnica(self, sesion: Session, juegoId: int) -> dict:
        """HU-21: ficha técnica completa sin costo de adquisición ni margen."""
        juego = self._obtenerJuegoPublicado(sesion, juegoId, "No fue posible consultar la ficha técnica")
        return respuesta("Consulta de ficha técnica exitosa", juegoAFichaTecnica(juego))

    def consultarRequisitos(self, sesion: Session, juegoId: int) -> dict:
        """HU-22: requisitos mínimos y recomendados; 200 informativo si no hay registros (p. ej. consola)."""
        mensajeError = "No fue posible consultar los requisitos"
        self._obtenerJuegoPublicado(sesion, juegoId, mensajeError)
        with manejarErroresBd(mensajeError):
            requisitos = self.repositorio.listarRequisitos(sesion, juegoId)
        datos = formatearRequisitos(requisitos)
        if datos is None:
            return respuesta("El juego no tiene requisitos de sistema registrados", None, False)
        return respuesta("Consulta de requisitos exitosa", datos)

    def consultarMultimedia(self, sesion: Session, juegoId: int) -> dict:
        """HU-23: solo URLs almacenadas; no se integra ninguna API externa de video."""
        mensajeError = "No fue posible consultar el material multimedia"
        self._obtenerJuegoPublicado(sesion, juegoId, mensajeError)
        with manejarErroresBd(mensajeError):
            recursos = self.repositorio.listarMultimedia(sesion, juegoId)
        datos = agruparMultimedia(recursos)
        if not datos["imagenes"] and not datos["videos"]:
            return respuesta("El juego no tiene material multimedia", datos, False)
        return respuesta("Consulta de multimedia exitosa", datos)

    # --- HU-24: Precio final público y contrato COM-11 ---

    def consultarPrecioFinal(self, sesion: Session, juegoId: int) -> dict:
        """HU-24: aplica RN-01/RN-02 con los parámetros vigentes de COM-01 (una sola llamada)."""
        juego = self._obtenerJuegoPublicado(sesion, juegoId, "No fue posible calcular el precio")
        parametros = self.clienteParametros.obtener(sesion)
        precioFinal = calcularPrecioFinal(juego.costoAdquisicion, parametros["margenGanancia"], parametros["tasaIva"])
        return respuesta(
            "Consulta de precio exitosa",
            {
                "juegoId": juego.id,
                "moneda": configuracion.MONEDA_BASE,
                "tasaIva": round(parametros["tasaIva"], 2),
                "precioFinal": precioFinal,
            },
        )

    def obtenerContratoCom11(self, sesion: Session, juegoId: int) -> dict:
        """
        COM-11 (proveedor MOD-02): {juegoId, existe, titulo, estado, precioFinal, precioMinimo}
        con precioMinimo = C_A × (1 + IVA). Consumido por MOD-04 (Carrito).
        """
        with manejarErroresBd("No fue posible calcular el precio"):
            juego = self.repositorio.obtenerPorId(sesion, juegoId)
        if juego is None:
            return {"juegoId": juegoId, "existe": False, "titulo": None, "estado": None, "precioFinal": None, "precioMinimo": None}
        parametros = self.clienteParametros.obtener(sesion)
        return {
            "juegoId": juego.id,
            "existe": True,
            "titulo": juego.titulo,
            "estado": juego.estado,
            "precioFinal": calcularPrecioFinal(juego.costoAdquisicion, parametros["margenGanancia"], parametros["tasaIva"]),
            "precioMinimo": calcularPrecioPiso(juego.costoAdquisicion, parametros["tasaIva"]),
        }

    # --- HU-18: Filtrado combinado por género y precio final ---

    def filtrarPorGeneroYPrecio(
        self,
        sesion: Session,
        genero: str | None,
        precioMin: float | None,
        precioMax: float | None,
        pagina: int,
        tamano: int,
    ) -> dict:
        """HU-18: el filtro opera sobre el precio final (RN-01) con una sola llamada a COM-01."""
        validarRangoPrecios(precioMin, precioMax)
        validarPaginacion(pagina, tamano)
        parametros = self.clienteParametros.obtener(sesion)
        margenGanancia, tasaIva = parametros["margenGanancia"], parametros["tasaIva"]
        costoMin, costoMax = convertirRangoPrecioACosto(precioMin, precioMax, margenGanancia, tasaIva)
        generoLimpio = (genero or "").strip() or None
        with manejarErroresBd("No fue posible filtrar el catálogo"):
            juegos, total = self.repositorio.filtrarPorGeneroYCosto(
                sesion, generoLimpio, costoMin, costoMax, pagina, tamano
            )
        if total == 0:
            return respuesta("No existen juegos con los filtros indicados", _pagina([], pagina, tamano, 0), False)
        items = [
            {
                **juegoAItem(juego),
                "precioFinal": calcularPrecioFinal(juego.costoAdquisicion, margenGanancia, tasaIva),
                "moneda": configuracion.MONEDA_BASE,
            }
            for juego in juegos
        ]
        return respuesta("Filtrado exitoso", {"items": items, "pagina": pagina, "tamano": tamano, "total": total})

    # --- HU-25: Disponibilidad de stock (COM-12) ---

    def verificarStock(self, sesion: Session, juegoId: int) -> dict:
        """HU-25: DISPONIBLE / AGOTADO sin exponer el conteo; si COM-12 falla responde 503."""
        juego = self._obtenerJuegoPublicado(sesion, juegoId, "No fue posible verificar el stock")
        try:
            disponibles = self.clienteInventario.contarDisponibles(sesion, juego.id)
        except InventarioNoDisponible as error:
            raise ErrorAplicacion(503, MENSAJE_COM12_NO_DISPONIBLE) from error
        return respuesta(
            "Consulta de stock exitosa",
            {"juegoId": juego.id, "estadoStock": determinarEstadoStock(disponibles)},
        )

    # Compatibilidad temporal: COM-11 con las claves anteriores, usado por MOD-04 (órdenes, HU-31)
    # mientras migra a la convención actualizada.
    def obtener_contrato_com11(self, sesion: Session, juego_id: int) -> dict:
        contrato = self.obtenerContratoCom11(sesion, juego_id)
        return {
            "exists": contrato["existe"],
            "title": contrato["titulo"],
            "status": contrato["estado"],
            "finalPrice": contrato["precioFinal"],
            "floorPrice": contrato["precioMinimo"],
        }
