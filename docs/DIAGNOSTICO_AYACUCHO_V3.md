# Diagnóstico CORREGIDO — Caja Ayacucho sobre el sistema V3 real

Fecha: 2026-10-21 · Reemplaza a `DIAGNOSTICO_AYACUCHO.md` (V2, obsoleto).
Fuente inspeccionada, **solo lectura**: `origin/migration/railway-shadow` @ `29fdda3` (extraída con `git archive` a un directorio temporal; no se hizo checkout, commit ni push sobre esa rama).

## 1. Qué auditó mal la primera vez (causa)
- Auditoría anterior: `/home/user/caja-tiquipaya-v2`, rama local = copia de **`origin/main` @ `8a5c6e8`** (el clon de la sesión solo traía `main`). Eso es V2 congelado: 378 tests.
- Error mío: concluí "no existe n8n / Railway / América / rectificación" sin listar las ramas remotas. Debí hacer `git fetch` y revisar ramas antes de afirmar ausencias.
- Relación de ramas (commits por delante de `main`): `v3-dev` +25 · `feature/caja-america` +70 · **`migration/railway-shadow` +93** (contiene a `v3-dev`: 68 commits por delante de ella).

## 2. Sistema real (V3 en `migration/railway-shadow`)
```
Navegador ── n8n_frontend/v3_control_cierres.html
   │ Basic Auth (TIQ_AUTH_USERNAME/PASSWORD) en scripts/serve_v3_frontend.py (puerto $PORT)
   ▼  /webhook/tiq-v3-dev/*  →  n8n (localhost:5678, arranca bajo demanda, se apaga a los 300 s)
n8n BACKEND DEV (aLs1f3GMqswbaENA) + 06B publicación oficial, PREFLIGHT, 01 ingesta, 07C/D/E (Drive)
   │ Execute Command:  python -m v3.dev_api --accion X --input in.json --output out.json
   ▼
Python (única autoridad): v3/*.py  →  reutiliza V2 sin cambios (motor, sap_writer, consolidador, control_*)
Drive = fuente de verdad (nodos googleDrive de n8n). Python NUNCA toca Drive.
```
- **Railway:** un contenedor Node 22 + Python (`Dockerfile`), n8n 2.35.7 vía npm, Postgres para n8n, `railway.json` (healthcheck `/healthz`), workflows sincronizados una vez por deploy (`scripts/sync_workflows_railway.sh`, preDeploy) desde `snapshots/railway-shadow/*.json`.
- **Guarda de entorno:** `TIQ_BLOCK_OFFICIAL_PUBLISH=true` (`v3/shadow_guard.py`) bloquea publicación oficial. `CURRENT_STATE.md` (19-sep) lo documenta en `true` para `cajas-gabo-shadow`. **No sé el valor actual en Railway**: confírmalo.
- **Cajas:** `config_cajas.py` define `CajaConfig` (`sfcs`, `cuenta_haber`, `nombre_sap`, `atc_caja`, `prefijo_archivo`, `reserva_posgrado`, `cuenta_reserva_posgrado`) con `TIQUIPAYA` (default absoluto) y `AMERICA` (SFC107/108, 110101003, reserva POSGRADO 210103003, prefijo `AME`). `resolver_caja()` falla cerrado ante códigos desconocidos. La caja del lote es **inmutable** (`lote["caja"]`).
- **Rectificación (existe):** `aplicar_correccion.py`/`correcciones_tiquipaya.py` (V2, reproceso con corrección autorizada), `publicar_seleccionados(..., rectificacion=True)` solo con `modo_oficial`, guard de periodo cerrado por CONTROL 1, estado `CIERRE_YA_PUBLICADO_REQUIERE_RECTIFICACION` → `RECTIFICADO_OFICIAL`. *Aviso del propio código:* en `v3/publicacion.py` un comentario dice que 06B respondía `RECTIFICACION_NO_IMPLEMENTADA_06B`; los commits posteriores (`2fd0061`, `66e13fe`, `f383201`) la completan. Verificar en vivo.
- **Publicación:** `v3/publicacion.py` (marcador `PROCESADO_<SHA256>` con 4 confirmaciones, idempotente) + 06B en n8n (SAP+RESULTADO a Drive, mueve a 03_PROCESADOS). Estado real validado: cierre 10/09/2026 `PUBLICADO_OFICIAL`.
- **Controles:** CONTROL 1 (asignaciones, revisión humana en Excel, cierre definitivo irreversible), CONTROL 3 (CxC/CxP acumulado), "institucionales" que unifican Tiquipaya+América, GLOBAL mensual por caja, precheck de MACROS, normalización de FECHA DE DEPOSITO (hallazgo real América), `avance_caja`.
- **Endpoints n8n** (`/webhook/tiq-v3-dev/`): `estado`, `procesar`, `datos`, `revisar`, `corregir`, `publicar`, `preflight`, `global`, `control1`, `control3`. Sin auth propia en n8n; la auth es el Basic del proxy.
- **Tests (ejecutados por mí sobre la rama, en Python 3.13):** `tests/` 547 OK · `tests_v3` + `parity_v3` 634 OK, **1 FALLA**, 2 skipped. La falla: `parity_v3/test_parity_scenarios.py::test_PARITY_001_contract_001_alquileres_excluidos` — el cierre sintético del test no trae la clave `facturas_anuladas` y el motor devuelve `ERROR 'facturas_anuladas'`. Es un problema de fixture/deriva, ya existente en la rama; `CURRENT_STATE.md` afirma 0 fallos (contabilizaba 432+315). No lo toqué. Frontend/JS (jsdom, node) no los ejecuté.

