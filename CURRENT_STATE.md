# CURRENT_STATE.md — Migración Railway sombra, estado real al 2026-09-19

> Generado durante la migración. Refleja lo que se verificó realmente en esta sesión —
> nada aquí es una proyección de lo que "debería" pasar. Ver §"Pendientes" para lo que
> todavía no se pudo verificar en vivo.

## HEAD / rama

- Fuente de verdad: `v3-dev` @ `fd2eccbf7e4f9a510fbd5c30cce14039c341485e` (verificado exacto
  contra `origin/v3-dev` al empezar; ver §1 de este documento en el historial de la sesión).
- Rama de migración (la que Railway realmente construye): `migration/railway-shadow`,
  creada sobre ese mismo commit exacto. Commits añadidos encima (solo portabilidad, ver
  `DEPLOY_RAILWAY.md §3`):
  1. `feat: portabilidad Railway para CAJAS GABO V3 (entorno sombra)`
  2. `fix: instalar Python detectando apt-get/apk en vez de asumir Alpine`
  3. `fix: base Debian + n8n via npm (la imagen n8nio/n8n no tiene gestor de paquetes)`
- `v3-dev` y `main` no se tocaron: cero commits, cero push a ninguna de las dos.

## Servicios Railway

| Servicio | ID | Estado |
|---|---|---|
| Proyecto `CAJAS-GABO-DEV` | `97144abb-71b7-4484-87c9-f2647529017c` | — |
| Entorno `production` | `79d1b49f-028b-4229-a1b9-f89ba44331ac` | — |
| `cajas-gabo-shadow` | `36c7e2fa-4060-4008-89a0-43f86c9b0e45` | **online**, 1/1 réplica corriendo, 0 crashes — deploy `0ce876e2` SUCCESS |
| `Postgres` | `c9c4d214-d602-41f8-91d7-ee7a82a3adec` | ya existía, online, volumen persistente, privado — no se tocó |

**URL del entorno sombra:** `https://cajas-gabo-shadow-production.up.railway.app` (dominio Railway generado, `railwayManaged`, certificado automático).

Confirmado en los logs de arranque reales (deploy `0ce876e2-6353-47c7-be0b-5fe6bd795596`):
- `[railway_entrypoint] TIQ_BLOCK_OFFICIAL_PUBLISH=true` — la guarda SHADOW está activa.
- `GET / HTTP/1.1" 200` — el proxy del frontend (`serve_v3_frontend.py`) sirve la interfaz.
- `n8n ready on ::, port 5678` y `Editor is now accessible via: https://cajas-gabo-shadow-production.up.railway.app`
  — `start_n8n.sh` detectó `RAILWAY_PUBLIC_DOMAIN` correctamente y configuró la URL pública sin
  necesitar `CODESPACE_NAME`.
- `Version: 2.35.7`, `Building workflow dependency index... Processed 0 draft workflows, 0 published workflows`
  — instancia nueva y limpia, ningún workflow importado todavía (pendiente, ver abajo).
- Sin errores de conexión a Postgres (n8n no habría llegado a "ready" si `DB_POSTGRESDB_*` fuera incorrecto).
- Nota menor no bloqueante: n8n advierte que `N8N_RUNNERS_ENABLED` ya no hace falta fijarla
  (deprecación propia de n8n) — se puede quitar en una limpieza futura, no afecta nada hoy.

## Variables fijadas en `cajas-gabo-shadow`

`DB_TYPE`, `DB_POSTGRESDB_HOST/PORT/DATABASE/USER/PASSWORD` (referencias `${{Postgres.*}}`,
sin secretos pegados), `N8N_ENCRYPTION_KEY` (generado localmente con `openssl rand -hex 32`,
no impreso en este repo ni en el chat), `TIQ_BLOCK_OFFICIAL_PUBLISH=true`,
`N8N_BLOCK_ENV_ACCESS_IN_NODE=false`, `GENERIC_TIMEZONE=America/La_Paz`,
`N8N_RUNNERS_ENABLED=true`. Detalle y justificación de cada una en `DEPLOY_RAILWAY.md §6`.

## Cómo arrancar / probar / restaurar

Ver `DEPLOY_RAILWAY.md §7-9`.

## Qué NO ejecutar

Ver `DEPLOY_RAILWAY.md §10`. Resumen: nunca publicación oficial, nunca tocar Drive
productivo, nunca cerrar CONTROL 1/3 desde este entorno.

## Resultado de las suites (corridas en esta sesión, sobre `migration/railway-shadow`)

| Suite | Resultado |
|---|---|
| V2 (`tests/`) | 432 passed, 0 failed |
| V3 + parity (`tests_v3/`, `parity_v3/`, sin subcarpetas n8n_*/frontend) | 315 passed, 0 failed |
| Frontend (`tests_v3/frontend`, jsdom) | 134 passed, 0 failed |
| n8n control1 (`tests_v3/n8n_control1_fuente_drive`) | 32 passed, 0 failed |
| n8n control3 (`tests_v3/n8n_control3_fuente_drive`) | 19 passed, 0 failed |
| n8n global (`tests_v3/n8n_global_fuente_drive`) | 15 passed, 0 failed |
| n8n hotfix diario (`tests_v3/n8n_hotfix_diario`) | 12 passed, 0 failed |
| n8n publicación mensual (`tests_v3/n8n_publicacion_mensual`) | 11 passed, 0 failed |
| n8n publicación oficial (`tests_v3/n8n_publicacion_oficial`) | 12 passed, 0 failed |

