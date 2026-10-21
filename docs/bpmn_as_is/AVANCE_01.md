# BPMN AS-IS CAJAS GABO V3 — AVANCE 01 (parcial)

Fecha: 2026-10-21 · Fuente: `migration/railway-shadow` @ `29fdda3a8ccabdb0f5053a26c8b5608fc4a2780c` (export de solo lectura; sin checkout ni cambios en esa rama).
Estado: **en curso**. Esto NO es el entregable final: los BPMN todavía no están generados.

## 1. Qué está terminado

| Entregable | Archivo | Estado |
|---|---|---|
| C. Inventario de workflows (mecánico) | `inventario/inventario_workflows.xlsx` (hojas Workflows, Nodos, Accion->Funcion) y `inventario/inventario_workflows.csv` | Hecho. Faltan columnas interpretativas (entradas detalladas, errores, idempotencia, efectos), que se completarán con los análisis. |
| D. Lista completa de nodos (base de la matriz nodo→BPMN) | `inventario/nodos_n8n.csv`: 317 nodos, con tipo, conexiones de entrada/salida, acción Python, operación Drive y condiciones IF | Hecho. La columna BPMN dice `PENDIENTE` hasta que existan los diagramas. |
| F. Mapa de dependencias (primera versión) | `inventario/dependencias_workflows.mmd` / `.svg` / `.png` | Hecho, versión mecánica. |
| Herramientas | generador DSL→BPMN 2.0 con DI, validador XSD OMG, render bpmn-js→SVG/PNG, verificador de cobertura nodo→BPMN | Probadas con un caso de prueba: XSD OK, render sin advertencias, subprocesos con drill-down. |

## 2. Inventario de workflows (snapshots `snapshots/railway-shadow/`)

| Workflow | ID | Nodos | Disparador | Lo invoca | Python | Escrituras en Drive |
|---|---|---|---|---|---|---|
| TIQ V3 · BACKEND DEV (webhooks) | `aLs1f3GMqswbaENA` | 196 | 10 webhooks `/webhook/tiq-v3-dev/{procesar, estado, datos, revisar, corregir, publicar, preflight, global, control1, control3}` | Navegador vía proxy | 18 acciones `v3.dev_api` | ninguna directa (solo búsquedas y descargas; escribe vía 06B/07D/07E) |
| TIQ V3 · 06B PUBLICACION OFICIAL · DRIVE | `wcgxNei3duWfMDp1` | 54 | subworkflow | BACKEND (`EJECUTAR - 06B Publicacion Oficial Drive`) | — | upload ×4, update ×3, move ×1, deleteFile ×2 |
| TIQ V3 · 01 INGESTA · DEV | `CanZtkmnm0ukAC8c` | 13 | subworkflow + manual trigger | BACKEND (`EJECUTAR - 01 INGESTA (Drive real)`) | `python -m v3.ingesta` | ninguna |
| TIQ V3 · PREFLIGHT OFICIAL (solo lectura) | `sJVgoBRpBntc96vf` | 13 | subworkflow | BACKEND | — | ninguna (9 búsquedas) |
| TIQ V3 · 07D PUBLICAR ARCHIVO OFICIAL (crear o actualizar) | `HhuQCVP2oCubavzY` | 13 | subworkflow | BACKEND ×3 (GLOBAL, CONTROL1, CONTROL3) | — | upload ×1, update ×1 |
| TIQ V3 · 07E BUSCAR O CREAR CARPETA OFICIAL | `Lht5xRinJ9nJpHCW` | 8 | subworkflow | BACKEND ×3 | — | folder.create ×1 |
| TIQ V3 · 07C DESCARGAR ARCHIVO OFICIAL SI EXISTE | `fn7lLjHsiMd48DGK` | 8 | subworkflow | **nadie** en railway-shadow | — | ninguna |
| TIQ V3 · AVANCE CAJA · DEV (solo lectura) | `AvncCajaRO7v3Dev` | 12 | webhook `GET /webhook/tiq-v3-dev/avance` | Navegador | `--accion avance_caja` | ninguna |

Total: 8 workflows y 317 nodos. El flag `active` es el del JSON; **el estado en vivo de n8n no está verificado** (no hay acceso a la instancia).

## 3. Hallazgos AS-IS hasta ahora (verificados en código/JSON)

