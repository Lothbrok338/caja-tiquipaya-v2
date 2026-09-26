"""auditar.py — Auditor de Cierres: Controles 1 a 6 (+ validacion cruzada con el motor CAJAS GABO), un solo proceso.

Modo NUBE (uso normal; los archivos ya fueron materializados por nube_drive.py desde Google Drive):

    python auditar.py --manifiesto "<sesion>/manifiesto.json"

  Toma cierres y MACROS del manifiesto, escribe en ~/AuditoriaCierres/<AAAA-MM-DD_HHMMSS>/ la SALIDA ESTANDAR y valida cada
  cierre contra el motor CAJAS GABO. Lo unico que queda suelto en la carpeta son los tres reportes breves y el ZIP:
    RESUMEN_GABO.pdf
    PARA_CAJA_AMERICA.pdf
    PARA_CAJA_TIQUIPAYA.pdf
    AUDITORIA_CIERRES_RESULTADOS.zip  = informe tecnico PDF/DOCX + JSON + CSV + Excel tecnico
                                        + CIERRES_NORMALIZADOS/<CAJA>/*.xlsm + RECURSOS_USADOS.txt
  Nada se publica en Drive.

Modo manual (rutas locales explicitas; --caja aplica a los --cierre/--carpeta que le siguen):

    python auditar.py --macros "MACROS SEPTIEMBRE.xlsm" \
        --caja tiquipaya --cierre "CIERRE 09-09-2026.xlsm" --cierre "CIERRE 10-09-2026.xlsm" \
        --caja america --carpeta "C:/cierres/america" \
        --salida-dir "C:/salida" --reporte-dir "C:/reportes"

  --manifiesto  Manifiesto de nube_drive.py (cierres + MACROS + trazabilidad de Drive).
  --macros      MACROS mensual (repetible; se combinan). Sin MACROS el Control 5 NO se detiene: igual normaliza el
                formato de las fechas de texto validas (sin contrastar voucher) y avisa que no hubo contraste.
  --salida-dir  Si se indica, el Control 5 escribe COPIAS con FECHA DE DEPOSITO normalizada en <salida-dir>/TIQUIPAYA/ y <salida-dir>/AMERICA/.
                Sin esto, solo diagnostica (no escribe ningun cierre).
  --reporte-dir Carpeta de la corrida (debe ser nueva o no tener ya un informe/ZIP; por defecto: carpeta actual; en modo nube,
                ~/AuditoriaCierres/<fecha_hora>).
  --sin-motor   No ejecutar la validacion cruzada con el motor CAJAS GABO.  --motor-dir DIR: repositorio del motor.

stdout: SOLO un JSON compacto (max. 15 hallazgos). El detalle completo esta en el .xlsx/.json/.csv.
Nunca modifica el original, nunca escribe en Drive, nunca usa Excel ni openpyxl.save() sobre cierres.
"""
import argparse
import csv
import datetime
import glob
import json
import os
import re
import subprocess
import sys
import time
import zipfile

_T0 = time.perf_counter()

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import control5_fecha_deposito as c5  # noqa: E402
import candidatos_voucher as cv  # noqa: E402
import controles_lectura as cl  # noqa: E402
import informe_corto as ic  # noqa: E402
import informe_humano as ih  # noqa: E402
import macros_vouchers as mv  # noqa: E402
import reporte_xlsx as rx  # noqa: E402
import xlsm_xml as X  # noqa: E402

MAX_HALLAZGOS_CONTEXTO = 15

# Salida estandar de cada corrida (nombres fijos; la carpeta de la corrida es nueva).
NOMBRE_PDF = "INFORME_AUDITORIA_CIERRES.pdf"          # entrega principal (lectura humana / impresion)
NOMBRE_DOCX = "INFORME_AUDITORIA_CIERRES.docx"        # mismo informe, editable
NOMBRE_DETALLE = "DETALLE_TECNICO_AUDITORIA.xlsx"     # Excel interno: solo dentro del ZIP, no es el informe
NOMBRE_ZIP = "AUDITORIA_CIERRES_RESULTADOS.zip"
NOMBRE_RECURSOS = "RECURSOS_USADOS.txt"
NOMBRE_JSON = "RESULTADOS_AUDITORIA.json"
NOMBRE_CSV = "HALLAZGOS_AUDITORIA.csv"

_RAZON_C5 = {
    "CELDA_CON_FORMULA_NO_SE_MODIFICA": "la celda tiene una fórmula",
    "TIPO_DE_CELDA_NO_SOPORTADO": "el tipo de dato no se reconoce",
    "TEXTO_FORMATO_NO_ADMITIDO": "la fecha está escrita como texto en un formato no admitido",
    "TEXTO_ANIO_2_DIGITOS_NO_COINCIDE_CON_ANIO_DEL_CIERRE": "el año de 2 dígitos no coincide con el año del cierre",
    "TEXTO_FECHA_INEXISTENTE_EN_CALENDARIO": "la fecha escrita no existe en el calendario",
    "NUMERO_FUERA_DE_RANGO_DE_FECHAS": "el valor no es una fecha",
    "NUMERO_SIN_FORMATO_DE_FECHA": "el valor no tiene formato de fecha",
    "FECHA_CON_HORA_NO_SE_MODIFICA": "la fecha incluye hora",
    "IMPORTE_NO_NUMERICO": "el importe del depósito no es un número",
    "ASIGNACION_VACIA_SIN_VOUCHER": "el depósito no tiene asignación",
    "SIN_VOUCHER_EN_MACROS": "no se encontró su voucher en MACROS",
    "VOUCHER_SIN_FECHA_VALIDA": "el voucher de MACROS no tiene una fecha válida",
    "TEXTO_DISTINTO_A_VOUCHER": "la fecha escrita no coincide con el voucher",
    "FECHA_DISTINTA_A_VOUCHER_Y_SU_INVERSION_TAMPOCO_COINCIDE": "la fecha no coincide con el voucher",
}


