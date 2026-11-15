from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from app.core.config import settings
from app.domain.parametros import MonedaCreate, MetodoPagoCreate
from app.repositories.parametros_repo import ParametrosRepository

class ParametrosService:
    """
    Capa Application / Service de MOD-00: Orquesta los casos de uso
    (PRO-00.1.1 a PRO-00.1.5) y los contratos internos (COM-01 a COM-03).
    """

    def __init__(self):
        self.repo = ParametrosRepository()

    def inicializar_datos_por_defecto(self, db: Session):
        """Garantiza que el sistema arranque con parámetros financieros y monedas base."""
        config = self.repo.obtener_configuracion_financiera(db)
        if not config:
            self.repo.crear_configuracion_inicial(
                db=db,
                tasa_iva=settings.TAX_RATE * 100,       # 0.19 -> 19.0%
                margen=settings.DEFAULT_MARGIN * 100,   # 0.25 -> 25.0%
                moneda=settings.DEFAULT_CURRENCY        # "COP"
            )

        # Sembrar monedas base (COP y USD mencionadas en Tabla 4 del informe)
        if not self.repo.obtener_moneda_por_codigo(db, "COP"):
            self.repo.crear_moneda(db, "COP", "Peso Colombiano", 3310.0) #Valor de la TRM hoy 15/11/2026
        if not self.repo.obtener_moneda_por_codigo(db, "USD"):
            self.repo.crear_moneda(db, "USD", "Dólar Estadounidense", 1.0)

        # Sembrar métodos de pago base para pruebas de HU-05
        for nombre_metodo in ["Tarjeta de Crédito", "PSE", "Nequi"]:
            if not self.repo.obtener_metodo_pago_por_nombre(db, nombre_metodo):
                self.repo.crear_metodo_pago(db, nombre_metodo)

    # --- CASOS DE USO DE HISTORIAS DE USUARIO (HU-01 a HU-05) ---

    def registrar_moneda(self, db: Session, datos: MonedaCreate):
        """HU-01 / PRO-00.1.1: Validar unicidad del código ISO y crear moneda activa."""
        existente = self.repo.obtener_moneda_por_codigo(db, datos.codigo_iso)
        if existente:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"La moneda con código ISO '{datos.codigo_iso}' ya se encuentra registrada."
            )
        return self.repo.crear_moneda(
            db=db,
            codigo_iso=datos.codigo_iso,
            nombre=datos.nombre,
            tasa_cambio_usd=datos.tasa_cambio_usd
        )

    def consultar_monedas_habilitadas(self, db: Session):
        """HU-02 / PRO-00.1.2: Retornar únicamente las monedas con estado 'Activo'."""
        return self.repo.listar_monedas_activas(db)

    def actualizar_tasa_iva(self, db: Session, nueva_tasa_iva: float):
        """HU-03 / PRO-00.1.3: Actualizar el porcentaje de IVA (validado 0-100 en Domain)."""
        self.inicializar_datos_por_defecto(db)
        config = self.repo.obtener_configuracion_financiera(db)
        return self.repo.actualizar_iva(db, config, nueva_tasa_iva)

    def configurar_margen_ganancia(self, db: Session, nuevo_margen: float):
        """HU-04 / PRO-00.1.4: Sobrescribir margen comercial (validado > 0 en Domain)."""
        self.inicializar_datos_por_defecto(db)
        config = self.repo.obtener_configuracion_financiera(db)
        return self.repo.actualizar_margen(db, config, nuevo_margen)

    def crear_metodo_pago(self, db: Session, datos: MetodoPagoCreate):
        """Auxiliar para registrar nuevos métodos de pago."""
        existente = self.repo.obtener_metodo_pago_por_nombre(db, datos.nombre)
        if existente:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"El método de pago '{datos.nombre}' ya existe."
            )
        return self.repo.crear_metodo_pago(db, datos.nombre)

    def listar_metodos_pago(self, db: Session):
        """Consultar todos los métodos de pago y sus estados."""
        self.inicializar_datos_por_defecto(db)
        return self.repo.listar_metodos_pago(db)

    def inactivar_metodo_pago(self, db: Session, metodo_id: int):
        """HU-05 / PRO-00.1.5: Inactivación lógica (borrado lógico) de método de pago."""
        metodo = self.repo.obtener_metodo_pago_por_id(db, metodo_id)
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
        return self.repo.inactivar_metodo_pago(db, metodo)

    # --- CONTRATOS INTERNOS ENTRE MICROSERVICIOS (Tabla 10 del informe) ---

    def obtener_contrato_com01(self, db: Session) -> dict:
        """COM-01 (Para MOD-02 Catálogo): Entrega taxRate y margin vigentes en formato decimal."""
        self.inicializar_datos_por_defecto(db)
        config = self.repo.obtener_configuracion_financiera(db)
        return {
            "taxRate": round(config.tasa_iva / 100, 4),
            "margin": round(config.margen_ganancia / 100, 4)
        }

    def obtener_contrato_com02(self, db: Session) -> dict:
        """COM-02 (Para MOD-04 Carrito y Órdenes): Entrega taxRate y currency vigentes."""
        self.inicializar_datos_por_defecto(db)
        config = self.repo.obtener_configuracion_financiera(db)
        return {
            "taxRate": round(config.tasa_iva / 100, 4),
            "currency": config.moneda_base
        }

    def obtener_contrato_com03(self, db: Session, currency: str) -> dict:
        """COM-03 (Para MOD-05 Transacciones): Entrega tasa de cambio vigente de la moneda."""
        self.inicializar_datos_por_defecto(db)
        moneda = self.repo.obtener_moneda_por_codigo(db, currency.upper())
        if not moneda or moneda.estado != "Activo":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"La moneda '{currency.upper()}' no existe o no está activa."
            )
        return {
            "currency": moneda.codigo_iso,
            "exchangeRate": moneda.tasa_cambio_usd
        }