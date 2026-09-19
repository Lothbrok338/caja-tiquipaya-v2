# DEPLOY_RAILWAY.md — Caja Tiquipaya V3 en Railway (entorno SOMBRA/DEV)

> **Esto NO es producción.** Railway (`CAJAS-GABO-DEV` → servicio `cajas-gabo-shadow`) es un
> entorno sombra para demostrar paridad determinística con `v3-dev`. Tiquipaya productivo
> sigue en Codespaces hasta que el auditor cierre septiembre 2026. Este servicio nunca debe
> publicar oficialmente en Drive — ver "Guarda SHADOW MODE" más abajo.

Rama fuente: `v3-dev` (HEAD verificado `fd2eccb`). Rama de migración (la que Railway
realmente despliega): **`migration/railway-shadow`**, creada exactamente sobre ese commit y
con solo los archivos de portabilidad añadidos encima — cero cambios de reglas contables,
cero cambios en `v2/` congelado.

## 1. Por qué `migration/railway-shadow` y no `v3-dev`

`v3-dev` no tiene `Dockerfile` ni `requirements.txt`: Railway no podría construir nada desde
ahí tal cual. Las restricciones del encargo prohíben commitear directamente sobre `v3-dev`.
`migration/railway-shadow` es `v3-dev` + los archivos de portabilidad de este documento,
nunca al revés. El servicio Railway está conectado a esta rama, no a `v3-dev` literal.

## 2. Arquitectura del contenedor

Un solo servicio (`cajas-gabo-shadow`), un solo contenedor, reproduciendo exactamente la
arquitectura del Codespace (`V3_OPEN_MONTH_STATE.md §1`):

```
Internet ── dominio *.up.railway.app ── scripts/serve_v3_frontend.py ($PORT, público)
                                              │  sirve n8n_frontend/v3_control_cierres.html
                                              │  reenvía /webhook/* →
                                              ▼
                                    n8n (localhost:5678, SOLO interno)
                                              │  Execute Command
                                              ▼
                                    python -m v3.dev_api (motor Python, v3/*.py + módulos V2)
```

`Postgres` (servicio ya creado, privado, con volumen persistente) es la base de datos
**interna de n8n** (definiciones de workflow, credenciales cifradas, historial de
ejecuciones) — no almacena datos contables; esos siguen viviendo en los `.xlsx`/`.xlsm`
que Drive y el motor Python intercambian. No se duplica infraestructura: un servicio de
aplicación + el Postgres ya existente, nada más.

## 3. Archivos nuevos/adaptados (todos en `migration/railway-shadow`)

| Archivo | Rol |
|---|---|
| `requirements.txt` | `openpyxl`, `pytest` — únicas dependencias reales (auditado por import en todo el repo) |
| `Dockerfile` | Imagen `node:22-bookworm-slim` (Debian) + `npm install -g n8n` + Python 3 vía `apt-get` (la imagen oficial `n8nio/n8n` no sirve de base: su capa final `n8nio/base` es Alpine sin `apk` ni compilador por diseño — no se le puede instalar Python encima) |
| `.dockerignore` | Excluye `.git`, `node_modules`, caches |
| `railway.json` | Declara build por Dockerfile |
| `scripts/railway_entrypoint.sh` | Arranca n8n (background) + `serve_v3_frontend.py` (foreground, proceso público) |
| `scripts/start_n8n.sh` | Adaptado: detecta Codespaces / Railway / genérico para la URL pública de n8n; soporte Codespaces intacto |
| `scripts/serve_v3_frontend.py` | Adaptado: puerto y origen de n8n desde `PORT`/`TIQ_N8N_ORIGIN`, con el mismo default de antes |
| `v3/shadow_guard.py` | Guarda de entorno SHADOW MODE (ver §5) |
| `v3/dev_api.py` | 2 puntos de enganche de la guarda (`publicar_seleccionados`, `consolidar_publicacion_oficial`) — nada más cambió |
| `scripts/adapt_workflows_for_railway.py` | Genera `snapshots/railway-shadow/*.json` parametrizando rutas hardcodeadas de Codespaces en los 2 workflows que las tenían |
| `snapshots/railway-shadow/*.json` | Copias de los 7 workflows activos, listas para importar en Railway (`snapshots/v3-final/` queda intacto) |
| `scripts/import_workflows_railway.sh` | Importa esos 7 workflows en la instancia n8n del contenedor (manual, una vez) |
| `tests_v3/frontend/test_frontend.js` | Bug de portabilidad corregido: ruta `/workspaces/caja-tiquipaya-v2` hardcodeada → relativa a `__dirname` |

