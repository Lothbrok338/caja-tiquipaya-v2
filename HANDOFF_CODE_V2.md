# HANDOFF — CAJA TIQUIPAYA V2 CLOUD (para Claude Code)

## 1. Arquitectura

- V2 = CLOUD-FIRST + CODE-FIRST.
- Cowork = operación diaria (Google Drive).
- Claude Code = desarrollo del software (esta etapa).
- Python = motor determinístico.
- openpyxl = lectura/escritura de Excel.
- Decimal = todos los importes.

## 2. Archivos actuales

- `excel_io.py`
- `motor_tiquipaya.py`
- `sap_writer.py`

## 3. Etapas validadas

- EXTRACCIÓN V2 OK
- CRUCES V2 OK
- CUADRE V2 OK
- ASIENTO V2 (ETAPA 5) OK

Estado actual: ETAPAS 1-5 están **congeladas** (commit base `d03c3ff`, 61/61
tests OK, validado contra cierres reales). ETAPA 6 (generación y validación
determinística del archivo SAP, en `sap_writer.py`) está en desarrollo sobre
la rama `claude/etapa-6-sap-3f7xzq`, consumiendo exclusivamente el asiento
ya producido por `construir_asiento()` — no recalcula cierres, cruces ni
cuadre. Desarrollada con plantilla SAP sintética (`tests/test_sap.py`); la
plantilla SAP real de Google Drive se probará después en Cowork.

## 4. Reglas técnicas críticas ya implementadas

- Fecha de cierre: `CIERRE DD-MM-YYYY`, se extrae del nombre de archivo (nunca de configuración regional).
- Vouchers siempre BNB.
- MACROS: única hoja exacta `Tablas Dinamicas Profesional`. No se lee ninguna otra pestaña.
- MACROS trae filas de encabezado repetidas dentro del rango de datos; se descartan de forma determinística por contenido (comparando cada fila contra el encabezado real leído en la misma pasada), sin depender de una cantidad fija de repeticiones.
- MACROS se usa únicamente para vouchers y NETO de ATC.
- ATC siempre BNB.
- CI no usa MACROS.
- **MAESTRO MENSUAL ÚNICO + ATC PRECONCILIADO (OPTIMIZACIÓN post-ETAPA 6):** `excel_io.leer_atc_mensual()` detecta el modo por el NOMBRE de hoja (normalizado, no exacto), nunca por un flag: si el archivo trae una hoja `ATC TIQUIPAYA` usa el modo **PRECONCILIADO** (`motor_tiquipaya.cruzar_atc_preconciliado`, sin macros_idx); si no, usa el modo **LEGADO** de siempre (`cruzar_atc`, cruce contra MACROS por importe+fecha — sin cambios). En PRECONCILIADO, cuenta contable/detalle/monto/asignación del NETO y de la COMISIÓN se leen literalmente de `ATC TIQUIPAYA` para la fecha del cierre; único control es NETO+COMISIÓN=ATC BRUTO del cierre (Decimal). Permite `ejecutar_v2(cierre, ruta_maestro, ruta_maestro)` (mismo archivo para MACROS y ATC — se abre dos veces, cada lector busca su propia hoja) sin romper la firma pública ni el flujo con ATC separado. Asignación `"REVISAR"` en una línea ATC nunca bloquea: se escribe literal, genera advertencia `ATC_ASIGNACION_REVISAR` (en `asiento["advertencias"]`) y en SAP recibe relleno amarillo puramente visual en la columna R (`sap_writer.py`). `_validar_partidas` (ETAPA 5, sin tocar) sigue exigiendo las cuentas 110103012/110201008 para ATC_NETO/ATC_COMISION, lo que además hace cumplir la "cuenta esperada" también para el ATC preconciliado sin duplicar la regla. Vouchers siguen leyendo EXCLUSIVAMENTE `Tablas Dinamicas Profesional`, esté o no presente `ATC TIQUIPAYA` en el mismo archivo.
- ALQUILERES excluido del asiento (nunca se crea partida ALQUILERES ni se compensa con otra cuenta); se conserva separado por SFC para ajustar el HABER: `HABER SFCxxx = TOTAL SFCxxx - ALQUILERES de ese SFC`.
- ATC NETO se cruza contra MACROS por importe exacto + fecha bancaria compatible (nunca ANTERIOR a la fecha de cierre; posteriores sí son válidas; sin ventana arbitraria de días).
- Vouchers: código de asignación + importe exacto; 0↔O solo autocorrección única; O↔P nunca autocorrección (POSIBLE_TYPO/bloqueante). Sin ventana de fecha propia.
- DOLARES determinístico (activo solo si importe > 0; no se trata como faltante). Regla vigente: ver sección 11 (CIERRE DEFINITIVO — regla USD Caja M/E); `USD_CUENTA_PENDIENTE` fue descartado y ya no lo produce ningún flujo.
- `_validar_partidas` bloquea importes negativos y cualquier problema estructural: si hay problemas, el asiento devuelto tiene `estado=ERROR` y `partidas=[]` (nunca partidas inválidas utilizables).
- CI: si trae fecha propia se propaga como `fecha_valor`; si no, `fecha_valor=None` (nunca se usa la fecha del cierre como reemplazo). CI con importe negativo bloquea.
- **TEXTO POSICIÓN Y FECHA VALOR (CORRECCIÓN FINAL post-ETAPA 6):** CI: `texto_posicion` (SGTXT) viene literal de la columna `GLOSA ASIENTO COMUNICACIONES INTERNAS` (nunca se reconstruye desde `N° DE FACTURA`/`referencia`); `fecha_valor` (VALUT) viene de la columna `FECHA2` (autoritativa; las variantes viejas `FECHA`/`FECHA CI`/`FECHA COMUNICACION INTERNA` quedan como fallback solo si no hay `FECHA2`, nunca al revés). VOUCHER: `fecha_valor` viene de la fecha propia de CADA depósito (`FECHA DE DEPOSITO` del cierre), no de la fecha bancaria de MACROS; `texto_posicion` se construye como `"DEPOSITO BNB DD/MM/YYYY"` con esa misma fecha (`motor_tiquipaya._texto_voucher`). El cruce de vouchers (código de asignación + importe exacto contra `Tablas Dinamicas Profesional`) no cambia. Ambas columnas (`GLOSA...`/`FECHA2`) son opcionales a nivel de lectura (`None` si la hoja no las trae, igual que el resto de columnas "blandas"), para no romper cierres sin esas columnas.
- ATC mensual: filas NETO o COMISIÓN duplicadas para la misma fecha lanzan excepción explícita (no se suman ni se usa "la última fila").
- Anulaciones/refacturaciones: inexistentes para V2.
- Decimal siempre, nunca float.
- Cada archivo (CIERRE, MACROS, ATC) se abre una sola vez por corrida.
- Índices en memoria (por código, por importe, por fecha) para evitar recorridos repetidos.

## 5. Regresión 19-08-2026

| Concepto | Valor |
|---|---|
| Universo | 282056.96 |
| Vouchers | 80805.00 |
| CI | 70368.96 |
| ATC bruto | 130883.00 |
| ATC neto | 130246.43 |
| Comisión | 636.57 |
| Diferencia | 0.00 |
| Excepciones | 0 |
| Estado | OK |

