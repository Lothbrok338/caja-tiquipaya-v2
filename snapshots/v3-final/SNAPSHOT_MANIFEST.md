# SNAPSHOT_MANIFEST.md — V3 FINAL (cierre formal)

Fecha de captura: **2026-09-17T20:55:26Z**
Commit Git de referencia: **`bd2424b`** (`feat: complete V3 official monthly persistence`, rama `v3-dev`)

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
| 8 | TIQ V3 · 06B PUBLICACION OFICIAL · DRIVE | `wcgxNei3duWfMDp1` | `wcgxNei3duWfMDp1_06b_publicacion_oficial.json` | false | 31 | `374d8f7aee375a4c94d4e2ecd71881f0696c1a99883858249b7296075d76555c` |
| 9 | TIQ V3 · 07 AUDITORIA · DEV | `Q81cDev3QSx5Zowc` | `Q81cDev3QSx5Zowc_07_auditoria.json` | false | 7 | `18ed3c9a516483ec481eba17d829d970dc4bed2e48de401588dc1453d1f095ce` |
| 10 | TIQ V3 · 07C DESCARGAR ARCHIVO OFICIAL SI EXISTE · DRIVE | `fn7lLjHsiMd48DGK` | `fn7lLjHsiMd48DGK_07c_descargar_oficial.json` | false | 8 | `2dcda703148d885ac1a7070876b595fb1af6c786e197f2289c96ad9c26fd6714` |
| 11 | TIQ V3 · 07D PUBLICAR ARCHIVO OFICIAL (crear o actualizar) · DRIVE | `HhuQCVP2oCubavzY` | `HhuQCVP2oCubavzY_07d_publicar_oficial.json` | false | 12 | `9f9aab93e4654612e8a1b10005975fac88ecfc793024b51ba0bab9ddbf848f78` |
| 12 | TIQ V3 · 07E BUSCAR O CREAR CARPETA OFICIAL · DRIVE | `Lht5xRinJ9nJpHCW` | `Lht5xRinJ9nJpHCW_07e_buscar_crear_carpeta.json` | false | 7 | `2b331e13b50c40d69eb46c06817b6f5aecdeca8d4a25af408274e11bd74cc15f` |
| 13 | TIQ V3 · PREFLIGHT OFICIAL (solo lectura) | `sJVgoBRpBntc96vf` | `sJVgoBRpBntc96vf_preflight_oficial.json` | false | 12 | `dccdfb3711e06518bce4d73c73acbfaa4a687457212e946d5b85321cb1f782de` |
| 14 | TIQ V3 · BACKEND DEV (webhooks) | `aLs1f3GMqswbaENA` | `aLs1f3GMqswbaENA_backend_dev.json` | false | 112 | `4396328cb60dd29834e0d3d2cd0285a919df05d6e806fd5bbb9153232cb56948` |

**Los 14 workflows están `active=false`.** Ninguno fue activado durante
esta fase ni en ninguna fase anterior de V3.

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
