# SNAPSHOT_MANIFEST.md — TIQ V3 DEV integrada (post-FASE 8 + FASE 9 + FASE 10A)

Fecha de captura inicial: **2026-09-14T04:29:44Z** (FASE 8, 8 workflows)
Fecha de actualización: **2026-09-14T11:29:00Z** (FASE 9, +1 workflow: backend DEV)
Fecha de actualización: **2026-09-14T11:56:00Z** (FASE 10A, conexión de solo lectura a Google Drive real en 01 INGESTA y 02 MATERIALIZACION)

Este snapshot congela el estado de los 9 workflows de Caja Tiquipaya V3
tras FASE 9 (frontend real conectado a un backend DEV vía `v3/dev_api.py` +
`n8n_frontend/v3_control_cierres.html`) y FASE 10A (conexión de SOLO
LECTURA a Google Drive real). Los 9 workflows están `active=false`; ninguno
usa Drive/SAP/marcadores productivos DE ESCRITURA — dos de ellos (01
INGESTA y 02 MATERIALIZACION) SÍ leen/descargan copias de Google Drive real
desde FASE 10A, ver sección dedicada más abajo. **No contiene secretos** —
cada JSON es exactamente el objeto workflow devuelto por
`get_workflow_details`, sin el bloque `scopes`/`canExecute`/`triggerInfo`
(metadata de lectura de la API, no parte del workflow en sí). Los 7
workflows sin Drive siguen sin el campo `credentials` en ningún nodo; los 2
workflows con Drive real (01, 02) tienen nodos `googleDrive` con
`credentials.googleDriveOAuth2Api: {id, name}` — una REFERENCIA a la
credencial ya existente en n8n ("Google Drive account", reutilizada de V2
tal cual, nunca duplicada), nunca el secreto/token en sí (n8n no lo expone
vía API bajo ninguna circunstancia).

## Referencia a V2 (oráculo, congelado)

- Rama: `v2-final-snapshot`
- Commit: `7dbcf93f7588baaa34d1e2bdd2b56af2830b1f3e`
- Tag: `v2.0-final`
- Workflow n8n V2: `LkS0RHu9KEbHCR4p` — `active=1`,
  `versionId=bded7b63-112f-4d28-9e0e-cb3d0cb42136`,
  `activeVersionId=ebb043e7-a5c1-48d7-a30a-cc3e02025949`, `triggerCount=7`
  — **sin cambios** en todo FASE 5-8.

## Resultado de tests al momento de esta captura

FASE 8 (captura inicial):

```
pytest tests_v3/ -q      -> 130 passed
pytest parity_v3/ -q     -> 18 passed, 0 skipped
pytest tests/ -q         -> 432 passed  (V2, sin cambios)
```

FASE 9 (cierre — validado manualmente por el usuario):

```
pytest tests_v3/ -q                    -> 147 passed
pytest parity_v3/ -q                   -> 18 passed, 0 skipped
pytest tests/ -q                       -> 432 passed  (V2, sin cambios)
node tests_v3/frontend/test_frontend.js -> 52 passed, 0 failed
```

FASE 10A (esta actualización — conexión de solo lectura a Google Drive real):

```
pytest tests_v3/ -q      -> 162 passed
pytest parity_v3/ -q     -> 18 passed, 0 skipped
pytest tests/ -q         -> 432 passed  (V2, sin cambios)
```

## Workflows exportados