## 4. Qué rutas hardcodeadas de Codespaces se parametrizaron (y por qué es seguro)

Los workflows `BACKEND DEV` (`aLs1f3GMqswbaENA`) y `01 INGESTA` (`CanZtkmnm0ukAC8c`) tenían,
en nodos Execute Command / Code, 3 literales fijos del Codespace real:

- `/workspaces/caja-tiquipaya-v2` (raíz del repo)
- `/workspaces/.venv-caja/bin/python3` (intérprete)
- `/home/codespace/.n8n-files/...` (directorio base de trabajo)

`scripts/adapt_workflows_for_railway.py` los sustituye por expresiones n8n/JS con **el mismo
valor original como fallback exacto** (`$env.TIQ_REPO_ROOT || '/workspaces/caja-tiquipaya-v2'`,
etc.), así que sin las variables nuevas el comportamiento es idéntico al snapshot original.
Es estrictamente portabilidad — no toca ninguna regla contable, ningún cálculo, ningún
módulo `v3/*.py`. Verificado: mismo número de nodos, mismos IDs de nodo, antes y después
(el script lo comprueba con un assert y falla si algo más cambiara). El snapshot fuente
(`snapshots/v3-final/`) nunca se toca; solo se leen copias en `snapshots/railway-shadow/`.

## 5. Guarda SHADOW MODE (bloqueo de publicación oficial)

Variable de entorno: **`TIQ_BLOCK_OFFICIAL_PUBLISH=true`** en el servicio `cajas-gabo-shadow`
(y solo ahí — el resto del sistema, incluido Codespaces, nunca la fija, así que no cambia de
comportamiento en ningún otro lugar).

Implementada en `v3/shadow_guard.py`, la única autoridad de reglas del sistema (Python), con
dos puntos de enganche independientes en `v3/dev_api.py`:

1. **Entrada**: `publicar_seleccionados(..., modo_oficial=True)` lanza
   `PublicacionOficialBloqueadaError` de inmediato si la variable está activa — ningún flag
   de request (`modo_oficial`, `publication_mode`) ni clic de la UI se lo puede saltar.
2. **Confirmación (defensa en profundidad)**: `consolidar_publicacion_oficial()` fuerza la
   evidencia de Drive (`publicados_drive_oficial`) a vacía si la variable está activa, así
   que aunque el guard de entrada se saltara por algún camino no previsto, ningún cierre
   puede terminar en `PUBLICADO_OFICIAL`.

Además, la credencial real de Google Drive (`aoEcEAFQQ38XcwZg`) **no se copia** a esta
instancia de n8n (nunca estuvo en el snapshot — n8n no la expone vía API bajo ninguna
circunstancia): sin OAuth reconectado a mano, 06B no puede escribir en Drive aunque alguien
lo intentara. Es una segunda capa involuntaria pero real, no sustituye a la guarda explícita.

**Lo que sí queda permitido en Railway DEV**: lectura de Drive (para reproducir/procesar
cierres), procesamiento completo del motor Python, generación de SAP/resultado LOCALES. Lo
que queda bloqueado: escritura productiva en Drive, publicación oficial, marcadores
oficiales — un marcador local DEV nunca equivale a publicación oficial (hotfix `fd2eccb`,
sin tocar).

## 6. Variables de entorno del servicio `cajas-gabo-shadow`

Nunca copiar valores reales de credenciales en este archivo ni en el repo. Referencias de
variable (`${{Postgres.X}}`) en vez de secretos pegados.

| Variable | Valor | Notas |
|---|---|---|
| `DB_TYPE` | `postgresdb` | n8n usa Postgres en vez de SQLite |
| `DB_POSTGRESDB_HOST` | `${{Postgres.PGHOST}}` | referencia al servicio Postgres ya creado |
| `DB_POSTGRESDB_PORT` | `${{Postgres.PGPORT}}` | |
| `DB_POSTGRESDB_DATABASE` | `${{Postgres.PGDATABASE}}` | |
| `DB_POSTGRESDB_USER` | `${{Postgres.PGUSER}}` | |
| `DB_POSTGRESDB_PASSWORD` | `${{Postgres.PGPASSWORD}}` | |
| `N8N_ENCRYPTION_KEY` | (generado, secreto, no en este repo) | cifra credenciales guardadas en n8n — sin esto n8n regenera una al azar en cada deploy y pierde credenciales guardadas |
| `TIQ_BLOCK_OFFICIAL_PUBLISH` | `true` | guarda SHADOW MODE — ver §5 |
| `N8N_BLOCK_ENV_ACCESS_IN_NODE` | `false` | los Code/Execute-Command nodes necesitan leer `$env`/`process.env` para `TIQ_REPO_ROOT`/`TIQ_BASE_DIR` |
| `GENERIC_TIMEZONE` | `America/La_Paz` | zona horaria de Tiquipaya, Bolivia |
| `N8N_RUNNERS_ENABLED` | `true` | recomendado por n8n para Code nodes en versiones recientes |

