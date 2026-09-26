---
name: auditor-cierres
description: >-
  Auditor de cierres .xlsm de Caja Tiquipaya y Caja America, cloud end-to-end. Localiza las ENTRADAS oficiales y el MACROS mensual en Google Drive, materializa temporalmente los binarios, ejecuta 6 controles (cuadre, comunicaciones internas, banco y cuenta, asignacion, fecha de deposito, alquileres), valida en lectura con el motor CAJAS GABO y genera RESUMEN_GABO.pdf, un PDF breve para cada caja y AUDITORIA_CIERRES_RESULTADOS.zip con el detalle tecnico. Drive es solo fuente de lectura y no se publica nada. Los originales nunca se modifican; solo se normaliza FECHA DE DEPOSITO sobre una copia. El usuario no debe descargar, sincronizar ni dar rutas. Usar para auditar cierres, verificar fechas de deposito, ver alquileres o preparar cierres antes de procesarlos con CAJAS GABO.
---

# Auditor de Cierres

Skill de **flujo cloud completo**. Un cierre "en ENTRADA" vive en Google Drive: la Skill lo obtiene sola con el conector de Drive.
**El usuario nunca descarga ni sincroniza nada ni entrega rutas locales.** Si Claude se descubre a punto de pedirle una ruta
o una descarga al usuario, es un error de ejecucion: debe seguir el flujo de abajo o, si el conector de Drive no esta
disponible en la sesion, detenerse e informar esa causa tecnica exacta.

```
Drive ENTRADA (TIQ + AME) + MACROS (solo lectura) -> materializacion temporal -> auditar.py (6 controles) -> validacion motor CAJAS GABO
   -> RESUMEN_GABO.pdf + PARA_CAJA_*.pdf + AUDITORIA_CIERRES_RESULTADOS.zip -> entrega al usuario en la sesion -> limpieza temporal
```

Independiente de CAJAS GABO en codigo (no lo modifica ni ejecuta n8n); solo LEE su motor (`excel_io.leer_cierre` y
`v3.precheck_maestro`) para validar. Un unico proceso Python de auditoria, una pasada por archivo.

## Flujo CLOUD (uso normal) — pasos que Claude ejecuta

Ubicaciones oficiales, IDs y reglas de verificacion: `config_nube.json` (misma fuente que `config_drive_oficial.py` de CAJAS GABO).
Herramientas del conector de Drive: `search_files`, `get_file_metadata`, `download_file_content`
(si figuran como diferidas, cargarlas con ToolSearch en **una sola** llamada).

**Drive es SOLO LECTURA, sin excepciones.** Prohibido usar `create_file`, `update_file`, `trash_file`, `share_file`, `copy_file` o cualquier
otra escritura: no se sube ningun informe, resultado ni cierre normalizado, ni se crean carpetas.

1. **Sesion temporal.** `python scripts/nube_drive.py iniciar` -> `{"sesion": "<dir temporal>"}`.
2. **Localizar las ENTRADAS oficiales.** Por cada caja (`tiquipaya`, `america`) de `config_nube.json`:
   `get_file_metadata(entradas.<caja>.id)` y comprobar `title` y `parentId` contra el config; ademas el id no puede estar en
   `carpetas_prohibidas` (p. ej. `00_ENTRADA_TEST_AME`). Si algo no coincide: **falla cerrado** para esa caja y se informa.
   Listar con `search_files` (`parentId = '<id>'`, `excludeContentSnippets: true`) **paginando hasta que no haya `nextPageToken`**
   (una pagina final puede venir vacia). Son cierres los archivos de nombre exacto `CIERRE DD-MM-YYYY.xlsm` (`fileExtension` xlsm,
   no carpetas). Todo lo demas se **ignora y se informa** por nombre. Nombre repetido en una misma ENTRADA = ambiguo: no elegir, informar.
   Guardar el conteo con `nube_drive.py anotar --sesion S --clave entrada_<caja> --valor '{"cierres":N,"ignorados":[...]}'`.