Tiempo aproximado `ejecutar_v2`: 0.7 s.

## 6. Siguiente etapa

ETAPA 5 — Construcción determinística del asiento.

## 7. Prohibiciones

- No rehacer ETAPAS 2–4.
- No leer V1.
- No rediseñar arquitectura.
- No cambiar reglas ya validadas salvo bug demostrado.
- No crear módulos innecesarios.
- No generar SAP todavía durante la primera parte de ETAPA 5.

## 8. ETAPA 8 — Ajustes finales SAP + control operativo

Sobre ETAPAS 1-7 ya validadas (congeladas), commit base `ba4fd20`,
137/137 tests OK. ETAPA 8 solo agrega los ajustes explícitos siguientes,
sin reinterpretar ninguna regla contable:

- **texto_posicion HABER SFC** (`motor_tiquipaya.py`): las 2 líneas HABER
  normales llevan ahora `texto_posicion` fijo — `UNIVERSO_SFC101` →
  `"RECAUDACION CAJA SFC101"`, `UNIVERSO_SFC102` → `"RECAUDACION CAJA
  SFC102"` (constantes `_TEXTO_HABER_SFC101`/`_TEXTO_HABER_SFC102`).
- **Fallback fecha_valor = fecha del cierre** (`motor_tiquipaya.py`,
  `construir_asiento`): toda partida sin fecha real específica de origen
  (CI sin FECHA2, VOUCHER sin FECHA DE DEPOSITO, HABER SFC101/SFC102, ATC
  sin fecha bancaria propia) recibe como `fecha_valor` la fecha del
  cierre. Una fecha real existente NUNCA se reemplaza. Esto **supersede**
  la regla anterior de ETAPA 6 que prohibía ese fallback (ver tests
  actualizados en `test_asiento.py`, `test_atc_preconciliado.py`,
  `test_sap.py`).
- **Fechas como tipo fecha Excel real** (`sap_writer.py`): D10
  (FechaRegistro), E10 (FechaContabilizacion) y la columna O
  (FechaValor, fila 16+) se escriben como `datetime.date` real (no
  texto), con `number_format="dd/mm/yyyy"` (`_fecha_desde_iso`/
  `_fecha_a_iso`, constante `_FORMATO_FECHA_CORTA`). La validación
  post-escritura normaliza esos valores de vuelta a ISO para compararlos
  contra el asiento/metadata fuente.
- **Cabecera derivada de la fecha real del cierre**
  (`pipeline_tiquipaya.derivar_cabecera_fecha_cierre`): FechaRegistro,
  FechaContabilizacion y Mes se calculan siempre a partir de
  `resultado_v2["fecha"]` (nunca fin de mes ni otro cálculo).
  `procesar_cierre_completo` sobrescribe con este resultado los campos
  `fecha_registro`/`fecha_contabilizacion`/`mes` de `metadata_cabecera`
  antes de llamar a `sap_writer` (el resto de la cabecera —
  tipo_asiento, texto_cabecera, referencia, Sociedad=BO01, Moneda=BOB—
  no cambia). `sap_writer.py` sigue sin decidir fechas por sí mismo.
- **Control de procesamiento como interfaz de datos limpia**
  (`pipeline_tiquipaya.py`): `construir_registro_control(resultado_json,
  estado=..., archivo_sap=..., observaciones=..., fecha_procesamiento=...)`
  devuelve el dict de una fila de control (mismas columnas que
  `COLUMNAS_CONTROL`: FechaCierre, ArchivoOrigen, HashOrigen, Estado,
  FechaProcesamiento, VersionCodigo, Resultado, Diferencia, Blockers,
  ArchivoSAP, Observaciones), reutilizado por `registrar_procesado`
  (destino CSV) y por `construir_marcador_procesado` (destino marcador
  inmutable, ver sección 10 — CORRECCIÓN POST-ETAPA 8).
  `procesar_cierre_completo` acepta además `hashes_procesados` (set/dict
  de HashOrigen ya PROCESADO) y `registros_control` (lista de dicts con
  esa misma forma) para resolver la idempotencia sin depender de que
  exista un CSV local. Python **no** implementa ninguna API de Google
  Drive/Sheets: solo produce/consume esta forma de dict; la ruta CSV
  (`ruta_control`) se conserva intacta como compatibilidad y auditoría.

### Contrato operativo de producción (Cowork) — ver corrección en sección 10

1. Cowork descarga/materializa CIERRE, MAESTRO mensual y PLANTILLA SAP.
2. Python procesa V2 → ASIENTO → SAP → validación → RESULTADO
   (`pipeline_tiquipaya.procesar_cierre_completo`).
3. Cowork puede subir automáticamente `RESULTADO.json` (vía
   `textContent`).
4. El SAP `.xlsx` queda disponible en Salidas para el usuario.
5. **Única intervención humana:** el usuario guarda/sube `SAP.xlsx` a
   Drive.
6. El usuario confirma `PUBLICADO`.
7. Cowork verifica el SAP en Drive, mueve el CIERRE a PROCESADOS y
   confirma `PROCESADO` — el registro de ese estado es el marcador
   inmutable `PROCESADO_<SHA256>.json` de la sección 10 (el CSV,
   vía `pipeline_tiquipaya.registrar_procesado`, sigue siendo el camino
   legacy/fallback equivalente).
8. Un reintento con el mismo SHA256 devuelve `YA_PROCESADO`, ya sea
   contra el CSV, contra `hashes_procesados`, o contra
   `registros_control` construidos a partir de los marcadores existentes.

## 9. Prohibiciones ETAPA 8

- No implementar Google Drive/Sheets API en Python.
- No implementar subida del SAP.
- No tocar importes, cuentas, asignaciones, Sociedad, Centro Beneficio,
  matching de vouchers, autocorrección 0↔O, POSIBLE_TYPO, CI glosa/FECHA2,
  voucher FECHA DE DEPOSITO/glosa, ATC preconciliado/ATC_NO_APLICA,
  REVISAR, ALQUILERES, USD, cálculo de diferencia, Cargo/Haber,
  estructura SAP ni XREF.

## 10. CORRECCIÓN POST-ETAPA 8 — Control inmutable por SHA256

Hallazgo real de Cowork: Google Sheets no permite append ni edición de
celdas con las herramientas disponibles, y `CONTROL_PROCESAMIENTO.csv`
tampoco puede actualizarse en sitio sin crear un archivo nuevo. **Se
descarta Google Sheets como control operativo de producción** (no debe
existir dependencia productiva de Sheets).

**Nueva arquitectura autorizada:** cada cierre oficialmente publicado
tiene un marcador inmutable en Drive:

```
PROCESADO_<SHA256>.json
```

Ejemplo: `PROCESADO_d2d18cbe98679cc5d67c9ae4399f2d5bc1295a12da02cbc9ec59991e995a6008.json`.

- `pipeline_tiquipaya.nombre_marcador_procesado(hash_origen)` devuelve
  ese nombre de archivo, determinístico y estable.
