# MATCH_CBB — cruce Ingresos Cochabamba vs extracto BCP nacional

Localiza dentro del extracto BCP nacional los pagos QR que aparecen en el reporte de
ingresos de Cochabamba, y devuelve el `Nro Oper.` que corresponde a cada pago.

**Los dos archivos de entrada son solo lectura.** El único archivo que se escribe es
`MATCH_CBB.xlsx`. Esta fase no escribe nada sobre la base nacional.

## Instalación

```bash
pip install -r match_cbb/requirements.txt
```

Python 3.11+.

## Uso

```bash
python match_cbb/matcher.py --cbb IngresosDiarios16092026_1548.xls --bcp BCP.xlsx
```

El orden no importa: el programa identifica cada archivo por su estructura, no por su
nombre ni por el nombre de la hoja. También funciona así:

```bash
python match_cbb/matcher.py IngresosDiarios16092026_1548.xls BCP.xlsx
```

Genera `MATCH_CBB.xlsx` en el directorio actual (`--salida` para cambiarlo).

### Opciones

| Opción | Por defecto | Para qué sirve |
|---|---|---|
| `--salida` | `MATCH_CBB.xlsx` | Nombre del Excel de resultado |
| `--seguro` | `5` | Segundos hasta los que un match es `MATCH_SEGURO` |
| `--probable` | `30` | Segundos hasta los que es `MATCH_PROBABLE` |
| `--revisar` | `120` | Segundos hasta los que es `REVISAR`; más allá es `SIN_MATCH` |
| `--margen-ambiguo` | `2` | Si otro movimiento BCP libre queda a esta distancia, el caso baja a `REVISAR` |
| `--sin-degradar-ambiguos` | — | No bajar a `REVISAR` los casos ambiguos |
| `--sin-filtro-qr` | — | No exigir "QR" en la glosa del BCP |

Todos los umbrales viven en la dataclass `Config` de `matcher.py`.

## Cómo cruza

Llave: **misma fecha + mismo monto exacto + hora más cercana**.

1. De Cochabamba entran solo los pagos QR (`Tipo Pago` / `Canal de Pago`). Los
   `Tarjeta D/C` nunca se fuerzan contra movimientos QR: van a la hoja `NO_QR`.
2. Del BCP entran solo los abonos positivos cuya glosa contiene "QR". La glosa es
   filtro secundario, nunca llave.
3. Dentro de cada grupo fecha+monto se arma la matriz de diferencias horarias y se
   resuelve la asignación **1 a 1** de mínima diferencia total con
   `scipy.optimize.linear_sum_assignment`. **Un `Nro Oper.` nunca se usa dos veces.**
4. Los pares que superan la ventana máxima quedan prohibidos, así que un movimiento
   lejano nunca se consume.

### Clasificación

| Estado | Criterio |
|---|---|
| `MATCH_SEGURO` | diferencia ≤ 5 s |
| `MATCH_PROBABLE` | 6 a 30 s |
| `REVISAR` | 31 a 120 s, o match ambiguo degradado |
| `SIN_MATCH` | sin candidato dentro de 120 s, o el candidato ya fue asignado a otro pago |
| `DATOS_INCOMPLETOS` | fecha u hora inválida, o monto no numérico |
| `NO_QR` | pago que no es QR |

### Control de ambigüedad

Aunque la asignación 1 a 1 elija bien, el resultado marca los casos dudosos:

- `Cantidad_candidatos`: movimientos BCP con la misma fecha y monto dentro de la ventana.
- `Segundo_mejor_delta_seg` y `Margen_vs_segundo_candidato`.
- `Ambiguo = SI` cuando existe un movimiento BCP **libre** a menos de `--margen-ambiguo`
  segundos del asignado. Ese caso baja a `REVISAR`: preferimos revisar antes que forzar.
  Si el otro candidato quedó asignado a otro pago no hay ambigüedad real.

### Cd. Confirmacion

Todo lo que está desde `Cd. Confirmacion` hacia la derecha es trabajo manual de las
sedes. **No decide el match y no se modifica.** Solo se muestra:

- `BCP_Cd_Confirmacion`: el valor original, literal.
- `Conflicto_Ciudad = SI` cuando ese valor apunta a otra ciudad. Un pago con
  `Cd. Confirmacion = SUCRE` que cruza perfecto por fecha+monto+hora sigue siendo
  `MATCH_SEGURO`.

## Detalles de lectura

- Cochabamba puede venir en `.xls` (Excel 97-2003, se lee con `xlrd`); BCP en `.xlsx`
  (`openpyxl`). Se revisan **todas las hojas** de ambos libros.
- La fila de encabezado se detecta exigiendo varios campos **a la vez** — Cochabamba:
  `Fecha` + `Número Factura` + `Monto` + `Nombre Estudiante`; BCP: `Fecha` + `Hora` +
  `Importe` + `Nro Oper.` Por eso el `Fecha:` suelto del membrete del reporte no se
  confunde con la tabla, y no se depende de ninguna fila fija.
- La `Fecha` de Cochabamba llega como serial de Excel y conserva la hora; el serial
  arrastra un desfase constante de +0,107 s, así que las marcas de tiempo de ambas
  bases se redondean al segundo entero antes de comparar.
- Los montos se comparan en centavos enteros, nunca como float.
- `Nro Oper.` se normaliza para comparar (`301902`, `"301902"`, `" 301902 "` y `301902.0`
  son el mismo identificador) pero en la salida se muestra el valor original.

## Salida: `MATCH_CBB.xlsx`

| Hoja | Contenido |
|---|---|
| `RESUMEN` | Parámetros, universo, resultado, importes, distribución de segundos y validaciones |
| `COCHABAMBA_MATCH` | Los pagos QR de Cochabamba con su movimiento BCP |
| `MATCH_SEGURO` / `MATCH_PROBABLE` / `REVISAR` / `SIN_MATCH` | Subconjuntos por estado |
| `NO_QR` | Pagos que no son QR (no se cruzan) |
| `TODOS` | Todo el reporte de Cochabamba |

## Validaciones

`RESUMEN` reporta: fechas/horas inválidas, montos no numéricos o no positivos, filas
incompletas, registros duplicados en Cochabamba, facturas repetidas, movimientos BCP sin
`Nro Oper.`, `Nro Oper.` duplicados en el extracto, pagos fuera del rango de fechas del
extracto, casos con más de un candidato, casos ambiguos y —como control crítico— si un
mismo movimiento BCP hubiera quedado asignado dos veces.

## Tests

```bash
python -m pytest match_cbb/tests -q
```
