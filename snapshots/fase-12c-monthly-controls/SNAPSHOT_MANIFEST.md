# SNAPSHOT_MANIFEST.md — FASE 12C · rutas n8n de cierre mensual (GLOBAL/CONTROL 1/CONTROL 3)

Fecha de captura: **2026-09-17**.

Este snapshot congela el estado de `TIQ V3 · BACKEND DEV (webhooks)`
(`aLs1f3GMqswbaENA`) después de FASE 12C: se agregaron 3 rutas nuevas
(`/global`, `/control1`, `/control3`) que exponen por HTTP las funciones
`generar_global`, `ejecutar_control1` y `ejecutar_control3` de
`v3/dev_api.py` (agregadas en FASE 12, sin cambios en esta fase). El
snapshot previo de referencia es `snapshots/fase-11a-official-publication/`
(64 nodos, sin las 3 rutas mensuales); este documento describe únicamente
el incremento de FASE 12C.

**No contiene secretos**: ninguno de los 21 nodos nuevos usa credenciales
(son `webhook`, `code`, `executeCommand`, `readWriteFile`,
`extractFromFile`, `respondToWebhook` — el mismo patrón sin credenciales ya
usado por `/revisar`, `/corregir`, `/datos`). Verificado con grep sobre el
export crudo: cero coincidencias de `credentials`, `apikey`, `token`,
`secret`, `password`, `clientSecret`.

## Workflow de este snapshot

| Nombre | Workflow ID | active | versionId | Nodos (antes → después) | Archivo |
|---|---|---|---|---|---|
| TIQ V3 · BACKEND DEV (webhooks) | `aLs1f3GMqswbaENA` | false | `80045cb2-1933-4617-b04a-41934c85ef1b` | 64 → 85 | `aLs1f3GMqswbaENA_backend_dev.json` |

El workflow permanece `active=false`. **No fue activado en ningún momento
durante FASE 12C** — las pruebas de los 3 endpoints nuevos se hicieron con
`execute_workflow` en modo manual (dispara un trigger específico sin
publicar/activar el workflow), no con activación real.

## Rutas nuevas agregadas (FASE 12C)

Cada ruta sigue EXACTAMENTE el mismo patrón de 7 nodos que las rutas
preexistentes (`/revisar`, `/corregir`, `/datos`): `Webhook → CONSTRUIR
payload (Code) → ESCRIBIR input (Execute Command, base64) → EJECUTAR
<accion> (Python, Execute Command) → LEER resultado (readWriteFile) →
INTERPRETAR resultado (extractFromFile) → RESPONDER (respondToWebhook)`.

| Endpoint | Payload | Comando Python ejecutado |
|---|---|---|
| `POST /webhook/tiq-v3-dev/global` | `{anio, mes}` | `python3 -m v3.dev_api --accion generar_global` |
| `POST /webhook/tiq-v3-dev/control1` | `{anio, mes}` | `python3 -m v3.dev_api --accion ejecutar_control1` |
| `POST /webhook/tiq-v3-dev/control3` | `{anio, mes}` | `python3 -m v3.dev_api --accion ejecutar_control3` |

`base_dir_dev` y (para `/global`) `ruta_plantilla_origen` son constantes
fijas del lado servidor dentro del nodo Code, igual que en `/procesar` — el
navegador solo envía `anio`/`mes`. Cero lógica contable en los nodos Code:
solo empaquetan el payload; toda decisión de negocio vive en
`v3/dev_api.py` / `v3/auditoria.py` (FASE 12, sin cambios en FASE 12C).

Ninguna ruta diaria (`/procesar`, `/publicar`, `/revisar`, `/corregir`,
`/datos`, `/estado`, `/preflight`) fue modificada — las 3 rutas nuevas son
ramas completamente independientes desde su propio nodo Webhook, sin
ninguna conexión entrante o saliente hacia las ramas diarias existentes
(verificado leyendo el grafo `connections` completo tras el cambio).

## Validación / manejo de errores

No se agregó validación adicional de `anio`/`mes` en los nodos Code: se
mantiene el mismo patrón que el resto del backend DEV, donde
`v3.dev_api.main()` envuelve toda la ejecución en un único `try/except` que
siempre devuelve JSON limpio (`{"resultado":"ERROR","codigo":<tipo de
excepción>,"mensaje":<detalle>}`) sin crashear ni exponer un stack trace.
Probado explícitamente con `mes=13` → `{"resultado":"ERROR","codigo":
"KeyError","mensaje":"13"}`.

## Pruebas realizadas (FASE 12C)

Todas usando el periodo **1900-01** (año/mes fuera de rango real, sin
ningún SAP ni GLOBAL existente para ese periodo) para garantizar que
ninguna prueba tocara datos reales de producción:

- `execute_workflow` (modo manual) → `WEBHOOK global` con `{anio:1900,
  mes:1}`: respuesta `estado:"ERROR_REVISAR"`,
  `blockers:["SIN_SAP_PARA_CONSOLIDAR"]`, `ruta_global_generado:null` — no
  se generó ningún archivo GLOBAL real. El único archivo de auditoría
  (`RESULTADO_GLOBAL_TIQ_ENERO_1900.json`) que sí se escribió como
  evidencia técnica del intento fue eliminado al finalizar la prueba.
- `WEBHOOK control1` con `{anio:1900, mes:1}`: respuesta
  `estado:"ERROR_TECNICO"`, `problemas:["GLOBAL_NO_ENCONTRADO"]` (correcto:
  no existe GLOBAL para ese periodo).
- `WEBHOOK control3` con `{anio:1900, mes:1}`: mismo resultado
  (`GLOBAL_NO_ENCONTRADO`).
- `WEBHOOK global` con `{anio:1900, mes:13}`: error controlado de mes
  inválido, JSON limpio.
- Suite completa: `pytest tests_v3/ -q` (203 passed), `pytest parity_v3/ -q`
  (18 passed), `pytest tests/ -q` (432 passed, V2 intacto), `node
  tests_v3/frontend/test_frontend.js` (96 passed).

En ningún momento se ejecutó GLOBAL/CONTROL 1/CONTROL 3 contra SAP reales,
se escribió a Drive, ni se activó el workflow en producción.

## Referencia a V2 y a FASE 12

- Python de GLOBAL/CONTROL 1/CONTROL 3 (`generar_global`,
  `ejecutar_control1`, `ejecutar_control3` en `v3/dev_api.py`;
  `generar_global_mensual`, `ejecutar_control1_mensual`,
  `ejecutar_control3_mensual` en `v3/auditoria.py`) fue implementado y
  probado en **FASE 12** (commit `feat: add V3 monthly global and controls
  interface`) y **no se modificó en FASE 12C** — esta fase solo agrega el
  transporte HTTP (n8n) sobre esa interfaz ya existente.
- V2 (`consolidador_mensual.py`, `control_asignaciones.py`,
  `control_cxc_cxp.py`) permanece sin cambios; las funciones mensuales de
  V3 delegan en ellos tal cual.
