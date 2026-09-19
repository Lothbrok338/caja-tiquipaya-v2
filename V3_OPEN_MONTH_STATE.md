# V3_OPEN_MONTH_STATE.md — Caja Tiquipaya V3 · CHECKPOINT "MES ABIERTO"

Fecha: 2026-09-19 · Rama: `v3-dev`.

**Esto NO es el estado final.** Septiembre 2026 sigue **abierto**. No existe `V3_FINAL_STATE.md` ni el tag `v3.0-final`
(se crean al final, ver "Pendiente para el cierre definitivo"). Snapshot de workflows: `snapshots/v3-final/` (nombre histórico) +
`SNAPSHOT_MANIFEST.md` (sección "CHECKPOINT V3 — MES ABIERTO").

---

## 1. Arquitectura actual

```
Navegador ── n8n_frontend/v3_control_cierres.html  (puerto 8090, scripts/serve_v3_frontend.py: estático + proxy /webhook/* → n8n:5678)
   │  POST/GET /webhook/tiq-v3-dev/*
   ▼
n8n · TIQ V3 · BACKEND DEV (webhooks)  (aLs1f3GMqswbaENA, 149 nodos)
   │  Webhook → Code (payload) → Execute Command (python -m v3.dev_api --accion …) → Respond
   │  Drive = fuente de verdad (nodos googleDrive + subworkflows 01, 06B, 07C, 07D, 07E, PREFLIGHT)
   ▼
Python (única autoridad de reglas):  v3/*.py  →  reutiliza SIN CAMBIOS los módulos V2 (motor_tiquipaya, control_asignaciones, control_cxc_cxp, consolidador_mensual…)
```

Principios: **Drive oficial = fuente de verdad; local = materialización temporal limpia** (`dev_workdir/<x>_entrada/<YYYY-MM>/`, se borra
antes de cada corrida). n8n solo arma payloads, materializa/publica en Drive y decide QUÉ publicar; toda regla contable vive en Python.
Modo `official` (viene del backend, `publication_mode`) escribe en Drive; modo `dev` no toca Drive.

## 2. Componentes

| Componente | Archivo / ID | Notas |
|---|---|---|
| Frontend | `n8n_frontend/v3_control_cierres.html` | sirve desde disco: lo que se ve = lo que hay en git |
| Proxy 8090 | `scripts/serve_v3_frontend.py` | `python3 scripts/serve_v3_frontend.py` (0.0.0.0:8090, sin auth) |
| Arranque n8n | `scripts/start_n8n.sh` | |
| API Python | `v3/dev_api.py` | acciones: procesar/publicar/…, `generar_global`, `preparar_global_entrada`, `preparar_control1_entrada`, `ejecutar_control1`, `preparar_control3_entrada`, `ejecutar_control3` |
| Modos CONTROL 1 | `v3/control1_modos.py` | PRELIMINAR / CERRAR sobre `control_asignaciones.py` (V2 intacto) |
| Modos CONTROL 3 | `v3/control3_modos.py` | PRELIMINAR / CERRAR sobre `control_cxc_cxp.py` (V2 intacto) |
| GLOBAL V3 | `v3/consolidador_mensual_v3.py` | acepta `SAP_DD-MM-YYYY.xlsx` y `SAP_TIQ_DD-MM-YYYY.xlsx` |
| Tests | `tests_v3/`, `parity_v3/`, `tests/` (V2), `tests_v3/frontend`, `tests_v3/n8n_*` | ver §7 |

## 3. Workflows n8n (V3)

Activos (7): BACKEND DEV `aLs1f3GMqswbaENA` (v `def3df19`, 162 nodos, hotfix diario 2026-09-19) · 01 INGESTA `CanZtkmnm0ukAC8c` (`fb597976`) · 06B PUBLICACION OFICIAL
`wcgxNei3duWfMDp1` (`88f1df1c`) · PREFLIGHT `sJVgoBRpBntc96vf` (`000214de`) · 07C descargar-si-existe `fn7lLjHsiMd48DGK` (`d65ae76c`) ·
07D publicar crear/actualizar `HhuQCVP2oCubavzY` (`42599278`) · 07E buscar-o-crear carpeta `Lht5xRinJ9nJpHCW` (`9bb4a9af`).
Inactivos (7, línea exploratoria FASE 1-8, no están en el camino productivo): principal `E114Ntgz3kM8E4T5`, 02–07 DEV.
V2 `LkS0RHu9KEbHCR4p`: activo, congelado, no tocar.