def fecha_de_nombre(ruta):
    m = re.search(r"(\d{2})-(\d{2})-(\d{4})", os.path.basename(ruta))
    if not m:
        return None
    d, mo, a = map(int, m.groups())
    try:
        return datetime.date(a, mo, d)
    except ValueError:
        return None


def _fd(d):
    return d.strftime("%d/%m/%Y") if d else "?"


def _razon(motivo):
    if motivo.startswith("VOUCHER_NO_UNICO"):
        return "hay más de un voucher igual en MACROS"
    return _RAZON_C5.get(motivo, motivo.replace("_", " ").lower())


def _d5(f, aplicado, error=None):
    """Metadatos estructurados de una fila del Control 5 (solo para redactar el informe humano)."""
    return {"tipo": "c5", "clase": f["clase"], "motivo": f["motivo"], "deposito": f["deposito"], "celda": f["celda"],
            "valor_actual": f["valor_actual"], "fecha_nueva": _fd(f["fecha_nueva"]) if f["fecha_nueva"] else None,
            "fecha_en_cierre": f["fecha_cierre"], "fecha_macros": f["fecha_macros"], "fecha_voucher": f["fecha_voucher"],
            "importe": f["importe"], "aplicado": aplicado, "error_aplicar": error, "candidatos": f.get("candidatos"),
            "asignacion": f.get("asignacion")}


def hallazgos_control5(informe, aplicado, error_aplicar, fecha, caja):
    out = []
    for h in informe["hojas_con_problema"]:
        out.append(cl._hallazgo(fecha, caja, h["hoja"], 5, cl.REVISAR,
                                "⚠️ No se pudo revisar las fechas de depósito de %s (no se reconoció la hoja)." % h["hoja"],
                                "Revisar la hoja manualmente", datos={"tipo": "c5_hoja_no_reconocida"}))
    hechos = {(c["hoja"], c["celda"]) for c in aplicado.get("cambios", [])}
    for f in informe["filas"]:
        sfc, ref, dep = f["hoja"], f["celda"], f["deposito"].title().replace("Deposito", "Depósito")
        if f["clase"] == c5.CORRECTA:
            continue
        if f["clase"] in (c5.DENTRO_TOLERANCIA, c5.CONVERTIR_TEXTO_TOLERANCIA):
            traza = ("%s — %s (celda %s): fecha en el cierre %s, fecha en MACROS %s (1 día de diferencia)."
                     % (f["motivo"], dep, ref, f["fecha_cierre"], f["fecha_macros"]))
            if f["clase"] == c5.DENTRO_TOLERANCIA:
                out.append(cl._hallazgo(fecha, caja, sfc, 5, cl.INFO, "ℹ️ " + traza + " No se modificó.",
                                        "Aceptada por tolerancia; sin cambios", f["celda"],
                                        datos=_d5(f, False, error_aplicar)))
            elif (sfc, ref) in hechos:
                out.append(cl._hallazgo(fecha, caja, sfc, 5, cl.INFO,
                                        "ℹ️ " + traza + " Se guardó como fecha real con el mismo valor.",
                                        "Aceptada por tolerancia; formato normalizado", f["celda"],
                                        datos=_d5(f, True, error_aplicar)))
            else:
                motivo = ("no se pudo aplicar: %s" % error_aplicar) if error_aplicar else "no se aplicó (sin carpeta de salida)"
                out.append(cl._hallazgo(fecha, caja, sfc, 5, cl.REVISAR,
                                        "⚠️ %s Pendiente: %s." % (traza, motivo),
                                        "Normalizar el formato de la fecha", f["celda"],
                                        datos=_d5(f, False, error_aplicar)))
        elif f["clase"] == c5.CONVERTIR_TEXTO_SIN_VOUCHER:
            traza = ("%s — %s (celda %s): %s → %s. No se encontró su voucher en MACROS; solo se normalizó el formato "
                     "(mismo día, mes y año)." % (f["motivo"], dep, ref, f["valor_actual"], _fd(f["fecha_nueva"])))
            if (sfc, ref) in hechos:
                out.append(cl._hallazgo(fecha, caja, sfc, 5, cl.INFO, "ℹ️ " + traza,
                                        "Normalizada automáticamente; contrastar cuando MACROS tenga el voucher", f["celda"],
                                        datos=_d5(f, True, error_aplicar)))
            else:
                motivo = ("no se pudo aplicar: %s" % error_aplicar) if error_aplicar else "no se aplicó (sin carpeta de salida)"
                out.append(cl._hallazgo(fecha, caja, sfc, 5, cl.REVISAR,
                                        "⚠️ %s Pendiente: %s." % (traza, motivo),
                                        "Normalizar el formato de la fecha", f["celda"],
                                        datos=_d5(f, False, error_aplicar)))
        elif f["accion"] in ("NORMALIZAR", "CONVERTIR"):
            if (sfc, ref) in hechos:
                out.append(cl._hallazgo(fecha, caja, sfc, 5, cl.OK,
                                        "✅ Fecha de depósito corregida — %s (celda %s): %s → %s, según el voucher de MACROS."
                                        % (dep, ref, f["valor_actual"], _fd(f["fecha_nueva"])),
                                        "Corregida automáticamente", f["celda"],
                                        datos=_d5(f, True, error_aplicar)))
            else:
                motivo = ("no se pudo aplicar: %s" % error_aplicar) if error_aplicar else "no se aplicó (sin carpeta de salida)"
                out.append(cl._hallazgo(fecha, caja, sfc, 5, cl.REVISAR,
                                        "⚠️ Fecha de depósito por corregir — %s (celda %s): %s → %s; %s."
                                        % (dep, ref, f["valor_actual"], _fd(f["fecha_nueva"]), motivo),
                                        "Corregir la fecha según el voucher", f["celda"],
                                        datos=_d5(f, False, error_aplicar)))
        elif f["clase"] == c5.VACIA:
            out.append(cl._hallazgo(fecha, caja, sfc, 5, cl.REVISAR,
                                    "⚠️ Falta la fecha de depósito — %s (celda %s)." % (dep, ref),
                                    "Completar la fecha manualmente (no se completa sola)", f["celda"],
                                        datos=_d5(f, False, error_aplicar)))
        else:
            extra = " Voucher: %s." % f["fecha_voucher"] if f["fecha_voucher"] else ""
            out.append(cl._hallazgo(fecha, caja, sfc, 5, cl.REVISAR,
                                    "⚠️ Revisar la fecha de depósito — %s (celda %s), valor: %s. %s.%s"
                                    % (dep, ref, f["valor_actual"], _razon(f["motivo"]).capitalize(), extra),
                                    "Revisar con el voucher; no se modifica", f["celda"],
                                        datos=_d5(f, False, error_aplicar)))
    return out