1. **07C está huérfano.** Ningún nodo de los 8 workflows lo invoca. Sí lo invocaba el BACKEND de `fase-12d`, y se sigue sincronizando en el deploy. [CODIGO]
2. **06B no usa 07C/07D/07E.** Hace sus 21 operaciones de Drive con nodos propios. 07D/07E solo los usa el BACKEND para GLOBAL y controles. Hay dos implementaciones de "subir/actualizar archivo oficial". [CODIGO]
3. **Snapshots editados sin cambiar `versionId`.** El BACKEND de `railway-shadow` tiene 196 nodos y el de `v3-final` 169, ambos con `versionId=def3df19`. Lo mismo ocurre con 06B (54 vs 53), 07D (13 vs 12) y 07E (8 vs 7). El `versionId` del JSON no prueba qué versión corre en n8n. [CODIGO]
4. **El patrón de invocación a Python es uniforme.** Cada acción hace Code (arma payload) → Execute Command (`printf base64 > input.json`) → Execute Command (`python -m v3.dev_api --accion X --input … --output …`) → lectura del JSON de salida. Muchos comandos terminan en `; true`: el código de salida de Python se ignora y el resultado se decide leyendo el archivo de salida. [CODIGO]
5. **Rutas de Codespaces cableadas en la ruta `/control1` (preliminar, en verificación).** En el snapshot `railway-shadow`, el nodo `CONSTRUIR payload control1` arma el comando con `cd /workspaces/caja-tiquipaya-v2` y `/workspaces/.venv-caja/bin/python3`, sin las variables `TIQ_REPO_ROOT` / `TIQ_PYTHON_BIN` que usan las otras rutas. El contenedor Railway usa `/app` y `/usr/bin/python3`, así que en Railway `/control1` probablemente no ejecuta Python. El `; true` final oculta el fallo. El código está confirmado [CODIGO]; su efecto en ejecución no está verificado [NO-VERIF].
6. **Acciones Python sin invocador en n8n.** 6 de las 21 acciones del CLI `v3.dev_api` no aparecen como acción fija en ningún nodo:
   - `ejecutar_control1`, `ejecutar_control3`, `preparar_control1_entrada`, `preparar_control3_entrada`: es la línea por caja anterior a los controles institucionales.
   - `ejecutar_control1_institucional` y `corregir_control1_institucional`: sí se invocan, pero dentro de un comando armado dinámicamente en el Code node de control1 (ver punto 5).
7. **Arquitectura de procesos confirmada en código.**
   - Un solo contenedor contiene el proxy Python (Basic Auth), n8n bajo demanda y Python CLI.
   - n8n guarda su estado en un Postgres externo.
   - Google Drive es la fuente de verdad y lo manejan solo los nodos de n8n.
   - El estado de cada lote vive en `dev_workdir/lotes/LOTE_<id>.json`, en el disco del contenedor.
   - Que ese estado sea efímero ante redeploy/sleep se está verificando.
8. **Test que falla en la rama.** `parity_v3/test_parity_scenarios.py::test_PARITY_001_contract_001_alquileres_excluidos`: al fixture le falta la clave `facturas_anuladas` y el motor devuelve `ERROR`. Los docs de la rama dicen 0 fallos. [TEST, ejecutado aquí]

## 4. En curso
- Lectura profunda con 9 analistas en paralelo:
  - BACKEND por grupos de rutas: procesar/estado/revisión; publicar/preflight/rectificación; global/controles y nodos huérfanos.
  - 06B y sus auxiliares.
  - Ingesta/precheck.
  - Motor contable/SAP.
  - Estado, publicación y rectificación en Python.
  - GLOBAL y controles.
  - Infraestructura, frontend y procesamiento múltiple.
  - Cada uno documenta los 15 puntos por workflow y agrupa todos los nodos por etapa.
  - Corren de 2 en 2 porque el contenedor tiene 4 CPU.
- Después:
  1. Modelado (Nivel 0, BPMN 01–09, técnico de arranque/sync y Nivel 2 por grupo de rutas y por subworkflow).
  2. Verificación adversarial contra el código.
  3. Matriz nodo→BPMN completa (meta: 317/317), documento explicativo y arquitectura de componentes.

## 5. Limitaciones declaradas
- El informe de Astra (`Informe_Preliminar_Caja_Ayacucho (1).md`) **no se recibió** en la sesión; se contrastará cuando esté disponible.
- Sin acceso a Railway ni a n8n en vivo: todo "estado en ejecución" proviene de la documentación del repo (`CURRENT_STATE.md`, `V3_OPEN_MONTH_STATE.md`, manifests). Se etiqueta como `[EJEC-DOC]`, nunca como observado por nosotros.
