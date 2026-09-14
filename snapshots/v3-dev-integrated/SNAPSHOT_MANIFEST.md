# SNAPSHOT_MANIFEST.md — TIQ V3 DEV integrada (post-FASE 8 + FASE 9)

Fecha de captura inicial: **2026-09-14T04:29:44Z** (FASE 8, 8 workflows)
Fecha de actualización: **2026-09-14T11:29:00Z** (FASE 9, +1 workflow: backend DEV)

Este snapshot congela el estado de los 9 workflows de Caja Tiquipaya V3
tras el cierre de FASE 9 (frontend real conectado a un backend DEV vía
`v3/dev_api.py` + `n8n_frontend/v3_control_cierres.html`, validado
manualmente por el usuario: procesamiento, revisión/corrección con
identificadores automáticos, campos corregibles filtrados por excepción,
reproceso sin datos stale, publicación idempotente sin inflar historial, y
tema visual claro UNIVALLE). Los 9 workflows están `active=false`; ninguno
usa Drive/SAP/marcadores productivos. **No contiene credenciales ni
secretos** — cada JSON es exactamente el objeto workflow devuelto por
`get_workflow_details`, sin el bloque `scopes`/`canExecute`/`triggerInfo`
(metadata de lectura de la API, no parte del workflow en sí); se verificó
explícitamente que ningún nodo de los 9 workflows tiene el campo
`credentials`.

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

FASE 9 (cierre, esta actualización — validado manualmente por el usuario):

```
pytest tests_v3/ -q                    -> 147 passed
pytest parity_v3/ -q                   -> 18 passed, 0 skipped
pytest tests/ -q                       -> 432 passed  (V2, sin cambios)
node tests_v3/frontend/test_frontend.js -> 52 passed, 0 failed
```

## Workflows exportados

| # | Nombre | Workflow ID | active | versionId | Nodos | SHA256 (del JSON exportado) | Archivo |
|---|---|---|---|---|---|---|---|
| Principal | TIQ · CAJA TIQUIPAYA · V3 DEV | `E114Ntgz3kM8E4T5` | false | `c718748b-20d1-4579-a96c-420856359c21` | 23 | `880191f8501885750f77b7d920bf9446985f5c918c069ec31fc88c1fba25d7ff` | `E114Ntgz3kM8E4T5_principal.json` |
| 01 | TIQ V3 · 01 INGESTA · DEV | `CanZtkmnm0ukAC8c` | false | `c9ed2605-64b0-47db-b3bf-eaae4d970f6f` | 4 | `91dda7a8bfef3a302e651b2f0dd089a0036b6323c4b1f4f036d9b4bc98a37f97` | `CanZtkmnm0ukAC8c_01_ingesta.json` |
| 02 | TIQ V3 · 02 MATERIALIZACION · DEV | `j88aiRsPF7g9kxhD` | false | `0a5880dd-4bc6-4a44-b53a-c4241536ed8b` | 7 | `02ad4d718fcc8b326a1bf45cfa271e1a4b21df8190d57ca92f204bb571fff9f1` | `j88aiRsPF7g9kxhD_02_materializacion.json` |
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
- Credenciales o secretos de ningún tipo (ninguno de los 9 workflows usa
  credenciales — todos son `Code`/`executeCommand`/`readWriteFile`/
  `extractFromFile`/`executeWorkflow`/`webhook`/`respondToWebhook`, sin
  nodos de credenciales; verificado programáticamente al exportar).