3. **MACROS oficial.** Para cada mes distinto presente en las fechas de los cierres (`AAAA-MM`): carpeta anio (`AAAA`) y carpeta periodo
   (`AAAA-MM`) bajo `macros.raiz_id` (verificar titulo y padre con `get_file_metadata`; los `ids_conocidos` son atajos, no verdad),
   y dentro el archivo de nombre exacto `MACROS <MES>.xlsm` (`SEPTIEMBRE`, ...). 0 coincidencias -> `MACROS_OFICIAL_NO_ENCONTRADO`;
   mas de 1 -> `ERROR_AMBIGUO_MACROS`; carpeta del periodo inexistente -> `MACROS_OFICIAL_NO_CONFIGURADO`. Ninguno de los tres detiene
   la auditoria: ese mes se audita **sin MACROS** (las normalizaciones de formato de fecha siguen aplicando; el informe avisa que no
   hubo contraste con vouchers). Un solo MACROS institucional sirve a ambas cajas.
4. **Materializar binarios (sin reconstruir base64).** Por cada cierre y cada MACROS: `download_file_content(fileId)` **sin**
   `exportMimeType`. El archivo es mas grande que el limite de respuesta, asi que el harness lo **guarda en disco** como JSON
   `{content(base64), id, mimeType, title}` y responde `Output has been saved to <RUTA>`. Con esa `<RUTA>` (sin abrirla) ejecutar:
   `python scripts/nube_drive.py registrar --sesion S --rol cierre|macros --caja <caja> --drive-id <id> --nombre "<title>" --tam-drive <fileSize del listado> --json-fuente "<RUTA>" --modificado <modifiedTime>`.
   `registrar` decodifica con Python, exige mismo id, mismo titulo y **mismo tamano que Drive**, ZIP integro y estructura de libro,
   guarda el `.xlsm` bit a bit en la carpeta temporal y **borra el JSON con el base64**. **Nunca** leer ese JSON, ni copiar base64 a un
   comando o archivo. Si la respuesta llega **en linea** (sin "saved to <RUTA>"), o `registrar` falla: ese archivo queda
   `NO_MATERIALIZADO`, se informa y se sigue con los demas; nunca se reescribe a mano.
5. **Auditar (un solo comando).** `python scripts/auditar.py --manifiesto "<sesion>/manifiesto.json"`. Ejecuta los 6 controles, escribe las
   copias normalizadas (Control 5) y **despues** valida con el motor CAJAS GABO, en solo lectura (lector del SAP + cobertura de MACROS),
   **exactamente el archivo que se entrega**: la copia normalizada resultante; si el cierre no necesito cambios, su copia temporal
   equivalente (el mismo archivo materializado). Nunca se valida el original previo a la normalizacion, para no crear falsas discrepancias
   de lectura (p. ej. `23/09/26` que el auditor ya normalizo a `23/09/2026`). Orden: original en Drive (solo lectura) -> copia temporal ->
   el auditor normaliza la copia -> el motor valida la copia resultante -> informe/resultados.
   Deja en una carpeta nueva `~/AuditoriaCierres/<AAAA-MM-DD_HHMMSS>/` **la salida estandar, y nada mas**:
   - `RESUMEN_GABO.pdf`: resumen breve para Gabo;
   - `PARA_CAJA_AMERICA.pdf` y `PARA_CAJA_TIQUIPAYA.pdf`: solo acciones que corresponden a cada caja; usan "registros bancarios", nunca
     el nombre interno MACROS, omiten fechas ya normalizadas automaticamente y problemas que dependen solo de actualizar registros bancarios;
   - `AUDITORIA_CIERRES_RESULTADOS.zip`: todo el detalle tecnico: `INFORME_AUDITORIA_CIERRES.pdf` y `.docx` +
     `DETALLE_TECNICO_AUDITORIA.xlsx` (Excel interno, **no** es
     el informe) + `RESULTADOS_AUDITORIA.json` (incluye el contenido del informe y la validacion detallada del motor) +
     `HALLAZGOS_AUDITORIA.csv` + `CIERRES_NORMALIZADOS/<CAJA>/*.xlsm` (copias con la fecha normalizada) + `RECURSOS_USADOS.txt`
     (solo metricas medidas o contadas).
   Los sueltos tecnicos (informe largo PDF/DOCX, Excel, json, csv, recursos y copias) se borran al crear el ZIP. Leer **solo el stdout**
   (JSON compacto); las rutas absolutas estan en `archivos.resumen_gabo`, `archivos.para_caja_america`,
   `archivos.para_caja_tiquipaya` y `archivos.zip`. Si falla el informe tecnico PDF/DOCX, el JSON trae
   `informe_humano_incidencias`; los demas detalles permanecen dentro del ZIP.
