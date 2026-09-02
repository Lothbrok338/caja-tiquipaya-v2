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
- ALQUILERES excluido del asiento (nunca se crea partida ALQUILERES ni se compensa con otra cuenta); se conserva separado por SFC para ajustar el HABER: `HABER SFCxxx = TOTAL SFCxxx - ALQUILERES de ese SFC`.
- ATC NETO se cruza contra MACROS por importe exacto + fecha bancaria compatible (nunca ANTERIOR a la fecha de cierre; posteriores sí son válidas; sin ventana arbitraria de días).
- Vouchers: código de asignación + importe exacto; 0↔O solo autocorrección única; O↔P nunca autocorrección (POSIBLE_TYPO/bloqueante). Sin ventana de fecha propia.
- DOLARES determinístico (activo solo si importe > 0; no se trata como faltante). Si DOLARES > 0.00 y la cuenta USD no está parametrizada, `ejecutar_v2` nunca devuelve "OK" (usa `USD_CUENTA_PENDIENTE`) y `construir_asiento` no genera partidas.
- `_validar_partidas` bloquea importes negativos y cualquier problema estructural: si hay problemas, el asiento devuelto tiene `estado=ERROR` y `partidas=[]` (nunca partidas inválidas utilizables).
- CI: si trae fecha propia se propaga como `fecha_valor`; si no, `fecha_valor=None` (nunca se usa la fecha del cierre como reemplazo). CI con importe negativo bloquea.
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
