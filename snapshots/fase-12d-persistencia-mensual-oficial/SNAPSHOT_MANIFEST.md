# SNAPSHOT_MANIFEST.md — FASE 12D · persistencia mensual oficial (GLOBAL/CONTROL 1/CONTROL 3)

Fecha de captura: **2026-09-17**.

Este snapshot congela `TIQ V3 · BACKEND DEV (webhooks)` (`aLs1f3GMqswbaENA`,
64→85→112 nodos a través de FASE 11A/12C/12D) tras conectar `/global`,
`/control1` y `/control3` a la persistencia oficial en Google Drive.
Reutiliza la estructura **ya existente** en Drive (`05_CONTROLES/`) — no se
creó `05_CONTROL_MENSUAL/` como sugería el fallback de la instrucción,
porque la inspección de solo lectura encontró la carpeta equivalente ya en
uso desde V2/FASE anteriores.

## 1. Estructura real encontrada en Drive (inventario de solo lectura)

Raíz `AGENTE TIQUIPAYA` (`1mAjsBNtGAPnCuHNYuJDxFZCP1Ncg3Xdd`):

```
AGENTE TIQUIPAYA/
  00_ENTRADA_CIERRES/          (1ntneoE3MI-25FyPXUymXEvIJmnaZWyJ1)
  01_SISTEMA_V2/                (1TayGIwn009F6bzoM1z6xG19dMUA0a7_1)
  02_MAESTROS/                  (1XOlFEKP3nKSvbHCEpk5l8BKWhOMbhMZB)
  03_PROCESADOS/                (1h1lUkZ3yE_tqmSylUwOqzV9JQTnqFNYN)
  04_SALIDAS/                   (1juCjs37OUbARIwkvCnHYom3iVtrQm2Ox)
    2026/2026-09/SAP/           (1mid4gUHnCmZbISlsAYMwWta3RudTSE13)
    2026/2026-09/RESULTADOS/    (16Z7Uhf-NgiZ6YuqWLnReaIozRIiOg5HO)
    2026/2026-09/REPORTES/      (1eJdzEfmv51YETJBRstzrt-bFevoN6BSz)
  05_CONTROLES/                 (1yZI_OCuYOAILg8E6uT-bAmkQtW-XB-qB)  <-- YA EXISTÍA
    HISTORICO_ASIGNACIONES.csv          (1D5SzH4_3kpvgbz3r6hXaMa8ejkt6RhIb)
    HISTORICO_CXC_CXP.csv                (1m7DsJGev6CWUnzOqTF2qPJpGc2-jHgiu)
    HISTORICO_CXC_CXP_PERIODOS.json      (1WpxdCKC6ppLwXclx0zgLrU2zHRdHiyEK)
    MARCADORES_PROCESAMIENTO/            (1i8wXRM-2yiH5N3SPOEd4eEqZnizCeCGu)
    CONTROL_1_ASIGNACIONES/              (1oOcwIgq_9uU9eRLV7z36zBjdBS-hBlRk)  -- vacia
    CONTROL_3_CXC_CXP/                   (15IYQDdpyBwrZTNS-qU8VZa47sVz1ziV_)  -- vacia
    CONTROL_PROCESAMIENTO / .csv          (legado, no tocado)
  06_REPORTES AUDITORIA/        (1rciHCS_gXcbDvcd0NHGTYvnGgBHY6yEn)
  99_ARCHIVO_V1/                 (1ufR_Wf5k_CP7UWEbVesgEZM5UR0f0Hmr)
```

`HISTORICO_ASIGNACIONES.csv` y `HISTORICO_CXC_CXP.csv` **ya contenían datos
reales** (de pruebas FASE 9-11), por lo que el diseño incluye
obligatoriamente una descarga previa antes de correr CONTROL 1/3 (ver §3) —
sin eso, la primera corrida oficial habría sobrescrito el acumulado real
con un histórico local vacío.

No existía ninguna carpeta `GLOBAL` dentro de `05_CONTROLES/`: se crea la
primera vez que `/global` publica en modo oficial (idempotente, ver
subworkflow 07E).

