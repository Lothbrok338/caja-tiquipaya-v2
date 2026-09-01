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

## 3. Etapas validadas

- EXTRACCIÓN V2 OK
- CRUCES V2 OK
- CUADRE V2 OK

## 4. Reglas técnicas críticas ya implementadas

- Fecha de cierre: `CIERRE DD-MM-YYYY`, se extrae del nombre de archivo (nunca de configuración regional).
- Vouchers siempre BNB.
- MACROS: única hoja exacta `Tablas Dinamicas Profesional`. No se lee ninguna otra pestaña.
- MACROS trae filas de encabezado repetidas dentro del rango de datos; se descartan de forma determinística por contenido (comparando cada fila contra el encabezado real leído en la misma pasada), sin depender de una cantidad fija de repeticiones.
- MACROS se usa únicamente para vouchers y NETO de ATC.
- ATC siempre BNB.
- CI no usa MACROS.
- ALQUILERES excluido (de CI operativas, de validación bancaria y del universo ajustado).
- DOLARES determinístico (activo solo si importe > 0; no se trata como faltante).
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