def hallazgos_especiales(especiales, fecha, caja):
    grupos = {}
    for e in especiales:
        grupos.setdefault((e["sfc"], e["categoria"]), []).append(e)
    out = []
    for (sfc, cat), lst in sorted(grupos.items()):
        total = sum((e["importe"] for e in lst if e["importe"] is not None), cl.Decimal("0"))
        filas = ", ".join(str(e["fila"]) for e in lst)
        pend = [e for e in lst if e["falta"]]
        base = "%s: %d fila(s) (%s), Bs %s." % (cat, len(lst), filas, cl.bs(total))
        if pend:
            out.append(cl._hallazgo(fecha, caja, sfc, 2, cl.REVISAR,
                                    "⚠️ " + base + " Completar cuenta contable y asignación a mano.",
                                    "Completar manualmente", lst[0]["fila"],
                                    datos={"tipo": "c2_especiales", "categoria": cat, "filas": [e["fila"] for e in lst],
                                           "importe": str(total), "completo": False}))
        else:
            out.append(cl._hallazgo(fecha, caja, sfc, 2, cl.INFO,
                                    "ℹ️ " + base + " Cuenta y asignación ya están completas.",
                                    "Solo informativo", lst[0]["fila"],
                                    datos={"tipo": "c2_especiales", "categoria": cat, "filas": [e["fila"] for e in lst],
                                           "importe": str(total), "completo": True}))
    return out


def destino_salida(salida_dir, caja, ruta):
    """Las copias normalizadas van SIEMPRE a <salida-dir>/<CAJA>/: dos cajas con un
    cierre del mismo nombre no pueden pisarse."""
    return os.path.join(salida_dir, caja.upper(), os.path.basename(ruta))


_MESES = ["ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO", "JUNIO", "JULIO", "AGOSTO", "SEPTIEMBRE", "OCTUBRE",
          "NOVIEMBRE", "DICIEMBRE"]


def _macros_de_cierre(macros, fecha):
    """MACROS que corresponde al mes del cierre (por el nombre 'MACROS <MES>.xlsm'); con un solo MACROS, ese."""
    if not macros:
        return None
    if fecha:
        for m in macros:
            if _MESES[fecha.month - 1] in os.path.basename(m).upper():
                return m
    return macros[0] if len(macros) == 1 else None


def _validar_motor(grupos, macros, motor_dir=None):
    """Corre validar_motor.py en otro proceso (solo lectura). Nunca detiene la auditoria."""
    items = []
    for caja, ruta in grupos:
        f = fecha_de_nombre(ruta)
        items.append({"caja": caja, "ruta": ruta, "fecha": f.isoformat() if f else None,
                      "maestro": _macros_de_cierre(macros, f)})
    import tempfile
    fd, tmp = tempfile.mkstemp(suffix=".json", prefix="motor_items_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(items, fh)
        cmd = [sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "validar_motor.py"), "--items", tmp]
        if motor_dir:
            cmd += ["--motor-dir", motor_dir]
        p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", timeout=600)
        return json.loads(p.stdout)
    except Exception as exc:  # noqa: BLE001
        return {"disponible": False, "motivo": "ERROR_VALIDACION_MOTOR: %s: %s" % (type(exc).__name__, exc), "items": []}
    finally:
        os.remove(tmp)


def hallazgos_motor(motor, cierres):
    """Convierte la validacion del motor en hallazgos. `cierres`: [(caja, ruta, fecha, leyo_auditor)]."""
    out = []
    por_clave = {(i["caja"], i["archivo"]): i for i in motor.get("items", [])}
    for caja, ruta, fecha, leyo in cierres:
        i = por_clave.get((caja, os.path.basename(ruta)))
        if i is None:
            continue
        if i["lectura_motor"] != "OK":
            texto = "⚠️ El motor CAJAS GABO no pudo leer el cierre (%s)." % (i["error"] or "sin detalle")
            if i.get("archivo_validado") == "original_con_cambios_pendientes":
                texto += (" Se validó el original porque no se generó la copia normalizada: el cierre aún tiene fechas por "
                          "normalizar (ver Control 5).")
            elif leyo:
                texto += " El auditor sí pudo leerlo: discrepancia de lectura."
            out.append(cl._hallazgo(fecha, caja, None, 7, cl.REVISAR, texto, "Revisar el cierre antes de procesarlo con CAJAS GABO",
                                    datos={"tipo": "motor_no_lee", "archivo_validado": i.get("archivo_validado"),
                                           "leyo_auditor": bool(leyo)}))
            continue
        problemas = []
        if i["estado_maestro"] and i["estado_maestro"] not in ("MAESTRO_APTO", "SIN_MACROS"):
            problemas.append("el motor no lo procesaría todavía (%s): %s" % (i["codigo_bloqueo"] or i["estado_maestro"], i["mensaje"]))
        for o in i["observaciones"]:
            problemas.append("observación del motor: %s" % o)
        if i["estado_maestro"] == "SIN_MACROS":
            problemas.append("no se pudo evaluar la cobertura de MACROS (no hay MACROS de ese mes)")
        if problemas:
            out.append(cl._hallazgo(fecha, caja, None, 7, cl.REVISAR, "⚠️ Motor CAJAS GABO: " + "; ".join(problemas),
                                    "Revisar antes de procesar con CAJAS GABO",
                                    datos={"tipo": "motor_observaciones", "estado_maestro": i["estado_maestro"],
                                           "codigo_bloqueo": i["codigo_bloqueo"], "fecha_maxima_macros": i["fecha_maxima_macros"],
                                           "fecha_requerida_deposito": i.get("fecha_requerida_deposito"),
                                           "fecha_cierre": fecha.isoformat() if fecha else None, "mensaje": i.get("mensaje"),
                                           "observaciones": list(i["observaciones"])}))
        else:
            out.append(cl._hallazgo(fecha, caja, None, 7, cl.OK,
                                    "✅ Motor CAJAS GABO: cierre legible y MACROS con cobertura (hasta %s)." % i["fecha_maxima_macros"],
                                    "Sin acción", datos={"tipo": "motor_ok"}))
    return out