6. **Entregar al usuario en la sesion (sin Drive).** Con la herramienta `SendUserFile` enviar exactamente los cuatro entregables
   (`RESUMEN_GABO.pdf`, los dos `PARA_CAJA_*.pdf` y el ZIP) para descarga directa. Nunca enviar el informe largo, el DOCX o el Excel
   tecnico como archivo suelto. Si `SendUserFile` no estuviera disponible, informar las rutas absolutas locales; nunca subirlos a Drive.
7. **Limpiar.** `python scripts/nube_drive.py limpiar --sesion S` (borra cierres y MACROS temporales y el manifiesto; solo actua sobre
   carpetas de sesion propias). Confirmar `"ok":true`, que ningun JSON `mcp-*download_file_content*` quedo en `tool-results` y que la carpeta
   de la corrida solo contiene los tres PDF breves y el ZIP. La salida final (esos cuatro archivos) **no** se borra.
8. **Informar** en lenguaje simple: cierres revisados por caja / sin observaciones / a revisar, hallazgos (max. 15), alquileres por dia y
   total, resultado de la validacion con el motor, MACROS usado (o su ausencia), los cuatro archivos entregados, el resultado de la limpieza y
   toda incidencia (archivos ignorados, no materializados, ambiguos). Si hay mas hallazgos: remitir al informe.

Reglas de eficiencia: **no abrir ni leer los Excel** (ni cierres, ni MACROS, ni el reporte): Python lo hace todo. Si el usuario pide el
detalle de un cierre, esta en el informe.

## Reglas de seguridad (siempre)

- **Los originales de Drive nunca se modifican.** El unico dato que la Skill puede modificar es `FECHA DE DEPOSITO` (Control 5), y solo
  escribiendo una **copia** en `CIERRES_NORMALIZADOS`. Controles 1, 2, 3, 4 y 6 son estrictamente LEER -> VALIDAR -> REPORTAR: nunca completan ni corrigen.
- La falta o falta de cobertura de MACROS **no impide** normalizar el formato de una fecha de texto valida (Control 5); solo impide contrastarla.
- Drive: **solo lectura, sin excepciones**. No se publican informes ni cierres normalizados en Drive ni en OneDrive; los resultados se entregan por la sesion.
- Los binarios temporales viven solo en la carpeta de sesion; se borran al final (paso 7), incluso si la auditoria termino con hallazgos.
- Nunca Excel COM ni `openpyxl.save()` sobre cierres: la escritura es edicion XML quirurgica (`scripts/xlsm_xml.py`).
- Ante una situacion no contemplada: no inventar regla, reportarla.
- El nombre del cierre debe conservar `DD-MM-YYYY` (de ahi sale la fecha del cierre).

## Uso manual (rutas locales explicitas; solo pruebas o si el usuario las entrega por decision propia)

```bash
python ~/.claude/skills/auditor-cierres/scripts/auditar.py \
  --macros "MACROS SEPTIEMBRE.xlsm" \
  --caja tiquipaya --cierre "CIERRE 09-09-2026.xlsm" --cierre "CIERRE 10-09-2026.xlsm" \
  --caja america --carpeta "C:/cierres/america" \
  --salida-dir "C:/salida" --reporte-dir "C:/reportes"
```

(En Windows: `C:\Users\<usuario>\.claude\skills\auditor-cierres\scripts\auditar.py`.)

- `--caja tiquipaya|america`: aplica a los `--cierre`/`--carpeta` que le siguen (nunca se infiere del archivo).
  `--carpeta` toma todos los `CIERRE*.xlsm` de la carpeta.