| # | Nombre | Workflow ID | active | versionId | Nodos | SHA256 (del JSON exportado) | Archivo |
|---|---|---|---|---|---|---|---|
| Principal | TIQ · CAJA TIQUIPAYA · V3 DEV | `E114Ntgz3kM8E4T5` | false | `c718748b-20d1-4579-a96c-420856359c21` | 23 | `880191f8501885750f77b7d920bf9446985f5c918c069ec31fc88c1fba25d7ff` | `E114Ntgz3kM8E4T5_principal.json` |
| 01 | TIQ V3 · 01 INGESTA · DEV | `CanZtkmnm0ukAC8c` | false | `fb597976-9c53-4579-8e73-8b4cbb86d9cb` | 13 | `ae926e7e620b4451ddbe40ea8986b757a2a09a795418251debd8e1435a32fb47` | `CanZtkmnm0ukAC8c_01_ingesta.json` |
| 02 | TIQ V3 · 02 MATERIALIZACION · DEV | `j88aiRsPF7g9kxhD` | false | `ef30ce36-3d23-41d7-9646-0d26d724bb32` | 25 | `ad6ee01ca362c06e0f349066093fb3751958f1849b3900405bf984b9eec44ea2` | `j88aiRsPF7g9kxhD_02_materializacion.json` |
| 03 | TIQ V3 · 03 MOTOR PYTHON · DEV | `mIawptMm4aUxbRNU` | false | `1562fe4d-7710-43d4-a59b-2028e08aa4ce` | 7 | `082601e5668364e8e32ee99aaa13fa144bf2cdbb0c6c1a49dc19a3d8a08f9235` | `mIawptMm4aUxbRNU_03_motor.json` |
| 04 | TIQ V3 · 04 CLASIFICACION · DEV | `NQFcE3VD3PsVUNjW` | false | `ed5128ae-f8fd-43cd-8ceb-c18d9402d02b` | 7 | `a0dcedcc04182f1caaa9fc83e6ad8da7ae2c0ac375c182bcc6fa6d94f87d5556` | `NQFcE3VD3PsVUNjW_04_clasificacion.json` |
| 05 | TIQ V3 · 05 REVISION CORRECCION · DEV | `xrnfWsvC4S54jIIY` | false | `14a4c43a-7a72-4cf8-bd33-37298ac37fb5` | 7 | `bd0a16a57934f0faa55322c4a880290523a8aadbbee2016678b03bd6b00b7e88` | `xrnfWsvC4S54jIIY_05_revision.json` |
| 06 | TIQ V3 · 06 PUBLICACION · DEV | `sI3aQmzD0SZTWahF` | false | `65f3d028-a3cb-4c99-a252-4074bf7fc1b5` | 7 | `a6602fa7bbafc601600bea76d26127ea5b80e3690a634c95558db824239f5f9c` | `sI3aQmzD0SZTWahF_06_publicacion.json` |
| 07 | TIQ V3 · 07 AUDITORIA · DEV | `Q81cDev3QSx5Zowc` | false | `dca0894e-b6bc-4240-8290-27886a8b3fc7` | 7 | `bfa253497be3b998104fbbebbd377d3b7477ea2175ed1d1e652300f432408468` | `Q81cDev3QSx5Zowc_07_auditoria.json` |
| 08 | TIQ V3 · BACKEND DEV (webhooks) | `aLs1f3GMqswbaENA` | false | `0d5387ba-ccef-4115-9799-ee0a86f7563e` | 52 | `9a60f7a5c43d17b2a05960e74f2ff902b4016610939d5de67308f261a88e9d34` | `aLs1f3GMqswbaENA_backend_dev.json` |

Los primeros 8 (Principal + 01-07): `active=false`, `activeVersionId=null`,
`triggerCount=0` — ninguno tiene webhooks/triggers productivos registrados.

El noveno workflow (`aLs1f3GMqswbaENA`, backend DEV de FASE 9) es distinto:
tiene 6 nodos `webhook` reales (`/webhook/tiq-v3-dev/{procesar,estado,datos,
revisar,corregir,publicar}`), por lo que `triggerCount=6` incluso estando
`active=false` (ese campo cuenta triggers registrados, no si están
actualmente sirviendo tráfico). Fue **activado temporalmente y por
autorización explícita** durante las pruebas manuales de FASE 9 para que
el usuario pudiera abrir el frontend real en el navegador, y **desactivado
al cierre de FASE 9** (este snapshot) — `active=false`,
`activeVersionId=null`. No requiere ni usa credenciales de n8n; cada nodo
`executeCommand` invoca `v3.dev_api` (Python, única autoridad) sobre rutas
fijas bajo `~/.n8n-files/tiq_v3_manual_dev/` y `~/.n8n-files/tiq_v3_tmp/`
— nunca sobre `poc_n8n_tiquipaya` (datos reales de V2).

## Ejecución manual DEV que valida este estado

- Execution ID: `157` (workflow `E114Ntgz3kM8E4T5`)
- Trigger: `INICIO (DEV — no activar)` (manualTrigger, pinData `{}`)
- Resultado: `status: success`, los 7 módulos ejecutados en orden real
  (01→02→03→04→06→07, 05 correctamente omitido por no haber cierres
  ERROR_REVISAR en el escenario de prueba), verificado también contra los
  archivos físicos escritos en `~/.n8n-files/tiq_v3_manual_dev/dev_workdir/`
  (SAP, resultado, marcador, registro de auditoría).

## Cierre de FASE 9 (esta actualización)