## 3. Conclusiones de mi diagnóstico anterior: qué se corrige

| Conclusión anterior | Veredicto |
|---|---|
| "No hay Railway, n8n, América, rectificación" | **Falsa** (auditoría sobre `main`). Todo existe. |
| "378 tests" | Solo V2/`main`. Real: ≥547 (V2) + 634 (V3/parity) + JS. |
| "Motor con Tiquipaya cableado; proponer `CajaConfig`" | **Ya existe** `config_cajas.py` y América lo usa. Ayacucho = **3ª entrada** + puntos de bifurcación, no un refactor. |
| "Reutilizar `procesar_cierre_completo` como endpoint" | Parcial: el punto de entrada real es `v3.dev_api` (lotes: crear → procesar → datos/revisar/corregir → publicar), que ya aplica precheck, normalización, clasificación y caja inmutable. |
| "API sin estado; PA pasa los hashes" | Sigue válido y coincide con el diseño V3 (Drive/almacén externo = verdad, local = materialización temporal). |
| "4 flujos Power Automate" | Se mantiene como punto de partida, pero deben **espejar el contrato de lotes V3**, no el pipeline V2 (ver §5). |
| "Los endpoints n8n no sirven como API" | Matiz: **no sirven para Power Automate+SharePoint** (están atados a nodos googleDrive y a un n8n que despierta en frío ≤60 s), pero **sí sirven para el smoke test** (§4). |
| "Flujo 05 Rectificación sin motor" | **Falsa**: hay motor y 06B. Lo que falta es su equivalente SharePoint. |
| "D3 ¿dónde vive el motor?" | Resuelto: esta rama. |

Lo que SÍ se mantiene: ninguna regla de Ayacucho está documentada en el repo ni hay cierres de ejemplo → **sin cierres reales no se define nada contable**.

## 4. Hallazgo útil para la primera prueba (sin tocar nada)
El proxy ya expone: `GET /healthz` (público, 200 texto plano) y rutas protegidas con **HTTP Basic**. Power Automate lo soporta nativamente en la acción HTTP (Autenticación → Básica). Por tanto el primer ZIP puede apuntar al **servicio existente, solo lectura y sin efectos**:
1. `GET /healthz` → 200 (conectividad, sin credenciales).
2. `GET /oauth-info.html` es público; para probar Basic usar `GET /` (HTML del frontend): 401 sin credenciales, 200 con ellas. No dispara n8n (solo `/webhook/*` lo arranca) ni Drive.
Limitación: no ejercita el motor. Eso corresponde a la API nueva (§5).

## 5. Cómo reutilizar el motor V3 con una API REST para Power Automate (sin afectar las cajas)
**Opción recomendada — servicio Railway NUEVO e independiente (`cajas-gabo-api`), misma base de código, sin n8n:**
- Imagen Python-only (sin Node/n8n, sin Postgres); `uvicorn` + FastAPI que **importa en proceso** las funciones de `v3.dev_api` (`crear_lote_pendiente`, `procesar_lote`, `obtener_datos`, `obtener_detalle_revision`, `aplicar_correccion`, `publicar_seleccionados`, `generar_global`, `ejecutar_control1/3`…). Cero reglas nuevas en la API: solo traduce HTTP↔funciones existentes, igual que hace hoy el nodo Execute Command.
- **No toca:** el servicio `cajas-gabo-shadow`, los workflows n8n, Postgres, credenciales de Drive, ni `main`/`v3-dev`/`migration/railway-shadow`. Se despliega desde una rama nueva derivada de la shadow (la shadow no se modifica).
- `TIQ_BLOCK_OFFICIAL_PUBLISH=true` también en el servicio nuevo mientras duren los ensayos. Su `modo_oficial` en Python solo cubre la guarda; **la escritura "oficial" a SharePoint la haría Power Automate** tras aprobación, no Python (coherente con "Python nunca escribe en Drive").
- Datos: por solicitud, PA envía cierre(s), maestro, plantilla y marcadores existentes; la API usa un `base_dir_dev` temporal por lote, devuelve el JSON de `datos`/`revisar` y los archivos SAP/RESULTADO (base64 o descarga firmada de corta vida). Larga duración: `202 + Location` (la acción HTTP de PA sigue `Location` sola). El `lote_id` ya es el identificador de trabajo; el estado vive en `LOTE_<id>.json` (disco efímero → ver D6).
- Seguridad: clave API (`X-API-Key`) o Basic, comparación en tiempo constante, falla cerrada, `X-Correlation-Id` (ya prototipado).
- Alternativa descartada: llamar los webhooks n8n desde PA → cold start, atados a googleDrive, un solo secreto Basic compartido con humanos.

