"""Genera QUICKVALLE_COLAB.txt: el mismo codigo, en una sola celda de Google Colab.

matcher.py, reporte.py y cierre.py se empotran literalmente, sin reescribirlos, para que la
version Colab no pueda desviarse de la aprobada. Regenerar con:

    python match_cbb/construir_colab.py
"""

from __future__ import annotations

import pathlib

RAIZ = pathlib.Path(__file__).resolve().parent
SALIDA = RAIZ / "QUICKVALLE_COLAB.txt"

CABECERA = '''#@title ▶ EJECUTAR QUICKVALLE { display-mode: "form" }
# =============================================================================
# QUICKVALLE - Cruce del reporte de Ingresos Cochabamba contra el extracto BCP.
#
# COMO SE USA: copiar TODO este contenido en UNA sola celda de Google Colab y
# ejecutarla. Queda plegada como formulario; basta pulsar el boton de ejecutar.
#
# Sube 2 archivos (Ingresos + BCP) o 3 (ademas el QUICKVALLE de un cierre
# anterior, cuyos matches quedan congelados). Genera QUICKVALLE.xlsx y lo baja.
#
# Los archivos subidos son solo lectura: nunca se escribe sobre ellos.
# No necesita IA, tokens, cuentas ni conexion a ningun servicio externo.
#
# Este archivo se genera desde matcher.py, reporte.py y cierre.py con
# construir_colab.py: el codigo va empotrado tal cual, sin modificaciones.
# =============================================================================

!pip install -q openpyxl xlrd scipy numpy

import os
import pathlib
import sys
import traceback

'''

PIE = '''

# --- Escribir los modulos y cargarlos ----------------------------------------
_CARPETA = pathlib.Path.cwd()
for _nombre, _fuente in (("matcher", _MATCHER_PY), ("reporte", _REPORTE_PY), ("cierre", _CIERRE_PY)):
    (_CARPETA / f"{_nombre}.py").write_text(_fuente, encoding="utf-8")
    sys.modules.pop(_nombre, None)
if str(_CARPETA) not in sys.path:
    sys.path.insert(0, str(_CARPETA))

import cierre
import matcher
import reporte

# --- Subir los archivos ------------------------------------------------------
from google.colab import files

print("Suba Ingresos y BCP.")
print("Opcional: QUICKVALLE anterior si desea conservar un cierre previo.")
print()

_subidos = files.upload()
_rutas = [n for n in _subidos if os.path.splitext(n)[1].lower() in (".xls", ".xlsx", ".xlsm")]
if len(_rutas) not in (2, 3):
    raise SystemExit(
        f"Suba 2 archivos (Ingresos y BCP) o 3 (ademas el QUICKVALLE anterior). "
        f"Recibidos: {sorted(_subidos)}"
    )

# --- Cruzar y generar el reporte ---------------------------------------------
try:
    _cfg = matcher.Config()
    _datos = matcher.ejecutar(_rutas, matcher.NOMBRE_SALIDA, _cfg)
except Exception:
    print()
    print("ERROR: no se pudo procesar. Detalle:")
    traceback.print_exc()
    raise

_res = _datos["resultados"]


def _contar(*estados):
    return sum(1 for r in _res if r.estado in estados)


_historicos = _contar(cierre.ESTADO_HISTORICO)
_automaticos = _contar(matcher.ESTADO_SEGURO, matcher.ESTADO_PROBABLE)
_pendientes = _contar(matcher.ESTADO_REVISAR)
_sin_match = _contar(matcher.ESTADO_SIN_MATCH, matcher.ESTADO_INCOMPLETO)
_tarjetas = _contar(matcher.ESTADO_NO_QR)

print()
print("=" * 46)
print("  PROCESO TERMINADO")
print("=" * 46)
if _datos["tabla_cierre"] is not None:
    print(f"  Cierre anterior aplicado: {os.path.basename(_datos['tabla_cierre'].ruta)}")
print(f"  Automaticos             : {_automaticos}")
print(f"  Confirmados historicos  : {_historicos}")
print(f"  Pendientes de revision  : {_pendientes}")
print(f"  Sin match               : {_sin_match}")
print(f"  Tarjetas                : {_tarjetas}")
print(f"  Total listo para pegar  : {_automaticos + _historicos}")
print("=" * 46)

_avisos = [(n, d, c) for n, d, c in _datos["alertas"] if n == "CRITICO"]
if _avisos:
    print()
    print("  REVISAR:")
    for _, _detalle, _cantidad in _avisos:
        print(f"   - {_detalle}: {_cantidad}")

print()
print(f"Archivo generado: {matcher.NOMBRE_SALIDA}")

# --- Descargar el resultado --------------------------------------------------
files.download(matcher.NOMBRE_SALIDA)
'''


def _empotrar(nombre_variable: str, ruta: pathlib.Path) -> str:
    codigo = ruta.read_text(encoding="utf-8")
    if "'''" in codigo or codigo.rstrip("\n").endswith("\\"):
        raise SystemExit(f"{ruta.name} no se puede empotrar literalmente en una cadena r'''")
    return f"{nombre_variable} = r'''\n{codigo}'''\n"


def construir() -> pathlib.Path:
    contenido = (
        CABECERA
        + _empotrar("_MATCHER_PY", RAIZ / "matcher.py")
        + "\n"
        + _empotrar("_REPORTE_PY", RAIZ / "reporte.py")
        + "\n"
        + _empotrar("_CIERRE_PY", RAIZ / "cierre.py")
        + PIE
    )
    compile(contenido.replace("!pip install -q openpyxl xlrd scipy numpy", "pass"),
            SALIDA.name, "exec")
    SALIDA.write_text(contenido, encoding="utf-8")
    return SALIDA


if __name__ == "__main__":
    ruta = construir()
    print(f"{ruta} ({ruta.stat().st_size:,} bytes, {len(ruta.read_text(encoding='utf-8').splitlines()):,} lineas)")