def _jsonable(o):
    if isinstance(o, (datetime.date, datetime.datetime)):
        return o.isoformat()
    if isinstance(o, cl.Decimal):
        return float(o)
    return str(o)


def _escribir_resultados(carpeta, hoy, resumen, cierres, hallazgos, alquileres, especiales, motor, origen, informe_humano=None):
    """Escribe en `carpeta` el .json completo y el .csv de hallazgos (van dentro del ZIP de resultados)."""
    ruta_json = os.path.join(carpeta, NOMBRE_JSON)
    ruta_csv = os.path.join(carpeta, NOMBRE_CSV)
    orden = sorted(hallazgos, key=lambda h: (h["fecha"] or datetime.date.min, h["caja"], h["sfc"] or "", h["control"], h["fila"] or 0))
    detalle = {"generado": hoy.isoformat(), "resumen": resumen, "cierres": cierres, "hallazgos": orden, "alquileres": alquileres,
               "especiales_a_completar": especiales, "motor_cajas_gabo": motor, "origen": origen,
               "originales_drive_modificados": False, "informe_humano": informe_humano}
    with open(ruta_json, "w", encoding="utf-8") as f:
        json.dump(detalle, f, ensure_ascii=False, indent=1, default=_jsonable)
    with open(ruta_csv, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["FECHA", "CAJA", "SFC", "RESULTADO", "HALLAZGO", "ACCION"])
        for h in orden:
            w.writerow([_fd(h["fecha"]) if h["fecha"] else "", h["caja"].upper(), h["sfc"] or "", rx.ETIQUETA[h["resultado"]],
                        h["hallazgo"], h["accion"]])
    return ruta_json, ruta_csv


def _memoria_pico_mb():
    """Pico de memoria residente del proceso (medido por el sistema operativo); None si no se puede medir."""
    try:
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes

            class PMC(ctypes.Structure):
                _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                            ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                            ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]
            k32, ps = ctypes.WinDLL("kernel32"), ctypes.WinDLL("psapi")
            k32.GetCurrentProcess.restype = wintypes.HANDLE
            ps.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(PMC), wintypes.DWORD]
            c = PMC()
            c.cb = ctypes.sizeof(PMC)
            if not ps.GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(c), c.cb):
                return None
            return c.PeakWorkingSetSize / 1048576.0
        import resource
        r = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return (r / 1048576.0) if sys.platform == "darwin" else (r / 1024.0)
    except Exception:  # noqa: BLE001
        return None


def _version(modulo):
    try:
        import importlib.metadata as md
        return md.version("python-docx" if modulo == "docx" else modulo)
    except Exception:  # noqa: BLE001
        return "no instalado"


def _mb(n):
    return "%.2f MB" % (n / 1048576.0)


