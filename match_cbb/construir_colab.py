"""Genera MATCH_CBB_COLAB.txt: el mismo codigo, en una sola celda de Google Colab.

matcher.py y reporte.py se empotran literalmente, sin reescribirlos, para que la
version Colab no pueda desviarse de la aprobada. Regenerar con:

    python match_cbb/construir_colab.py
"""

from __future__ import annotations

import pathlib

RAIZ = pathlib.Path(__file__).resolve().parent
SALIDA = RAIZ / "MATCH_CBB_COLAB.txt"

CABECERA = '''# =============================================================================
# MATCH_CBB - Cruce del reporte de Ingresos Cochabamba contra el extracto BCP.
#
# COMO SE USA: copiar TODO este contenido en UNA sola celda de Google Colab y
# ejecutarla. Pide los dos archivos, genera MATCH_CBB.xlsx y lo descarga.
#
# Los archivos subidos son solo lectura: nunca se escribe sobre ellos.
# No necesita IA, tokens, cuentas ni conexion a ningun servicio externo.
#
# Este archivo se genera desde matcher.py y reporte.py con construir_colab.py:
# el codigo del motor y del reporte va empotrado tal cual, sin modificaciones.
# =============================================================================

!pip install -q openpyxl xlrd scipy numpy

import os
import pathlib
import sys

'''

PIE = '''

# --- Escribir los dos modulos y cargarlos -----------------------------------
_CARPETA = pathlib.Path.cwd()
(_CARPETA / "matcher.py").write_text(_MATCHER_PY, encoding="utf-8")
(_CARPETA / "reporte.py").write_text(_REPORTE_PY, encoding="utf-8")
if str(_CARPETA) not in sys.path:
    sys.path.insert(0, str(_CARPETA))
for _nombre in ("matcher", "reporte"):
    sys.modules.pop(_nombre, None)

import matcher

# --- Subir los dos archivos --------------------------------------------------
from google.colab import files

print("Sube los DOS archivos:")
print("   1) Ingresos Cochabamba  (.xls o .xlsx)")
print("   2) Extracto BCP         (.xlsx)")
print("El orden no importa: se identifican por su estructura, no por el nombre.")
print()

_subidos = files.upload()
_rutas = [n for n in _subidos if os.path.splitext(n)[1].lower() in (".xls", ".xlsx", ".xlsm")]
if len(_rutas) != 2:
    raise SystemExit(
        f"Debes subir exactamente 2 archivos Excel. Recibidos: {sorted(_subidos)}"
    )

# --- Cruzar y generar el reporte --------------------------------------------
_cfg = matcher.Config()
_datos = matcher.ejecutar(_rutas, matcher.NOMBRE_SALIDA, _cfg)

print()
matcher.imprimir_reporte(_datos, _cfg)

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
        + PIE
    )
    compile(contenido.replace("!pip install -q openpyxl xlrd scipy numpy", "pass"),
            SALIDA.name, "exec")
    SALIDA.write_text(contenido, encoding="utf-8")
    return SALIDA


if __name__ == "__main__":
    ruta = construir()
    print(f"{ruta} ({ruta.stat().st_size:,} bytes, {len(ruta.read_text(encoding='utf-8').splitlines()):,} lineas)")