- `--macros`: MACROS mensual (repetible; se combinan). Sin MACROS (o ilegible) el Control 5 **no se detiene**: normaliza el formato de las fechas de texto validas y avisa que no hubo contraste con vouchers.
- `--manifiesto`: modo nube (cierres + MACROS + trazabilidad de Drive del manifiesto de `nube_drive.py`); por defecto escribe en `~/AuditoriaCierres/<fecha>/`.
- `--sin-motor` / `--motor-dir DIR`: omitir o ubicar la validacion con el motor CAJAS GABO (por defecto se busca en `CAJAS_GABO_MOTOR_DIR` y en `config_nube.json`; si no esta, se informa y la auditoria sigue).
- `--salida-dir`: si se indica, el Control 5 escribe copias con la fecha normalizada en `<salida-dir>/TIQUIPAYA/` y `<salida-dir>/AMERICA/` (nunca se pisan entre cajas; un nombre repetido dentro de la misma caja se avisa como colision y no se sobrescribe). Sin esto solo diagnostica y avisa "por corregir".
- `--reporte-dir`: carpeta de la corrida (por defecto la actual; en modo nube, una nueva `~/AuditoriaCierres/<fecha_hora>`). Recibe los tres PDF breves y el ZIP. Si ya contiene entregables de otra corrida, la auditoria se detiene con `SALIDA_YA_EXISTE` (nunca se sobrescribe). Las copias normalizadas que caigan dentro de esa carpeta se empaquetan y se borran sueltas; con `--salida-dir` fuera de ella, las copias se conservan ahi y tambien van en el ZIP.
- Requisitos: Python 3.10+, `openpyxl` (lee MACROS y crea el Excel interno), `reportlab` (PDF) y `python-docx` (DOCX): `pip install openpyxl reportlab python-docx`. Todo lo demas es biblioteca estandar.

### Salida (stdout, JSON compacto)

`estado` (`OK`/`CON_HALLAZGOS`/`ERROR`), `cierres` {revisados, sin_observaciones, requieren_revision}, `cuadres_ok`,
`fechas_normalizadas`, `hallazgos` (max. 15 + "y N adicionales; ver reporte"), `especiales_a_completar`,
`alquileres` {dias, detalle, total_periodo}, `reporte` (ruta de `RESUMEN_GABO.pdf`), `archivos`
{pdf/resumen_gabo, para_caja_america, para_caja_tiquipaya, zip, contenido_zip},
`motor_cajas_gabo` {disponible, sin_observaciones, con_observaciones | motivo},
`candidatos_voucher` (solo si hubo depositos sin voucher exacto: una linea por deposito con su veredicto; max. 10).
(Ante un error, p. ej. `SALIDA_YA_EXISTE`, el JSON trae `estado: ERROR` y el detalle.)

### Reportes breves (`RESUMEN_GABO.pdf` / `PARA_CAJA_*.pdf`)

`scripts/informe_corto.py` usa exclusivamente los datos estructurados de cada hallazgo (`datos.tipo`, `datos.motivo`,
`datos.candidatos`, etc.); no analiza las frases de `hallazgo`. Los PDF de caja solo muestran acciones de caja: nunca incluyen la
palabra interna `MACROS`, fechas que ya se normalizaron automaticamente ni problemas que dependan unicamente de actualizar registros
bancarios. Una fecha imposible/no resoluble si se muestra con su valor. ALQUILERES nunca se presenta como error de banco/cuenta; si fue
marcado en ASIGNACION, `marcado_en` permite mostrar solo a Gabo la nota pertinente sobre el motor.

### Informe tecnico (`INFORME_AUDITORIA_CIERRES.pdf` / `.docx`, solo dentro del ZIP)

