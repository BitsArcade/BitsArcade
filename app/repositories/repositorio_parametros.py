from sqlalchemy.orm import Session
from app.domain.parametros import Moneda, ConfiguracionFinanciera, MetodoPago

class RepositorioParametros:
    """
    Capa Repository de MOD-00: Única encargada de ejecutar consultas
    y persistir cambios en la base de datos SQLite (Tabla 8 del informe).
    """

    # --- OPERACIONES DE MONEDAS (HU-01, HU-02) ---

    def obtener_moneda_por_codigo(self, sesion: Session, codigo_iso: str) -> Moneda | None:
        return sesion.query(Moneda).filter(Moneda.codigo_iso == codigo_iso).first()

    def crear_moneda(self, sesion: Session, codigo_iso: str, nombre: str, tasa_cambio_usd: float) -> Moneda:
        nueva_moneda = Moneda(
            codigo_iso=codigo_iso,
            nombre=nombre,
            tasa_cambio_usd=tasa_cambio_usd,
            estado="Activo"
        )
        sesion.add(nueva_moneda)
        sesion.commit()
        sesion.refresh(nueva_moneda)
        return nueva_moneda

    def listar_monedas_activas(self, sesion: Session) -> list[Moneda]:
        return sesion.query(Moneda).filter(Moneda.estado == "Activo").all()

    # --- OPERACIONES DE CONFIGURACIÓN FINANCIERA (HU-03, HU-04, COM-01, COM-02) ---

    def obtener_configuracion_financiera(self, sesion: Session) -> ConfiguracionFinanciera | None:
        return sesion.query(ConfiguracionFinanciera).first()

    def crear_configuracion_inicial(
        self, sesion: Session, tasa_iva: float, margen: float, moneda: str
    ) -> ConfiguracionFinanciera:
        configuracion = ConfiguracionFinanciera(
            tasa_iva=tasa_iva,
            margen_ganancia=margen,
            moneda_base=moneda
        )
        sesion.add(configuracion)
        sesion.commit()
        sesion.refresh(configuracion)
        return configuracion

    def actualizar_iva(
        self, sesion: Session, configuracion: ConfiguracionFinanciera, nueva_tasa_iva: float
    ) -> ConfiguracionFinanciera:
        configuracion.tasa_iva = nueva_tasa_iva
        sesion.commit()
        sesion.refresh(configuracion)
        return configuracion

    def actualizar_margen(
        self, sesion: Session, configuracion: ConfiguracionFinanciera, nuevo_margen: float
    ) -> ConfiguracionFinanciera:
        configuracion.margen_ganancia = nuevo_margen
        sesion.commit()
        sesion.refresh(configuracion)
        return configuracion

    # --- OPERACIONES DE MÉTODOS DE PAGO (HU-05) ---

    def crear_metodo_pago(self, sesion: Session, nombre: str) -> MetodoPago:
        metodo = MetodoPago(nombre=nombre, estado="Activo")
        sesion.add(metodo)
        sesion.commit()
        sesion.refresh(metodo)
        return metodo

    def obtener_metodo_pago_por_id(self, sesion: Session, metodo_id: int) -> MetodoPago | None:
        return sesion.query(MetodoPago).filter(MetodoPago.id == metodo_id).first()

    def obtener_metodo_pago_por_nombre(self, sesion: Session, nombre: str) -> MetodoPago | None:
        return sesion.query(MetodoPago).filter(MetodoPago.nombre == nombre).first()

    def listar_metodos_pago(self, sesion: Session) -> list[MetodoPago]:
        return sesion.query(MetodoPago).all()

    def inactivar_metodo_pago(self, sesion: Session, metodo: MetodoPago) -> MetodoPago:
        # PRO-00.1.5: Borrado lógico cambiando el estado a "Inactivo" sin eliminar el registro
        metodo.estado = "Inactivo"
        sesion.commit()
        sesion.refresh(metodo)
        return metodo