- `pipeline_tiquipaya.construir_marcador_procesado(resultado_json,
  sap_publicado_por_usuario, sap_verificado_en_drive, resultado_publicado,
  cierre_movido_a_procesados, archivo_sap=..., observaciones=...,
  fecha_procesamiento=...)` devuelve `(nombre_archivo, contenido)` —
  `contenido` es exactamente `construir_registro_control(...)` (mismas
  claves que `COLUMNAS_CONTROL`, sin datos personales de CI). Las 4
  confirmaciones deben ser `True`; si falta alguna, lanza `ValueError`
  con el detalle (`MARCADOR_NO_AUTORIZADO:...`) y no construye nada. El
  marcador **nunca** se construye al terminar el motor: solo después de
  que el usuario publicó el SAP, Cowork lo verificó en Drive, el
  RESULTADO está publicado y el CIERRE fue movido a PROCESADOS.
- Python **nunca** escribe este archivo en Drive: Cowork lo materializa
  con `textContent` usando el `(nombre_archivo, contenido)` devuelto.
- Antes de procesar un cierre, Cowork calcula/obtiene su SHA256 y
  busca si ya existe un marcador con ese HashOrigen y Estado=PROCESADO;
  si existe, no reprocesa. Este chequeo usa el mecanismo genérico ya
  existente de ETAPA 8: `procesar_cierre_completo(...,
  hashes_procesados=..., registros_control=[...])`, pasando los
  HashOrigen o el contenido ya parseado de los marcadores encontrados —
  no requiere ningún cambio adicional en Python.
- `CONTROL_PROCESAMIENTO.csv` (`registrar_procesado`) se conserva
  intacto como LEGACY/FALLBACK: no se elimina ninguna función ni test.

## 11. CIERRE DEFINITIVO — Regla USD / DOLARES (Caja M/E)

Validada end-to-end por Cowork sobre el cierre real `CIERRE
05-08-2026.xlsm` (USD 3606.00 → diferencia 0.00, asiento de 59 partidas,
Cargo = Haber = 547882.23, SAP generado y validado OK). Implementada
directamente en el repo canónico (Cowork no pudo hacer push desde su
sesión).

**Regla:** DOLARES > 0.00 genera una única partida:

| Campo | Valor |
|---|---|
| Cuenta | `110101010` ("Caja M/E") |
| Lado | DEBE (cargo = importe DOLARES, haber = 0.00) |
| Texto posición | `RECAUDACION DOLARES` |
| FechaValor | fecha del cierre (USD no trae fecha propia) |
| Asignación | vacía (`None` — no existe fuente autorizada) |
| Sociedad | `BO01` |
| Centro Beneficio | `10010101` |

USD **nunca** se concilia contra banco/MACROS: no cruza contra ninguna
fuente externa, se toma literal de la columna DOLARES del cierre
(`motor_tiquipaya.calcular_componentes`, sin cambios). DOLARES = 0.00 no
genera ninguna partida (como siempre).

**Supersede** la regla anterior (`USD_CUENTA_PENDIENTE`): DOLARES > 0.00
ya NO bloquea `ejecutar_v2` (nunca vuelve a devolver ese estado) ni
`construir_asiento` (ya no existe el corte temprano por USD). El importe
USD ya se sumaba a `recaudacion_explicada` desde antes (sin cambios en
esa fórmula ni en el resto del cuadre); lo único que cambia es que ahora,
en vez de bloquear, se refleja como partida DEBE real.

Constantes en `motor_tiquipaya.py`: `_CUENTA_USD = "110101010"`,
`_TEXTO_USD = "RECAUDACION DOLARES"`. `_validar_partidas` exige que toda
partida `origen == "DOLARES"` use esa cuenta (`DOLARES_CUENTA_INVALIDA`
si no). El fallback de `fecha_valor` de ETAPA 8 (fecha del cierre cuando
no hay fecha real propia) cubre esta partida sin necesitar código nuevo.

Sin cambios en: vouchers, CI, ATC, ALQUILERES, SFC101/SFC102, resto de
reglas SAP (ETAPA 6/8) ni control inmutable por SHA256 (ETAPA 8 y su
corrección).

## 12. RUNNER BATCH CANÓNICO

Elimina la necesidad de que Cowork escriba scripts ad hoc en cada batch.
`run_batch.py` es el runner productivo genérico: orquesta
`pipeline_tiquipaya.procesar_cierre_completo()` sobre un rango de fechas
de UN MISMO MES, exclusivamente sobre archivos YA MATERIALIZADOS
localmente. No reinterpreta contabilidad, no cambia ninguna regla de
`excel_io.py`/`motor_tiquipaya.py`/`sap_writer.py`, y **nunca** se
conecta a Google Drive.

**División de responsabilidades:**

- **Cowork:** Drive → localiza los cierres del rango, materializa el
  CIERRE de cada día, materializa UNA VEZ el maestro mensual y UNA VEZ
  la plantilla SAP, y obtiene/materializa los marcadores
  `PROCESADO_<SHA256>.json` existentes en un directorio local
  (`--controles-dir` y, opcionalmente, `--marcadores-dir` — ver
  MIGRACIÓN DE UBICACIÓN más abajo).
- **`run_batch.py`:** procesa el rango completo de forma local — nunca
  lee ni escribe nada en Drive.
- **Cowork:** publica SAP/RESULTADO/CONTROL en Drive solo tras
  confirmación explícita del usuario (igual que el contrato operativo
  de la sección 8; `run_batch.py` no crea marcadores PROCESADO ni mueve
  cierres).

**Uso:**

```
python run_batch.py \
  --fecha-inicio 2026-09-01 \
  --fecha-fin 2026-09-03 \
  --cierres-dir /ruta/cierres \
  --maestro /ruta/MACROS_SEPTIEMBRE.xlsm \
  --plantilla /ruta/Plantilla_SAP_maestra.xlsx \
  --salidas-dir /ruta/salidas \
  --resultados-dir /ruta/resultados \
  --controles-dir /ruta/controles
```

**Comportamiento clave:**

- Rango dinámico (`--fecha-inicio`/`--fecha-fin`, sin fechas
  hardcodeadas), exigiendo que ambas pertenezcan al mismo mes: si
  cruzan de mes, se detiene con error claro (`RANGO_CRUZA_MES`) y nunca
  combina maestros mensuales distintos. Un día sin `CIERRE
  DD-MM-YYYY.xlsm` en `--cierres-dir` se reporta como `SIN_ARCHIVO` y el
  batch continúa con el siguiente día.
- Texto de cabecera SAP (G10) derivado automáticamente del mes de cada
  cierre: `INGRESOS <MES_ABREV> CBBA` (ENE..DIC). L10/Referencia se
  mantiene fija: `CAJA TIQUIPAYA`.
- `--maestro` y `--plantilla` se reciben por ruta local, se validan una
  vez (existencia, hoja `ATC TIQUIPAYA` en el maestro, coincidencia de
  mes cuando es determinable por el nombre de archivo) y se reutilizan
  tal cual para todos los cierres del rango.