def _texto_recursos(inicio, hoy_dt, t_total, t_motor, grupos, macros, resumen, hallazgos, copias, motor, origen, salidas):
    """RECURSOS_USADOS.txt: SOLO metricas que el propio proceso puede verificar (medidas o contadas)."""
    try:
        import openpyxl
        ver_opx = openpyxl.__version__
    except Exception:  # noqa: BLE001
        ver_opx = "?"
    por_caja = {}
    for caja, _r in grupos:
        por_caja[caja] = por_caja.get(caja, 0) + 1
    b_cierres = sum(os.path.getsize(r) for _c, r in grupos if os.path.isfile(r))
    b_macros = sum(os.path.getsize(m) for m in macros if os.path.isfile(m))
    mem = _memoria_pico_mb()
    L = ["RECURSOS USADOS EN ESTA CORRIDA — auditor-cierres",
         "Solo se declaran metricas medidas o contadas por el propio proceso de auditoria.", "",
         "== Tiempo (medido) ==",
         "Inicio del proceso de auditoria : %s" % inicio.strftime("%Y-%m-%d %H:%M:%S"),
         "Fin de la auditoria             : %s" % hoy_dt.strftime("%Y-%m-%d %H:%M:%S"),
         "Duracion del proceso (reloj)    : %.2f s" % t_total,
         "Tiempo de CPU del proceso Python: %.2f s" % time.process_time(),
         "Duracion validacion motor CAJAS GABO (subproceso, reloj): %s" % ("%.2f s" % t_motor if t_motor is not None else "no ejecutada")]
    sesion_creada = (origen or {}).get("sesion_creada")
    if sesion_creada:
        try:
            seg = (hoy_dt - datetime.datetime.fromisoformat(sesion_creada)).total_seconds()
            L.append("Desde iniciar la sesion temporal hasta fin de auditoria (incluye materializacion; reloj): %.1f s" % seg)
        except ValueError:
            pass
    L += ["", "== Memoria (medida por el sistema operativo) ==",
          "Pico de memoria residente del proceso de auditoria: %s" % ("%.1f MB" % mem if mem is not None else "no disponible en esta plataforma"),
          "(no incluye el subproceso del motor)", "",
          "== Entradas (contadas) ==",
          "Cierres auditados: %d (%s)" % (len(grupos), ", ".join("%s: %d" % (c.upper(), n) for c, n in sorted(por_caja.items())) or "-"),
          "Bytes de cierres leidos : %d (%s)" % (b_cierres, _mb(b_cierres)),
          "MACROS usados          : %d archivo(s), %d bytes (%s)" % (len(macros), b_macros, _mb(b_macros))]
    if origen:
        L.append("Archivos descargados de Google Drive (registrados por la materializacion): %d cierre(s) + %d MACROS"
                 % (len(origen.get("cierres", [])), len(origen.get("macros", []))))
        L.append("Descargas = solo lectura; los originales en Drive no se modificaron.")
    L += ["", "== Salidas (contadas) ==",
          "Hallazgos registrados: %d | cierres sin observaciones: %d | a revisar: %d" % (len(hallazgos), resumen["sin_observaciones"], resumen["requieren_revision"]),
          "Fechas de deposito normalizadas (copias escritas): %d" % len(copias),
          "Informe PDF : %s | Informe DOCX : %s | Detalle tecnico (Excel interno): %s" % tuple(
              ("%d bytes" % salidas[k]) if salidas.get(k) is not None else "no generado" for k in ("pdf", "docx", "xlsx")),
          "Motor CAJAS GABO: %s" % ("disponible (excel_io %s, precheck_maestro %s)" % (motor["motor"]["excel_io_sha"], motor["motor"]["precheck_maestro_sha"])
                                    if motor and motor.get("disponible") else "no disponible / no ejecutado"),
          "", "== Entorno (verificado) ==",
          "Python %s | openpyxl %s | reportlab %s | python-docx %s | %s" % (sys.version.split()[0], ver_opx, _version("reportlab"),
                                                                              _version("docx"), sys.platform), "",
          "== NO medido por la skill (no se declara) ==",
          "Tokens/contexto del asistente, costo, llamadas de listado y metadatos a Drive, trafico de red.",
          "La limpieza de temporales se ejecuta DESPUES de crear este archivo; su resultado se informa en la respuesta de la sesion."]
    return "\n".join(L) + "\n"


def _empaquetar(reporte_dir, salida_dir, miembros, copias, sueltos):
    """Crea AUDITORIA_CIERRES_RESULTADOS.zip con `miembros` [(ruta, nombre_en_zip)] y las copias normalizadas; lo verifica y
    borra los `sueltos` (temporales que ya estan dentro del ZIP) y las copias ubicadas dentro de `reporte_dir`."""
    ruta_zip = os.path.join(reporte_dir, NOMBRE_ZIP)
    miembros = list(miembros)
    for c in copias:
        if os.path.isfile(c):
            miembros.append((c, "CIERRES_NORMALIZADOS/%s/%s" % (os.path.basename(os.path.dirname(c)), os.path.basename(c))))
    with zipfile.ZipFile(ruta_zip, "w", zipfile.ZIP_DEFLATED) as z:
        for ruta, arc in miembros:
            z.write(ruta, arc)
    with zipfile.ZipFile(ruta_zip) as z:
        if z.testzip() is not None or sorted(z.namelist()) != sorted(a for _r, a in miembros):
            raise RuntimeError("ZIP_DE_RESULTADOS_INVALIDO")
    base = os.path.abspath(reporte_dir)
    for ruta in sueltos:
        if os.path.isfile(ruta):
            os.remove(ruta)
    if salida_dir and os.path.abspath(salida_dir).startswith(base + os.sep):
        for c in copias:
            if os.path.isfile(c):
                os.remove(c)
        for r, dirs, _f in os.walk(salida_dir, topdown=False):
            if not os.listdir(r):
                os.rmdir(r)
    return ruta_zip, [a for _r, a in miembros]


def _generar_informe_humano(reporte_dir, ejecucion, cierres, hallazgos, alquileres, motor, macros):
    """PDF (principal) y DOCX (editable) desde el mismo modelo. Cada uno es independiente: si falta una biblioteca o falla,
    se informa un motivo legible y la auditoria continua."""
    res = {"pdf": None, "docx": None, "motivos": [], "modelo": None}
    try:
        modelo = ih.modelo_limpio(ejecucion, cierres, hallazgos, alquileres, motor, [os.path.basename(m) for m in macros])
    except Exception as exc:  # noqa: BLE001
        res["motivos"].append("no se pudo preparar el contenido del informe (%s)" % type(exc).__name__)
        return res
    res["modelo"] = modelo
    for clave, nombre, fn, lib in (("pdf", NOMBRE_PDF, ih.escribir_pdf, "reportlab"), ("docx", NOMBRE_DOCX, ih.escribir_docx, "python-docx")):
        ruta = os.path.join(reporte_dir, nombre)
        try:
            fn(modelo, ruta)
            res[clave] = ruta
        except ImportError:
            res["motivos"].append("%s no generado: falta la biblioteca %s (pip install %s)" % (nombre, lib, lib))
        except Exception as exc:  # noqa: BLE001
            res["motivos"].append("%s no generado (%s)" % (nombre, type(exc).__name__))
            if os.path.exists(ruta):
                os.remove(ruta)
    return res


