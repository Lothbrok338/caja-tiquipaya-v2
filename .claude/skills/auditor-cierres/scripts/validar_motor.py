"""validar_motor.py — Validacion cruzada de solo LECTURA contra el motor CAJAS GABO.

Corre en su propio proceso (para no mezclar modulos con los del auditor) y NO escribe nada: para cada cierre
usa el mismo lector que alimenta el SAP (`excel_io.leer_cierre`, con la caja indicada) y el mismo precheck de
cobertura de MACROS (`v3.precheck_maestro.evaluar_cobertura_maestro`). No genera SAP ni publica.

Entrada:  --items ARCHIVO.json  con [{"caja","ruta","fecha":"YYYY-MM-DD","maestro":"ruta MACROS"|null}, ...]
Motor:    --motor-dir DIR  (o CAJAS_GABO_MOTOR_DIR; o los candidatos de config_nube.json)
Salida:   un JSON en stdout: {"disponible":bool, "motor":{...}, "items":[...]} — nunca lanza a la consola.
"""
import argparse
import hashlib
import json
import os
import sys
import warnings

RAIZ_SKILL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def candidatos(motor_dir=None):
    if motor_dir:  # ruta explicita: exclusiva, sin caer a otros repositorios
        return [motor_dir]
    out = []
    if os.environ.get("CAJAS_GABO_MOTOR_DIR"):
        out.append(os.environ["CAJAS_GABO_MOTOR_DIR"])
    try:
        with open(os.path.join(RAIZ_SKILL, "config_nube.json"), encoding="utf-8") as f:
            out += json.load(f)["motor_cajas_gabo"]["candidatos"]
    except (OSError, ValueError, KeyError):
        pass
    return out


def localizar(motor_dir=None):
    for c in candidatos(motor_dir):
        if os.path.isfile(os.path.join(c, "excel_io.py")) and os.path.isfile(os.path.join(c, "v3", "precheck_maestro.py")):
            return os.path.abspath(c)
    return None


def _sha(ruta):
    with open(ruta, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()[:12]


def validar(items, motor_dir=None):
    raiz = localizar(motor_dir)
    if raiz is None:
        return {"disponible": False, "motivo": "MOTOR_NO_ENCONTRADO: no hay un repositorio del motor CAJAS GABO en las rutas conocidas "
                                              "(defina CAJAS_GABO_MOTOR_DIR)", "items": []}
    sys.path.insert(0, raiz)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            import excel_io  # noqa: E402
            from v3 import precheck_maestro as pm  # noqa: E402
    except Exception as exc:  # noqa: BLE001
        return {"disponible": False, "motivo": "MOTOR_NO_IMPORTABLE: %s: %s" % (type(exc).__name__, exc), "items": []}
    motor = {"dir": raiz, "excel_io_sha": _sha(os.path.join(raiz, "excel_io.py")),
             "precheck_maestro_sha": _sha(os.path.join(raiz, "v3", "precheck_maestro.py"))}
    res = []
    for it in items:
        r = {"caja": it["caja"], "fecha": it["fecha"], "archivo": os.path.basename(it["ruta"]), "lectura_motor": None,
             "depositos_motor": None, "fechas_deposito_motor": None, "estado_maestro": None, "fecha_maxima_macros": None, "fecha_maxima_atc": None,
             "fecha_requerida_deposito": None, "codigo_bloqueo": None,
             "observaciones": [], "mensaje": None, "error": None}
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                cierre = excel_io.leer_cierre(it["ruta"], caja=it["caja"])
            claves = [k for k in cierre if k.startswith("sfc")]
            r["lectura_motor"] = "OK"
            r["depositos_motor"] = sum(len(cierre[k]["depositos"]) for k in claves)
            # fechas de deposito tal como las recibio el motor (evidencia de que leyo el archivo ya normalizado)
            r["fechas_deposito_motor"] = sorted({d.get("fecha_deposito") for k in claves for d in cierre[k]["depositos"]
                                                 if d.get("fecha_deposito")})
            r["total_movimiento_motor"] = {k.upper(): cierre[k]["total_movimiento"] for k in claves}
        except Exception as exc:  # noqa: BLE001
            r["lectura_motor"] = "ERROR"
            r["error"] = "%s: %s" % (type(exc).__name__, str(exc)[:300])
        if it.get("maestro") and r["lectura_motor"] == "OK":
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    cob = pm.evaluar_cobertura_maestro(it["maestro"], it["fecha"], it["ruta"], caja=it["caja"])
                r["estado_maestro"] = cob["estado"]
                r["fecha_maxima_macros"] = cob.get("fecha_maxima_macros")
                r["fecha_maxima_atc"] = cob.get("fecha_maxima_atc")
                r["fecha_requerida_deposito"] = cob.get("fecha_requerida_deposito")
                r["codigo_bloqueo"] = cob.get("codigo_bloqueo")
                r["observaciones"] = [o["codigo"] + ": " + str(o.get("fecha_deposito")) for o in cob.get("observaciones") or []]
                r["mensaje"] = cob.get("mensaje")
            except Exception as exc:  # noqa: BLE001
                r["estado_maestro"] = "ERROR"
                r["error"] = "%s: %s" % (type(exc).__name__, str(exc)[:300])
        elif not it.get("maestro"):
            r["estado_maestro"] = "SIN_MACROS"
        res.append(r)
    return {"disponible": True, "motor": motor, "items": res}


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser()
    p.add_argument("--items", required=True)
    p.add_argument("--motor-dir")
    ns = p.parse_args(argv)
    try:
        with open(ns.items, encoding="utf-8-sig") as f:
            items = json.load(f)
        salida = validar(items, ns.motor_dir)
    except Exception as exc:  # noqa: BLE001
        salida = {"disponible": False, "motivo": "ERROR: %s: %s" % (type(exc).__name__, exc), "items": []}
    print(json.dumps(salida, ensure_ascii=False, separators=(",", ":"), default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