- Idempotencia dinámica: si se pasa `--controles-dir`, se leen todos los
  `PROCESADO_<SHA256>.json` presentes (solo cuentan los que traen
  `HashOrigen` y `Estado=PROCESADO`) y se arma `hashes_procesados`/
  `registros_control` para `procesar_cierre_completo(...)`. Sin
  `--controles-dir`, se usa un set vacío de forma explícita, indicado en
  `resultado_batch.json["idempotencia"]`. Nunca se asume
  `HASHES_PROCESADOS = set()` como supuesto fijo de producción.

**MIGRACIÓN DE UBICACIÓN de los marcadores (sin tocar contenido/esquema):**
los `PROCESADO_<SHA256>.json` pueden vivir en una subcarpeta dedicada:

```
05_CONTROLES/
  HISTORICO_ASIGNACIONES.csv
  CONTROL_1_ASIGNACIONES/
  MARCADORES_PROCESAMIENTO/
```

`run_batch.py` agrega `--marcadores-dir` (opcional; por defecto
`<--controles-dir>/MARCADORES_PROCESAMIENTO` si no se indica
explícitamente). `cargar_marcadores_procesados()` busca PRIMERO ahí y
mantiene como FALLBACK la lectura de marcadores LEGACY sueltos
directamente en `--controles-dir` (esquema anterior a la migración) —
ambas ubicaciones son válidas simultáneamente. Un mismo `HashOrigen`
presente en los dos lugares nunca se cuenta dos veces: se conserva la
copia de `MARCADORES_PROCESAMIENTO/` (ubicación migrada) y se descarta
la legacy equivalente. El contenido/esquema del marcador, la lógica
contable, `pipeline_tiquipaya.py`, CONTROL 1, el consolidador mensual,
`sap_writer.py` y `excel_io.py` no cambian.
- Un blocker en un cierre individual se refleja como `ERROR_REVISAR` y
  **no** detiene el batch: se continúa con el siguiente cierre.
- Ejecuta exclusivamente `pipeline_tiquipaya.procesar_cierre_completo()`
  — no duplica lógica contable ni llama funciones privadas del motor.
- Salida: `resultado_batch.json` en `--resultados-dir`, con fecha,
  archivo, hash, estado (`LISTO_PARA_PUBLICAR` / `YA_PROCESADO` /
  `ERROR_REVISAR` / `SIN_ARCHIVO` / `ERROR_TECNICO`), diferencia,
  blockers, líneas SAP, tiempos (batch total, por cierre, generación y
  validación SAP cuando `sap_writer` los expone), rutas de SAP y
  RESULTADO, y `detalle_error` cuando corresponde.
- El runner **no** mueve cierres, **no** publica SAP, **no** crea
  marcadores PROCESADO, **no** escribe en Google Drive, **no** modifica
  archivos fuente, **no** corrige blockers y **no** inventa
  cuentas/asignaciones: solo genera salidas locales pendientes de
  publicación.

Tests: `tests/test_run_batch.py` (29 pruebas: rango dinámico, cabecera
automática por mes, rango cruzando mes, `SIN_ARCHIVO`, idempotencia
dinámica vía marcadores, blocker sin detener el batch, reutilización de
maestro/plantilla, validación de maestro, ausencia de cualquier
dependencia de Google Drive, y la migración de ubicación de marcadores:
detección en `MARCADORES_PROCESAMIENTO/` por defecto y con
`--marcadores-dir` explícito fuera de `--controles-dir`, convivencia de
marcadores migrados y legacy para hashes distintos, un mismo `HashOrigen`
en ambos lugares sin duplicarse, y el comportamiento legacy intacto
cuando no existe la subcarpeta migrada).

## 13. CONSOLIDADOR MENSUAL SAP

Módulo **separado e independiente** (`consolidador_mensual.py`), **posterior**
al V2 diario. No modifica ninguna regla contable ni ningún archivo del motor
diario: toma SAP diarios **ya validados y publicados** por el flujo diario y
produce un **nuevo archivo** SAP GLOBAL mensual.

```
SAP diarios validados
        ↓
consolidador_mensual.py
        ↓
NUEVO archivo: SAP_GLOBAL_TIQ_<MES>_<AÑO>.xlsx
```

**Principios (no negociables):**

- Los SAP diarios de origen son **solo lectura**: se abren siempre con
  `read_only=True, data_only=True` y **nunca** reciben `.save()`. No se
  modifican, no se renombran, no se mueven y no se vuelven a conciliar
  (no repite vouchers/CI/ATC/USD ni ninguna regla de `motor_tiquipaya.py`).
- La plantilla SAP maestra nunca se abre en modo escritura: se copia con
  `shutil.copyfile` y solo esa copia (`--salida`) se escribe.
- El SAP global es un **archivo nuevo**: la consolidación es detallada
  (copia TODAS las partidas de TODOS los SAP diarios incluidos), **nunca
  agrupa por cuenta ni suma partidas equivalentes**.
- `FechaValor` de cada partida se **conserva tal cual** (nunca se
  reemplaza por fin de mes). El fin de mes aplica únicamente a
  `FechaRegistro`/`FechaContabilizacion` de la cabecera global.
- **Riesgo de doble contabilización:** el SAP global y los SAP diarios que
  lo componen representan la MISMA operación. No corresponde contabilizar
  ambos simultáneamente: el global reemplaza a los diarios como fuente de
  contabilización mensual una vez publicado (decisión operativa de
  Cowork/usuario, fuera de este script).

**Uso:**

```
python consolidador_mensual.py \
  --anio 2026 --mes 8 \
  --sap-dir /ruta/sap_diarios \
  --plantilla /ruta/Plantilla_SAP_maestra.xlsx \
  --salida /ruta/SAP_GLOBAL_TIQ_AGOSTO_2026.xlsx
```

`--archivos-lista <ruta1> <ruta2> ...` consolida EXCLUSIVAMENTE esa lista
explícita de SAP aprobados (ignora `--sap-dir` y el filtro de año/mes).
`--force` permite reemplazar `--salida` si ya existe; nunca habilita
reemplazar un SAP diario ni la plantilla (esos archivos jamás se abren en
modo escritura, con o sin `--force`).

**Selección y guardarraíles:**

- Por defecto selecciona `SAP_TIQ_DD-MM-YYYY.xlsx` del año/mes pedido,
  ordenados cronológicamente; ignora `SAP_GLOBAL_*`, temporales
  (`~$...`, `.tmp`, ocultos) y nombres no compatibles.
- Duplicados por nombre: SHA256 idéntico → se usa una sola copia
  (`duplicados_identicos_ignorados`); SHA256 distinto → BLOQUEA la
  consolidación (`DUPLICADO_SAP_DIFERENTE`), nunca elige arbitrariamente.
- `--salida` no puede coincidir con la plantilla, con un SAP origen, ni
  con el patrón de nombre de un SAP diario; sin `--force` no sobrescribe
  una salida global existente.

**Validación mínima por SAP diario (solo lectura, sección 5):** hoja
exacta `"1"`, cabecera fija (`B10=BO01`, `C10=DB`, `H10=BOB`,
`L10=CAJA TIQUIPAYA`), al menos una partida desde la fila 16, cuentas no
vacías, Cargo/Haber consistentes por partida, y Cargo total = Haber total
del propio SAP. Cualquier problema bloquea toda la consolidación
(`ERROR_REVISAR`): no corrige nada automáticamente.

