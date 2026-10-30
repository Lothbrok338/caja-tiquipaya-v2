---
name: cruce-bnb-cierres
description: Cruza los depósitos declarados en los cierres de cajeros (SFC101, SFC102, SFC107, SFC108) contra el detalle de abonos BNB del macro mensual y genera un PDF con discrepancias. Úsala para la revisión diaria de vouchers o cuando se pida un cruce por rango de fechas.
---

# Cruce BNB vs cierres de cajeros

## Ventana por defecto

- Hoy `H`: revisar cierres con fecha de caja entre `H-3` y `H-2`.
- Ejemplo: hoy 30-10-2026 → cierres del 27 y 28-10-2026.
- Motivo: los vouchers de un día se depositan al día siguiente y el extracto llega un día después. Por eso los depósitos del último cierre pueden quedar como PENDIENTE sin ser discrepancia.
- Si el usuario indica otro rango, usa ese rango.

## Alcance

- Solo cajas SFC101, SFC102, SFC107 y SFC108.
- SFC105 y demás cajas NO se revisan, salvo que el usuario lo pida.

## Fuentes en Drive

Los archivos tienen el mismo nombre en carpetas distintas. Identifica cada archivo por su carpeta.

| Qué | Dónde | Carpeta (id) |
|---|---|---|
| Cierres América | CAJA AMERICA / PROCESADOS | `1GXMCRtGGI3J3eYQivnnOWMNR8PI-IiWm` |
| Cierres América (respaldo) | CAJA AMERICA / ENTRADA | `1UtGafpCPaXBKwxWb3Hv53gjf1ErIk1VS` |
| Cierres Tiquipaya | AGENTE TIQUIPAYA / 03_PROCESADOS / 2026 / 2026-09 | `1BkNC6lnonMM7YeWDKck-TM8WTyY2BJJP` |
| Cierres Tiquipaya | AGENTE TIQUIPAYA / 03_PROCESADOS / 2026 / 2026-10 | `1v_eXoYr_4KGRj1-bPlI_glEuiFTAztyZ` |
| Cierres Tiquipaya (respaldo) | AGENTE TIQUIPAYA / 00_ENTRADA_CIERRES | `1ntneoE3MI-25FyPXUymXEvIJmnaZWyJ1` |
| Detalle BNB (macro) | AGENTE TIQUIPAYA / 02_MAESTROS / 2026 / 2026-10 | `1-aFzsjbg0pqAF1SQN1CdOCHN-LYocNf8` |

Reglas de búsqueda:

1. Para cada fecha de la ventana, busca `CIERRE dd-mm-2026.xlsm` dentro de la carpeta de PROCESADOS. Si no está, usa la de ENTRADA y márcalo en el reporte.
2. Si hay más de un archivo con la misma fecha en la misma carpeta, usa el de `modifiedTime` más reciente y anótalo.
3. El macro BNB es el archivo `MACROS <MES>.xlsm` con `modifiedTime` más reciente en la carpeta de 2026-10 (o de mes actual). Anota su fecha de modificación.

## Pasos

1. Descarga con `download_file_content` cada cierre de la ventana y el macro. Guarda las copias en una carpeta nueva dentro del scratchpad. Nunca ejecutes macros.
2. Ejecuta el script:

   ```bash
   python3 .claude/skills/cruce-bnb-cierres/conciliar.py \
     --cierres <carpeta_con_cierres> \
     --macro <ruta_macro.xlsm> \
     --desde dd-mm-aaaa --hasta dd-mm-aaaa \
     --salida <carpeta_salida>
   ```

   Usa `python3 -I` si ejecutas código que lee archivos descargados.
3. Revisa `resultado.json`. Los estados son:
   - `OK`: código, importe y fecha cuadran.
   - `FECHA_INVERTIDA`: el cierre tiene día y mes al revés.
   - `FECHA_DISTINTA`: el código y el importe cuadran, la fecha no.
   - `MONTO_DISTINTO`: el código existe en el BNB con otro importe.
   - `SIN_ABONO`: discrepancia real. No hay abono con ese código.
   - `PENDIENTE`: la fecha de depósito es posterior a la cobertura del detalle BNB. No es discrepancia.
   - `REVISAR`: fecha ilegible en el cierre.
4. Genera el PDF desde `reporte.html`, usando `render.js` de esta carpeta:

   ```bash
   cd <carpeta_salida> && node /home/user/caja-tiquipaya-v2/.claude/skills/cruce-bnb-cierres/render.js reporte.html reporte.pdf
   ```

5. Entrega el PDF y un resumen corto en el chat. Incluye por cada discrepancia: cierre, caja, asignación, importe y qué se observó.

## Reglas de decisión

- Nunca marques `SIN_ABONO` si la fecha de depósito está fuera de la cobertura del detalle BNB. Ese caso es `PENDIENTE`.
- Un depósito es OK solo si código, importe y fecha coinciden. Si solo coincide el código, es discrepancia.
- No modifiques cierres, macros ni archivos de Drive. Solo lees y generas el reporte.
- Si el detalle BNB no cubre la fecha del cierre más reciente de la ventana, dilo en el resumen.

## Salida

- `resultado.json`: todos los depósitos con su estado.
- `reporte.html` y `reporte.pdf`: reporte para leer. Las cifras del resumen deben salir del JSON, no escribirse a mano.
- Carpeta de entrega en Drive: pendiente de confirmar por el usuario. Propuesta: `AGENTE TIQUIPAYA/06_REPORTES`.