Validado manualmente por el usuario en el frontend real (proxy DEV local,
fuera del repo) antes de esta captura: procesamiento, revisión/corrección
con `identificadores.sfc`/`identificadores.factura` viajando automáticos,
`campos_corregibles_aplicables` filtrado por excepción real (no por
categoría entera), reproceso refrescando datos reales (nunca resultados
de revisión obsoletos), publicación idempotente sin duplicar SAP/
resultado/marcador ni inflar el historial, y el tema visual claro UNIVALLE
(guindo/dorado/marfil) aprobado. Batería completa verde en el momento de
este cierre (ver sección de tests arriba). El backend DEV
(`aLs1f3GMqswbaENA`) quedó desactivado (paso 1 de este cierre).

## FASE 10A — conexión de solo lectura a Google Drive real (esta actualización)

**Objetivo:** conectar V3 al Drive real de Caja Tiquipaya en modo SOLO
LECTURA (sin procesar aún ningún cierre real, sin MOTOR PYTHON, sin
publicar). Se agregó `source_mode` (`fixture` | `drive_readonly`) a los
subworkflows 01 INGESTA y 02 MATERIALIZACION; en `drive_readonly` ambos
usan la credencial `Google Drive account` (id `aoEcEAFQQ38XcwZg`, ya
existente en n8n — la MISMA que usa V2, reutilizada sin duplicar, sin
exponer el secreto) únicamente con operaciones de lectura: `fileFolder`
`search` y `file` `download` (ver `tests_v3/test_drive_readonly_safety.py`,
que verifica programáticamente que ningún nodo Google Drive de estos dos
workflows usa una operación de escritura).

**DEBT-001 cerrado** (ver `v3/TECHNICAL_DEBT.md`): el subworkflow 01
INGESTA ya no reimplementa REGLA G en JavaScript — se agregó CLI a
`v3/ingesta.py` (`python3 -m v3.ingesta`, mismo patrón Execute-Command que
el módulo 02) y se eliminaron los nodos Code `GENERAR - Rango y nombres
esperados` / `APLICAR - Busqueda exacta (REGLA G)`. Python es ahora la
única autoridad para REGLA G en ambos modos.

**Carpeta real de entrada:** `00_ENTRADA_CIERRES`, folder ID
`1ntneoE3MI-25FyPXUymXEvIJmnaZWyJ1` (misma referencia que usa V2, ID
tomado por lectura directa de los nodos `googleDrive` de `LkS0RHu9KEbHCR4p`
— nunca modificado). Root de maestros mensuales: `17ErHuUwCkRW750NiSvjjv69778IyEflS`.
Plantilla SAP (archivo fijo): `1RUH99XheyDx0z88SA_YFt3kgWrvbLc9Z`. Carpeta
de marcadores: `1i8wXRM-2yiH5N3SPOEd4eEqZnizCeCGu`.

**Inventario real obtenido (ejecución `246`, workflow `CanZtkmnm0ukAC8c`,
rango 2026-09-01..2026-09-30, `source_mode=drive_readonly`):**

| Archivo real en Drive | fileId | Tamaño | modifiedTime | Fecha reconocida |
|---|---|---|---|---|
| CIERRE 10-09-2026.xlsm | `1R9e4ZnuRShw2byVQD0CSfDhhkj4i3-ns` | 57375 B | 2026-09-11T20:18:58.840Z | 2026-09-10 → **ENCONTRADO** |
| CIERRE 11-09-2026.xlsm | `10MkXa2cdJ-FJx-S-W0cVHpSToL3LOltr` | 56371 B | 2026-09-12T14:27:07.014Z | 2026-09-11 → **ENCONTRADO** |

Las 28 fechas restantes de septiembre 2026 → `SIN_ARCHIVO` (0 coincidencias
exactas; ninguna es AMBIGUA). REGLA G resolvió correctamente cada fecha
contra el listado COMPLETO de la carpeta (nunca un query por nombre),
confirmando que 10 y 11 nunca se confunden entre sí ni con ninguna otra.

**Maestro/plantilla/markers localizados y descargados como COPIA (ejecución
`249`, workflow `j88aiRsPF7g9kxhD`, `cierres_ingesta=[]` a propósito — sin
tocar ningún cierre diario):**
- Maestro real: carpeta mensual `2026-09` (id `1U0HBoAsiDZy8Dqr3zEHa8_YfS5XcoMab`)
  → archivo `MACROS SEPTIEMBRE.xlsm` (id `1UZdibCEZY3aNtfFmUrBfqGE1mRYlLNUL`).