**Cuadre global:** `CargoGlobal` = suma de Cargo de todos los SAP
incluidos; `HaberGlobal` = suma de Haber. Si no coincide: `ERROR_REVISAR`,
sin generar el `.xlsx` global.

**Cargo/Haber: celda vacía, nunca cero explícito** (`escribir_sap_global`/
`_celda_importe_o_vacia`): SAP no acepta un 0/0.00 en la columna que no
corresponde a la partida. En el `.xlsx` global, una partida DEBE escribe
Cargo=importe y Haber=`None` (celda realmente vacía); una partida HABER
escribe Cargo=`None` y Haber=importe. Nunca se escribe `0`, `"0"`,
`0.00` ni `Decimal("0")` en la columna opuesta. El importe positivo real
nunca se altera.

**Trazabilidad:** además del `.xlsx`, genera
`RESULTADO_GLOBAL_TIQ_<MES>_<AÑO>.json` (junto a `--salida`) con año, mes,
fecha de generación, SAP incluidos, SHA256 de cada uno, duplicados
(idénticos/diferentes), cantidad total de partidas, CargoGlobal,
HaberGlobal, diferencia, ruta del global generado, blockers y estado
(`VALIDADO_PENDIENTE_PUBLICACION` / `ERROR_REVISAR`).

No se conecta a Google Drive: opera solo sobre archivos ya materializados
localmente (misma responsabilidad de Cowork que en la sección 12).

Tests: `tests/test_consolidador_mensual.py` (50 pruebas: consolidación
detallada sin agrupar, cabecera global por mes/fin de mes, febrero
bisiesto, preservación de FechaValor/Asignacion/XREF/cuentas/importes,
selección por año-mes, exclusión de `SAP_GLOBAL_*`/temporales/nombres no
compatibles, orden cronológico, `--archivos-lista`, duplicados idénticos y
diferentes, SAP descuadrado o estructuralmente inválido bloquea,
guardarraíles de `--salida` (incluye `--force` solo sobre el global),
inmutabilidad de orígenes y plantilla (hash/tamaño/mtime sin cambios),
celda vacía en Cargo/Haber sin cero explícito, JSON de trazabilidad, y
ausencia de dependencia de Google Drive).

## 14. CONTROL 1 — ASIGNACIONES DUPLICADAS / HISTÓRICAS

Módulo **separado e independiente** (`control_asignaciones.py`),
**posterior** al SAP GLOBAL mensual (`consolidador_mensual.py`). Base
tomada de la primera versión funcional creada por Cowork, endurecida en
Claude Code (rama → tests → revisión → commit → merge autorizado por
separado). Esta sección describe el flujo **vigente**: validación humana
en Excel, una fila por ocurrencia, y corrección autorizada del propio
GLOBAL (supersede el flujo intermedio que usaba un CSV agrupado por
asignación y que nunca tocaba el GLOBAL).

**Objetivo:** auditar la columna Asignacion (ZUONR, columna R) del SAP
GLOBAL mensual, detectando repeticiones (1) dentro del mismo GLOBAL y (2)
contra GLOBAL de meses anteriores vía `HISTORICO_ASIGNACIONES.csv`. Un
duplicado **nunca** significa error contable: se marca `REVISAR` y queda
sujeto a validación humana — nunca se corrige nada automáticamente. El
GLOBAL es de **solo lectura mientras haya alertas sin validar**; solo
después de que el auditor validó TODAS las alertas de un periodo,
CONTROL 1 puede corregir ÚNICAMENTE la columna Asignacion (R) de las
filas explícitamente autorizadas y sobrescribir ESE MISMO GLOBAL — el
archivo que el auditor luego carga a SAP. Nunca crea un `_VALIDADO` ni
una copia de respaldo productiva; nunca vuelve a abrir un GLOBAL de un
mes anterior (la memoria histórica vive en el CSV compacto).

**Script oficial:** `control_asignaciones.py` — mismo layout que
`sap_writer.py`/`consolidador_mensual.py` (hoja **EXACTA** `"1"`,
partidas desde la fila 16; C=CuentaMayor, D=TextoPosicion/glosa,
E=Cargo, F=Haber, O=FechaValor, R=Asignacion). La hoja `"1"` es
**obligatoria**: si no existe, el control se detiene con
`ERROR_TECNICO`/`GLOBAL_HOJA_1_NO_ENCONTRADA` — **nunca** hace fallback a
`wb.sheetnames[0]` ni adivina otra hoja.

**Histórico:** `HISTORICO_ASIGNACIONES.csv` (una fila por ocurrencia NO
excluida de una asignación, en cualquier GLOBAL ya incorporado). La
incorporación es siempre incremental y nunca reescribe filas existentes.
Columnas (esquema extendido, compatible con archivos anteriores —
columnas nuevas siempre al final):

```
asignacion, fecha_valor, cuenta_mayor, glosa, monto, archivo_global,
fila_sap, sha256_archivo, fecha_incorporacion, alerta_duplicado,
validacion_auditor, observacion_auditor, fecha_validacion,
asignacion_original, asignacion_final, fila_global,
sha256_global_original, sha256_global_final
```

**`asignacion` guarda siempre la asignación FINAL** — la que realmente
quedó en el GLOBAL que se cargó a SAP — para que los meses siguientes
comparen contra la referencia realmente válida. `asignacion_original`
conserva la trazabilidad del valor de origen:

- `CORRECTA`: `asignacion_original = asignacion_final = asignacion = X`.
- `INCORRECTA` (corregida a Y): `asignacion_original = X`,
  `asignacion_final = asignacion = Y`.

`sha256_archivo` (columna heredada) guarda el SHA-256 **FINAL** del
GLOBAL de esa incorporación (igual a `sha256_global_final`) — así los
guardarraíles de idempotencia (CASO A/B, sin cambios de código) siguen
funcionando tal cual sobre un GLOBAL que el propio CONTROL 1 corrigió.

**Exclusiones** (nunca se marcan como duplicado, ni dentro del mismo
GLOBAL ni contra el histórico):

- `asignacion == "SFC101"`
- `asignacion == "SFC102"`
- `asignacion == "TIQUIPAYA <MES>"` (una de las 12 abreviaturas
  oficiales de `motor_tiquipaya._asignacion_comision()`, ENE..DIC)
- **`cuenta_mayor == "110201008"`** (comisión ATC) — exclusión **POR
  CUENTA**, independientemente del texto de Asignacion: una comisión ATC
  puede traer `"REVISAR"` u otro valor cualquiera en ZUONR y sigue
  siendo una comisión. `_normalizar_cuenta()` compara de forma segura
  sin asumir el tipo de origen (Excel puede entregar la cuenta como
  str/int/float, p. ej. `110201008.0`).

**`"FORTALEZA"` SIEMPRE se evalúa** (nunca forma parte de las
exclusiones): si se repite, se marca `REVISAR` igual que cualquier otra
asignación no excluida. No existen exclusiones adicionales a las cuatro
de arriba.

