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
  - excel_io.leer_atc_mensual() -> fechas con registro real en la hoja
    "ATC TIQUIPAYA" (modo PRECONCILIADO) o el ATC legado.
  - excel_io.leer_cierre()      -> cobros_atc de SFC101/SFC102 del propio
    cierre, para decidir si ESE día tuvo movimiento ATC.

Criterio MACROS (sin cambios desde FASE 10C): fecha_cierre debe estar
dentro del rango que MACROS ya cubre (fecha_cierre <= fecha_maxima_macros).
Un maestro sin ninguna fecha registrada en MACROS, o ilegible, SIEMPRE
bloquea.

Criterio ATC (CORREGIDO en FASE 10E — ver hallazgo real del 12/09/2026,
día real sin movimiento ATC que el criterio anterior bloqueaba
incorrectamente por comparar contra una fecha máxima global):
  1. Se determina, a partir del PROPIO archivo del cierre
     (excel_io.leer_cierre), si tuvo movimiento ATC — MISMO criterio
     EXACTO que motor_tiquipaya.cruzar_atc_preconciliado() ya usa para
     decidir ATC_NO_APLICA: bruto_cierre = cobros_atc(SFC101) +
     cobros_atc(SFC102); tiene movimiento si bruto_cierre != 0.
  2. Si TUVO movimiento ATC: se exige una fila REAL en ATC TIQUIPAYA para
     ESA fecha EXACTA (fecha_cierre in atc["por_fecha"]) — nunca un proxy
     de fecha máxima. Si falta, bloquea con un mensaje simple y literal.
  3. Si NO tuvo movimiento ATC: la ausencia de fila ATC para esa fecha es
     legítima (mismo día sin ATC que V2 ya reconoce) — NO se exige nada
     de ATC, y NUNCA se inventa una fila cero para "completar" la
     evidencia.

`fecha_maxima_atc` se sigue calculando y devolviendo (informativo, para
mostrar "cobertura ATC hasta" en la interfaz), pero YA NO es, por sí solo,
motivo de bloqueo.