Solo presentacion (`scripts/informe_humano.py`): traduce los hallazgos ya calculados a lenguaje natural; no cambia ninguna regla. Un unico
modelo de contenido alimenta el PDF y el DOCX, por lo que dicen exactamente lo mismo. A4 vertical, fondo blanco, sobrio, legible en blanco
y negro (el estado se lee por su texto, no solo por color), encabezado de tabla repetido, filas que no se parten, pie
`CAJAS GABO — Auditoría de cierres` y `Página X de Y`. Sin codigos internos, trazas, nombres de funciones ni rutas.

1. **Resumen ejecutivo**: fecha y hora, periodo, cajas, total de cierres; recuadros `Cierres revisados | Sin observaciones | Requieren revisión |
   Informativos | Correcciones automáticas`; tabla `Caja | Fecha del cierre | Estado | Motivo principal` con solo tres estados:
   `SIN OBSERVACIONES`, `REQUIERE REVISIÓN`, `OBSERVACIÓN INFORMATIVA` (un cierre cuyo unico hallazgo es una correccion automatica o un hecho
   informativo es *informativo*; `requiere revision` coincide exactamente con los cierres "a revisar" de la auditoria).
2. **Casos que requieren revisión**: `Caja | Fecha | Qué ocurrió | Qué debe revisarse` (filas repetidas del mismo problema se agrupan).
   **2.1 Detalle de vouchers no encontrados en MACROS** (solo si hay casos): por cada deposito sin voucher exacto, los datos declarados en el
   cierre, la tabla `Fecha | Importe | Asignación / Voucher | Cuenta / Banco | Caja / SFC | Coincidencias | Diferencias` con todos los candidatos
   razonables de MACROS, el veredicto (`CANDIDATO PROBABLE` / `CANDIDATO POSIBLE — REVISIÓN MANUAL` / `VARIOS CANDIDATOS — REVISIÓN MANUAL` / `SIN CANDIDATOS EN MACROS`), la
   interpretacion probable en lenguaje humano y la accion requerida al cajero. Es solo una ayuda: nunca se corrige el cierre.
3. **Correcciones automáticas**: `Caja | Fecha del cierre | Campo | Valor original | Valor normalizado | Motivo` (normalizacion de formato,
   tolerancia de 1 dia de MACROS e inversion DD/MM confirmada por voucher, explicadas en lenguaje natural).
4. **Observaciones informativas**: cada una termina con `Acción requerida: Ninguna.`
5. **Conclusión** breve y sin alarmismo, generada con las cifras reales; **Anexo** breve (MACROS usados, validacion con el motor, alquileres).

El Excel `DETALLE_TECNICO_AUDITORIA.xlsx` (hojas Resumen, Auditoria, Alquileres, Completar a mano, Validacion motor) existe solo dentro del ZIP.

### Contenido tecnico del Excel interno

- **Resumen**: cierres revisados, sin observaciones, a revisar, fechas normalizadas, dias con alquileres, importe total de alquileres, y estado por cierre.
- **Auditoria**: `FECHA | CAJA | SFC | RESULTADO | HALLAZGO | ACCION` (incluye los cuadres correctos y las fechas corregidas).
- **Alquileres**: `FECHA | CAJA | SFC | IMPORTE`, con total por dia y total del periodo.
- **Completar a mano**: filas OTROS INGRESOS / GASTO.ADM / POSGRADO.PLA con fecha, caja, SFC, importe y que falta.
- **Validacion motor** (control 7, solo lectura): por cierre, lectura con el lector del SAP de CAJAS GABO, depositos leidos y cobertura de MACROS. Columnas `ARCHIVO VALIDADO` y `FECHAS DE DEPOSITO QUE LEYO EL MOTOR`.

## Controles