**Estados posibles (`estado` — mantiene la semántica previa a la
validación humana, para no romper consumidores existentes como
auditor-caja-tiquipaya):**

- `OK_SIN_DUPLICADOS` — sin alertas; si no es `--dry-run`, incorpora las
  filas candidatas al histórico (`alerta_duplicado="SIN_ALERTA"`).
  `estado_validacion` viene `None` (no aplica).
- `REVISAR_DUPLICADOS_ENCONTRADOS` — hay una o más alertas (mismo GLOBAL
  y/o contra histórico), **hayan sido ya validadas por el auditor o
  no**. Este campo por sí solo no dice si el mes puede cerrarse: para
  eso está el campo nuevo `estado_validacion`:
  - `PENDIENTE_VALIDACION_AUDITOR` — al menos una fila de
    `REVISION_ASIGNACIONES_<PERIODO>.csv` sigue sin `VALIDACION_AUDITOR`
    completa; el histórico **no** se modifica.
  - `CERRADO_CON_VALIDACION_AUDITOR` — TODAS las alertas de este periodo
    están validadas (`CORRECTA` o `INCORRECTA`); se incorporan al
    histórico las ocurrencias evaluadas, llevando consigo esa
    validación/observación.

  El JSON de detalle conserva los hallazgos "por par" (`hallazgos`,
  formato anterior sin cambios) y agrega `alertas` (una entrada por
  asignación, igual a las filas de `REVISION_ASIGNACIONES_*`). El
  resumen también expone los conteos `alertas_mismo_mes`,
  `alertas_contra_historico`, `alertas_pendientes_validacion`,
  `alertas_correctas` y `alertas_incorrectas`.
- `YA_PROCESADO_SIN_CAMBIOS` — idempotencia CASO A: mismo SHA-256 ya
  existe en el histórico; no se relee el GLOBAL ni se incorpora nada.
- `GLOBAL_MODIFICADO_REQUIERE_REVISION` — idempotencia CASO B: existe una
  fila en el histórico con el mismo `archivo_global` (mismo
  nombre/periodo, convención `SAP_GLOBAL_TIQ_<MES>_<AÑO>.xlsx`) pero un
  `sha256_archivo` distinto. **No** se trata como GLOBAL nuevo: no se
  leen partidas, no se incorpora nada, no se decide automáticamente cuál
  versión es correcta — requiere decisión humana explícita.
- `ERROR_TECNICO` — GLOBAL no encontrado, nombre no canónico
  (`GLOBAL_NOMBRE_NO_CANONICO`, ver más abajo), hoja `"1"` ausente
  (`GLOBAL_HOJA_1_NO_ENCONTRADA`) o GLOBAL ilegible.