## 2. Ubicaciones de publicación

| Artefacto | Carpeta Drive | Idempotencia |
|---|---|---|
| `SAP_GLOBAL_TIQ_<MES>_<AÑO>.xlsx` | `05_CONTROLES/GLOBAL/` (creada bajo demanda) | inmutable: 0→sube, 1→reutiliza (nunca sobrescribe), >1→`ERROR_AMBIGUO` |
| `RESULTADO_GLOBAL_TIQ_<MES>_<AÑO>.json` | `05_CONTROLES/GLOBAL/` | igual que el SAP global |
| `REVISION_ASIGNACIONES_<PERIODO>.xlsx` | `05_CONTROLES/CONTROL_1_ASIGNACIONES/` | mutable: 0→crea, 1→actualiza contenido, >1→`ERROR_AMBIGUO` |
| `HISTORICO_ASIGNACIONES.csv` | `05_CONTROLES/` (raíz, existente) | mutable, mismo criterio |
| `CONTROL3_CXC_CXP_<PERIODO>.xlsx`/`.json` | `05_CONTROLES/CONTROL_3_CXC_CXP/` | mutable, mismo criterio |
| `HISTORICO_CXC_CXP.csv` + `HISTORICO_CXC_CXP_PERIODOS.json` | `05_CONTROLES/` (raíz, existente) | mutable, mismo criterio |

## 3. Subworkflows nuevos (reutilizables, sin lógica contable)

- **07C · DESCARGAR ARCHIVO OFICIAL SI EXISTE** (`fn7lLjHsiMd48DGK`) — busca
  por nombre exacto; 0→no hace nada, 1→descarga a una ruta local, >1→
  `ERROR_AMBIGUO_DESCARGA`. Usado ANTES de correr Python en CONTROL 1/3
  (modo oficial) para partir del histórico real más reciente y no perder
  contenido previo.
- **07D · PUBLICAR ARCHIVO OFICIAL (crear o actualizar)** (`HhuQCVP2oCubavzY`)
  — busca por nombre exacto; 0→sube, 1→actualiza contenido
  (`modo_si_existe=actualizar`, para históricos/reportes mutables) o
  reutiliza sin tocar (`modo_si_existe=mantener`, para GLOBAL/RESULTADO
  inmutables, mismo criterio que SAP/RESULTADO diarios en 06B), >1→
  `ERROR_AMBIGUO_PUBLICACION`.
- **07E · BUSCAR O CREAR CARPETA OFICIAL** (`Lht5xRinJ9nJpHCW`) — busca
  subcarpeta por nombre exacto; 0→crea, 1→reutiliza, >1→
  `ERROR_AMBIGUO_CARPETA`. Solo usado para `05_CONTROLES/GLOBAL/`.

Los tres reutilizan la credencial `Google Drive account`
(`aoEcEAFQQ38XcwZg`), igual que 06B. Cero lógica contable: solo
comparan nombres y cuentan coincidencias.

## 4. Wiring en BACKEND DEV (`/global`, `/control1`, `/control3`)

Cada ruta añade, alrededor del núcleo ya existente de FASE 12C:

- **Antes de correr Python** (solo CONTROL 1/3): `IF modo==official` →
  descarga (vía 07C) el/los históricos oficiales a la ruta local que
  Python va a leer; en modo dev o si no hay nada que descargar, salta
  directo a `CONSTRUIR payload`.
- **Después de correr Python**: `DECIDIR` (Code, banderas ya calculadas
  por Python: `estado`, `historico_actualizado`, `ruta_revision`,
  `archivo_control_xlsx` — cero lógica contable en n8n) → `IF
  debe_publicar` → si aplica, sube/actualiza (vía 07D) cada artefacto
  correspondiente y combina el resultado con `publicacion_oficial:
  {publicado, archivos}`; si no aplica (dev, o nada que publicar),
  combina con `publicacion_oficial: {publicado:false}`. Ambas ramas
  convergen al mismo `RESPONDER`.