## 4. Endpoints (`/webhook/tiq-v3-dev/…`)

| Ruta | Método | Qué hace |
|---|---|---|
| `estado` | GET | salud + `publication_mode` (dev/official) |
| `procesar` | POST | ingesta Drive + precheck maestro + procesamiento del rango |
| `datos`, `revisar`, `corregir` | GET/POST | lectura, revisión y corrección autorizada de cierres |
| `publicar` | POST | 06B: SAP + resultado a Drive, mueve cierre a Procesados, marker (idempotente/reentrante) |
| `preflight` | GET | verificación de solo lectura antes de publicar |
| `global` | POST | genera `SAP_GLOBAL_TIQ_<MES>_<AÑO>.xlsx` desde la carpeta SAP oficial (regenerable mientras el periodo esté abierto; se bloquea con `PERIODO_CERRADO_CONTROL1` si CONTROL 1 ya cerró) |
| `control1` | POST | Auditoría de Asignaciones: `modo_control1` = `preliminar` (defecto) / `cerrar` + `confirmacion_cierre=true` |
| `control3` | POST | Auditoría CxC / CxP: `modo_control3` = `preliminar` (defecto) / `cerrar` + `confirmacion_cierre=true` |

Cerrar sin `confirmacion_cierre=true` → `ERROR_CONFIRMACION_CIERRE_REQUERIDA`. El cierre nunca se infiere.

## 5. Rutas de Drive (mi unidad · producción)

| Carpeta | ID | Contenido |
|---|---|---|
| `00_ENTRADA_CIERRES` | `1ntneoE3MI-25FyPXUymXEvIJmnaZWyJ1` | cierres `.xlsm` pendientes |
| SAP oficial (sept.) | `1mid4gUHnCmZbISlsAYMwWta3RudTSE13` | SAP diarios del mes (fuente del GLOBAL) |
| `RESULTADOS` | `16Z7Uhf-NgiZ6YuqWLnReaIozRIiOg5HO` | `RESULTADO_TIQ_<fecha>.json` |
| `03_PROCESADOS` | `1BkNC6lnonMM7YeWDKck-TM8WTyY2BJJP` | cierres ya publicados |
| Markers (`MARCADORES_PROCESAMIENTO`) | `1i8wXRM-2yiH5N3SPOEd4eEqZnizCeCGu` | `PROCESADO_<sha256>.json` |
| `05_CONTROLES` | `1yZI_OCuYOAILg8E6uT-bAmkQtW-XB-qB` | **maestros**: `HISTORICO_ASIGNACIONES.csv`, `HISTORICO_CXC_CXP.csv`, `HISTORICO_CXC_CXP_PERIODOS.json` |
| `05_CONTROLES/GLOBAL` | `1KREzDpgptWRwuArA1qYco49rplOEeeNU` | `SAP_GLOBAL_TIQ_<MES>_<AÑO>.xlsx` (uno por mes) |
| `05_CONTROLES/CONTROL_1_ASIGNACIONES/<YYYY-MM>` | raíz `1oOcwIgq_9uU9eRLV7z36zBjdBS-hBlRk` | revisión `REVISION_ASIGNACIONES_<PERIODO>.xlsx`, detalle `CONTROL_ASIGNACIONES_<PERIODO>.json`, (al cierre) snapshot del histórico |
| `05_CONTROLES/CONTROL_3_CXC_CXP/<YYYY-MM>` | raíz `15IYQDdpyBwrZTNS-qU8VZa47sVz1ziV_` | reporte `CONTROL_CXC_CXP_<PERIODO>.xlsx/.json`, (al cierre) snapshots de ambos maestros |

Los históricos por periodo NUNCA son fuente maestra; solo evidencia. Nada mensual suelto en la raíz de `05_CONTROLES`.

## 6. Estado por módulo

**Validado EN REAL (Drive/n8n reales, clic del auditor):**

