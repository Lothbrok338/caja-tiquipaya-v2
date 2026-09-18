# SNAPSHOT_MANIFEST.md — V3 FINAL (cierre formal)

Fecha de captura inicial: **2026-09-17T20:55:26Z**
Última actualización: **2026-09-18T14:10:00Z** — GLOBAL mensual V3 ya
consolida los 9 SAP reales de septiembre 2026 de punta a punta (bug C10
resuelto exclusivamente en V3, sin tocar V2)
(ver §"Cambios posteriores al cierre formal" al final de este archivo).
Commit Git de referencia: **`bd2424b`** (`feat: complete V3 official monthly persistence`, rama `v3-dev`) + `fix: preserve Drive ingesta in official processing` + `fix: finalize official V3 publication path` + `feat: allow monthly GLOBAL regeneration in V3` + `fix: consolidate all monthly SAP files in V3` + `fix: validate daily SA entries in V3 monthly consolidation`

Este snapshot congela el estado de **los 14 workflows n8n de V3** en el momento
del cierre formal, tras validar FASE 12E (E2E mensual completo, sandbox
desechable, sin tocar producción). Cada archivo es el **export crudo
completo** (`workflow` tal cual lo devuelve n8n), no un resumen — se pudo
lograr para todos, incluido el más grande (112 nodos), extrayendo el JSON
directamente del resultado de la herramienta en lugar de reescribirlo a
mano. **No contiene credenciales**: todas las referencias a la credencial
`Google Drive account` son pares `{id, name}` (`aoEcEAFQQ38XcwZg`), nunca
el secreto — n8n no lo expone vía API bajo ninguna circunstancia.
Verificado con grep sobre los 14 archivos: cero coincidencias de
`apikey`/`token`/`secret`/`password`/`clientSecret`/`accessToken`/
`refreshToken`.

## Inventario completo (14 workflows)

