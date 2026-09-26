# Control 5 — regla definitiva (aprobada)

```
FECHA EXCEL = FECHA VOUCHER                 -> CORRECTA / SIN CAMBIO
FECHA EXCEL SWAP DD/MM = FECHA VOUCHER      -> NORMALIZAR AUTOMATICAMENTE
TEXTO DE FECHA VALIDO = FECHA VOUCHER        -> CONVERTIR A FECHA EXCEL REAL
|FECHA - VOUCHER| = 1 DIA CALENDARIO          -> ACEPTABLE (tolerancia): no se cambia el valor; texto valido -> fecha real
                                                con el MISMO valor; traza FECHA_DENTRO_TOLERANCIA_MACROS_1_DIA
|FECHA - VOUCHER| > 1 DIA                     -> REVISION MANUAL, sin corregir el valor
TEXTO VALIDO SIN VOUCHER EN MACROS           -> CONVERTIR SOLO EL FORMATO + traza FECHA_NORMALIZADA_SIN_VOUCHER_MACROS
FECHA VACIA                                 -> AVISAR / NO COMPLETAR
CUALQUIER OTRO CASO                         -> AVISAR / NO MODIFICAR
```

Prohibido como evidencia: ventana de dias, cercania a la fecha del cierre, heuristicas.

## Voucher

- Fuente: MACROS mensual, hoja `Tablas Dinamicas Profesional`, columnas `Fecha`, `Codigo de Asignacion`, `Creditos`.
- Clave: `(codigo normalizado, importe a 2 decimales)`. Codigo normalizado = mayusculas, sin tildes ni espacios.
- **Unico** = exactamente 1 movimiento con esa clave. 0 o >1 -> no hay evidencia -> no se corrige.
- La fecha del voucher debe ser valida (fecha real, `YYYY-MM-DD` o `DD/MM/YYYY`); si no, no hay evidencia.
- Mismo criterio para Tiquipaya y America.

## Filas auditadas

En cada hoja SFC de la caja: bloque `COMPOSICION DE DEPOSITOS` (sin posiciones fijas), solo filas
con `IMPORTE` > 0. Columnas localizadas por encabezado: IMPORTE, FECHA DE DEPOSITO, ASIGNACION.

## Clasificacion de una celda (orden)

1. Vacia -> `VACIA` (aviso, nunca se completa).
2. Formula / tipo no soportado / numero fuera de rango / numero sin formato de fecha / fecha con hora
   -> `REQUIERE_REVISION` (`NO_VERIFICABLE`).
3. Texto: solo `D/M/YYYY`, `DD/M/YYYY`, `DD/MM/YYYY`, `D/M/YY` o `DD/MM/YY` (separador `/`, sin espacios) y fecha existente
   en el calendario. El año de 2 dígitos se resuelve **exclusivamente contra el año del cierre** (`15/09/26` en un cierre 2026 ->
   15/09/2026); si no coincide, o no se conoce el año del cierre, no se corrige. Sigue exigiendo voucher unico e igual.
   Se guarda como fecha Excel real. Manual (no se corrige): `05/0/2026`, `31/02/2026`, `15-09-2026`, `" 15/09/2026"`, `15/09/25` en un cierre 2026.
4. Texto valido y voucher NO encontrado (o sin asignacion): `CONVERTIR_TEXTO_SIN_VOUCHER_MACROS` -> fecha Excel real con el mismo
   dia/mes/año (solo se expande el año de 2 digitos con el año del cierre), cualquiera sea el dia; se registra
   `FECHA_NORMALIZADA_SIN_VOUCHER_MACROS` (valor original y normalizado). Que el motor luego bloquee por
   `MACROS_NO_CUBRE_FECHA_DEPOSITO` es un resultado distinto y se mantiene.
   Fecha Excel real sin voucher, voucher no unico o sin fecha valida -> `REQUIERE_REVISION` (`NO_VERIFICABLE`).
5. Con voucher unico:
   - fecha Excel == voucher -> `CORRECTA`
   - diferencia de 1 dia calendario (`abs(fecha - voucher) == 1`, por fechas, nunca por horas; cruza fin de mes/año) ->
     `DENTRO_TOLERANCIA_1_DIA` (fecha real, sin cambios) o `CONVERTIR_TEXTO_DENTRO_TOLERANCIA_1_DIA` (texto -> fecha real, mismo valor)
   - fecha Excel invertida (dia<=12, dia!=mes) == voucher -> `NORMALIZAR_INVERSION_DDMM` (regla previa, intacta)
   - texto == voucher -> `CONVERTIR_TEXTO_A_FECHA`
   - texto != voucher (incluido texto que seria la inversion del voucher) -> `REQUIERE_REVISION` (`CONFLICTO`)
   - fecha Excel != voucher y su inversion tampoco -> `REQUIERE_REVISION` (`CONFLICTO`)

La inversion solo se considera para fechas Excel reales, no para texto.

## Efecto en CAJAS GABO (comprobado con CIERRE 09-09-2026)

`SFC101!F4` estaba como 09/10/2026 (voucher 10/09/2026). Con ese valor el precheck bloqueaba
(`MACROS_NO_CUBRE_FECHA_DEPOSITO`) y la fecha valor del asiento salia 2026-10-09. Tras la normalizacion:
precheck `MAESTRO_APTO` y fecha valor 2026-09-10.

## Candidatos cuando no hay voucher exacto (solo informativo)

Ver `SKILL.md` (Control 5). Con `SIN_VOUCHER_EN_MACROS`, `ASIGNACION_VACIA_SIN_VOUCHER` o una fecha de texto normalizada sin voucher, el valor NO se corrige por candidatos (la normalizacion de formato no depende de ellos); `scripts/candidatos_voucher.py` solo muestra los registros de MACROS que podrian corresponder (importe exacto, cuenta, caja, fecha esperada ±1 dia; luego otras fechas del mismo MACROS). Ningun candidato modifica el cierre.
