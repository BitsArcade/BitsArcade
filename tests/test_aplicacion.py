"""Pruebas de los endpoints generales de la aplicación (raíz y verificación de salud)."""


def test_raizRetornaInformacionDelSistema(cliente):
    respuesta = cliente.get("/")
    assert respuesta.status_code == 200
    assert set(respuesta.json()) == {"sistema", "entorno", "version", "documentacion"}


def test_saludRetornaEstadoActivo(cliente):
    respuesta = cliente.get("/salud")
    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["estado"] == "ACTIVO"
    assert set(cuerpo) == {"estado", "servicio", "entorno"}


def test_rutaHealthEnInglesYaNoExiste(cliente):
    assert cliente.get("/health").status_code == 404