| # | Que hace | Regla |
|---|---|---|
| 1 | Cuadre de recaudacion (cada hoja SFC) | Efectivo disponible + Dolares + Cheques + Cobros ATC + Total comunicaciones internas - Facturas anuladas = Total movimiento del dia. Campos por etiqueta; `Decimal`; comparacion a centavos. Si falta un campo: no se asume cero, se avisa. |
| 2 | Comunicaciones Internas completas | En filas usadas (con N°/factura): BANCO, CUENTA CONTABLE BANCO y ASIGNACION deben estar llenos. Nunca se completa. |
| 3 | BANCO <-> CUENTA CONTABLE | Tabla oficial unica (`scripts/catalogo_bancos.py`). Sufijos MN/ME/AH/EURO/CLINICA importan; sin sufijo se asume MN; alias BANECO=BANCO ECONOMICO, BUSA=BANCO UNION, BMS=BMSC. |
| 4 | Formato de ASIGNACION (solo Comunicaciones Internas) | Por familia: BANECO/BUSA/BCP/BISA -> numerico; BMS/BNB -> alfanumerico (con letras). |
| 5 | FECHA DE DEPOSITO vs voucher MACROS | Ver abajo. Unico control que modifica (copia). |
| 6 | Alquileres | Filas de Comunicaciones Internas con BANCO = ALQUILERES (o, con BANCO vacio, ASIGNACION = ALQUILERES; quedan exentas de los controles 2, 3 y 4): fecha (FECHA2; si falta, la del cierre y se marca), caja, SFC, importe; total por dia y del periodo. |

**Categorias especiales** (OTROS INGRESOS, GASTO.ADM, POSGRADO.PLA): solo se exige BANCO; no entran a los controles 3 y 4; **siempre** se listan
(fecha, caja, SFC) para que el usuario complete cuenta y asignacion a mano. ALQUILERES esta exento de los controles 2, 3 y 4 y va al Control 6.

### Control 5 — FECHA DE DEPOSITO (regla definitiva)

Evidencia: voucher de MACROS por **asignacion + importe**, valido solo si es **unico y exacto**. Sin ventana de dias ni proximidad al cierre. La ausencia de voucher no impide normalizar el **formato** de un texto valido, pero sin voucher nunca se corrige un valor (ni inversiones DD/MM). Un voucher no unico o sin fecha valida sigue siendo revision manual.

| Situacion (solo filas con IMPORTE > 0) | Resultado |
|---|---|
| fecha Excel = voucher | correcta, sin hallazgo |
| diferencia exacta de **1 dia calendario** con el voucher (±1) | aceptable por tolerancia: **no se cambia el valor**; un texto valido pasa a fecha Excel real con el mismo valor; traza `FECHA_DENTRO_TOLERANCIA_MACROS_1_DIA` (fecha en el cierre y fecha en MACROS) |
| diferencia mayor a 1 dia | avisar, no corregir el valor |
| fecha Excel con DD<->MM invertidos = voucher | normalizar |
| texto `D/M/YYYY`, `DD/M/YYYY`, `DD/MM/YYYY`, `D/M/YY` o `DD/MM/YY` (fecha real; el año de 2 dígitos solo se acepta si es el año del cierre) = voucher | convertir a fecha Excel real |
| texto de fecha valido **sin voucher en MACROS** (o MACROS sin cobertura) | convertir solo el formato a fecha Excel real (mismo dia/mes/año; año de 2 digitos = año del cierre) y dejar traza `FECHA_NORMALIZADA_SIN_VOUCHER_MACROS` con valor original y normalizado |
| celda vacia | avisar, no completar |
| cualquier otro caso | avisar, no modificar |

**Candidatos cuando no hay voucher exacto** (`scripts/candidatos_voucher.py`; solo evidencia adicional para el informe, no cambia ninguna regla anterior). Se ejecuta cuando
un deposito queda en revision por `SIN_VOUCHER_EN_MACROS` / `ASIGNACION_VACIA_SIN_VOUCHER` y **tambien** cuando una fecha de texto valida sin voucher se normaliza sola. La
clasificacion, el plan y la normalizacion NO dependen de la busqueda (corre aislada: si fallara, `candidatos` queda en None). Nunca se corrige nada a partir de un candidato.
Busca en MACROS registros con **importe exacto**, misma **cuenta/banco**, misma **caja/SFC** y **fecha esperada ±1 dia** (fecha esperada = dia siguiente al cierre; si es
domingo, el lunes); si no hay candidato fuerte, tambien el importe exacto en otras fechas del mismo MACROS. Un candidato es razonable si el importe es exacto y no difiere a la
vez en cuenta y caja. Un dato no verificable (falta en el cierre o en MACROS) no descarta al candidato, pero impide que sea probable. Cuatro veredictos:
`CANDIDATO PROBABLE` (unico candidato con los cuatro criterios), `CANDIDATO POSIBLE — REVISIÓN MANUAL` (unico candidato fuera de ±1 dia, con coincidencia parcial o con criterios
no verificables), `VARIOS CANDIDATOS — REVISIÓN MANUAL` (mas de un candidato razonable) y `SIN CANDIDATOS EN MACROS`. Cada candidato lista coincidencias y diferencias
(asignacion, fecha —incluida la inversion de dia y mes—, cuenta, caja, importe unico en MACROS). El resultado va en `datos.candidatos` del hallazgo (JSON), en la seccion 2.1
del PDF/DOCX (con una leyenda de los cuatro veredictos) y en `candidatos_voucher` del stdout.