- **Cierre diario 10/09/2026**: `PUBLICADO_OFICIAL`; `SAP_TIQ_10-09-2026.xlsx` y `RESULTADO_TIQ_10-09-2026.json` publicados; cierre movido a
  `03_PROCESADOS`; marker creado; sin duplicados (PREFLIGHT posterior). Incluye lectura Drive real con `drive_file_id` exacto, precheck
  maestro, revisión/corrección, idempotencia/retry (06B reentrante) y confirmación humana en la interfaz.
- **GLOBAL septiembre**: fuente = carpeta SAP oficial de Drive; 9 SAP (01,02,03,04,05,07,08,09,10); 257 partidas; débito = crédito = 1,199,527.12;
  diferencia 0.00; C10 = `DB`; un único GLOBAL oficial en `05_CONTROLES/GLOBAL`; residuos locales ignorados; regenerable mientras el periodo esté abierto.
- **Auditoría de Asignaciones — PRELIMINAR** (ejecución 446): histórico maestro en la raíz (441 filas, solo agosto) **sin cambios**; GLOBAL **sin cambios**;
  3 alertas de septiembre con decisiones del auditor conservadas (2 CORRECTA por mismo depósito, 1 CORRECTA FORTALEZA); estado `PRELIMINAR_LISTO_PARA_CERRAR`;
  septiembre abierto. Copia de agosto preservada en `CONTROL_1_ASIGNACIONES/2026-08/`.
- **Auditoría CxC / CxP — PRELIMINAR** (ejecución 452): `PRELIMINAR_OK`; 5 llaves: 4 ABIERTO normales (CAF, FORTALEZA en 110201003; FORTALEZA y GASTOS ADM.
  en 110201004) y **1 REVISAR: CxP EMPRESAS (210103003) / POSGRADO AGOSTO, saldo −1.000** ("saldo negativo sin apertura previa registrada"); maestros de la raíz
  **sin cambios** (`HISTORICO_CXC_CXP.csv` 4 filas AGOSTO_2026; `PERIODOS.json` solo AGOSTO_2026 APLICADO); reporte publicado en `CONTROL_3_CXC_CXP/2026-09/`;
  `periodo_cerrado=false`. Los maestros de CxC/CxP de la raíz son el histórico real (no se migró nada).

**Validado SOLO por tests (nunca ejecutado en real):**

- **CONTROL 1 — CIERRE DEFINITIVO**: exige confirmación explícita y todas las alertas resueltas (`INCORRECTA` exige `ASIGNACION_CORRECTA`); corrige la columna R del
  GLOBAL solo si hay correcciones autorizadas; actualiza el histórico maestro; publica snapshot en la carpeta del periodo; segundo cierre → `YA_CERRADO`;
  tras el cierre `/global` se bloquea (`PERIODO_CERRADO_CONTROL1`).
- **CONTROL 3 — CIERRE DEFINITIVO**: exige confirmación; verificación en seco y luego V2 (PENDIENTE → histórico → APLICADO); publica reporte, snapshots, histórico y, al final,
  el libro de periodos; segundo cierre → `YA_CERRADO`; recupera una publicación interrumpida sin reacumular. REVISAR/partidas sin asignación se informan como advertencias y **no bloquean**
  (decisión de diseño: CONTROL 3 no tiene flujo de "revisión pendiente"; se resuelven con `OBSERVACION_AUDITOR`).
- Bloqueo de regeneración de GLOBAL tras el cierre de CONTROL 1 (guardia con histórico descargado de Drive).

**Solo visual (ya hecho):** ajuste de alineación de los botones del cierre mensual (`0e42474`) — CSS + un `div` contenedor; sin cambios de lógica, ids, handlers ni endpoints.

**Hotfix diario (2026-09-19):** `/procesar` descarga el MACROS oficial y los cierres de Drive en cada corrida (`procesar_entrada/<lote>/`) y el precheck exige cobertura de MACROS
sobre las fechas de depósito; en modo oficial "Publicado" solo con 06B (`PUBLICADO_OFICIAL`). Detalle en `snapshots/v3-final/SNAPSHOT_MANIFEST.md` (sección HOTFIX DIARIO).

## 7. Tests de referencia (últimos resultados registrados)