def auditar(grupos, macros, salida_dir=None, reporte_dir=".", hoy=None, validar_motor=False, motor_dir=None, origen=None):
    inicio = datetime.datetime.now()
    hoy = hoy or datetime.date.today()
    if any(os.path.exists(os.path.join(reporte_dir, n)) for n in
           (NOMBRE_PDF, NOMBRE_DOCX, ic.NOMBRE_RESUMEN, ic.NOMBRE_AMERICA, ic.NOMBRE_TIQUIPAYA, NOMBRE_ZIP)):
        raise FileExistsError("SALIDA_YA_EXISTE: %s ya tiene un informe/ZIP de otra corrida; use una carpeta nueva" % reporte_dir)
    indice, macros_error, registros = None, None, None
    if macros:
        try:
            indice, registros = {}, []
            for m in macros:
                leido = mv.leer_indice_macros(m)
                for k, v in leido["indice"].items():
                    indice.setdefault(k, []).extend(v)
                registros += leido["registros"]
        except Exception as exc:  # noqa: BLE001
            indice, registros, macros_error = None, None, "%s: %s" % (type(exc).__name__, exc)

    hallazgos, alquileres, especiales, cierres = [], [], [], []
    normalizadas = 0
    destinos_usados = set()
    copias = []
    copia_de, con_plan = {}, {}    # ruta original -> copia normalizada verificada | si el auditor tenia cambios que aplicar
    leidos = []
    for caja, ruta in grupos:
        fecha = fecha_de_nombre(ruta)
        h_cierre = []
        leyo = False
        try:
            pq = X.Paquete(ruta)
            sfcs = c5.CAJAS[caja]
            h, alq, esp = cl.auditar_lectura(pq, sfcs, fecha, caja)
            h_cierre += h + hallazgos_especiales(esp, fecha, caja)
            especiales += esp
            if any(a["fecha_del_cierre"] for a in alq):
                n = sum(1 for a in alq if a["fecha_del_cierre"])
                h_cierre.append(cl._hallazgo(fecha, caja, None, 6, cl.INFO,
                                             "ℹ️ %d alquiler(es) sin FECHA2 válida: se usó la fecha del cierre." % n,
                                             "Solo informativo", datos={"tipo": "c6_fecha_del_cierre", "cantidad": n}))
            alquileres += alq

            leyo = True
            if indice is None:
                # La falta (o ilegibilidad) de MACROS NO impide normalizar formatos: se analiza con un indice
                # vacio (sin vouchers) y se avisa que no hubo contraste.
                h_cierre.append(cl._hallazgo(fecha, caja, None, 5, cl.REVISAR,
                                             "⚠️ Las fechas de depósito no se contrastaron con vouchers: " + (
                                                 "no se pudo leer MACROS (%s)." % macros_error if macros_error
                                                 else "no se indicó el archivo MACROS.")
                                             + " Solo se normaliza el formato de las fechas escritas como texto válido.",
                                             "Contar con el MACROS oficial del mes y volver a auditar",
                                             datos={"tipo": "c5_sin_macros", "ilegible": bool(macros_error)}))
            indice_cierre = indice if indice is not None else {}
            informe = c5.analizar(ruta, indice_cierre, caja, paquete=pq, fecha_cierre=fecha, registros_macros=registros)
            con_plan[ruta] = bool(informe["plan"])
            aplicado, error = {"cambios": []}, None
            if salida_dir and informe["plan"]:
                try:
                    destino = destino_salida(salida_dir, caja, ruta)
                    clave = os.path.normcase(os.path.abspath(destino))
                    if clave in destinos_usados:
                        raise X.ErrorXlsm("colisión de salida: ya se escribió %s en esta corrida" % destino)
                    os.makedirs(os.path.dirname(destino), exist_ok=True)
                    aplicado = c5.aplicar(ruta, destino, informe)
                    destinos_usados.add(clave)
                    copias.append(destino)
                    problemas, _ = c5.reanalizar_y_comparar(destino, indice_cierre, caja, informe, fecha_cierre=fecha)
                    if problemas:
                        os.remove(destino)
                        raise X.ErrorXlsm("la verificación posterior falló")
                    copia_de[ruta] = destino          # copia verificada: es la que se valida con el motor y se entrega
                except Exception as exc:  # noqa: BLE001
                    aplicado, error = {"cambios": []}, str(exc)
            h_cierre += hallazgos_control5(informe, aplicado, error, fecha, caja)
            normalizadas += len(aplicado.get("cambios", []))
        except Exception as exc:  # noqa: BLE001
            h_cierre.append(cl._hallazgo(fecha, caja, None, 1, cl.NO_CUADRA,
                                         "❌ No se pudo leer el cierre (%s)." % type(exc).__name__,
                                         "Revisar que el archivo esté completo y vuelva a auditar",
                                         datos={"tipo": "cierre_ilegible"}))
        hallazgos += h_cierre
        avisos = sum(1 for h in h_cierre if h["resultado"] in (cl.REVISAR, cl.NO_CUADRA))
        cierres.append({"fecha": fecha, "caja": caja, "estado": "OK" if avisos == 0 else "REVISAR", "avisos": avisos,
                        "archivo": os.path.basename(ruta)})
        leidos.append((caja, ruta, fecha, leyo))

    motor, t_motor = None, None
    if validar_motor and grupos:
        # ORDEN: el motor valida el archivo que se ENTREGA -> la copia normalizada (post-auditoria) si existe;
        # si el cierre no necesito cambios, su copia temporal equivalente (el mismo archivo materializado).
        grupos_motor = [(caja, copia_de.get(ruta, ruta)) for caja, ruta in grupos]
        _tm = time.perf_counter()
        motor = _validar_motor(grupos_motor, macros, motor_dir)
        t_motor = time.perf_counter() - _tm
        for it, (_c, r_val), (_c2, r_orig) in zip(motor.get("items", []), grupos_motor, grupos):
            it["archivo_validado"] = ("copia_normalizada" if r_orig in copia_de else
                                      "original_con_cambios_pendientes" if con_plan.get(r_orig) else "original_sin_cambios")
        if motor.get("disponible"):
            for h in hallazgos_motor(motor, leidos):
                hallazgos.append(h)
                if h["resultado"] in (cl.REVISAR, cl.NO_CUADRA):
                    for c in cierres:
                        if c["caja"] == h["caja"] and c["fecha"] == h["fecha"]:
                            c["avisos"] += 1
                            c["estado"] = "REVISAR"

    por_dia = {}
    for a in alquileres:
        por_dia[a["fecha"]] = por_dia.get(a["fecha"], cl.Decimal("0")) + a["importe"]
    total_alq = sum(por_dia.values(), cl.Decimal("0"))
    resumen = {
        "revisados": len(cierres),
        "sin_observaciones": sum(1 for c in cierres if c["estado"] == "OK"),
        "requieren_revision": sum(1 for c in cierres if c["estado"] != "OK"),
        "fechas_normalizadas": normalizadas,
        "dias_alquileres": len(por_dia),
        "total_alquileres": float(total_alq),
    }
    os.makedirs(reporte_dir, exist_ok=True)
    ruta_xlsx = rx.generar(os.path.join(reporte_dir, NOMBRE_DETALLE), hoy, cierres, hallazgos, alquileres, especiales, resumen,
                           motor=motor)
    copias = [c for c in copias if os.path.isfile(c)]
    humano = _generar_informe_humano(reporte_dir, inicio, cierres, hallazgos, alquileres, motor, macros)
    cortos = ic.generar(reporte_dir, inicio, cierres, hallazgos, alquileres, macros)
    ruta_json, ruta_csv = _escribir_resultados(reporte_dir, hoy, resumen, cierres, hallazgos, alquileres, especiales, motor, origen,
                                               informe_humano=humano["modelo"])
    tam = lambda r: os.path.getsize(r) if r and os.path.isfile(r) else None  # noqa: E731
    texto = _texto_recursos(inicio, datetime.datetime.now(), time.perf_counter() - _T0, t_motor, grupos, macros, resumen, hallazgos,
                            copias, motor, origen, {"pdf": tam(humano["pdf"]), "docx": tam(humano["docx"]), "xlsx": tam(ruta_xlsx)})
    ruta_rec = os.path.join(reporte_dir, NOMBRE_RECURSOS)
    with open(ruta_rec, "w", encoding="utf-8") as f:
        f.write(texto)
    miembros = [(r, n) for r, n in ((humano["pdf"], NOMBRE_PDF), (humano["docx"], NOMBRE_DOCX)) if r]
    miembros += [(ruta_xlsx, NOMBRE_DETALLE), (ruta_json, NOMBRE_JSON), (ruta_csv, NOMBRE_CSV), (ruta_rec, NOMBRE_RECURSOS)]
    # Todo el detalle tecnico queda exclusivamente dentro del ZIP.
    sueltos = [ruta_json, ruta_csv, ruta_rec, ruta_xlsx] + [r for r in (humano["pdf"], humano["docx"]) if r]
    ruta_zip, contenido = _empaquetar(reporte_dir, salida_dir, miembros, copias, sueltos)
    principal = cortos["resumen_gabo"]
    out = _salida_compacta(resumen, cierres, hallazgos, por_dia, total_alq, especiales, principal)
    cand = _lineas_candidatos(hallazgos)
    if cand:
        out["candidatos_voucher"] = cand
    out["archivos"] = {"pdf": cortos["resumen_gabo"],
                       "resumen_gabo": cortos["resumen_gabo"],
                       "para_caja_america": cortos["para_caja_america"],
                       "para_caja_tiquipaya": cortos["para_caja_tiquipaya"],
                       "zip": os.path.abspath(ruta_zip), "contenido_zip": contenido,
                       "informe_tecnico_pdf_en_zip": NOMBRE_PDF if humano["pdf"] else None,
                       "informe_tecnico_docx_en_zip": NOMBRE_DOCX if humano["docx"] else None}
    if humano["motivos"]:
        out["informe_humano_incidencias"] = humano["motivos"]
    if motor is not None:
        ok = sum(1 for h in hallazgos if h["control"] == 7 and h["resultado"] == cl.OK)
        rev = sum(1 for h in hallazgos if h["control"] == 7 and h["resultado"] in (cl.REVISAR, cl.NO_CUADRA))
        out["motor_cajas_gabo"] = ({"disponible": True, "sin_observaciones": ok, "con_observaciones": rev}
                                   if motor.get("disponible") else {"disponible": False, "motivo": motor.get("motivo")})
    return out


