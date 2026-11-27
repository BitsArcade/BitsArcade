"""Pruebas de HU-11: Carga masiva de claves al vault (POST /api/v1/inventario/claves/lotes)."""
from sqlalchemy.exc import OperationalError

from app.core.cifrado import descifrarClave
from app.domain.inventario import AlertaStock, ClaveLicencia
from app.repositories.repositorio_inventario import RepositorioInventario
from tests.conftest import encabezadoAuth

URL = "/api/v1/inventario/claves/lotes"
ADMIN = encabezadoAuth(1, rol="ADMIN")
LOTE = {"juegoId": 101, "plataforma": "PC", "claves": ["AAAAA-BBBBB-CCCCC", "DDDDD-EEEEE-FFFFF", "AAAAA-BBBBB-CCCCC"]}


def test_flujoExitosoConRechazoPorDuplicada(cliente, sesion):
    respuesta = cliente.post(URL, json=LOTE, headers=ADMIN)
    assert respuesta.status_code == 201
    assert respuesta.json() == {
        "message": "Carga de claves finalizada",
        "data": {"juegoId": 101, "plataforma": "PC", "recibidas": 3, "cargadas": 2,
                 "rechazadas": [{"indice": 2, "motivo": "DUPLICADA"}]},
        "success": True,
    }
    claves = sesion.query(ClaveLicencia).all()
    assert len(claves) == 2 and all(k.estado == "DISPONIBLE" for k in claves)


def test_claveSeGuardaCifradaYNormalizada(cliente, sesion):
    cliente.post(URL, json={"juegoId": 101, "plataforma": "PC", "claves": ["  aaaaa-bbbbb -ccccc "]}, headers=ADMIN)
    registroClave = sesion.query(ClaveLicencia).one()
    assert "AAAAA-BBBBB-CCCCC" not in registroClave.claveCifrada
    assert descifrarClave(registroClave.claveCifrada) == "AAAAA-BBBBB-CCCCC"
    assert len(registroClave.claveHash) == 64


def test_rn03RechazaDuplicadaYaExistenteSinExponerValor(cliente):
    cliente.post(URL, json={"juegoId": 101, "plataforma": "PC", "claves": ["AAAAA-BBBBB-CCCCC"]}, headers=ADMIN)
    respuesta = cliente.post(URL, json={"juegoId": 101, "plataforma": "PC", "claves": ["AAAAA-BBBBB-CCCCC", "##"]},
                             headers=ADMIN)
    datos = respuesta.json()["data"]
    assert datos["cargadas"] == 0
    assert datos["rechazadas"] == [{"indice": 0, "motivo": "DUPLICADA"}, {"indice": 1, "motivo": "FORMATO_INVALIDO"}]
    assert "AAAAA" not in respuesta.text


def test_mismaClaveEnOtraPlataformaEsValida(cliente):
    cliente.post(URL, json={"juegoId": 101, "plataforma": "PC", "claves": ["AAAAA-BBBBB-CCCCC"]}, headers=ADMIN)
    respuesta = cliente.post(URL, json={"juegoId": 101, "plataforma": "CONSOLA", "claves": ["AAAAA-BBBBB-CCCCC"]},
                             headers=ADMIN)
    assert respuesta.json()["data"]["cargadas"] == 1


def test_reposicionCierraAlertaDeStock(cliente, sesion):
    sesion.add(AlertaStock(juegoId=101, plataforma="PC", activa=True))
    sesion.commit()
    cliente.post(URL, json={"juegoId": 101, "plataforma": "PC", "claves": ["AAAAA-BBBBB-CCCCC"]}, headers=ADMIN)
    sesion.expire_all()
    assert sesion.query(AlertaStock).one().activa is False


def test_error400LoteVacio(cliente):
    respuesta = cliente.post(URL, json={"juegoId": 101, "plataforma": "PC", "claves": []}, headers=ADMIN)
    assert respuesta.status_code == 400
    assert respuesta.json() == {"message": "El lote no contiene claves", "data": None, "success": False}


def test_error400FaltaJuegoId(cliente):
    respuesta = cliente.post(URL, json={"plataforma": "PC", "claves": ["AAAAA-BBBBB-CCCCC"]}, headers=ADMIN)
    assert respuesta.status_code == 400
    assert respuesta.json()["message"] == "juegoId y plataforma son obligatorios"


def test_error401SinToken(cliente):
    assert cliente.post(URL, json=LOTE).status_code == 401


def test_error403RolCliente(cliente):
    respuesta = cliente.post(URL, json=LOTE, headers=encabezadoAuth(2, rol="CLIENTE"))
    assert respuesta.status_code == 403
    assert respuesta.json()["message"] == "No cuenta con permisos para realizar esta operación"


def test_error503BaseDeDatos(cliente, monkeypatch):
    def _falla(*_args, **_kwargs):
        raise OperationalError("SELECT", {}, Exception("BD caída"))

    monkeypatch.setattr(RepositorioInventario, "obtenerHashesExistentes", _falla)
    respuesta = cliente.post(URL, json=LOTE, headers=ADMIN)
    assert respuesta.status_code == 503
    assert respuesta.json()["message"] == "No fue posible cargar las claves"