**Bug real encontrado y corregido durante las pruebas en vivo**: un nodo
que recibe 0 items de entrada NO se ejecuta en n8n (`alwaysOutputData`
solo ayuda cuando el nodo SÍ corre pero su propia operación no devuelve
nada, no cuando no le llega ningún item). El primer diseño de CONTROL 1/3
dejaba pasar 0 items en modo dev, cortando la cadena antes de
`RESPONDER` — se corrigió reemplazando ese patrón por `IF` explícitos
(con `typeValidation:"loose"` y `sourceIndex` correcto — dos bugs de
sintaxis adicionales encontrados y corregidos en el camino: `sourceOutput`
no es un campo válido de `addConnection`, es `sourceIndex`). GLOBAL no
tenía este bug (su lista de archivos a publicar es incondicional una vez
decidido publicar) y no se tocó.

## 5. DEV vs OFFICIAL

El body de cada request ahora acepta `modo` (`"dev"` u `"official"`,
enviado por la interfaz según `state.publicationMode`, ya calculado desde
`/estado`). En `modo!="official"` ninguna de las 3 rutas hace ninguna
llamada a Drive — comportamiento idéntico a FASE 12C. En
`modo=="official"`, CONTROL 1/3 primero descargan su histórico oficial y,
tras correr Python, publican lo que corresponda; GLOBAL publica cuando
queda `VALIDADO_PENDIENTE_PUBLICACION`.

## 6. Pruebas realizadas

- **Sandbox Drive desechable** (fuera de `05_CONTROLES`, creada y borrada
  en la misma sesión): 07E crea/reutiliza carpeta, 07D crea/actualiza/
  reutiliza archivo, 07C descarga — los 3 casos (0/1 coincidencias)
  verificados con Drive real, contenido descargado verificado byte a
  byte contra el original.
- **Backend completo, año/mes 1900** (sin SAP real, sin GLOBAL real):
  - `/global` modo dev y official: llega a `RESPONDER` en ambos casos,
    `publicacion_oficial.publicado:false` (correcto, sin blockers=false
    para 1900 no hay nada que publicar).
  - `/control1` modo dev y official: en official, descargó de verdad
    `HISTORICO_ASIGNACIONES.csv` real desde `05_CONTROLES/` (lectura,
    contenido intacto) antes de fallar con `GLOBAL_NO_ENCONTRADO`
    (esperado, no existe GLOBAL para 1900); ambos modos llegan a
    `RESPONDER`.
  - `/control3` modo dev y official: igual, descargó
    `HISTORICO_CXC_CXP.csv` y `HISTORICO_CXC_CXP_PERIODOS.json` reales;
    ambos modos llegan a `RESPONDER`.
  - En ningún momento se escribió a `05_CONTROLES/` real (las ramas de
    publicación nunca se activaron porque GLOBAL nunca tuvo éxito con
    año 1900 — esa parte de la lógica de escritura solo fue probada en
    el sandbox, no dentro del backend completo, para no requerir un
    GLOBAL real).
- `pytest tests_v3/ parity_v3/ -q` → 221 passed. `pytest tests/ -q` → 432
  passed (V2 intacto). `node tests_v3/frontend/test_frontend.js` → 96
  passed.
- El workflow permaneció `active=false` durante toda la fase.

## 7. Cambios de código (fuera de n8n)

- `v3/dev_api.py`: `ejecutar_control3()` ahora calcula `ruta_salida_xlsx`/
  `ruta_salida_json` por defecto (antes no se pasaban y CONTROL 3 nunca
  escribía su reporte, solo el histórico) — fix mínimo, sin tocar
  `control_cxc_cxp.py`.
- `n8n_frontend/v3_control_cierres.html`: los 3 botones mensuales ahora
  envían `modo: state.publicationMode` y muestran si se publicó en Drive
  oficial.
- `tests_v3/test_auditoria_mensual.py`: nueva aserción cubriendo el fix
  de `ejecutar_control3`.