| # | Nombre | Workflow ID | Archivo | active | Nodos | SHA256 (archivo completo) |
|---|---|---|---|---|---|---|
| 1 | TIQ · CAJA TIQUIPAYA · V3 DEV (**principal**) | `E114Ntgz3kM8E4T5` | `E114Ntgz3kM8E4T5_principal.json` | false | 23 | `b31b7d269a765429e080e191f24217f5ee283b17cf0baa01b7c8223ad6cf7b25` |
| 2 | TIQ V3 · 01 INGESTA · DEV | `CanZtkmnm0ukAC8c` | `CanZtkmnm0ukAC8c_01_ingesta.json` | false | 13 | `bf9f7837369a68f2e85e9a714e9a72ba5fe41051cf6693335ef28e97f3a962c5` |
| 3 | TIQ V3 · 02 MATERIALIZACION · DEV | `j88aiRsPF7g9kxhD` | `j88aiRsPF7g9kxhD_02_materializacion.json` | false | 25 | `1b123860feb289252d009cf55400406c9ba9af273337e29d8fa487e59abe8230` |
| 4 | TIQ V3 · 03 MOTOR PYTHON · DEV | `mIawptMm4aUxbRNU` | `mIawptMm4aUxbRNU_03_motor.json` | false | 7 | `6b4f26c229304c345fc9520edb68981a242862e9cc6cc6725a8cde1ee54d3c57` |
| 5 | TIQ V3 · 04 CLASIFICACION · DEV | `NQFcE3VD3PsVUNjW` | `NQFcE3VD3PsVUNjW_04_clasificacion.json` | false | 7 | `e7908795a9a1883daf5ef5808dcf1186e9d715ae75cd34dfd429349a5793a723` |
| 6 | TIQ V3 · 05 REVISION CORRECCION · DEV | `xrnfWsvC4S54jIIY` | `xrnfWsvC4S54jIIY_05_revision.json` | false | 7 | `6e81a9ebdc6e724ebdba0bbbf66881f94b5f43fc98c0b63e61c62faf62414ba3` |
| 7 | TIQ V3 · 06 PUBLICACION · DEV | `sI3aQmzD0SZTWahF` | `sI3aQmzD0SZTWahF_06_publicacion.json` | false | 7 | `0e2aaf8eff2488462c52517ffb7f8ee5591689f8c9a4c1601af9c41ade637d2b` |
| 8 | TIQ V3 · 06B PUBLICACION OFICIAL · DRIVE | `wcgxNei3duWfMDp1` | `wcgxNei3duWfMDp1_06b_publicacion_oficial.json` | **true** | 31 | `8c6a63063f6ee4537179bd1c1cdddeb9bc9e3a640ba86406f33f0dfa23c94a4a` |
| 9 | TIQ V3 · 07 AUDITORIA · DEV | `Q81cDev3QSx5Zowc` | `Q81cDev3QSx5Zowc_07_auditoria.json` | false | 7 | `18ed3c9a516483ec481eba17d829d970dc4bed2e48de401588dc1453d1f095ce` |
| 10 | TIQ V3 · 07C DESCARGAR ARCHIVO OFICIAL SI EXISTE · DRIVE | `fn7lLjHsiMd48DGK` | `fn7lLjHsiMd48DGK_07c_descargar_oficial.json` | false | 8 | `2dcda703148d885ac1a7070876b595fb1af6c786e197f2289c96ad9c26fd6714` |
| 11 | TIQ V3 · 07D PUBLICAR ARCHIVO OFICIAL (crear o actualizar) · DRIVE | `HhuQCVP2oCubavzY` | `HhuQCVP2oCubavzY_07d_publicar_oficial.json` | false | 12 | `9f9aab93e4654612e8a1b10005975fac88ecfc793024b51ba0bab9ddbf848f78` |
| 12 | TIQ V3 · 07E BUSCAR O CREAR CARPETA OFICIAL · DRIVE | `Lht5xRinJ9nJpHCW` | `Lht5xRinJ9nJpHCW_07e_buscar_crear_carpeta.json` | false | 7 | `2b331e13b50c40d69eb46c06817b6f5aecdeca8d4a25af408274e11bd74cc15f` |
| 13 | TIQ V3 · PREFLIGHT OFICIAL (solo lectura) | `sJVgoBRpBntc96vf` | `sJVgoBRpBntc96vf_preflight_oficial.json` | false | 12 | `dccdfb3711e06518bce4d73c73acbfaa4a687457212e946d5b85321cb1f782de` |
| 14 | TIQ V3 · BACKEND DEV (webhooks) | `aLs1f3GMqswbaENA` | `aLs1f3GMqswbaENA_backend_dev.json` | **true** | 112 | `bad138256de28b2518f7bb5ed9be117756be8becfffe3c8a2c000997d896bb82` |

**Estado `active` real en n8n al momento de esta actualización (2026-09-18):**
7 workflows están activos — `aLs1f3GMqswbaENA` (BACKEND DEV), `CanZtkmnm0ukAC8c`
(01 INGESTA), `wcgxNei3duWfMDp1` (06B), `sJVgoBRpBntc96vf` (PREFLIGHT),
`fn7lLjHsiMd48DGK` (07C), `HhuQCVP2oCubavzY` (07D), `Lht5xRinJ9nJpHCW` (07E) —
activados para que el auditor pudiera operar el primer cierre oficial real
(10/09/2026) desde la interfaz. Los otros 7 (línea exploratoria FASE 1-8:
`principal` + 02/03/04/05/06/07 · DEV) siguen `active=false`, sin cambios.
**Los archivos de BACKEND DEV y 06B en este snapshot se re-exportaron**
(son los únicos dos cuyo contenido cambió — los fixes de esta sección);
los otros 5 archivos activados conservan el contenido/SHA256 capturado el
2026-09-17 (su lógica no cambió, solo su bandera `active` en n8n, que este
snapshot no vuelve a congelar por no ser parte de lo pedido).

## Dos líneas de trabajo dentro de V3 (aclaración honesta)

Durante el desarrollo de V3 coexisten dos implementaciones, y este
manifiesto las nombra tal cual el usuario las pidió, pero es importante
dejar constancia de cuál es la que realmente opera hoy:

- **Línea real en uso (FASE 9–12E, la que valida `v3_control_cierres.html`
  y todas las pruebas E2E de este proyecto):** un único workflow
  **BACKEND DEV** (`aLs1f3GMqswbaENA`) con rutas `/webhook/tiq-v3-dev/*`
  que invoca `v3/*.py` directamente (Execute Command), y reutiliza como
  subworkflows separados solo **01 INGESTA** (para Drive real de lectura),
  **06B**, **07C**, **07D**, **07E** y **PREFLIGHT** (para Drive real de
  escritura/lectura oficial). Esta es la arquitectura descrita en
  `V3_FINAL_STATE.md`.
