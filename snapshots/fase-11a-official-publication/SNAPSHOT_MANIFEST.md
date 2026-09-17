# SNAPSHOT_MANIFEST.md — FASE 11A · flujo de publicación oficial (checkpoint)

Fecha de captura: **2026-09-17** (checkpoint diferido de la sesión del
2026-09-15, completado en esta sesión).

Este snapshot congela el estado de los 3 workflows n8n creados/modificados
durante FASE 11A (11A.1 publicación oficial reentrante, 11A.2 ingesta Drive
real + publication_mode + preflight, 11A.3 modo oficial sin fallback
local). **No contiene secretos**: cada archivo referencia la credencial
`Google Drive account` (`aoEcEAFQQ38XcwZg`) solo como `{id, name}` — nunca
el token/secreto, que n8n no expone vía API bajo ninguna circunstancia.

Los archivos `*.json` de esta carpeta son **resúmenes estructurales**
(metadatos, grafo de conexiones completo, resumen de propósito por nodo,
carpetas/credenciales usadas) en vez del export crudo nodo-por-nodo de n8n:
la herramienta de escritura de archivos de esta sesión tuvo problemas con
el JSON crudo del backend DEV (64 nodos, muy extenso). Para el JSON crudo
completo de cualquiera de los 3, usar `get_workflow_details(workflowId=...)`
vía el MCP de n8n — los IDs están en la tabla de abajo.

## Workflows de este snapshot

| # | Nombre | Workflow ID | active | versionId | Nodos | Archivo |
|---|---|---|---|---|---|---|
| 1 | TIQ V3 · BACKEND DEV (webhooks) | `aLs1f3GMqswbaENA` | false | `e2b48658-61ae-43e7-ba3f-ec10fd153817` | 64 | `aLs1f3GMqswbaENA_backend_dev.json` |
| 2 | TIQ V3 · 06B PUBLICACION OFICIAL · DRIVE | `wcgxNei3duWfMDp1` | false | `c8c6b42a-dceb-49a1-8161-4087693851e1` | 31 | `wcgxNei3duWfMDp1_06b_publicacion_oficial.json` |
| 3 | TIQ V3 · PREFLIGHT OFICIAL (solo lectura) | `sJVgoBRpBntc96vf` | false | `000214de-f942-4b18-a7fd-295cfd1d393f` | 12 | `sJVgoBRpBntc96vf_preflight_oficial.json` |

Los 3 workflows están `active=false`. Ninguno fue activado durante FASE 11A.

## Workflow reemplazado (archivado, no referenciado)

`PQocEfOB00Bxvy0p` — primera versión de 06B (FASE 11A, no reentrante).
Reemplazada por `wcgxNei3duWfMDp1` (FASE 11A.1) por no ser segura ante
reintento parcial. Archivada vía `archive_workflow`; verificado que ningún
nodo activo (backend DEV, subworkflows 01-07, frontend, snapshots) la
referencia — solo queda mencionada en un comentario de documentación en
`tests_v3/n8n_publicacion_oficial/logic_reference.js`.

## Referencia a V2 (oráculo, congelado)

- Workflow n8n V2: `LkS0RHu9KEbHCR4p` — `active=true`, sin cambios en toda
  FASE 5-11A (verificado: `updatedAt` idéntico desde antes de FASE 9).
- Código V2 (motor_tiquipaya.py, pipeline_tiquipaya.py, excel_io.py,
  sap_writer.py, control_asignaciones.py, control_cxc_cxp.py,
  consolidador_mensual.py, run_batch.py, correcciones_tiquipaya.py,
  publicar_cierre.py, aplicar_correccion.py): diff = 0 líneas contra el
  commit de freeze `7dbcf93`.

## Qué cambió en cada sub-fase (resumen)

