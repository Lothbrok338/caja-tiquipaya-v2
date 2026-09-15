"""v3/precheck_maestro.py — Precondición V3 (FASE 10C) entre el Módulo 02
MATERIALIZACION y el Módulo 03 MOTOR PYTHON.

Responsabilidad ÚNICA: confirmar, con evidencia OBJETIVA ya presente en el
propio contenido del maestro mensual (nunca en metadatos externos como
`modifiedTime` de Drive), si ese maestro tiene cobertura temporal suficiente
para procesar el cierre de una fecha dada — ANTES de invocar el motor.

Esto NO es una regla contable nueva: MAESTRO_APTO significa únicamente
"el maestro tiene registros que alcanzan la fecha del cierre" — nunca
"los importes son correctos", "el cierre cuadra" ni "no hay excepciones".
Esas decisiones siguen siendo exclusivas de motor_tiquipaya.py (vía
v3.motor), sin cambios.

Evidencia objetiva reutilizada (ningún parser nuevo, ningún criterio de
fecha reinterpretado dos veces):
  - excel_io.leer_macros_bnb()  -> fecha máxima con movimientos reales en
    la hoja "Tablas Dinamicas Profesional".
  - excel_io.leer_atc_mensual() -> fecha máxima con registro real en la
    hoja "ATC TIQUIPAYA" (modo PRECONCILIADO) o el ATC legado.

Criterio (FASE 10B, confirmado con el maestro real de septiembre 2026 —
MACROS y ATC ambos hasta 2026-09-10; cierre 2026-09-10 cubierto,
2026-09-11 sin ningún registro):

    fecha_cierre <= fecha_maxima_macros  Y  fecha_cierre <= fecha_maxima_atc
        -> MAESTRO_APTO
    en cualquier otro caso (incluido un maestro sin ninguna fecha
    registrada, o ilegible)
        -> BLOQUEADO_MAESTRO_COBERTURA_NO_CONFIRMADA

Un hueco INTERMEDIO (una fecha sin fila propia pero anterior a la fecha
máxima real) NUNCA se interpreta automáticamente como desactualización:
solo importa hasta dónde llegan los datos, no si cada día individual tiene
fila (un día sin ATC puede ser legítimo — ver motor_tiquipaya.ATC_NO_APLICA
para bruto_cierre == 0, que este módulo no reinterpreta).

NO se usa `MAESTRO_DESACTUALIZADO` como afirmación automática: el nombre
del estado bloqueado es deliberadamente literal sobre lo que se sabe
("cobertura no confirmada"), nunca una acusación de que el maestro esté
desactualizado (podría, por ejemplo, ser un mes que genuinamente todavía
no tiene más movimientos porque el mes no ha avanzado más).
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import excel_io  # noqa: E402  (reutilizado tal cual, ver docstring)
from v3.materializacion import MATERIALIZADO  # noqa: E402
from v3.motor import NO_PROCESADO  # noqa: E402


MAESTRO_APTO = "MAESTRO_APTO"
BLOQUEADO_MAESTRO_COBERTURA_NO_CONFIRMADA = "BLOQUEADO_MAESTRO_COBERTURA_NO_CONFIRMADA"

_ESTADOS_VALIDOS = (MAESTRO_APTO, BLOQUEADO_MAESTRO_COBERTURA_NO_CONFIRMADA)


def _fecha_maxima(fechas):
    fechas_validas = [f for f in fechas if f]
    return max(fechas_validas) if fechas_validas else None


def _fecha_maxima_macros(ruta_maestro):
    indices = excel_io.leer_macros_bnb(ruta_maestro)
    fechas = [m.get("fecha") for movimientos in indices["por_codigo"].values() for m in movimientos]
    return _fecha_maxima(fechas)


def _fecha_maxima_atc(ruta_maestro):
    atc = excel_io.leer_atc_mensual(ruta_maestro)
    return _fecha_maxima(atc["por_fecha"].keys())


def evaluar_cobertura_maestro(ruta_maestro, fecha_cierre):
    """Evalúa UN maestro contra UNA fecha de cierre. Devuelve dict con
    EXACTAMENTE estas claves: estado, fecha_cierre, fecha_maxima_macros,
    fecha_maxima_atc, mensaje.

    `estado` in (MAESTRO_APTO, BLOQUEADO_MAESTRO_COBERTURA_NO_CONFIRMADA).
    Un maestro ilegible (archivo inexistente, hoja faltante, columnas
    faltantes, workbook corrupto) o sin NINGUNA fecha registrada en
    ninguna de las dos hojas SIEMPRE bloquea — nunca se asume apto por
    defecto ante evidencia insuficiente ("no adivinar")."""
    try:
        fecha_maxima_macros = _fecha_maxima_macros(ruta_maestro)
        fecha_maxima_atc = _fecha_maxima_atc(ruta_maestro)
    except Exception as exc:
        return {
            "estado": BLOQUEADO_MAESTRO_COBERTURA_NO_CONFIRMADA,
            "fecha_cierre": fecha_cierre,
            "fecha_maxima_macros": None,
            "fecha_maxima_atc": None,
            "mensaje": (
                f"MAESTRO_ILEGIBLE: {type(exc).__name__}: {exc}. No se puede "
                "confirmar objetivamente la cobertura del maestro."
            ),
        }

    if fecha_maxima_macros is None or fecha_maxima_atc is None:
        return {
            "estado": BLOQUEADO_MAESTRO_COBERTURA_NO_CONFIRMADA,
            "fecha_cierre": fecha_cierre,
            "fecha_maxima_macros": fecha_maxima_macros,
            "fecha_maxima_atc": fecha_maxima_atc,
            "mensaje": (
                "MAESTRO_SIN_FECHAS_REGISTRADAS: no se encontró ninguna fecha "
                "con movimientos reales en MACROS y/o ATC TIQUIPAYA. No se "
                "puede confirmar objetivamente la cobertura del maestro."
            ),
        }

    if fecha_cierre <= fecha_maxima_macros and fecha_cierre <= fecha_maxima_atc:
        return {
            "estado": MAESTRO_APTO,
            "fecha_cierre": fecha_cierre,
            "fecha_maxima_macros": fecha_maxima_macros,
            "fecha_maxima_atc": fecha_maxima_atc,
            "mensaje": (
                "Cobertura temporal minima confirmada: MACROS y ATC TIQUIPAYA "
                "tienen registros que alcanzan la fecha del cierre. Esto NO "
                "confirma importes ni ausencia de errores contables."
            ),
        }

    return {
        "estado": BLOQUEADO_MAESTRO_COBERTURA_NO_CONFIRMADA,
        "fecha_cierre": fecha_cierre,
        "fecha_maxima_macros": fecha_maxima_macros,
        "fecha_maxima_atc": fecha_maxima_atc,
        "mensaje": (
            f"El maestro no tiene registros que alcancen la fecha del cierre "
            f"({fecha_cierre}): MACROS llega hasta {fecha_maxima_macros}, ATC "
            f"TIQUIPAYA llega hasta {fecha_maxima_atc}. Esto NO es necesariamente "
            "un error del cierre: verifique o actualice el maestro antes de procesar."
        ),
    }


# ---------------------------------------------------------------------------
# Orquestación por lote — se inserta entre v3.materializacion.ejecutar_materializacion()
# y v3.motor.ejecutar_motor(). NUNCA evalúa un maestro que de todos modos no
# se iba a usar (un cierre SIN_ARCHIVO/AMBIGUO/ERROR_MATERIALIZACION nunca
# llega al motor, con o sin este precheck).
# ---------------------------------------------------------------------------

def aplicar_precheck_maestro(cierres_materializados):
    """Anota cada item MATERIALIZADO con estado_precheck_maestro/
    fecha_maxima_macros/fecha_maxima_atc/mensaje_precheck_maestro. Los
    demás items pasan intactos (mismo criterio de "no evaluar lo que no
    hace falta" que el resto de V3). Para los items BLOQUEADOS, fija
    también estado_motor=NO_PROCESADO (v3.motor.ejecutar_motor NUNCA
    los ve — ver filtrar_aptos_para_motor)."""
    resultados = []
    for item in cierres_materializados:
        if item.get("estado_materializacion") != MATERIALIZADO:
            resultados.append(dict(item))
            continue

        cobertura = evaluar_cobertura_maestro(item.get("ruta_maestro_local"), item.get("fecha"))
        salida = dict(item)
        salida.update({
            "estado_precheck_maestro": cobertura["estado"],
            "fecha_maxima_macros": cobertura["fecha_maxima_macros"],
            "fecha_maxima_atc": cobertura["fecha_maxima_atc"],
            "mensaje_precheck_maestro": cobertura["mensaje"],
        })
        if cobertura["estado"] == BLOQUEADO_MAESTRO_COBERTURA_NO_CONFIRMADA:
            salida["estado_motor"] = NO_PROCESADO
            salida["resultado"] = None
        resultados.append(salida)
    return resultados


def filtrar_aptos_para_motor(cierres_anotados):
    """Devuelve SOLO los items que deben pasar a v3.motor.ejecutar_motor():
    excluye explícitamente los BLOQUEADOS por este precheck (v3.motor
    JAMÁS los recibe, no solo "no los procesa")."""
    return [
        item for item in cierres_anotados
        if item.get("estado_precheck_maestro") != BLOQUEADO_MAESTRO_COBERTURA_NO_CONFIRMADA
    ]


# ---------------------------------------------------------------------------
# CLI — mismo patrón Execute-Command-invoca-Python que el resto de V3 (n8n
# solo invocaría esto, transportaría el resultado y enrutaría; no hace
# falta un octavo subworkflow para eso).
# ---------------------------------------------------------------------------

def main(argv=None):
    parser = argparse.ArgumentParser(description="Precheck de cobertura del maestro de V3 (FASE 10C), entre Modulo 02 y Modulo 03.")
    parser.add_argument("--input", required=True, help="JSON {'cierres_materializados': [...]}")
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)

    with open(args.input, "r", encoding="utf-8") as f:
        datos = json.load(f)

    try:
        anotados = aplicar_precheck_maestro(datos["cierres_materializados"])
        salida = {"resultado": "OK", "cierres": anotados}
    except Exception as exc:
        salida = {"resultado": "ERROR", "codigo": type(exc).__name__, "mensaje": str(exc)}

    try:
        texto = json.dumps(salida, ensure_ascii=False, indent=2)
    except TypeError as exc:
        texto = json.dumps({"resultado": "ERROR", "codigo": "SALIDA_NO_SERIALIZABLE", "mensaje": str(exc)}, ensure_ascii=False, indent=2)

    with open(args.output, "w", encoding="utf-8") as f:
        f.write(texto)
    return 0


if __name__ == "__main__":
    sys.exit(main())