NO se usa `MAESTRO_DESACTUALIZADO` como afirmación automática: el nombre
del estado bloqueado es deliberadamente literal sobre lo que se sabe
("cobertura no confirmada"), nunca una acusación de que el maestro esté
desactualizado (podría, por ejemplo, ser un mes que genuinamente todavía
no tiene más movimientos porque el mes no ha avanzado más, o un día
genuinamente sin ATC).
"""

import argparse
import json
import os
import sys
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import excel_io  # noqa: E402  (reutilizado tal cual, ver docstring)
from v3.materializacion import MATERIALIZADO  # noqa: E402
from v3.motor import NO_PROCESADO  # noqa: E402


MAESTRO_APTO = "MAESTRO_APTO"
BLOQUEADO_MAESTRO_COBERTURA_NO_CONFIRMADA = "BLOQUEADO_MAESTRO_COBERTURA_NO_CONFIRMADA"
MACROS_NO_CUBRE_FECHA_DEPOSITO = "MACROS_NO_CUBRE_FECHA_DEPOSITO"

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


def _cierre_tiene_movimiento_atc(ruta_cierre):
    """MISMO criterio EXACTO que motor_tiquipaya.cruzar_atc_preconciliado()
    usa para decidir ATC_NO_APLICA: bruto_cierre = cobros_atc(SFC101) +
    cobros_atc(SFC102). Reutiliza excel_io.leer_cierre() (mismo parser que
    ya usa V2/V3) -- no reinterpreta el archivo del cierre."""
    cierre = excel_io.leer_cierre(ruta_cierre)
    bruto = Decimal(cierre["sfc101"]["cobros_atc"]) + Decimal(cierre["sfc102"]["cobros_atc"])
    return bruto != 0


def _depositos_del_cierre(ruta_cierre):
    """Fechas de depósito (YYYY-MM-DD) de SFC101/SFC102, separadas en plausibles
    (mismo año que el cierre) y anómalas (otro año, p. ej. un tipeo 2016 en vez de
    2026). Reutiliza excel_io.leer_cierre(); nunca corrige la fecha del cierre."""
    cierre = excel_io.leer_cierre(ruta_cierre)
    return cierre, [d.get("fecha_deposito") for k in ("sfc101", "sfc102") for d in cierre[k]["depositos"]]


def _clasificar_fechas_deposito(fechas, fecha_cierre):
    anio = (fecha_cierre or "")[:4]
    plausibles = [f for f in fechas if f and f[:4] == anio]
    anomalas = sorted({f for f in fechas if f and f[:4] != anio})
    return plausibles, anomalas


def _evaluar_cobertura_base(ruta_maestro, fecha_cierre, ruta_cierre):
    """Evalúa UN maestro (más el propio cierre, para saber si ese día tuvo
    movimiento ATC) contra UNA fecha de cierre. Devuelve dict con
    EXACTAMENTE estas claves: estado, fecha_cierre, fecha_maxima_macros,
    fecha_maxima_atc, mensaje.

    `estado` in (MAESTRO_APTO, BLOQUEADO_MAESTRO_COBERTURA_NO_CONFIRMADA).

    Además de la fecha del cierre, MACROS debe cubrir la fecha máxima de los
    DEPÓSITOS del cierre (columna FECHA DE DEPOSITO): un depósito posterior a
    lo que MACROS registra no puede tener voucher todavía y se reporta como
    `MACROS_NO_CUBRE_FECHA_DEPOSITO` (con fecha requerida y disponible), no
    como un voucher inexistente. Las fechas de depósito de otro año que el
    cierre (tipeo, p. ej. 2016) NO se usan para exigir cobertura: se
    reportan aparte en `observaciones` (FECHA_DEPOSITO_ANOMALA) para decisión
    humana. Claves adicionales: `codigo_bloqueo`, `fecha_requerida_deposito`,
    `observaciones`.
    Un maestro ilegible (archivo inexistente, hoja faltante, columnas
    faltantes, workbook corrupto), sin NINGUNA fecha registrada en MACROS,
    o un cierre cuyo archivo no se puede leer para determinar si tuvo
    movimiento ATC, SIEMPRE bloquea — nunca se asume apto por defecto ante
    evidencia insuficiente ("no adivinar")."""
    try:
        fecha_maxima_macros = _fecha_maxima_macros(ruta_maestro)
        atc = excel_io.leer_atc_mensual(ruta_maestro)
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
    fecha_maxima_atc = _fecha_maxima(atc["por_fecha"].keys())

    if fecha_maxima_macros is None:
        return {
            "estado": BLOQUEADO_MAESTRO_COBERTURA_NO_CONFIRMADA,
            "fecha_cierre": fecha_cierre,
            "fecha_maxima_macros": None,
            "fecha_maxima_atc": fecha_maxima_atc,
            "mensaje": (
                "MAESTRO_SIN_FECHAS_REGISTRADAS: no se encontró ninguna fecha "
                "con movimientos reales en MACROS. No se puede confirmar "
                "objetivamente la cobertura del maestro."
            ),
        }

    if fecha_cierre > fecha_maxima_macros:
        return {
            "estado": BLOQUEADO_MAESTRO_COBERTURA_NO_CONFIRMADA,
            "fecha_cierre": fecha_cierre,
            "fecha_maxima_macros": fecha_maxima_macros,
            "fecha_maxima_atc": fecha_maxima_atc,
            "mensaje": (
                f"El maestro no tiene registros de MACROS que alcancen la fecha "
                f"del cierre ({fecha_cierre}): MACROS llega hasta "
                f"{fecha_maxima_macros}. Esto NO es necesariamente un error del "
                "cierre: verifique o actualice el maestro antes de procesar."
            ),
        }

    try:
        _cierre, fechas_dep = _depositos_del_cierre(ruta_cierre)
    except Exception:  # noqa: BLE001 — un cierre ilegible lo reporta el chequeo ATC de abajo, con su mensaje de siempre
        fechas_dep = []
    plausibles, anomalas = _clasificar_fechas_deposito(fechas_dep, fecha_cierre)
    fecha_requerida = _fecha_maxima(plausibles)
    if fecha_requerida and fecha_requerida > fecha_maxima_macros:
        return {
            "estado": BLOQUEADO_MAESTRO_COBERTURA_NO_CONFIRMADA,
            "fecha_cierre": fecha_cierre,
            "fecha_maxima_macros": fecha_maxima_macros,
            "fecha_maxima_atc": fecha_maxima_atc,
            "codigo_bloqueo": MACROS_NO_CUBRE_FECHA_DEPOSITO,
            "fecha_requerida_deposito": fecha_requerida,
            "mensaje": (
                f"{MACROS_NO_CUBRE_FECHA_DEPOSITO}: el cierre trae depósitos hasta {fecha_requerida} "
                f"pero MACROS solo llega hasta {fecha_maxima_macros}. Los vouchers de esos depósitos "
                "todavía no pueden estar en MACROS: actualice MACROS en Drive y vuelva a procesar."
            ),
        }

    try:
        tiene_atc = _cierre_tiene_movimiento_atc(ruta_cierre)
    except Exception as exc:
        return {
            "estado": BLOQUEADO_MAESTRO_COBERTURA_NO_CONFIRMADA,
            "fecha_cierre": fecha_cierre,
            "fecha_maxima_macros": fecha_maxima_macros,
            "fecha_maxima_atc": fecha_maxima_atc,
            "mensaje": (
                f"No se pudo leer el cierre para determinar si tuvo movimiento "
                f"ATC: {type(exc).__name__}: {exc}."
            ),
        }

    if tiene_atc and fecha_cierre not in atc["por_fecha"]:
        return {
            "estado": BLOQUEADO_MAESTRO_COBERTURA_NO_CONFIRMADA,
            "fecha_cierre": fecha_cierre,
            "fecha_maxima_macros": fecha_maxima_macros,
            "fecha_maxima_atc": fecha_maxima_atc,
            "mensaje": (
                "No se encontró información ATC del maestro para la fecha del "
                "cierre. Actualice/verifique el maestro y vuelva a procesar."
            ),
        }

    return {
        "estado": MAESTRO_APTO,
        "fecha_cierre": fecha_cierre,
        "fecha_maxima_macros": fecha_maxima_macros,
        "fecha_maxima_atc": fecha_maxima_atc,
        "mensaje": (
            "Cobertura minima confirmada: MACROS alcanza la fecha del cierre"
            + (", y ATC TIQUIPAYA tiene fila para esa fecha." if tiene_atc else
               " y el cierre no tuvo movimiento ATC ese día (no se exige fila).")
            + " Esto NO confirma importes ni ausencia de errores contables."
        ),
    }


def evaluar_cobertura_maestro(ruta_maestro, fecha_cierre, ruta_cierre):
    r = _evaluar_cobertura_base(ruta_maestro, fecha_cierre, ruta_cierre)
    r.setdefault("codigo_bloqueo", None)
    r.setdefault("fecha_requerida_deposito", None)
    observaciones = []
    if r["estado"] == MAESTRO_APTO or r.get("codigo_bloqueo") == MACROS_NO_CUBRE_FECHA_DEPOSITO:
        try:
            _c, fechas_dep = _depositos_del_cierre(ruta_cierre)
            _pl, anomalas = _clasificar_fechas_deposito(fechas_dep, fecha_cierre)
            if r.get("fecha_requerida_deposito") is None:
                r["fecha_requerida_deposito"] = _fecha_maxima(_pl)
            for f in anomalas:
                observaciones.append({
                    "codigo": "FECHA_DEPOSITO_ANOMALA", "fecha_deposito": f,
                    "mensaje": (f"FECHA_DEPOSITO_ANOMALA: un depósito del cierre tiene fecha {f}, de un año distinto al del cierre "
                                f"({(fecha_cierre or '')[:4]}). No afecta la coincidencia del voucher (código/importe) pero esa fecha llegaría "
                                "al SAP como fecha valor: requiere decisión humana; no se corrige automáticamente."),
                })
        except Exception:  # noqa: BLE001 — ya reportado por _evaluar_cobertura_base
            pass
    r["observaciones"] = observaciones
    if observaciones and r["estado"] == MAESTRO_APTO:
        r["mensaje"] += " OBSERVACIÓN: " + " ".join(o["mensaje"] for o in observaciones)
    return r


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

        cobertura = evaluar_cobertura_maestro(
            item.get("ruta_maestro_local"), item.get("fecha"), item.get("ruta_cierre_local"),
        )
        salida = dict(item)
        salida.update({
            "estado_precheck_maestro": cobertura["estado"],
            "fecha_maxima_macros": cobertura["fecha_maxima_macros"],
            "fecha_maxima_atc": cobertura["fecha_maxima_atc"],
            "mensaje_precheck_maestro": cobertura["mensaje"],
            "codigo_bloqueo_precheck": cobertura.get("codigo_bloqueo"),
            "fecha_requerida_deposito": cobertura.get("fecha_requerida_deposito"),
            "observaciones_precheck": cobertura.get("observaciones") or [],
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