`TIQ_REPO_ROOT`, `TIQ_PYTHON_BIN`, `TIQ_BASE_DIR`, `PORT` ya tienen default correcto en el
`Dockerfile` (`/app`, `/usr/bin/python3`, `/app/dev_workdir`, `8090`) — no hace falta
repetirlos en Railway salvo que se quiera cambiar alguno.

## 7. Cómo arrancar (primera vez)

1. Verificar que el servicio `cajas-gabo-shadow` está conectado a
   `Lothbrok338/caja-tiquipaya-v2` rama `migration/railway-shadow` (Railway construye y
   despliega automáticamente al conectar/pushear).
2. Fijar las variables de la tabla §6 (`set-variables` / UI de Railway).
3. Esperar el primer deploy sano (`environment-status` / logs).
4. Generar dominio público del servicio (`generate-domain`) si no existe aún.
5. Ejecutar **una vez** `bash scripts/import_workflows_railway.sh` dentro del contenedor
   (`railway ssh -s cajas-gabo-shadow` o `railway run -s cajas-gabo-shadow -- bash scripts/import_workflows_railway.sh`,
   con la Railway CLI autenticada en tu máquina) para importar los 7 workflows activos.
   Esto no se pudo ejecutar desde la sesión que preparó esta migración: no tuvo acceso de
   shell al contenedor ni salida de red hacia el dominio desplegado — ver `CURRENT_STATE.md §Pendientes`.
6. En la UI de n8n (`https://<dominio>`, ruta `/` es n8n mismo si se accede directo al
   puerto 5678 vía túnel, pero el uso normal es la interfaz V3 en la raíz del dominio
   público): reconectar la credencial OAuth2 "Google Drive account" y activar los 7
   workflows importados. Paso manual deliberado — no se puede automatizar sin exponer
   secretos.
7. Confirmar `GET /webhook/tiq-v3-dev/estado` responde y muestra `publication_mode` según
   corresponda.

## 8. Cómo probar

- Suites Python: `pip install -r requirements.txt && pytest tests/ tests_v3/ parity_v3/ -q`
- Suites JS n8n: `node tests_v3/n8n_<carpeta>/test_*.js` (o `test_logic_reference.js`)
- Frontend: `cd tests_v3/frontend && npm install && npm test`
- Prueba sombra end-to-end: reprocesar un cierre diario ya conocido (p. ej. 10/09/2026) desde
  la interfaz Railway con `TIQ_BLOCK_OFFICIAL_PUBLISH=true`, comparar contra el resultado
  real ya validado en `V3_OPEN_MONTH_STATE.md §6` (estado, partidas, debe, haber, diferencia,
  cuentas, asignaciones, fechas valor, excepciones, SAP). Ver CURRENT_STATE.md §"Paridad" para
  el estado real de este paso (requiere credencial Drive reconectada a mano — pendiente).

## 9. Cómo restaurar / rollback

- El servicio Railway es prescindible: se puede borrar y recrear desde cero sin afectar
  `v3-dev`, `main`, Drive ni Codespaces — nada de este entorno es fuente de verdad.
- Para revertir código: `migration/railway-shadow` es una rama normal; borrar el servicio
  Railway no toca git. Para volver a un estado limpio, reconectar el servicio a un commit
  anterior de `migration/railway-shadow` o recrearlo desde `v3-dev`.
- El volumen de Postgres es del servicio `Postgres` (no de `cajas-gabo-shadow`): borrar y
  recrear `cajas-gabo-shadow` NO borra el historial de n8n a menos que también se borre el
  volumen explícitamente.

## 10. Qué NO ejecutar nunca en este entorno

- No pulsar "PUBLICAR" esperando que escriba en Drive oficial (está bloqueado por diseño,
  ver §5) — si alguna vez lo permite, es un bug de la guarda, no un comportamiento esperado.
- No mover ni tocar archivos en las carpetas de Drive productivas listadas en
  `V3_OPEN_MONTH_STATE.md §5`.
- No cerrar CONTROL 1 ni CONTROL 3 desde este entorno.
- No copiar la credencial OAuth2 real de Drive al repo ni a variables de entorno en texto
  plano fuera del mecanismo de credenciales de n8n.
- No usar este entorno como reemplazo de Codespaces mientras septiembre 2026 siga abierto.
