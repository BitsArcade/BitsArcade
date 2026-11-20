from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from app.core.configuracion import settings
from app.domain.parametros import CrearMonedaEntrada, CrearMetodoPagoEntrada
from app.repositories.repositorio_parametros import RepositorioParametros

class ServicioParametros:
    """
    Capa Application / Service de MOD-00: Orquesta los casos de uso
    (PRO-00.1.1 a PRO-00.1.5) y los contratos internos (COM-01 a COM-03).
    """

    def __init__(self):
        self.repositorio = RepositorioParametros()

    def inicializar_datos_por_defecto(self, sesion: Session):
        """Garantiza que el sistema arranque con parámetros financieros y monedas base."""
        configuracion = self.repositorio.obtener_configuracion_financiera(sesion)
        if not configuracion:
            self.repositorio.crear_configuracion_inicial(
                sesion=sesion,
                tasa_iva=settings.TAX_RATE * 100,       # 0.19 -> 19.0%
                margen=settings.DEFAULT_MARGIN * 100,   # 0.25 -> 25.0%
                moneda=settings.DEFAULT_CURRENCY        # "COP"
            )

        if not self.repositorio.obtener_moneda_por_codigo(sesion, "COP"):
            self.repositorio.crear_moneda(sesion, "COP", "Peso Colombiano", 4200.0)
        if not self.repositorio.obtener_moneda_por_codigo(sesion, "USD"):
            self.repositorio.crear_moneda(sesion, "USD", "Dólar Estadounidense", 1.0)

        for nombre_metodo in ["Tarjeta de Crédito", "PSE", "Nequi"]:
            if not self.repositorio.obtener_metodo_pago_por_nombre(sesion, nombre_metodo):
                self.repositorio.crear_metodo_pago(sesion, nombre_metodo)

    # --- CASOS DE USO DE HISTORIAS DE USUARIO (HU-01 a HU-05) ---

    def registrar_moneda(self, sesion: Session, datos: CrearMonedaEntrada):
        """HU-01 / PRO-00.1.1: Validar unicidad del código ISO y crear moneda activa."""
        existente = self.repositorio.obtener_moneda_por_codigo(sesion, datos.codigo_iso)
        if existente:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"La moneda con código ISO '{datos.codigo_iso}' ya se encuentra registrada."
            )
        return self.repositorio.crear_moneda(
            sesion=sesion,
            codigo_iso=datos.codigo_iso,
            nombre=datos.nombre,
            tasa_cambio_usd=datos.tasa_cambio_usd
        )

    def consultar_monedas_habilitadas(self, sesion: Session):
        """HU-02 / PRO-00.1.2: Retornar únicamente las monedas con estado 'Activo'."""
        return self.repositorio.listar_monedas_activas(sesion)

    def actualizar_tasa_iva(self, sesion: Session, nueva_tasa_iva: float):
        """HU-03 / PRO-00.1.3: Actualizar el porcentaje de IVA (validado 0-100 en Domain)."""
        self.inicializar_datos_por_defecto(sesion)
        configuracion = self.repositorio.obtener_configuracion_financiera(sesion)
        return self.repositorio.actualizar_iva(sesion, configuracion, nueva_tasa_iva)

    def configurar_margen_ganancia(self, sesion: Session, nuevo_margen: float):
        """HU-04 / PRO-00.1.4: Sobrescribir margen comercial (validado > 0 en Domain)."""
        self.inicializar_datos_por_defecto(sesion)
        configuracion = self.repositorio.obtener_configuracion_financiera(sesion)
        return self.repositorio.actualizar_margen(sesion, configuracion, nuevo_margen)

    def crear_metodo_pago(self, sesion: Session, datos: CrearMetodoPagoEntrada):
        """Auxiliar para registrar nuevos métodos de pago."""
        existente = self.repositorio.obtener_metodo_pago_por_nombre(sesion, datos.nombre)
        if existente:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"El método de pago '{datos.nombre}' ya existe."
            )
        return self.repositorio.crear_metodo_pago(sesion, datos.nombre)

    def listar_metodos_pago(self, sesion: Session):
        """Consultar todos los métodos de pago y sus estados."""
        self.inicializar_datos_por_defecto(sesion)
        return self.repositorio.listar_metodos_pago(sesion)

    def inactivar_metodo_pago(self, sesion: Session, metodo_id: int):
        """HU-05 / PRO-00.1.5: Inactivación lógica (borrado lógico) de método de pago."""
        metodo = self.repositorio.obtener_metodo_pago_por_id(sesion, metodo_id)
        if not metodo:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No se encontró el método de pago con ID {metodo_id}."
            )
        if metodo.estado == "Inactivo":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"El método de pago '{metodo.nombre}' ya se encontraba inactivo."
            )
        return self.repositorio.inactivar_metodo_pago(sesion, metodo)

    # --- CONTRATOS INTERNOS ENTRE MICROSERVICIOS (Tabla 10 del informe) ---

    def obtener_contrato_com01(self, sesion: Session) -> dict:
        """COM-01 (Para MOD-02 Catálogo): Entrega taxRate y margin vigentes en formato decimal."""
        self.inicializar_datos_por_defecto(sesion)
        configuracion = self.repositorio.obtener_configuracion_financiera(sesion)
        return {
            "taxRate": round(configuracion.tasa_iva / 100, 4),
            "margin": round(configuracion.margen_ganancia / 100, 4)
        }

    def obtener_contrato_com02(self, sesion: Session) -> dict:
        """COM-02 (Para MOD-04 Carrito y Órdenes): Entrega taxRate y currency vigentes."""
        self.inicializar_datos_por_defecto(sesion)
        configuracion = self.repositorio.obtener_configuracion_financiera(sesion)
        return {
            "taxRate": round(configuracion.tasa_iva / 100, 4),
            "currency": configuracion.moneda_base
        }

    def obtener_contrato_com03(self, sesion: Session, moneda_iso: str) -> dict:
        """COM-03 (Para MOD-05 Transacciones): Entrega tasa de cambio vigente de la moneda."""
        self.inicializar_datos_por_defecto(sesion)
        moneda = self.repositorio.obtener_moneda_por_codigo(sesion, moneda_iso.upper())
        if not moneda or moneda.estado != "Activo":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"La moneda '{moneda_iso.upper()}' no existe o no está activa."
            )
        return {
            "currency": moneda.codigo_iso,
            "exchangeRate": moneda.tasa_cambio_usd
        }