`tests_v3` + `parity_v3`: 315 · tests V2 (`tests/`): 432 · frontend (jsdom): 134 · JS n8n: control1 32, global 15, control3 19, publicación mensual 11, publicación oficial 12, hotfix diario 12.
Comandos: `/workspaces/.venv-caja/bin/python3 -m pytest tests_v3 parity_v3 -q` · `python -m pytest tests -q` · `node tests_v3/<dir>/test_nodos.js` · `cd tests_v3/frontend && node test_frontend.js`.
(El Python correcto es el venv `/workspaces/.venv-caja`; el `python3` del sistema no trae `pytest`/`openpyxl`.)

## 8. QUÉ NO DEBE EJECUTARSE TODAVÍA

- **NO** pulsar `CERRAR AUDITORÍA DE ASIGNACIONES` ni `CERRAR AUDITORÍA CxC / CxP` hasta terminar septiembre: cierran el periodo y escriben los maestros (irreversible; no hay reapertura).
- **NO** regenerar GLOBAL "por si acaso" después del cierre de CONTROL 1 (queda bloqueado) ni antes de tener todos los SAP de septiembre (sí es seguro mientras el mes está abierto, pero hay que volver a correr los preliminares).
- **NO** crear `V3_FINAL_STATE.md` ni el tag `v3.0-final` todavía. **NO** V4.
- **NO** tocar V2 (`LkS0RHu9KEbHCR4p`), `control_cxc_cxp.py`, `control_asignaciones.py`, `consolidador_mensual.py`.
- Los preliminares (`AUDITORÍA DE ASIGNACIONES`, `AUDITORÍA CxC / CxP`) y `GENERAR GLOBAL` con el mes abierto SÍ son repetibles y seguros.

## 9. Cómo retomar (pasos exactos)

1. `git status` (debe estar limpio en `v3-dev`) y `git log -3`.
2. n8n arriba: `curl -s localhost:5678/healthz`; si no, `bash scripts/start_n8n.sh`. Verificar BACKEND DEV `active=true` versión `def3df19`, y V2 activo.
3. Proxy: `python3 scripts/serve_v3_frontend.py` → `http://localhost:8090/v3_control_cierres.html`.
4. Si la interfaz da error de Drive: reconectar la credencial "Google Drive account" en n8n (ya ocurrió una vez con "needs to be reconnected").
5. Continuar con "Pendiente para el cierre definitivo".

## 10. PENDIENTE PARA CIERRE DEFINITIVO

1. Terminar septiembre (procesar/publicar los cierres diarios que faltan; ya están 01–05, 07–10).
2. Regenerar GLOBAL completo (`GENERAR GLOBAL`, mes aún abierto).
3. Ejecutar Auditoría de Asignaciones **preliminar** sobre el GLOBAL completo.
4. Validar alertas nuevas (Excel de revisión en `CONTROL_1_ASIGNACIONES/2026-09/`; `INCORRECTA` exige `ASIGNACION_CORRECTA`).
5. **CERRAR** Auditoría de Asignaciones (actualiza histórico maestro y protege el GLOBAL).
6. Ejecutar Auditoría CxC / CxP **preliminar** (sobre el GLOBAL ya definitivo/corregido).
7. Revisar la llave REVISAR (CxP EMPRESAS / POSGRADO AGOSTO −1.000) y las demás; registrar observaciones del auditor (p. ej. `CERRADO MANUALMENTE …`) en el Excel del reporte.
8. **CERRAR** Auditoría CxC / CxP (actualiza `HISTORICO_CXC_CXP.csv` y `HISTORICO_CXC_CXP_PERIODOS.json`).
9. Verificar los históricos finales en Drive (441 + filas de septiembre en asignaciones; CxC/CxP con `SEPTIEMBRE_2026` APLICADO; snapshots en las carpetas del periodo).
10. Crear `V3_FINAL_STATE.md`.
11. Snapshot final (`snapshots/…`) y manifest.
12. Tag `v3.0-final`.

Deuda técnica menor: el orden de publicación de los maestros no es atómico entre archivos (mitigado: el libro de periodos siempre va al final y hay recuperación);
el proxy 8090 no tiene autenticación (uso interno); las carpetas SAP oficiales por periodo están fijas en el nodo `RESOLVER` (solo `2026-09` configurado).