Todos coinciden exactamente con los últimos resultados registrados en el repo (315/432/134/
32/15/19/12) — **cero regresiones** tras los cambios de portabilidad. Corridas de forma
local en el entorno de esta sesión (Python 3.11 + openpyxl 3.1.5 + pytest 9.1.1; Node 22),
no dentro del contenedor Railway todavía — eso es parte de los pendientes.

## Paridad (prueba sombra con un cierre conocido)

**No ejecutada todavía — pendiente, no un resultado.** Requiere: (1) el servicio Railway
desplegado y sano, (2) los 7 workflows importados (`scripts/import_workflows_railway.sh`),
(3) la credencial OAuth2 de Google Drive reconectada A MANO en la instancia de n8n de
Railway (paso deliberadamente manual — nunca se copia ni expone ese secreto desde esta
sesión ni desde el repo). Sin esos tres pasos no hay forma honesta de comparar un
resultado real contra Railway; cualquier número aquí antes de eso sería inventado. El
cierre de referencia sugerido es 10/09/2026 (ya validado en real, ver
`V3_OPEN_MONTH_STATE.md §6`: estado `PUBLICADO_OFICIAL`, `SAP_TIQ_10-09-2026.xlsx`,
`RESULTADO_TIQ_10-09-2026.json`, sin duplicados).

## Consumo / recursos observados

Medido con `get-service-metrics` sobre la última hora (incluye el build + arranque, no un
uso normal sostenido — la muestra es corta a propósito porque el servicio recién arrancó):

| Métrica | Actual | Promedio | Máximo |
|---|---|---|---|
| CPU | 0.016 vCPU | 0.010 vCPU | 0.367 vCPU (pico de arranque) |
| Memoria | 0.499 GB | 0.090 GB | 1.093 GB (pico de arranque) |

En reposo, sin tráfico, el consumo es bajo (n8n + el proxy Python, nada más). El pico de
~1.1 GB corresponde al arranque de n8n (carga de ~2200 paquetes npm en memoria); conviene
revisar de nuevo tras la importación de workflows y un uso real con Drive.

## Pendientes (honesto, en orden — lo único que falta)

Esta sesión no tiene acceso de shell al contenedor de Railway (no hay una herramienta de
`exec`/`ssh` en el MCP de Railway disponible aquí) ni salida de red hacia el dominio
desplegado (`cajas-gabo-shadow-production.up.railway.app` — el proxy de egreso de este
entorno la rechaza por política de la organización). Por eso lo que sigue requiere que el
usuario (o una sesión con esos accesos) lo ejecute:

1. `bash scripts/import_workflows_railway.sh` — necesita correr DENTRO del contenedor
   (`railway ssh -s cajas-gabo-shadow` o `railway run`, con la CLI de Railway autenticada).
   Importa los 7 workflows activos desde `snapshots/railway-shadow/*.json`.
2. Reconectar a mano la credencial OAuth2 "Google Drive account" en la UI de n8n
   (`https://cajas-gabo-shadow-production.up.railway.app`) — nunca automatizable sin
   exponer el secreto.
3. Activar (toggle ON) los 7 workflows importados.
4. Ejecutar la prueba sombra de paridad contra el cierre 10/09/2026 y completar la
   sección "Paridad" de este documento con el resultado real.
5. Volver a medir consumo (`get-service-metrics`) tras un rato de uso real con Drive.
6. Opcional: quitar `N8N_RUNNERS_ENABLED` (deprecada, ver arriba) en una limpieza menor.
7. Opcional: en el dashboard de Railway, el campo "Branch" del servicio quedó como cambio
   pendiente sin confirmar (`accept-deploy` no se ejecutó — quedó sin aprobar en esta
   sesión); no bloquea nada porque los deploys ya corren sobre `migration/railway-shadow`
   en la práctica, pero conviene confirmarlo desde el dashboard para que quede prolijo.

Todo lo demás — build, deploy, Postgres, guarda SHADOW MODE, dominio público, suites de
test — está verificado en vivo, no proyectado.

## Confirmación

- No se ejecutó ninguna publicación oficial, ni desde Python ni desde n8n, en ningún
  entorno, durante esta migración.
- No se movió ni modificó ningún archivo en Drive productivo.
- No se cerró CONTROL 1 ni CONTROL 3.
- `v3-dev` y `main` permanecen exactamente como estaban (`fd2eccb` y `8a5c6e8`
  respectivamente) — cero commits nuevos en ninguna de las dos.
- V2 (`v2/`, módulos raíz `motor_tiquipaya.py`/`control_asignaciones.py`/etc.) no se
  modificó: los únicos archivos Python tocados fueron `v3/dev_api.py` (2 líneas de
  enganche a la guarda) y el nuevo `v3/shadow_guard.py`.