- Plantilla SAP real: `Plantilla SAP maestra.xlsx` (id fijo, sin búsqueda).
- Marcadores reales: 31 archivos `PROCESADO_<SHA256>.json` listados y
  descargados.
- Resultado de `v3.materializacion` (Python, sin cambios): `{"resultado":
  "OK", "cierres": []}` — maestro/plantilla/markers quedaron `MATERIALIZADO`
  vía `shutil.copyfile` desde las copias reales, cero cierres diarios
  tocados.

**Rutas de las COPIAS DEV** (todas bajo `~/.n8n-files/tiq_v3_real_readonly_dev/`,
la ÚNICA ruta de escritura permitida en esta fase):
```
maestro_origen/MACROS SEPTIEMBRE.xlsm
plantilla_origen/Plantilla SAP maestra.xlsx
markers_origen/PROCESADO_<...>.json  (31 archivos)
cierres_origen/  (vacío a propósito)
dev_workdir/{maestro,plantilla,markers,cierres}/  (copia final de v3.materializacion)
```

**Evidencia Drive antes/después = sin cambios:** se relistó
`00_ENTRADA_CIERRES` (ejecución `250`) tras las descargas y se comparó
contra la ejecución `246`: mismos 2 archivos, mismo `id`, mismo `size`,
mismo `md5Checksum`/`sha256Checksum`, mismo `version` y `modifiedTime` —
ningún byte, nombre, ubicación ni metadato cambió. Ninguna operación de
escritura (move/update/delete/upload/create) se ejecutó en ningún momento
(ver `tests_v3/test_drive_readonly_safety.py`).

**Gaps encontrados:**
- Solo hay 2 cierres reales disponibles en `00_ENTRADA_CIERRES` a la fecha
  de esta prueba (10 y 11 de septiembre 2026) — el resto del mes está
  `SIN_ARCHIVO` genuinamente (carpeta real, no un límite de la prueba).
- Autenticación de los endpoints (`RISK-001`, ya documentado desde FASE 9)
  sigue pendiente antes de exponer esto fuera de un entorno DEV controlado
  — no cambia con esta fase (solo lectura, sin nuevos endpoints HTTP).
- El nodo Merge (`SINCRONIZAR - Esperar 4 ramas reales`) fue necesario tras
  descubrir que 4 conexiones directas al mismo nodo Code NO esperan a que
  todas las ramas paralelas terminen en n8n (cada conexión dispara una
  corrida independiente) — corregido antes de la prueba real exitosa (ver
  historial de versiones del workflow `j88aiRsPF7g9kxhD`).

**No se ejecutó el módulo 03 MOTOR PYTHON ni ningún paso posterior sobre
estos archivos reales; no se publicó nada.** El usuario elegirá qué cierre
real (10 o 11 de septiembre 2026, o uno futuro) usar para la primera
prueba COMPLETA.

## Qué NO incluye este snapshot

- `~/.n8n/database.sqlite` (contiene credenciales cifradas de la instancia).
- `~/.n8n-files/tiq_v3_manual_dev/` y `~/.n8n-files/tiq_v3_tmp/` (fixtures,
  lotes y outputs DEV de las ejecuciones manuales — regenerables con
  `tests/xlsx_fixtures.py`, no versionados).
- `/tmp/dev_proxy_server.py` — proxy DEV local usado solo para servir el
  frontend y evitar CORS durante las pruebas manuales en el navegador; es
  infraestructura de conveniencia local, no parte de V3, nunca estuvo en
  el repo.
- `node_modules/` de `tests_v3/frontend/` (dependencias de prueba jsdom,
  instaladas ad-hoc para correr la batería y luego removidas).
- Archivos temporales, cachés, `__pycache__`, `.pytest_cache`.
- Secretos de ningún tipo. Desde FASE 10A, 2 de los 9 workflows (01 INGESTA,
  02 MATERIALIZACION) SÍ tienen nodos `googleDrive` con una referencia de
  credencial (`{id, name}`, nunca el token/secreto — ver
  `tests_v3/test_drive_readonly_safety.py::test_credenciales_expuestas_son_solo_referencia_sin_secreto`);
  los otros 7 siguen sin ningún nodo de credenciales
  (`Code`/`executeCommand`/`readWriteFile`/`extractFromFile`/
  `executeWorkflow`/`webhook`/`respondToWebhook`).