**Duplicados NO se incorporan al histórico mientras existan alertas sin
validar** (reemplaza la regla anterior "si hay duplicados, nunca se
incorpora"; ver subsección "Validación humana" más abajo).
`--dry-run` nunca actualiza el histórico ni escribe el archivo de
revisión bajo ningún estado.

### Nombre canónico del GLOBAL — OBLIGATORIO, sin fallback

El periodo (usado para nombrar `REVISION_ASIGNACIONES_<PERIODO>.csv` y
para el campo `periodo` del resumen) se deriva ÚNICAMENTE de
`archivo_global` con la convención `SAP_GLOBAL_TIQ_<MES>_<AÑO>.xlsx`. Si
el nombre no calza con esa convención, **ya no hay fallback** al nombre
de archivo sin extensión: el control se detiene con `ERROR_TECNICO` /
`GLOBAL_NOMBRE_NO_CANONICO`, ANTES de leer partidas y sin escribir
`REVISION_ASIGNACIONES_*.csv` ni tocar `HISTORICO_ASIGNACIONES.csv`.
Esta validación ocurre incluso antes que los CASO A/B de idempotencia.
(Para mostrar de forma legible el antecedente de una fila ya existente
en el histórico que hubiera sido grabada antes de exigir esta
convención, el `DETALLE` de una alerta usa una variante NO estricta
—`_periodo_para_mostrar()`— que nunca se usa para decidir el periodo del
GLOBAL que se está auditando ahora.)

### Validación humana en Excel (CIERRE DEL MES)

La coincidencia de la Asignacion por sí sola es suficiente para generar
alerta — **una validación humana anterior NUNCA evita una alerta
futura**: si `3P66536982` fue validada `CORRECTA` en agosto y vuelve a
aparecer en septiembre, septiembre vuelve a salir `REVISAR`/pendiente
(la validación de agosto queda solo como antecedente informativo en
`ANTECEDENTE_HISTORICO`).

Cuando hay alertas se crea/actualiza:

```
REVISION_ASIGNACIONES_<PERIODO>.xlsx      (hoja única "REVISION")
```

(mismo directorio que `--historico` por defecto, o `--revision-dir`),
con **UNA FILA POR OCURRENCIA ACTUAL DEL GLOBAL** involucrada en una
alerta — nunca una fila agrupada por asignación: si `3P66536982`
aparece en las filas 146 y 278 del GLOBAL, el Excel trae **dos** filas.
`FILA_GLOBAL` la calcula Python leyendo el GLOBAL — **el auditor nunca
la digita**.

Columnas: `PERIODO, FILA_GLOBAL, ASIGNACION_ORIGINAL, TIPO_ALERTA,
FECHA_VALOR, CUENTA_MAYOR, GLOSA, IMPORTE, ANTECEDENTE_HISTORICO,
VALIDACION_AUDITOR, ASIGNACION_CORRECTA, OBSERVACION_AUDITOR,
FECHA_VALIDACION, SHA256_GLOBAL`. Formato pensado para el auditor:
encabezados en negrita, autofiltro, fila superior congelada, texto
ajustado en GLOSA/OBSERVACION_AUDITOR/ANTECEDENTE_HISTORICO, y una lista
desplegable (`CORRECTA`/`INCORRECTA`) en `VALIDACION_AUDITOR`. El
auditor solo completa `VALIDACION_AUDITOR`, `ASIGNACION_CORRECTA` y
`OBSERVACION_AUDITOR` — el módulo **nunca** decide esos valores por su
cuenta.

**Significado de la validación:**

- `CORRECTA` = "la asignación observada es válida tal como está": no se
  toca esa fila del GLOBAL; la asignación final es la original;
  `ASIGNACION_CORRECTA` se ignora (queda vacía).
- `INCORRECTA` exige `ASIGNACION_CORRECTA` no vacía y distinta de
  `ASIGNACION_ORIGINAL`. Si falta o es igual al original, la fila sigue
  **PENDIENTE** — nunca se asume una corrección.

Al reejecutar sobre el mismo SHA-256, `fusionar_filas_revision()`
conserva las decisiones humanas ya escritas (emparejando por
`FILA_GLOBAL`):

- si queda alguna fila sin resolver →
  `estado_validacion = PENDIENTE_VALIDACION_AUDITOR` (con `estado`
  siempre en `REVISAR_DUPLICADOS_ENCONTRADOS`); **no** se toca el
  GLOBAL, no se actualiza el histórico — solo se regenera el .xlsx;
- si TODAS están resueltas, antes de cerrar se aplican las correcciones
  **EN MEMORIA** y se vuelve a evaluar duplicados con las asignaciones
  **finales** contra el propio GLOBAL y el histórico. Si esa
  reevaluación descubre una ocurrencia nueva no vista antes (una
  corrección que generaría una duplicidad silenciosa), el cierre se
  aborta: esa ocurrencia se incorpora al .xlsx (preservando TODAS las
  decisiones anteriores, incluida una duplicidad ya marcada `CORRECTA`
  explícitamente, que puede permanecer) y el mes sigue
  `PENDIENTE_VALIDACION_AUDITOR`. Solo si no aparece nada nuevo se
  cierra: `estado_validacion = CERRADO_CON_VALIDACION_AUDITOR`.

**Corrección del GLOBAL (solo al cerrar, todo o nada):** se reabre el
GLOBAL en modo escritura (nunca `read_only`, nunca `data_only` — así se
conservan fórmulas/formato del resto del workbook), se verifica que cada
`R[fila]` siga conteniendo exactamente `ASIGNACION_ORIGINAL` para TODAS
las correcciones a aplicar, y solo si todas verifican se reemplaza esa
única celda por `ASIGNACION_CORRECTA` en cada una — ninguna otra celda
se toca. Si una sola verificación falla, no se aplica ninguna
(`aplicar_correcciones_global()` lanza `CorreccionInvalidaError` sin
escribir nada). Se sobrescribe el **mismo** archivo
`SAP_GLOBAL_TIQ_<MES>_<AÑO>.xlsx` — nunca se crea un `_VALIDADO` ni una
copia de respaldo productiva. `FECHA_VALIDACION` vacía se autocompleta
con la fecha de cierre.

**Guardarraíl SHA256_GLOBAL:** una fila de `REVISION_ASIGNACIONES_*.xlsx`
solo se reutiliza si su `SHA256_GLOBAL` coincide con el GLOBAL actual —
si el GLOBAL cambió de contenido antes de cerrarse, esa validación
previa **nunca** se aplica en silencio; la alerta nace de nuevo sin
validar.

**Compatibilidad con el CSV de revisión anterior:** si existe un
`REVISION_ASIGNACIONES_<PERIODO>.csv` del esquema previo (una fila por
asignación) para el mismo SHA y todavía no existe el `.xlsx`, sus
decisiones (`VALIDACION_AUDITOR`/`OBSERVACION_AUDITOR`/
`FECHA_VALIDACION`) se importan como semilla al generar el `.xlsx` por
primera vez. Ese CSV nunca se borra ni se vuelve a escribir.

**Ciclo completo:**

```
GLOBAL
  → CONTROL 1 (control_asignaciones.py)
  → REVISION_ASIGNACIONES_<PERIODO>.xlsx (una fila por ocurrencia)
  → auditor revisa directamente en Excel: CORRECTA / INCORRECTA + asignación correcta
  → rerun
  → CONTROL 1 corrige ÚNICAMENTE columna R de las filas autorizadas
  → sobrescribe el mismo GLOBAL
  → actualiza HISTORICO_ASIGNACIONES.csv (con la asignación FINAL)
  → GLOBAL listo para cargar a SAP
  → mes siguiente vuelve a comparar contra el histórico (asignación final, validaciones incluidas)
```

No existe ningún mecanismo de override que salte la validación humana
(requiere autorización futura, fuera de este módulo).

**Seguridad de escritura:** el GLOBAL es solo lectura MIENTRAS haya
alertas sin validar (`leer_partidas_global` nunca guarda nada). Una vez
cerrado, el único cambio autorizado sobre el GLOBAL es la celda
Asignacion (R) de las filas explícitamente corregidas. El script además
escribe `HISTORICO_ASIGNACIONES.csv`, `REVISION_ASIGNACIONES_*.xlsx` y
el JSON de detalle (`--salida-json`). Nunca toca SAP diarios, cierres,
MACROS, plantilla, marcadores PROCESADO ni el motor diario.

**Idempotencia sobre el GLOBAL final:** si el mes ya fue cerrado y el
GLOBAL actual coincide con el `sha256_global_final` registrado →
`YA_PROCESADO_SIN_CAMBIOS` (la corrección autorizada del propio CONTROL 1
nunca se interpreta como `GLOBAL_MODIFICADO_REQUIERE_REVISION`). Si el
mismo GLOBAL cambia después a un SHA distinto del final registrado (una
edición NO autorizada), se mantiene el guardarraíl existente:
`GLOBAL_MODIFICADO_REQUIERE_REVISION`.

El JSON de detalle conserva los hallazgos "por par" (`hallazgos`,
formato anterior, basado en las asignaciones ORIGINALES) y agrega, entre
otros: `filas_revisadas`, `filas_correctas`, `filas_incorrectas`,
`correcciones_aplicadas`, `global_modificado`,
`sha256_global_original`, `sha256_global_final` (además de los alias
retrocompatibles `alertas_pendientes_validacion`/`alertas_correctas`/
`alertas_incorrectas` con el mismo significado que
`filas_pendientes`/`filas_correctas`/`filas_incorrectas`).

**Sin dependencias de Google Drive ni Base64:** opera exclusivamente
sobre rutas de archivo locales ya materializadas; la responsabilidad de
materializar/publicar en Drive es de quien invoca el script
(Cowork/`auditor-caja-tiquipaya`), nunca de este módulo.

**JSON PUENTE de decisiones (`--revision-json`) — vía alterna de
producción:** el `.xlsx` (`REVISION_ASIGNACIONES_<PERIODO>.xlsx`) sigue
siendo la **única interfaz del auditor humano**: es donde revisa cada
ocurrencia y completa `VALIDACION_AUDITOR`/`ASIGNACION_CORRECTA`/
`OBSERVACION_AUDITOR` directamente en Drive, sin descargar ni subir nada.
El problema que resuelve `--revision-json` es puramente técnico: Cowork
puede **leer** ese `.xlsx` vía su conector de Drive, pero no siempre
puede materializar el binario en un filesystem accesible a Python sin
recurrir a una transcripción Base64 (prohibida en todo el proyecto, y
bloqueada además por el guardrail HOOK 1). La solución es que Cowork
genere un **JSON pequeño** con las decisiones que ya leyó del `.xlsx.`
Este JSON es un **puente técnico**, nunca una interfaz nueva para el
auditor: el auditor jamás lo edita, jamás sabe que existe.

Formato sugerido: `REVISION_ASIGNACIONES_<PERIODO>_DECISIONES.json`

```json
{
  "periodo": "AGOSTO_2026",
  "sha256_global": "...",
  "decisiones": [
    {
      "fila_global": 278,
      "asignacion_original": "3P66536982",
      "validacion_auditor": "INCORRECTA",
      "asignacion_correcta": "3P79981158",
      "observacion_auditor": "ERROR DE TAIPEO EN VOUCHER"
    },
    {
      "fila_global": 26,
      "asignacion_original": "FORTALEZA",
      "validacion_auditor": "CORRECTA",
      "asignacion_correcta": "",
      "observacion_auditor": "CUENTAS POR COBRAR FORTALEZA"
    }
  ]
}
```

Uso: `python control_asignaciones.py --global ... --historico ...
--revision-json /ruta/REVISION_ASIGNACIONES_AGOSTO_2026_DECISIONES.json`
(mutuamente excluyente en cada corrida con `--revision-dir`/el `.xlsx`:
si se pasa `--revision-json`, esa corrida **no lee ni escribe** el
`.xlsx` ni el CSV legado — el `.xlsx` de Drive permanece exactamente
como el auditor lo dejó). Ambas vías (`.xlsx` y JSON) convergen en la
**misma** función de validación/fusión (`fusionar_filas_revision` para
el `.xlsx`, `validar_y_construir_filas_desde_json` para el JSON, ambas
produciendo filas con la misma forma) y comparten sin duplicación toda
la lógica posterior: reevaluación de duplicados con asignaciones
finales, aplicación todo-o-nada de correcciones sobre la columna R, y
escritura del histórico.

El JSON **no es confianza ciega**: antes de aceptar cualquier
corrección se valida contra el estado ACTUAL del GLOBAL — periodo
coincide, `sha256_global` coincide con el GLOBAL vigente, cada
`fila_global` corresponde a una alerta real y vigente, `
asignacion_original` coincide exactamente con la celda R de esa fila,
`validacion_auditor` es `CORRECTA` o `INCORRECTA`, `INCORRECTA` exige
`asignacion_correcta` no vacía y distinta de la original, no se
aceptan filas que no correspondan a una alerta real, no se aceptan
decisiones duplicadas para la misma ocurrencia, y deben estar
representadas TODAS las alertas vigentes (ninguna puede quedar sin
decisión). Si **cualquier** regla falla, se rechaza el lote **completo**
(nunca una corrección parcial): no se toca el GLOBAL, no se toca el
histórico, y el resumen queda `PENDIENTE_VALIDACION_AUDITOR` con el
detalle de cada problema en `problemas_revision_json`.

**Nueva duplicidad generada por una corrección, en vía JSON:** si al
aplicar las correcciones en memoria la reevaluación final descubre una
ocurrencia nueva no vista antes, Cowork no puede decidirla por sí solo
(no es una decisión que venga en el JSON). En ese caso CONTROL 1: no
toca el GLOBAL, no toca el histórico, mantiene el mes
`PENDIENTE_VALIDACION_AUDITOR`, y **sí genera o actualiza localmente**
`REVISION_ASIGNACIONES_<PERIODO>.xlsx` incorporando la nueva ocurrencia
sin validar (`VALIDACION_AUDITOR` vacío) y **preservando** dentro de
ese mismo `.xlsx` las decisiones ya recibidas por JSON
(`VALIDACION_AUDITOR`/`ASIGNACION_CORRECTA`/`OBSERVACION_AUDITOR` de
las filas ya decididas). `resumen["ruta_revision"]` pasa a apuntar a
ese `.xlsx` local (no al JSON) para que Cowork sepa exactamente qué
archivo publicar en Drive — sin necesidad de descargar ningún `.xlsx`
anterior. Una vez que el auditor completa esa fila nueva directamente
en Drive, una corrida posterior (vía `.xlsx` normal, o vía un nuevo
JSON que Cowork genere tras releer esa decisión) cierra el mes
normalmente. `nuevas_alertas_generadas` en el resumen indica cuántas
ocurrencias nuevas aparecieron en la corrida.

Nuevos campos del resumen: `fuente_revision` (`"xlsx"` o `"json"`),
`problemas_revision_json` (lista de problemas de validación, vacía si
todo fue válido) y `nuevas_alertas_generadas`.

**Integración futura:** pensado para ser invocado por la Skill
`auditor-caja-tiquipaya` después de que `consolidador_mensual.py` genera
el SAP GLOBAL del mes; la Skill se actualiza manualmente y por separado
(no se edita desde Code).

Tests: `tests/test_control_asignaciones.py` (64 pruebas: las 46
anteriores sin cambios + 18 nuevas para `--revision-json` — conserva y
adapta los escenarios de las etapas anteriores sin reducir cobertura, y
agrega la validación humana en Excel + corrección del GLOBAL: se genera
el `.xlsx` con una fila por ocurrencia (nunca agrupada por asignación) y
`FILA_GLOBAL` calculada por Python; la lista desplegable
`CORRECTA`/`INCORRECTA` existe; las decisiones humanas sobreviven a la
reejecución; `CORRECTA` nunca modifica el GLOBAL; `INCORRECTA` sin
`ASIGNACION_CORRECTA` válida queda pendiente; `INCORRECTA` con
`ASIGNACION_CORRECTA` modifica ÚNICAMENTE `R[fila]` (el resto de columnas
y filas del GLOBAL permanece idéntico); varias correcciones se aplican
juntas; una sola fila pendiente bloquea TODAS las correcciones; un SHA
distinto o un `ASIGNACION_ORIGINAL` que ya no coincide con la celda
impiden aplicar cualquier corrección (todo o nada); una corrección que
generaría una nueva duplicidad silenciosa bloquea el cierre y preserva
todas las decisiones previas (incluida una duplicidad ya marcada
`CORRECTA`); el histórico registra `asignacion` = FINAL y conserva
`asignacion_original`; el mes siguiente compara contra la asignación
final y una validación `CORRECTA` anterior NO evita una alerta futura;
`sha256_global_original`/`sha256_global_final` quedan registrados; un
rerun sobre el GLOBAL final ya cerrado es `YA_PROCESADO_SIN_CAMBIOS`,
mientras que un cambio posterior NO autorizado dispara
`GLOBAL_MODIFICADO_REQUIERE_REVISION`; el CSV de revisión del esquema
anterior sigue funcionando como semilla de decisiones; `--dry-run` no
modifica el `.xlsx`, el GLOBAL ni el histórico; exclusiones
SFC101/SFC102/TIQUIPAYA `<MES>`/cuenta 110201008 y FORTALEZA siempre
evaluada permanecen intactas; hoja `"1"` y nombre canónico del GLOBAL
siguen obligatorios sin fallback; y ausencia de dependencias de Google
Drive/Base64/módulos del V2 diario). Las 18 pruebas nuevas cubren la vía
`--revision-json`: cierre correcto, `CORRECTA` no modifica la fila,
`INCORRECTA` corrige únicamente la columna R, SHA/fila/`
ASIGNACION_ORIGINAL` inválidos bloquean, decisión faltante/extra/
duplicada bloquean, `INCORRECTA` sin `ASIGNACION_CORRECTA` bloquea, una
nueva duplicidad generada por una corrección bloquea el cierre sin
tocar GLOBAL/histórico Y genera/actualiza localmente el `.xlsx`
preservando las decisiones ya recibidas por JSON con la nueva alerta
sin validar, un rerun posterior (una vez el auditor valida esa nueva
alerta directamente en ese `.xlsx`) sí cierra el mes, el histórico
conserva la decisión y la asignación final, la idempotencia sobre el
GLOBAL final sigue funcionando, el flujo `.xlsx` existente no tiene
regresión, `--dry-run` con `--revision-json` no escribe nada, y la vía
JSON ignora por completo un `.xlsx`/CSV legado existente en el mismo
directorio.
