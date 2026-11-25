"""Pruebas de HU-22: Ver requisitos del sistema (GET /api/v1/catalogo/juegos/{gameId}/requisitos)."""
from sqlalchemy.exc import OperationalError

from app.domain.catalogo import RequisitoSistema, formatear_requisitos
from app.repositories.repositorio_catalogo import RepositorioCatalogo


def _registrar_requisitos(sesion, juego_id):
    sesion.add_all([
        RequisitoSistema(juego_id=juego_id, tipo="MINIMO", so="Windows 10", procesador="Intel i5-8400",
                         memoria="8 GB", grafica="GTX 1060", almacenamiento="60 GB"),
        RequisitoSistema(juego_id=juego_id, tipo="RECOMENDADO", so="Windows 11", procesador="Intel i7-9700",
                         memoria="16 GB", grafica="RTX 2060", almacenamiento="60 GB SSD"),
    ])
    sesion.commit()


def test_flujo_exitoso(cliente, sesion, crear_juego):
    juego = crear_juego()
    _registrar_requisitos(sesion, juego.id)
    respuesta = cliente.get(f"/api/v1/catalogo/juegos/{juego.id}/requisitos")
    assert respuesta.status_code == 200
    assert respuesta.json() == {
        "message": "Consulta de requisitos exitosa",
        "data": {
            "minimos": {"so": "Windows 10", "procesador": "Intel i5-8400", "memoria": "8 GB",
                        "grafica": "GTX 1060", "almacenamiento": "60 GB"},
            "recomendados": {"so": "Windows 11", "procesador": "Intel i7-9700", "memoria": "16 GB",
                             "grafica": "RTX 2060", "almacenamiento": "60 GB SSD"},
        },
        "success": True,
    }


def test_juego_de_consola_sin_requisitos_retorna_200_informativo(cliente, crear_juego):
    juego = crear_juego(plataformas=("CONSOLA",))
    respuesta = cliente.get(f"/api/v1/catalogo/juegos/{juego.id}/requisitos")
    assert respuesta.status_code == 200
    assert respuesta.json() == {
        "message": "El juego no tiene requisitos de sistema registrados", "data": None, "success": False,
    }


def test_dominio_formatea_solo_minimos():
    datos = formatear_requisitos([RequisitoSistema(tipo="MINIMO", so="Windows 10")])
    assert datos["minimos"]["so"] == "Windows 10"
    assert datos["recomendados"] is None
    assert formatear_requisitos([]) is None


def test_error_404_juego_inexistente(cliente):
    respuesta = cliente.get("/api/v1/catalogo/juegos/9999/requisitos")
    assert respuesta.status_code == 404
    assert respuesta.json() == {"message": "El juego indicado no existe", "data": None, "success": False}


def test_error_503_base_de_datos(cliente, crear_juego, monkeypatch):
    juego = crear_juego()

    def _falla(*_args, **_kwargs):
        raise OperationalError("SELECT", {}, Exception("BD caída"))

    monkeypatch.setattr(RepositorioCatalogo, "listar_requisitos", _falla)
    respuesta = cliente.get(f"/api/v1/catalogo/juegos/{juego.id}/requisitos")
    assert respuesta.status_code == 503
    assert respuesta.json() == {"message": "No fue posible consultar los requisitos", "data": None, "success": False}
