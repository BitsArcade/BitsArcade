from sqlalchemy.orm import Session
from app.domain.parametros import Moneda, ConfiguracionFinanciera, MetodoPago

class ParametrosRepository:
    """
    Capa Repository de MOD-00: Única encargada de ejecutar consultas
    y persistir cambios en la base de datos SQLite
    """

    # --- OPERACIONES DE MONEDAS (HU-01, HU-02) ---

    def obtener_moneda_por_codigo(self, db: Session, codigo_iso: str) -> Moneda | None:
        return db.query(Moneda).filter(Moneda.codigo_iso == codigo_iso).first()

    def crear_moneda(self, db: Session, codigo_iso: str, nombre: str, tasa_cambio_usd: float) -> Moneda:
        nueva_moneda = Moneda(
            codigo_iso=codigo_iso,
            nombre=nombre,
            tasa_cambio_usd=tasa_cambio_usd,
            estado="Activo"
        )
        db.add(nueva_moneda)
        db.commit()
        db.refresh(nueva_moneda)
        return nueva_moneda

    def listar_monedas_activas(self, db: Session) -> list[Moneda]:
        return db.query(Moneda).filter(Moneda.estado == "Activo").all()

    # --- OPERACIONES DE CONFIGURACIÓN FINANCIERA (HU-03, HU-04, COM-01, COM-02) ---

    def obtener_configuracion_financiera(self, db: Session) -> ConfiguracionFinanciera | None:
        return db.query(ConfiguracionFinanciera).first()

    def crear_configuracion_inicial(self, db: Session, tasa_iva: float, margen: float, moneda: str) -> ConfiguracionFinanciera:
        config = ConfiguracionFinanciera(
            tasa_iva=tasa_iva,
            margen_ganancia=margen,
            moneda_base=moneda
        )
        db.add(config)
        db.commit()
        db.refresh(config)
        return config

    def actualizar_iva(self, db: Session, config: ConfiguracionFinanciera, nueva_tasa_iva: float) -> ConfiguracionFinanciera:
        config.tasa_iva = nueva_tasa_iva
        db.commit()
        db.refresh(config)
        return config

    def actualizar_margen(self, db: Session, config: ConfiguracionFinanciera, nuevo_margen: float) -> ConfiguracionFinanciera:
        config.margen_ganancia = nuevo_margen
        db.commit()
        db.refresh(config)
        return config

    # --- OPERACIONES DE MÉTODOS DE PAGO (HU-05) ---

    def crear_metodo_pago(self, db: Session, nombre: str) -> MetodoPago:
        metodo = MetodoPago(nombre=nombre, estado="Activo")
        db.add(metodo)
        db.commit()
        db.refresh(metodo)
        return metodo

    def obtener_metodo_pago_por_id(self, db: Session, metodo_id: int) -> MetodoPago | None:
        return db.query(MetodoPago).filter(MetodoPago.id == metodo_id).first()

    def obtener_metodo_pago_por_nombre(self, db: Session, nombre: str) -> MetodoPago | None:
        return db.query(MetodoPago).filter(MetodoPago.nombre == nombre).first()

    def listar_metodos_pago(self, db: Session) -> list[MetodoPago]:
        return db.query(MetodoPago).all()

    def inactivar_metodo_pago(self, db: Session, metodo: MetodoPago) -> MetodoPago:
        # PRO-00.1.5: Borrado lógico cambiando el estado a "Inactivo" sin eliminar el registro
        metodo.estado = "Inactivo"
        db.commit()
        db.refresh(metodo)
        return metodo