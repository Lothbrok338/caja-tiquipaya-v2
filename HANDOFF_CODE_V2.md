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
- DOLARES determinístico (activo solo si importe > 0; no se trata como faltante). Si DOLARES > 0.00 y la cuenta USD no está parametrizada, `ejecutar_v2` nunca devuelve "OK" (usa `USD_CUENTA_PENDIENTE`) y `construir_asiento` no genera partidas.
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