- **Línea exploratoria temprana (FASE 1–8, `principal` +
  02/03/04/05/06/07 · DEV):** un workflow separado (`E114Ntgz3kM8E4T5`)
  que encadena subworkflows individuales por módulo (01→02→03→04→05→06→07),
  cada uno invocando su propio `v3/*.py` vía el mismo patrón
  Execute-Command. **02 MATERIALIZACION** y **01 INGESTA** sí tienen
  integración real de Drive de solo lectura (FASE 10A); el resto
  (03/04/05/06/07) son adaptadores Python reales pero **nunca conectados
  a Drive ni al backend webhook real** — quedaron como una ruta de
  pruebas manuales aislada, superada por la línea BACKEND DEV. Se
  incluyen en este snapshot porque el usuario los pidió explícitamente
  por nombre, no porque estén en el camino de ejecución productivo.

## Verificación de integridad

Para verificar que un archivo no fue alterado tras este commit:

```bash
sha256sum -c <(grep -oP '`\K[a-f0-9]{64}(?=`)' SNAPSHOT_MANIFEST.md | \
  paste - <(ls *.json | sort) | awk '{print $1"  "$2}')
```

O individualmente: `sha256sum <archivo>.json` y comparar contra la tabla.

## Referencia a V2

`LkS0RHu9KEbHCR4p` (V2, `active=true`) no forma parte de este snapshot —
V2 permanece congelado desde `7dbcf93` (`release: freeze validated Caja
Tiquipaya V2 baseline`) y no fue tocado en ninguna fase de V3.

## Cambios posteriores al cierre formal (2026-09-18)

**Bug real encontrado en el primer intento de procesamiento oficial**
(disparado por el auditor desde la interfaz, sobre el cierre real
10/09/2026, no un fixture): `/procesar` fallaba siempre con
`IngestaDriveRequeridaError: INGESTA_DRIVE_REQUERIDA`, incluso cuando
`01 INGESTA (Drive real)` sí resolvía el `drive_file_id` correcto.

**Causa:** el nodo `CONSTRUIR payload procesar_lote` leía
`$input.first().json.cierres`, pero el nodo anterior
(`EJECUTAR - 01 INGESTA (Drive real)`) envuelve su salida bajo `.data`
(mismo patrón que todo `INTERPRETAR resultado *` de este backend, vía
`extractFromFile`/`fromJson`). `t.cierres` era siempre `undefined`, así
que `ingesta_precomputada` llegaba a `procesar_lote()` como `null`
**siempre**, sin importar la fecha — el guard `requiere_ingesta_drive`
(FASE 11A.3) disparaba de forma sistemática pese a que Drive sí resolvía
el cierre.

**Fix:** una línea, `t.cierres` → `t.data.cierres`, en
`CONSTRUIR payload procesar_lote`. El guard (`requiere_ingesta_drive:
true`) y el resto del wiring no se tocaron; ninguna lógica contable,
ningún módulo Python, V2 no se tocó.

**Validado en vivo** (10/09/2026, real, vía la interfaz activada):
`drive_file_id: "1R9e4ZnuRShw2byVQD0CSfDhhkj4i3-ns"` llega íntegro hasta
el resultado final de `procesar_lote()`; el cierre queda
`estado_final: "LISTO_PARA_PUBLICAR"`, `diferencia: "0.00"`,
`bloqueadores: 0`, **`publicado: 0`** — nunca se llamó `/publicar`, nunca
se escribió nada oficial en Drive, nunca se movió el cierre ni se creó
marker.

Commit de este fix: `fix: preserve Drive ingesta in official processing`.

### Fix de los 4 IF booleanos de 06B (2026-09-18)

**Bug real encontrado en el primer intento de PUBLICAR oficial** (segundo
bloqueador tras el fix de ingesta, disparado por el auditor desde la
interfaz sobre el mismo cierre real 10/09/2026): `/publicar` fallaba con
`Error in workflow` al invocar el subworkflow `TIQ V3 · 06B PUBLICACION
OFICIAL · DRIVE` (`wcgxNei3duWfMDp1`). Diagnóstico forense (ejecuciones
376, 382/383) confirmó que 06B sí se invocaba y sí ejecutaba sus primeras
búsquedas de solo lectura en Drive, pero moría con `NodeOperationError`
en el primer nodo `IF` booleano que encontraba en su camino — mismo
defecto de plataforma n8n ya visto y corregido en FASE 12D (`IF` con
`conditions.options.typeValidation: "strict"` sobre una condición
`boolean/true` cuya entrada real es un booleano JS genuino, pero que n8n
evalúa igual como error de tipo).

**Fix (en bloque, no reactivo):** se revisaron los 5 nodos `IF` de 06B y
se corrigió `typeValidation` de `"strict"` a `"loose"` únicamente en los
4 que usan el patrón booleano defectuoso: `IF - SAP ya existe en Drive`,
`IF - Resultado ya existe en Drive`, `IF - Cierre encontrado en ENTRADA`,
`IF - Cierre ya esta en PROCESADOS`. `IF - Marker ya existe en Drive` se
dejó intacto (compara `string`/`notEmpty`, no tiene el defecto). Ninguna
expresión, valor esperado, rama, conexión ni orden de publicación se
tocó. Workflow re-publicado inmediatamente tras el cambio
(`activeVersionId` = `versionId` = `88f1df1c-e40e-4d8a-8280-9600a25f864f`).

**Validado estructuralmente antes de publicar de nuevo:** dos ejecuciones
de prueba (`test_workflow`, pin data sintética, cero escrituras reales en
Drive) cubrieron las 8 ramas posibles de los 4 IF corregidos (true/false
en cada uno), ambas `status: success`, sin `NodeOperationError`.

**Validado en producción real** (10/09/2026, mismo cierre, clic real del
auditor en PUBLICAR vía la interfaz): ejecución backend 388 → subworkflow
06B ejecución 389, `estado_publicacion: "PUBLICADO_OFICIAL"`,
`publicado: true`. Resultado real en Drive:
- `SAP_TIQ_10-09-2026.xlsx` subido a la carpeta SAP oficial.
- `RESULTADO_TIQ_10-09-2026.json` subido a la carpeta RESULTADOS oficial.
- `CIERRE 10-09-2026.xlsm` movido de `00_ENTRADA_CIERRES` a `03_PROCESADOS`.
- Marker `PROCESADO_32a86dca...json` creado en `05_CONTROLES/MARCADORES_PROCESAMIENTO`.
- Sin duplicados en ninguna de las 4 carpetas (confirmado también con un
  PREFLIGHT de solo lectura posterior: `sap_duplicado: false`,
  `resultado_duplicado: false`).

Este es el **primer cierre oficial V3 publicado de punta a punta contra
Drive real**, cerrando la cadena completa `/procesar` → `/publicar` → 06B
→ Drive oficial.

Commit de este fix: `fix: finalize official V3 publication path`.

### GLOBAL mensual: consolida todo SAP oficial del mes + regenerable en Drive (2026-09-18)

**Disparador:** el auditor generó el primer GLOBAL real de septiembre 2026
desde la interfaz. Resultado: `ERROR_REVISAR`, `1 SAP incluidos, 29
fecha(s) sin cierre`, `ruta_global_generado: null` (nunca se llegó a
escribir el `.xlsx`).

**Dos problemas reales, distintos, encontrados en esa única corrida:**

1. **GLOBAL solo veía los SAP que V3 había publicado** (`publicacion/sap/`
   local), nunca los `SAP_DD-MM-YYYY.xlsx` (nombre legacy, sin `TIQ_`) que
   ya existían en la carpeta SAP oficial de Drive desde antes de V3.
   Confirmado leyendo Drive real (workflow de diagnóstico temporal, creado
   y borrado en esta misma sesión): la carpeta SAP oficial de septiembre
   2026 tiene exactamente 9 archivos — `SAP_01-09-2026.xlsx` ...
   `SAP_05-09-2026.xlsx`, `SAP_07-09-2026.xlsx` ... `SAP_09-09-2026.xlsx`
   (legacy, 8 archivos) y `SAP_TIQ_10-09-2026.xlsx` (V3, 1 archivo) — sin
   `SAP_06-09-2026`, sin duplicados de fecha, sin `SAP_GLOBAL_*` mezclado.

2. **Bug real, preexistente, en `consolidador_mensual.py` (V2, congelado
   antes de `7dbcf93`):** `_CABECERA_ESPERADA["C"]` exige `"DB"` en la
   celda C10 (BLART/tipo de asiento) de cada SAP diario de entrada, pero
   todo SAP diario real trae `"SA"` (`run_batch.py::_TIPO_ASIENTO`,
   confirmado leyendo el SAP oficial real). `"DB"` es en realidad
   `_TIPO_ASIENTO_GLOBAL`, la constante separada para la cabecera de
   SALIDA del propio GLOBAL — nunca debió usarse para validar la entrada.
   Nunca se había detectado porque este era el primer SAP real (no un
   fixture sintético) que pasaba por este validador.

**Corregido en esta sesión (problema 1, capa V3, `v3/auditoria.py`):**
nuevas `_fecha_y_origen_desde_nombre_sap()` / `descubrir_sap_oficiales_del_mes()`
que escanean la carpeta SAP oficial aceptando AMBOS formatos (legacy y
V3), filtran por año/mes, excluyen `SAP_GLOBAL_*`/temporales/nombres
inválidos, y aplican protección por fecha: como máximo un SAP efectivo
por fecha — mismo contenido con dos nombres se deduplica (se prefiere el
nombre V3, el otro queda registrado como duplicado idéntico omitido);
contenido distinto para la misma fecha genera un blocker
`DUPLICADO_FECHA_AMBIGUA` y detiene la consolidación (nunca elige uno
arbitrariamente). `generar_global_mensual()` usa este descubrimiento por
defecto (si no se pasa `archivos_lista` explícito) y se lo pasa a
`consolidador_mensual.ejecutar_consolidacion()` vía `--archivos-lista`,
que ya soportaba una lista explícita sin cambios. `fechas_faltantes` (ya
existente) se recalculó para comparar por FECHA, no por nombre de
archivo, para no marcar como "faltante" un día cubierto por un SAP
legacy. **`consolidador_mensual.py` no se tocó.**

**También corregido (Drive oficial, BACKEND DEV):** el nodo `CONSTRUIR -
Lista publicaciones GLOBAL` pasaba `modo_si_existe: "mantener"` a `07D
PUBLICAR ARCHIVO OFICIAL` para el SAP_GLOBAL y su JSON de resultado
(tratándolos como inmutables). Ahora pasa `modo_si_existe: "actualizar"`,
consistente con la decisión de que GLOBAL es regenerable mientras el mes
está abierto: una republicación reemplaza el archivo oficial existente en
`05_CONTROLES/GLOBAL/` en vez de dejarlo intacto. `07D`/`07E` (lógica
genérica, ya soportaba ambos modos) no se tocaron. Re-publicado
(`activeVersionId` = `versionId` = `78ab08f3-1bad-4e8b-a849-271835dc90d2`).

**Problema 2 (bug de C10/BLART en `consolidador_mensual.py`) — NO
corregido en esta sesión, pendiente de decisión del auditor.** Es código
V2 congelado; corregirlo requiere tocar `_CABECERA_ESPERADA` (o añadir un
punto de extensión) dentro de ese archivo. Por instrucción explícita del
auditor ("si descubres que no puede resolverse sin modificar una pieza
compartida de V2, detente y explícame antes de hacerlo"), esta sesión se
detuvo ahí: el descubrimiento V3 ya acepta correctamente cualquier SAP
diario real (`origen: "legacy"` o `"v3"`), pero `consolidador_mensual.py`
sigue rechazando su cabecera aguas abajo con
`SAP_INVALIDO:...:CABECERA_C10_ESPERADO_'DB'_OBTENIDO_'SA'` para los 9
SAP reales de septiembre. **Por eso GLOBAL de septiembre 2026 sigue sin
poder generarse de punta a punta todavía** — el auditor debe decidir
cómo corregir `_CABECERA_ESPERADA["C"]` antes de que esto quede resuelto.
Cubierto con dos tests `xfail(strict=True)` en
`tests_v3/test_auditoria_mensual.py` (dejan de ser xfail automáticamente
el día que se aplique la corrección).

Commits de este fix: `feat: allow monthly GLOBAL regeneration in V3` (GLOBAL
regenerable, turno anterior) + `fix: consolidate all monthly SAP files in V3`
(descubrimiento legacy+V3, protección por fecha, Drive `actualizar`).

### Bug C10/BLART resuelto EXCLUSIVAMENTE en V3 (2026-09-18)

**Decisión del auditor:** no modificar `consolidador_mensual.py` (V2,
congelado). Contrato V3 explícito: SAP diario de ENTRADA acepta
C10/BLART="SA" (el valor real); SAP GLOBAL de SALIDA sigue con C10="DB"
(sin cambios).

**Implementación — nuevo módulo `v3/consolidador_mensual_v3.py`:**
reutiliza SIN NINGÚN CAMBIO todas las funciones públicas de
`consolidador_mensual.py` que no tienen relación con el valor de C10 de
entrada: `validar_guardarrieles_salida`, `detectar_duplicados`,
`leer_y_validar_sap_diario`, `construir_metadata_cabecera_global`,
`escribir_sap_global`, `nombre_sap_global`, `nombre_resultado_json`,
`ultimo_dia_mes`, `_es_temporal`, `_sha256_archivo`. La escritura del
GLOBAL (con su cabecera "DB") sigue siendo, byte a byte, la misma llamada
de V2 — `construir_metadata_cabecera_global()`/`escribir_sap_global()` no
se tocaron, así que la regla de salida no cambió ni un poco.

Lo único nuevo es `_reinterpretar_problemas_entrada_v3()`: recibe la
lista `problemas` que `leer_y_validar_sap_diario()` YA calculó (llamada
sin cambios, sobre el archivo real, en modo solo lectura) y, usando el
formato EXACTO del mensaje que V2 genera para un mismatch de C10
(`CABECERA_C10_ESPERADO_'DB'_OBTENIDO_'<valor>'`), deja de considerar
problema el caso `<valor>=='SA'`; cualquier OTRO valor de C10 sigue
bloqueando, con un mensaje reescrito para reflejar el contrato real de V3
(`CABECERA_C10_ESPERADO_'SA'_OBTENIDO_'<valor>'`) en vez de confundir con
el de V2. Ningún otro problema (hoja, partidas, cuadre, otras columnas de
cabecera) se toca. **No hay monkeypatch, no hay mutación de constantes en
runtime, no hay copias adulteradas de ningún SAP diario** — solo se
post-procesa, en memoria, el resultado ya calculado por una función de V2
sin modificar.

El orquestador `ejecutar_consolidacion_v3()` es un espejo delgado de
`consolidador_mensual.ejecutar_consolidacion()` (mismo formato de
resultado JSON), necesario porque esa función de V2 no expone un punto de
extensión para inyectar la reinterpretación sin reimplementar el bucle
que la contiene — pero cada paso dentro de ese espejo llama a una función
pública de V2 sin cambios. `v3/auditoria.py::generar_global_mensual()`
(la API pública que sigue usando `dev_api.generar_global`, sin cambios de
firma) ahora delega en este nuevo módulo en vez de llamar directamente a
`consolidador_mensual.ejecutar_consolidacion()`.

**Validado con guardarraíl de regresión propio**
(`test_v2_mensaje_cabecera_c10_no_cambio_de_formato`): si V2 alguna vez
cambia el formato de ese mensaje, este test falla en rojo — señal
explícita de revisar el regex, en vez de dejar de filtrar en silencio.

**Validado en sandbox** (fixtures equivalentes a los 9 SAP reales de
septiembre 2026 detectados en Drive — 8 legacy + 1 V3, fechas
01-05/07-09/10, sin el 06 — ningún archivo real tocado, ningún Drive
productivo escrito):

```
estado: VALIDADO_PENDIENTE_PUBLICACION
cantidad_sap_incluidos: 9
blockers: []
cargo_global / haber_global / diferencia: 900.00 / 900.00 / 0.00
fechas_faltantes: 21 (incluye 2026-09-06; informativas, no bloquean)
C10 del GLOBAL generado: DB
```

Commit de este fix: `fix: validate daily SA entries in V3 monthly consolidation`.
