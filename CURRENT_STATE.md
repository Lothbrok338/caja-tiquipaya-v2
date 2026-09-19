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
| `cajas-gabo-shadow` | `36c7e2fa-4060-4008-89a0-43f86c9b0e45` | conectado a `migration/railway-shadow`; ver estado de deploy abajo |
| `Postgres` | `c9c4d214-d602-41f8-91d7-ee7a82a3adec` | ya existía, online, volumen persistente, privado — no se tocó |

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

**No medido todavía.** `get-service-metrics` de Railway requiere que el servicio lleve
tiempo corriendo con tráfico real; en el momento de escribir esto el primer deploy
recién se está construyendo. Pendiente actualizar esta sección una vez el servicio esté
en marcha.

## Pendientes (honesto, en orden)

1. Confirmar que el deploy actual de `cajas-gabo-shadow` termina `SUCCESS` (build con
   `node:22-bookworm-slim` + `npm install -g n8n`, tras dos builds fallidos previos por
   incompatibilidad con la imagen base `n8nio/n8n` — ver commits 2 y 3 de la lista de arriba).
2. Generar el dominio público del servicio.
3. `bash scripts/import_workflows_railway.sh` dentro del contenedor.
4. Reconectar a mano la credencial OAuth2 de Google Drive en la UI de n8n de Railway.
5. Activar los 7 workflows importados.
6. Ejecutar la prueba sombra de paridad contra el cierre 10/09/2026 y completar la
   sección "Paridad" de este documento con el resultado real.
7. Medir consumo real (`get-service-metrics`) tras un rato de uso normal.
8. Confirmar `N8N_ENCRYPTION_KEY`/credenciales sobreviven un redeploy (Postgres ya
   persiste esto, pero conviene verificarlo en vivo una vez).

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