Detalle en `references/control5_regla.md`. Garantias del mecanismo XML: solo cambia la celda autorizada; `vbaProject.bin` y demas partes identicas;
nunca se toca una celda con formula; verificacion byte a byte y reanalisis tras escribir (si falla, se elimina la salida); segunda ejecucion sin cambios.

## Pruebas

```bash
python -m unittest discover -s tests -v
```

Pruebas de Control 5 (incluye fechas de texto D/M/YY y salida por caja), Controles 1-4 y 6, reporte, salida compacta y orquestador, mas una prueba opcional contra copias reales locales.
`tests/test_candidatos_voucher.py`: candidatos de MACROS sin voucher exacto (ejemplo real America 03/09/2026 SFC107 como candidato probable sin autocorregir; candidato unico fuerte,
varios candidatos, candidato posible, ningun candidato, candidato fuera de ±1 dia con importe unico en MACROS, fecha de texto normalizada con candidatos; el Control 5 no cambia de clase ni de plan; salida compacta, JSON, PDF y DOCX).
`tests/test_informe_humano.py`: contenido en lenguaje natural, tres estados humanos, ausencia de codigos internos/rutas/trazas, equivalencia exacta PDF/DOCX (mismo contenido), formato A4, encabezados repetidos, filas que no se parten, pie numerado, casos limite y explicacion de cada motivo de bloqueo del motor.
`tests/test_informe_corto.py`: clasificacion solo desde datos estructurados, America 03/09 centrada en asignacion/voucher, fechas
autocorregibles omitidas, fechas imposibles visibles, pendientes bancarios fuera de los PDF de caja, MACROS oculto y ALQUILERES conservado.
`tests/test_nube.py` incluye la prueba del orden auditor->motor (entrada `23/09/26`: el auditor la normaliza, el motor recibe `23/09/2026` en la copia que se entrega, no falla por formato y no hay falsa discrepancia de lectura), ademas de: materializacion segura (bit a bit, tamano/id/titulo, base64 corrupto, no-ZIP, duplicado, borrado de la fuente, limpieza solo de sesiones propias), MACROS ausente/ilegible sin bloquear la normalizacion, salidas JSON/CSV, modo `--manifiesto` extremo a extremo y motor no disponible.

## Fuera de alcance / pendiente

- La composicion de depositos de las hojas SFC no se revisa con el Control 4 (decision del usuario).
- Bancos fuera de la tabla oficial se reportan como "no figura en la tabla"; no se inventan reglas.
- No se conecta a n8n, no publica en las carpetas oficiales de CAJAS GABO (SAP/RESULTADO/PROCESADOS/MARKERS) ni procesa cierres con el motor: solo lo usa para validar en lectura.
- Drive es solo fuente: no se sube nada (ni informes, ni ZIP, ni cierres normalizados). Los binarios se **descargan** por el mecanismo de "resultado guardado en disco" y los resultados se entregan al usuario con `SendUserFile`.
- Si una descarga llegara en linea (archivo mas pequeno que el limite de respuesta), no hay como materializarla sin escribir base64: se informa `NO_MATERIALIZADO`. (Verificado: cierres de ~50 KB y MACROS de ~158 KB se guardan en disco.)
