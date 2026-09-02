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
