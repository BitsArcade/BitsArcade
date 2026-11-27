"""Pruebas de HU-22: Ver requisitos del sistema (GET /api/v1/catalogo/juegos/{juegoId}/requisitos)."""
from sqlalchemy.exc import OperationalError

from app.domain.catalogo import RequisitoSistema, formatearRequisitos
from app.repositories.repositorio_catalogo import RepositorioCatalogo


def _registrarRequisitos(sesion, juegoId):
    sesion.add_all([
        RequisitoSistema(juegoId=juegoId, tipo="MINIMO", sistemaOperativo="Windows 10", procesador="Intel i5-8400",
                         memoria="8 GB", grafica="GTX 1060", almacenamiento="60 GB"),
        RequisitoSistema(juegoId=juegoId, tipo="RECOMENDADO", sistemaOperativo="Windows 11", procesador="Intel i7-9700",
                         memoria="16 GB", grafica="RTX 2060", almacenamiento="60 GB SSD"),
    ])
    sesion.commit()


def test_flujoExitoso(cliente, sesion, crearJuego):
    juego = crearJuego()
    _registrarRequisitos(sesion, juego.id)
    respuesta = cliente.get(f"/api/v1/catalogo/juegos/{juego.id}/requisitos")
    assert respuesta.status_code == 200
    assert respuesta.json() == {
        "message": "Consulta de requisitos exitosa",
        "data": {
            "minimos": {"sistemaOperativo": "Windows 10", "procesador": "Intel i5-8400", "memoria": "8 GB",
                        "grafica": "GTX 1060", "almacenamiento": "60 GB"},
            "recomendados": {"sistemaOperativo": "Windows 11", "procesador": "Intel i7-9700", "memoria": "16 GB",
                             "grafica": "RTX 2060", "almacenamiento": "60 GB SSD"},
        },
        "success": True,
    }


def test_juegoDeConsolaSinRequisitosRetorna200Informativo(cliente, crearJuego):
    juego = crearJuego(plataformas=("CONSOLA",))
    respuesta = cliente.get(f"/api/v1/catalogo/juegos/{juego.id}/requisitos")
    assert respuesta.status_code == 200
    assert respuesta.json() == {
        "message": "El juego no tiene requisitos de sistema registrados", "data": None, "success": False,
    }


def test_dominioFormateaSoloMinimos():
    datos = formatearRequisitos([RequisitoSistema(tipo="MINIMO", sistemaOperativo="Windows 10")])
    assert datos["minimos"]["sistemaOperativo"] == "Windows 10"
    assert datos["recomendados"] is None
    assert formatearRequisitos([]) is None


def test_error404JuegoInexistente(cliente):
    respuesta = cliente.get("/api/v1/catalogo/juegos/9999/requisitos")
    assert respuesta.status_code == 404
    assert respuesta.json() == {"message": "El juego indicado no existe", "data": None, "success": False}


def test_error503BaseDeDatos(cliente, crearJuego, monkeypatch):
    juego = crearJuego()

    def _falla(*_args, **_kwargs):
        raise OperationalError("SELECT", {}, Exception("BD caída"))

    monkeypatch.setattr(RepositorioCatalogo, "listarRequisitos", _falla)
    respuesta = cliente.get(f"/api/v1/catalogo/juegos/{juego.id}/requisitos")
    assert respuesta.status_code == 503
    assert respuesta.json() == {"message": "No fue posible consultar los requisitos", "data": None, "success": False}
