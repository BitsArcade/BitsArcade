# BitArcade – Backend

Backend de la tienda de licencias digitales BitArcade, construido con FastAPI, SQLAlchemy 2 y SQLite,
alineado con las historias de usuario ajustadas HU-01 a HU-50.

## Arquitectura

Arquitectura por capas:

| Capa | Carpeta | Responsabilidad |
|---|---|---|
| API | `app/api` | Rutas HTTP, validación de entrada y sobre de respuesta `{message, data, success}` |
| Servicio | `app/services` | Casos de uso por HU y adaptadores entre módulos (contratos COM) |
| Dominio | `app/domain` | Entidades, esquemas, reglas de negocio (RN) y mensajes |
| Repositorio | `app/repositories` | Acceso a datos con SQLAlchemy |
| Núcleo | `app/core` | Configuración, base de datos, seguridad (JWT y token de servicio), cifrado, fechas |

Módulos: MOD-00 Parametrización, MOD-01 Usuarios, MOD-02 Catálogo, MOD-03 Inventario,
MOD-04 Carrito y Órdenes, MOD-05 Pagos, MOD-06 Despacho y Biblioteca.

## Prefijos de rutas

- `/api/v1/...`: rutas públicas y de clientes (JWT `Authorization: Bearer` cuando aplica).
- `/interno/v1/...`: contratos entre módulos (COM-01 a COM-13). Exigen el encabezado
  `X-Token-Servicio` (y opcionalmente `X-Modulo-Solicitante`). Sin token responden 401
  "Token de servicio inválido o ausente".
- `/externo/v1/...`: servicios externos simulados (notificaciones).

## Convención de nombres

- Funciones, variables, argumentos, campos JSON y columnas: camelCase en español (`precioFinal`, `juegoId`).
- Clases: PascalCase en español (`ServicioOrdenes`). Constantes: MAYÚSCULAS_CON_GUION_BAJO (`TASA_IVA`).
- Archivos y tablas: snake_case en español; tablas en plural (`claves_licencia`, `ordenes`).
- Pruebas: `test_` + camelCase (`test_flujoExitosoPagoEnProceso`).
- `tasaIva` y `margenGanancia` se manejan como porcentajes de 0 a 100.

## Puesta en marcha

```bash
python -m venv .venv
source .venv/bin/activate          # En Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env               # y reemplace los valores
uvicorn main:app --reload
```

Documentación interactiva: `http://localhost:8000/docs`.

## Pruebas

```bash
python -m pytest -q
```

Cada HU tiene su archivo `tests/test_huXX_*.py`; el flujo completo de compra está en
`tests/test_flujo_compra_extremo_a_extremo.py`.
