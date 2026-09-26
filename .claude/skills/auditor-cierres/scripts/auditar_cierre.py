"""auditar_cierre.py — CLI del Auditor de Cierres (por ahora: Control 5).

Uso (solo diagnostico, NO escribe nada):
    python auditar_cierre.py --cierre "CIERRE 09-09-2026.xlsm" --macros "MACROS SEPTIEMBRE.xlsm" --caja tiquipaya

Con correccion (escribe una COPIA normalizada; nunca sobrescribe la entrada):
    python auditar_cierre.py ... --salida "salida/CIERRE 09-09-2026.xlsm"

Opcional: --json reporte.json  (guarda el reporte completo)

Codigos de salida: 0 = ejecuto bien (mira `estado` en el JSON), 1 = error.
La Skill nunca lee ni escribe Drive: trabaja sobre rutas locales que le da
quien la invoca.
"""
import argparse
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import control5_fecha_deposito as c5  # noqa: E402
import macros_vouchers as mv  # noqa: E402


def _fecha_de_nombre(ruta):
    import re
    m = re.search(r"(\d{2})-(\d{2})-(\d{4})", os.path.basename(ruta))
    if not m:
        return None
    try:
        return datetime.date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    except ValueError:
        return None


def _json_default(o):
    if isinstance(o, (datetime.date, datetime.datetime)):
        return o.strftime("%d/%m/%Y")
    raise TypeError(type(o))


def ejecutar(cierre, macros, caja, salida=None):
    ev = mv.leer_indice_macros(macros)
    fecha = _fecha_de_nombre(cierre)
    informe = c5.analizar(cierre, ev["indice"], caja, fecha_cierre=fecha)
    aplicado = {"escrito": False, "cambios": [], "estilo": None}
    verificacion = None
    if salida and informe["plan"]:
        aplicado = c5.aplicar(cierre, salida, informe)
        problemas, _ = c5.reanalizar_y_comparar(salida, ev["indice"], caja, informe, fecha_cierre=fecha)
        if problemas:
            os.remove(salida)
            raise RuntimeError("Reanalisis de la salida fallo: %s" % problemas)
        verificacion = "OK: integridad y reanalisis"

    r = informe["resumen"]
    pendientes = r.get(c5.REQUIERE_REVISION, 0) + r.get(c5.VACIA, 0) + len(informe["hojas_con_problema"])
    hay_plan = bool(informe["plan"])
    if hay_plan and not salida:
        estado = "CORRECCIONES_DISPONIBLES_NO_APLICADAS"
    elif hay_plan:
        estado = "CORREGIDO_CON_PENDIENTES" if pendientes else "CORREGIDO"
    else:
        estado = "SIN_CAMBIOS_CON_PENDIENTES" if pendientes else "SIN_CAMBIOS"
    return {
        "control": "CONTROL_5_FECHA_DEPOSITO",
        "caja": caja,
        "cierre": os.path.basename(cierre),
        "estado": estado,
        "resumen_clases": r,
        "movimientos_macros_leidos": ev["movimientos"],
        "hojas_con_problema": informe["hojas_con_problema"],
        "filas": informe["filas"],
        "aplicado": aplicado,
        "verificacion": verificacion,
    }


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # emojis/tildes seguros en consolas Windows (cp1252)
    p = argparse.ArgumentParser(description="Auditor de Cierres - Control 5 (FECHA DE DEPOSITO)")
    p.add_argument("--cierre", required=True)
    p.add_argument("--macros", required=True)
    p.add_argument("--caja", required=True, choices=sorted(c5.CAJAS))
    p.add_argument("--salida", help="ruta de la COPIA normalizada (si se omite: solo diagnostico)")
    p.add_argument("--json", help="guardar el reporte completo en este archivo")
    a = p.parse_args(argv)
    try:
        rep = ejecutar(a.cierre, a.macros, a.caja, a.salida)
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"estado": "ERROR", "error": "%s: %s" % (type(exc).__name__, exc)}, ensure_ascii=False))
        return 1
    texto = json.dumps(rep, ensure_ascii=False, indent=2, default=_json_default)
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            f.write(texto)
    print(texto)
    return 0


if __name__ == "__main__":
    sys.exit(main())