## 6. Ayacucho sobre el código real
1. Alta de `AYACUCHO` en `config_cajas.py` (SFCs, cuenta HABER, `nombre_sap`, `atc_caja`, `prefijo_archivo`, reserva POSGRADO sí/no) — **valores a confirmar con evidencia**: no los invento.
2. Revisar los ~15 puntos que hoy conocen "america/AME" fuera de `config_cajas.py`: `config_drive_oficial.py` (IDs de Drive por caja → en Ayacucho serían rutas SharePoint, configuración de PA), `v3/control1_institucional.py`, `v3/control3_institucional.py` (unen Tiq+AME con variables fijas `CAJA_AME`, `correcciones_tiq/ame`: **no escalan a 3 cajas sin cambio**), `v3/dev_api.py`, `v3/consolidador_mensual_v3.py`, `v3/normalizacion_fecha_deposito.py`, `v3/precheck_maestro.py`, `v3/motor.py`.
3. Regla de oro ya usada por América: cambios aditivos + tests de que Tiquipaya/América dan salida idéntica.
4. Diferencias de negocio de Ayacucho: **desconocidas** hasta analizar cierres reales (D4).

## 7. Prototipo ya construido: qué se reutiliza
Ruta: rama `claude/charming-pasteur-l1uxy1` (sin cambios, intacta). Verificado: nada colisiona con la rama shadow y sus 13 tests pasan **superpuestos sobre el árbol de la shadow**.

| Pieza | Estado | Uso |
|---|---|---|
| `powerautomate/build_zip.py` (builder determinístico, legacy + solución, validador estático de referencias/parámetros/secretos) + `tests/test_powerautomate_zip.py` | **Reutilizable 100 %**, independiente del backend | Base de TODOS los ZIP futuros |
| `powerautomate/flows/flow00_smoke.py` | Reutilizable con ajuste | Cambiar destino a `/healthz` y `/` con Basic (§4); conservar la versión `X-API-Key` para la API nueva |
| `api_caja/` (FastAPI: health/ping/API key/correlation id/falla cerrada) + `tests/test_api_caja.py` | **Reutilizable como esqueleto** | Se convierte en la capa HTTP de `cajas-gabo-api` (§5); sus tests de auth/correlation se conservan |
| `api_caja/Dockerfile` | Se reemplaza | Hay que basar la imagen nueva en el `Dockerfile` real (sin n8n); su `COPY *.py` era para V2 |
| `docs/DIAGNOSTICO_AYACUCHO.md` | Obsoleto (se conserva como historial con aviso) | — |
| Decisión legacy-vs-solución, parámetros, README clic a clic | Vigentes | — |

Nada de lo construido hay que rehacer; lo que cambia es el **destino** (V3, no V2) y el **modelo de auth**.

## 8. Decisiones pendientes (mínimas)
- **D1** Formato de importación (paquete heredado vs solución) y un ZIP de referencia exportado de tu tenant.
- **D2** ¿Servicio nuevo `cajas-gabo-api` autorizado (en el mismo proyecto Railway o en uno aparte)?
- **D3** Valor actual de `TIQ_BLOCK_OFFICIAL_PUBLISH` y de `TIQ_AUTH_*` en Railway (no necesito los valores, solo si están fijadas).
- **D4** Cierres reales de Ayacucho (copias) + maestro + plantilla; y datos de cuentas/SFC de Ayacucho.
- **D5** Destino de archivos de Ayacucho: SharePoint (¿sitio/biblioteca?) en lugar de Drive.
- **D6** Estado entre llamadas: ¿aceptas API efímera (todo el lote en una sola solicitud/job) o prefieres volumen en Railway?