def _lineas_candidatos(hallazgos):
    """Una linea por deposito sin voucher exacto con su veredicto de candidatos (solo informativo; max. 10)."""
    lineas = []
    for h in sorted(hallazgos, key=lambda h: (h["fecha"] or datetime.date.min, h["caja"], h["sfc"] or "", str(h["fila"] or ""))):
        c = (h.get("datos") or {}).get("candidatos")
        if not c:
            continue
        principal = c["candidatos"][0] if c["candidatos"] else None
        det = (" — MACROS %s, Bs %s, asignación %s" % (principal["fecha"], principal["importe"], principal["asignacion"])
               if principal and c["veredicto"] in (cv.PROBABLE, cv.POSIBLE) else "")
        lineas.append("%s %s %s · %s%s" % (_fd(h["fecha"])[:5], h["caja"][:3].upper(), h["sfc"], c["veredicto"], det))
    if len(lineas) > 10:
        lineas = lineas[:10] + ["y %d más; ver reporte" % (len(lineas) - 10)]
    return lineas


def _salida_compacta(resumen, cierres, hallazgos, por_dia, total_alq, especiales, ruta_reporte):
    """JSON pequeno para el contexto de Claude: cifras + max. 15 hallazgos."""
    graves = [h for h in hallazgos if h["resultado"] in (cl.NO_CUADRA, cl.REVISAR)]
    graves.sort(key=lambda h: (0 if h["resultado"] == cl.NO_CUADRA else 1, h["fecha"] or datetime.date.min, h["caja"], h["sfc"] or ""))
    lineas = ["%s %s%s · %s" % (_fd(h["fecha"])[:5], h["caja"][:3].upper(), (" " + h["sfc"]) if h["sfc"] else "",
                                h["hallazgo"].replace("\n", " | ")) for h in graves]
    if len(lineas) > MAX_HALLAZGOS_CONTEXTO:
        extra = len(lineas) - MAX_HALLAZGOS_CONTEXTO
        lineas = lineas[:MAX_HALLAZGOS_CONTEXTO] + ["y %d adicionales; ver reporte" % extra]
    esp = {}
    for e in especiales:
        esp.setdefault((e["fecha"], e["caja"], e["categoria"]), []).append(e["fila"])
    esp_lista = ["%s %s %s (filas %s)" % (_fd(f)[:5], c[:3].upper(), cat, ",".join(map(str, fl)))
                 for (f, c, cat), fl in sorted(esp.items(), key=lambda kv: (kv[0][0] or datetime.date.min, kv[0][1], kv[0][2]))]
    if len(esp_lista) > 10:
        esp_lista = esp_lista[:10] + ["y %d más; ver reporte" % (len(esp_lista) - 10)]
    dias = sorted(por_dia.items())
    alq_lista = ["%s — Bs %s" % (_fd(f), cl.bs(t)) for f, t in dias[:10]]
    if len(dias) > 10:
        alq_lista.append("y %d días más; ver reporte" % (len(dias) - 10))
    return {
        "estado": "OK" if not graves else "CON_HALLAZGOS",
        "cierres": {"revisados": resumen["revisados"], "sin_observaciones": resumen["sin_observaciones"],
                    "requieren_revision": resumen["requieren_revision"]},
        "cuadres_ok": sum(1 for h in hallazgos if h["control"] == 1 and h["resultado"] == cl.OK),
        "fechas_normalizadas": resumen["fechas_normalizadas"],
        "normalizadas_sin_voucher_macros": sum(1 for h in hallazgos if "FECHA_NORMALIZADA_SIN_VOUCHER_MACROS" in h["hallazgo"]
                                               and h["resultado"] == cl.INFO),
        "dentro_tolerancia_1_dia": sum(1 for h in hallazgos if "FECHA_DENTRO_TOLERANCIA_MACROS_1_DIA" in h["hallazgo"]
                                       and h["resultado"] == cl.INFO),
        "hallazgos": lineas,
        "especiales_a_completar": esp_lista,
        "alquileres": {"dias": len(dias), "detalle": alq_lista, "total_periodo": "Bs " + cl.bs(total_alq)},
        "reporte": ruta_reporte,
    }