**FASE 11A.1 — Publicación oficial reentrante (06B):**
Nuevo workflow (`wcgxNei3duWfMDp1`) que sube a Drive lo que
`v3.publicacion` (Módulo 06) ya publicó localmente: busca por nombre
oficial exacto antes de crear SAP/resultado (0→sube, 1→reutiliza,
>1→`ERROR_AMBIGUO_*`), usa el `drive_file_id` de INGESTA como
identificador primario del cierre (verificado contra el nombre actual,
nunca redescubierto por búsqueda como mecanismo principal), detecta si el
cierre ya fue movido en un retry previo, y sube el marker SIEMPRE al
final. Enganchado en la rama `/publicar` del backend DEV vía
`EJECUTAR - 06B Publicacion Oficial Drive` (Execute Workflow, mode=each).

**FASE 11A.2 — Ingesta Drive real + publication_mode + preflight:**
- Corregido un descarte silencioso de `drive_file_id` en
  `v3/materializacion.py` (ya lo calculaba `v3/ingesta.py` desde FASE 10A).
- `/procesar` ahora invoca el subworkflow **ya existente**
  `TIQ V3 · 01 INGESTA · DEV` (`CanZtkmnm0ukAC8c`, `source_mode=drive_readonly`)
  antes de llamar a `v3.dev_api.procesar_lote()`, pasando su resultado como
  `ingesta_precomputada` — mismo Módulo 01, nada reimplementado.
- `GET /estado` expone `publication_mode` (agregado en n8n, no en Python:
  Python no sabe nada de 06B). El frontend lee este campo en vez de decidir
  con una constante propia; badge dinámico "ENTORNO: DEV" / "PUBLICACIÓN:
  OFICIAL".
- Confirmación humana explícita (`window.confirm`) antes de todo
  `POST /publicar`.
- Nuevo workflow de solo lectura `TIQ V3 · PREFLIGHT OFICIAL (solo lectura)`
  (`sJVgoBRpBntc96vf`, 12 nodos, solo operaciones `search`) + ruta mínima
  `GET /preflight` en el backend DEV para poder invocarlo.

**FASE 11A.3 — Modo oficial sin fallback local:**
`v3/dev_api.py::procesar_lote()` gana el parámetro `requiere_ingesta_drive`
(default `False`, preserva el comportamiento DEV/fixture existente). Cuando
es `True` (backend DEV lo envía siempre como `true` en este despliegue,
mismo criterio que `publication_mode='official'`): si la ingesta Drive no
llegó, o algún cierre `ENCONTRADO` no trae `drive_file_id`, se rechaza el
lote entero (`IngestaDriveRequeridaError`, `estado_lote=ERROR`, mensaje
"No se pudo identificar el cierre original en Google Drive. Verifique la
conexión y vuelva a procesar.") **antes** de tocar materialización/motor —
nunca se procesa localmente un cierre cuyo origen en Drive no se pudo
verificar.

## Verificaciones reales de solo lectura (preflight) realizadas en FASE 11A

| Fecha | Ejecución | Resultado |
|---|---|---|
| 2026-09-10 | `272` (2026-09-15) | `apto_para_publicar: true`, sin bloqueadores |
| 2026-09-11 | `274` (2026-09-15) | `apto_para_publicar: true`, sin bloqueadores |
| 2026-09-10 | `276` (2026-09-17, re-verificación) | `apto_para_publicar: true`, sin bloqueadores |

Ninguna de estas ejecuciones escribió, subió, movió ni creó nada en Drive
(el workflow de preflight solo tiene nodos `search`).

## Qué NO incluye este snapshot

- `~/.n8n/database.sqlite` (credenciales cifradas de la instancia).
- El JSON crudo nodo-por-nodo de los 3 workflows (ver nota arriba —
  disponible bajo demanda vía MCP).
- Secretos de ningún tipo.

## Tests al momento de este checkpoint

```
pytest tests_v3/ -q                                          -> 189 passed
pytest parity_v3/ -q                                          -> 18 passed, 0 skipped
pytest tests/ -q                                               -> 432 passed  (V2, sin cambios)
node tests_v3/n8n_publicacion_oficial/test_logic_reference.js -> 12 passed
node tests_v3/frontend/test_frontend.js                        -> 80 passed
```

Ningún cierre real (10/09, 11/09, 12/09) fue procesado, publicado, movido
ni marcado como procesado durante FASE 11A.
