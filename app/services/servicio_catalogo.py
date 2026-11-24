from sqlalchemy.orm import Session

from app.core.configuracion import settings
from app.core.respuestas import ErrorAplicacion, manejar_errores_bd, respuesta
from app.domain.catalogo import (
    MENSAJE_JUEGO_NO_EXISTE,
    agrupar_multimedia,
    calcular_precio_final,
    calcular_precio_piso,
    convertir_rango_precio_a_costo,
    determinar_estado_stock,
    formatear_requisitos,
    juego_a_ficha_tecnica,
    juego_a_item,
    validar_limite_destacados,
    validar_paginacion,
    validar_plataforma,
    validar_rango_precios,
    validar_texto_busqueda,
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
    Adaptador del contrato COM-01 (proveedor MOD-00): {tasaIva, margen} en formato decimal.
    """

    def __init__(self, servicio_parametros: ServicioParametros | None = None):
        self.servicio_parametros = servicio_parametros or ServicioParametros()

    def obtener(self, sesion: Session) -> dict:
        try:
            contrato = self.servicio_parametros.obtener_contrato_com01(sesion)
            return {"tasaIva": float(contrato["tasaIva"]), "margen": float(contrato["margen"])}
        except Exception as error:
            raise ErrorAplicacion(503, MENSAJE_COM01_NO_DISPONIBLE) from error


def _pagina(juegos, page: int, size: int, total: int) -> dict:
    return {"items": [juego_a_item(j) for j in juegos], "page": page, "size": size, "total": total}


class ServicioCatalogo:
    """Capa Application / Service de MOD-02: casos de uso del catálogo (HU-16 a HU-25)."""

    def __init__(self):
        self.repositorio = RepositorioCatalogo()
        self.cliente_parametros = ClienteParametrosFinancieros()
        self.cliente_inventario = ClienteInventario()

    def consultar_catalogo(self, sesion: Session, page: int, size: int) -> dict:
        """HU-20: listado paginado de juegos publicados (sin C_A ni precio)."""
        validar_paginacion(page, size)
        with manejar_errores_bd("No fue posible consultar el catálogo"):
            juegos, total = self.repositorio.listar_publicados(sesion, page, size)
        if total == 0:
            return respuesta("No existen juegos publicados", _pagina([], page, size, 0), False)
        return respuesta("Consulta de catálogo exitosa", _pagina(juegos, page, size, total))

    def buscar_por_nombre(self, sesion: Session, texto: str | None, page: int, size: int) -> dict:
        """HU-16: búsqueda parcial por título sobre juegos publicados."""
        texto_limpio = validar_texto_busqueda(texto)
        validar_paginacion(page, size)
        with manejar_errores_bd("No fue posible realizar la búsqueda"):
            juegos, total = self.repositorio.buscar_por_titulo(sesion, texto_limpio, page, size)
        if total == 0:
            return respuesta("No se encontraron juegos para la búsqueda", _pagina([], page, size, 0), False)
        return respuesta("Búsqueda exitosa", _pagina(juegos, page, size, total))

    def filtrar_por_plataforma(self, sesion: Session, plataforma: str, page: int, size: int) -> dict:
        """HU-17: filtra el catálogo publicado por plataforma (PC / CONSOLA), orden alfabético."""
        plataforma_valida = validar_plataforma(plataforma)
        validar_paginacion(page, size)
        with manejar_errores_bd("No fue posible filtrar el catálogo"):
            juegos, total = self.repositorio.filtrar_por_plataforma(sesion, plataforma_valida, page, size)
        if total == 0:
            return respuesta("No existen juegos para la plataforma indicada", _pagina([], page, size, 0), False)
        return respuesta("Filtrado por plataforma exitoso", _pagina(juegos, page, size, total))

    def listar_destacados(self, sesion: Session, limite: int) -> dict:
        """HU-19: destacados y novedades definidos solo con atributos del catálogo."""
        validar_limite_destacados(limite)
        with manejar_errores_bd("No fue posible consultar los destacados"):
            juegos = self.repositorio.listar_destacados(sesion, limite)
        if not juegos:
            return respuesta("No existen juegos destacados", [], False)
        return respuesta("Consulta de destacados exitosa", [juego_a_item(j) for j in juegos])

    def _obtener_juego_publicado(self, sesion: Session, juego_id: int, mensaje_error_bd: str):
        """Obtiene un juego publicado o lanza 404; los fallos de BD se traducen a 503."""
        with manejar_errores_bd(mensaje_error_bd):
            juego = self.repositorio.obtener_publicado_por_id(sesion, juego_id)
        if juego is None:
            raise ErrorAplicacion(404, MENSAJE_JUEGO_NO_EXISTE)
        return juego

    def consultar_ficha_tecnica(self, sesion: Session, juego_id: int) -> dict:
        """HU-21: ficha técnica completa sin costo de adquisición ni margen."""
        juego = self._obtener_juego_publicado(sesion, juego_id, "No fue posible consultar la ficha técnica")
        return respuesta("Consulta de ficha técnica exitosa", juego_a_ficha_tecnica(juego))

    def consultar_requisitos(self, sesion: Session, juego_id: int) -> dict:
        """HU-22: requisitos mínimos y recomendados; 200 informativo si no hay registros."""
        mensaje_error = "No fue posible consultar los requisitos"
        self._obtener_juego_publicado(sesion, juego_id, mensaje_error)
        with manejar_errores_bd(mensaje_error):
            requisitos = self.repositorio.listar_requisitos(sesion, juego_id)
        datos = formatear_requisitos(requisitos)
        if datos is None:
            return respuesta("El juego no tiene requisitos de sistema registrados", None, False)
        return respuesta("Consulta de requisitos exitosa", datos)

    def consultar_multimedia(self, sesion: Session, juego_id: int) -> dict:
        """HU-23: solo URLs almacenadas; no se integra ninguna API externa de video."""
        mensaje_error = "No fue posible consultar el material multimedia"
        self._obtener_juego_publicado(sesion, juego_id, mensaje_error)
        with manejar_errores_bd(mensaje_error):
            recursos = self.repositorio.listar_multimedia(sesion, juego_id)
        datos = agrupar_multimedia(recursos)
        if not datos["imagenes"] and not datos["videos"]:
            return respuesta("El juego no tiene material multimedia", datos, False)
        return respuesta("Consulta de multimedia exitosa", datos)

    # --- HU-24: Precio final público y contrato COM-11 ---

    def consultar_precio_final(self, sesion: Session, juego_id: int) -> dict:
        """HU-24: aplica RN-01/RN-02 con los parámetros vigentes de COM-01 (una sola llamada)."""
        juego = self._obtener_juego_publicado(sesion, juego_id, "No fue posible calcular el precio")
        parametros = self.cliente_parametros.obtener(sesion)
        precio_final = calcular_precio_final(juego.costo_adquisicion, parametros["margen"], parametros["tasaIva"])
        return respuesta(
            "Consulta de precio exitosa",
            {
                "juegoId": juego.id,
                "moneda": settings.DEFAULT_CURRENCY,
                "ivaPorcentaje": round(parametros["tasaIva"] * 100, 2),
                "precioFinal": precio_final,
            },
        )

    def obtener_contrato_com11(self, sesion: Session, juego_id: int) -> dict:
        """
        COM-11 (proveedor MOD-02): {existe, titulo, estado, precioFinal, precioPiso}
        con precioPiso = C_A × (1 + IVA). Consumido por MOD-04 (Carrito).
        """
        with manejar_errores_bd("No fue posible calcular el precio"):
            juego = self.repositorio.obtener_por_id(sesion, juego_id)
        if juego is None:
            return {"existe": False, "titulo": None, "estado": None, "precioFinal": None, "precioPiso": None}
        parametros = self.cliente_parametros.obtener(sesion)
        return {
            "existe": True,
            "titulo": juego.titulo,
            "estado": juego.estado,
            "precioFinal": calcular_precio_final(juego.costo_adquisicion, parametros["margen"], parametros["tasaIva"]),
            "precioPiso": calcular_precio_piso(juego.costo_adquisicion, parametros["tasaIva"]),
        }

    # --- HU-18: Filtrado combinado por género y precio final ---

    def filtrar_por_genero_y_precio(
        self,
        sesion: Session,
        genero: str | None,
        precio_min: float | None,
        precio_max: float | None,
        page: int,
        size: int,
    ) -> dict:
        """HU-18: el filtro opera sobre el precio final (RN-01) con una sola llamada a COM-01."""
        validar_rango_precios(precio_min, precio_max)
        validar_paginacion(page, size)
        parametros = self.cliente_parametros.obtener(sesion)
        margen, tasa_iva = parametros["margen"], parametros["tasaIva"]
        costo_min, costo_max = convertir_rango_precio_a_costo(precio_min, precio_max, margen, tasa_iva)
        genero_limpio = (genero or "").strip() or None
        with manejar_errores_bd("No fue posible filtrar el catálogo"):
            juegos, total = self.repositorio.filtrar_por_genero_y_costo(
                sesion, genero_limpio, costo_min, costo_max, page, size
            )
        if total == 0:
            return respuesta("No existen juegos con los filtros indicados", _pagina([], page, size, 0), False)
        items = [
            {
                **juego_a_item(juego),
                "precioFinal": calcular_precio_final(juego.costo_adquisicion, margen, tasa_iva),
                "moneda": settings.DEFAULT_CURRENCY,
            }
            for juego in juegos
        ]
        return respuesta("Filtrado exitoso", {"items": items, "page": page, "size": size, "total": total})

    # --- HU-25: Disponibilidad de stock (COM-12) ---

    def verificar_stock(self, sesion: Session, juego_id: int) -> dict:
        """HU-25: DISPONIBLE / AGOTADO sin exponer el conteo; si COM-12 falla responde 503."""
        juego = self._obtener_juego_publicado(sesion, juego_id, "No fue posible verificar el stock")
        try:
            disponibles = self.cliente_inventario.contar_disponibles(sesion, juego.id)
        except InventarioNoDisponible as error:
            raise ErrorAplicacion(503, MENSAJE_COM12_NO_DISPONIBLE) from error
        return respuesta(
            "Consulta de stock exitosa",
            {"juegoId": juego.id, "estado": determinar_estado_stock(disponibles)},
        )