class _Cierre(argparse.Action):
    def __call__(self, parser, ns, valores, option_string=None):
        caja = getattr(ns, "_caja", None)
        if not caja:
            parser.error("%s debe ir después de --caja" % option_string)
        rutas = [valores] if option_string == "--cierre" else sorted(
            p for p in glob.glob(os.path.join(valores, "CIERRE*.xlsm")) if not os.path.basename(p).startswith("~$"))
        for r in rutas:
            ns.grupos.append((caja, r))


class _Caja(argparse.Action):
    def __call__(self, parser, ns, valores, option_string=None):
        ns._caja = valores


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # emojis/tildes seguros en consolas Windows (cp1252)
    p = argparse.ArgumentParser(description="Auditor de Cierres (Controles 1-6)")
    p.add_argument("--caja", action=_Caja, choices=sorted(c5.CAJAS))
    p.add_argument("--cierre", action=_Cierre)
    p.add_argument("--carpeta", action=_Cierre)
    p.add_argument("--macros", action="append", default=[])
    p.add_argument("--manifiesto")
    p.add_argument("--salida-dir")
    p.add_argument("--reporte-dir")
    p.add_argument("--sin-motor", action="store_true")
    p.add_argument("--motor-dir")
    p.set_defaults(grupos=[], _caja=None)
    ns = p.parse_args(argv)
    origen = None
    if ns.manifiesto:
        with open(ns.manifiesto, encoding="utf-8") as f:
            man = json.load(f)
        for c in sorted(man["cierres"], key=lambda c: (c["caja"], c["fecha"])):
            ns.grupos.append((c["caja"], c["ruta"]))
        ns.macros += [m["ruta"] for m in man["macros"]]
        origen = {"cierres": [{k: c.get(k) for k in ("caja", "nombre", "drive_id", "bytes", "sha256", "modificado_drive")}
                              for c in man["cierres"]],
                  "macros": [{k: m.get(k) for k in ("nombre", "drive_id", "bytes", "sha256", "modificado_drive")}
                             for m in man["macros"]],
                  "notas": man.get("notas", {}), "sesion_creada": man.get("creada")}
        if not ns.reporte_dir:
            ns.reporte_dir = os.path.join(os.path.expanduser("~"), "AuditoriaCierres",
                                          datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S"))
        if not ns.salida_dir:
            ns.salida_dir = os.path.join(ns.reporte_dir, "CIERRES_NORMALIZADOS")
    if not ns.reporte_dir:
        ns.reporte_dir = "."
    if not ns.grupos:
        p.error("no se indicó ningún cierre (--manifiesto ARCHIVO | --caja X --cierre ARCHIVO | --carpeta DIR)")
    try:
        res = auditar(ns.grupos, ns.macros, ns.salida_dir, ns.reporte_dir, validar_motor=not ns.sin_motor,
                      motor_dir=ns.motor_dir, origen=origen)
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"estado": "ERROR", "error": "%s: %s" % (type(exc).__name__, exc)}, ensure_ascii=False, separators=(",", ":")))
        return 1
    print(json.dumps(res, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
