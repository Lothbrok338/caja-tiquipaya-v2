"""reporte_xlsx.py — Genera INFORME_AUDITORIA_CIERRES.xlsx (la ruta la fija auditar.py).

Es un archivo NUEVO (openpyxl solo se usa para crearlo; nunca para guardar un
cierre). Hojas: Resumen, Auditoria, Alquileres, Completar a mano.
"""
import datetime
import os

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from controles_lectura import bs

ETIQUETA = {"OK": "✅ Correcto", "REVISAR": "⚠️ Revisar", "NO_CUADRA": "❌ No cuadra", "INFO": "ℹ️ Informativo"}
_RELLENO = {"OK": "E8F5E9", "REVISAR": "FFF8E1", "NO_CUADRA": "FDECEA", "INFO": "EEF3FA"}
_ORDEN = {"NO_CUADRA": 0, "REVISAR": 1, "INFO": 2, "OK": 3}
_CAB = PatternFill("solid", fgColor="1F3A5F")
_FMT_FECHA = "dd/mm/yyyy"


def _cabecera(ws, titulos, anchos):
    ws.append(titulos)
    for i, a in enumerate(anchos, 1):
        c = ws.cell(1, i)
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = _CAB
        c.alignment = Alignment(vertical="center", wrap_text=True)
        ws.column_dimensions[get_column_letter(i)].width = a
    ws.freeze_panes = "A2"


def _fecha_cel(ws, fila, col, f):
    c = ws.cell(fila, col, f)
    if isinstance(f, (datetime.date, datetime.datetime)):
        c.number_format = _FMT_FECHA
    c.alignment = Alignment(vertical="top", horizontal="left")


def generar(ruta, hoy, cierres, hallazgos, alquileres, especiales, resumen, motor=None):
    """cierres: [{fecha, caja, estado, avisos}]; resumen: dict de cifras; motor: salida de validar_motor (opcional)."""
    wb = Workbook()

    # --- Resumen ------------------------------------------------------------
    ws = wb.active
    ws.title = "Resumen"
    ws["A1"] = "Auditoría de cierres"
    ws["A1"].font = Font(bold=True, size=14)
    ws["A2"] = "Generado el %s" % hoy.strftime("%d/%m/%Y")
    filas = [
        ("Cierres revisados", resumen["revisados"]),
        ("Cierres sin observaciones", resumen["sin_observaciones"]),
        ("Cierres que requieren revisión", resumen["requieren_revision"]),
        ("Fechas de depósito normalizadas", resumen["fechas_normalizadas"]),
        ("Días con alquileres", resumen["dias_alquileres"]),
        ("Importe total de alquileres (Bs)", resumen["total_alquileres"]),
    ]
    for i, (k, v) in enumerate(filas, 4):
        ws.cell(i, 1, k).font = Font(bold=True)
        ws.cell(i, 2, v).alignment = Alignment(horizontal="right")
    fila0 = 4 + len(filas) + 1
    for j, t in enumerate(("FECHA", "CAJA", "ESTADO", "AVISOS"), 1):
        c = ws.cell(fila0, j, t)
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = _CAB
    for i, c in enumerate(sorted(cierres, key=lambda x: (x["fecha"] or datetime.date.min, x["caja"])), fila0 + 1):
        _fecha_cel(ws, i, 1, c["fecha"])
        ws.cell(i, 2, c["caja"].upper())
        e = ws.cell(i, 3, "Sin observaciones" if c["estado"] == "OK" else "Requiere revisión")
        e.fill = PatternFill("solid", fgColor=_RELLENO["OK" if c["estado"] == "OK" else "REVISAR"])
        ws.cell(i, 4, c["avisos"])
    for col, a in zip("ABCD", (38, 14, 22, 10)):
        ws.column_dimensions[col].width = a

    # --- Auditoria ----------------------------------------------------------
    wa = wb.create_sheet("Auditoria")
    _cabecera(wa, ["FECHA", "CAJA", "SFC", "RESULTADO", "HALLAZGO", "ACCION"], [13, 12, 9, 15, 70, 44])
    orden = sorted(hallazgos, key=lambda h: (h["fecha"] or datetime.date.min, h["caja"], h["sfc"] or "",
                                              _ORDEN[h["resultado"]], h["control"], h["fila"] or 0))
    for i, h in enumerate(orden, 2):
        _fecha_cel(wa, i, 1, h["fecha"])
        wa.cell(i, 2, h["caja"].upper())
        wa.cell(i, 3, h["sfc"])
        r = wa.cell(i, 4, ETIQUETA[h["resultado"]])
        r.fill = PatternFill("solid", fgColor=_RELLENO[h["resultado"]])
        wa.cell(i, 5, h["hallazgo"]).alignment = Alignment(wrap_text=True, vertical="top")
        wa.cell(i, 6, h["accion"]).alignment = Alignment(wrap_text=True, vertical="top")
        for col in (2, 3, 4):
            wa.cell(i, col).alignment = Alignment(vertical="top")
    wa.auto_filter.ref = "A1:F%d" % max(len(orden) + 1, 2)

    # --- Alquileres ---------------------------------------------------------
    wq = wb.create_sheet("Alquileres")
    _cabecera(wq, ["FECHA", "CAJA", "SFC", "IMPORTE"], [13, 20, 9, 16])
    fila = 2
    por_dia = {}
    for a in sorted(alquileres, key=lambda x: (x["fecha"], x["caja"], x["sfc"], x["fila"])):
        _fecha_cel(wq, fila, 1, a["fecha"])
        wq.cell(fila, 2, a["caja"].upper())
        wq.cell(fila, 3, a["sfc"])
        c = wq.cell(fila, 4, float(a["importe"]))
        c.number_format = "#,##0.00"
        por_dia[a["fecha"]] = por_dia.get(a["fecha"], 0) + a["importe"]
        fila += 1
    if alquileres:
        fila += 1
        for f, t in sorted(por_dia.items()):
            _fecha_cel(wq, fila, 1, f)
            wq.cell(fila, 2, "TOTAL DEL DÍA").font = Font(bold=True)
            c = wq.cell(fila, 4, float(t))
            c.number_format = "#,##0.00"
            c.font = Font(bold=True)
            fila += 1
        wq.cell(fila, 1, "TOTAL PERIODO").font = Font(bold=True)
        c = wq.cell(fila, 4, float(sum(por_dia.values())))
        c.number_format = "#,##0.00"
        c.font = Font(bold=True)
    else:
        wq.cell(2, 1, "No hay alquileres en el periodo revisado.")

    # --- Completar a mano ---------------------------------------------------
    wm = wb.create_sheet("Completar a mano")
    _cabecera(wm, ["FECHA", "CAJA", "SFC", "CATEGORIA", "FILA", "IMPORTE", "FALTA"], [13, 12, 9, 18, 8, 14, 34])
    for i, e in enumerate(sorted(especiales, key=lambda x: (x["fecha"] or datetime.date.min, x["caja"], x["sfc"], x["fila"])), 2):
        _fecha_cel(wm, i, 1, e["fecha"])
        wm.cell(i, 2, e["caja"].upper())
        wm.cell(i, 3, e["sfc"])
        wm.cell(i, 4, e["categoria"])
        wm.cell(i, 5, e["fila"])
        if e["importe"] is not None:
            c = wm.cell(i, 6, float(e["importe"]))
            c.number_format = "#,##0.00"
        wm.cell(i, 7, (" y ".join(e["falta"]) if e["falta"] else "Completo"))
    if not especiales:
        wm.cell(2, 1, "No hay filas OTROS INGRESOS / GASTO.ADM / POSGRADO.PLA.")

    # --- Validacion con el motor CAJAS GABO (solo lectura) ------------------------
    if motor is not None:
        wv = wb.create_sheet("Validacion motor")
        if not motor.get("disponible"):
            wv.cell(1, 1, "Validación con el motor CAJAS GABO no disponible: %s" % motor.get("motivo"))
        else:
            _cabecera(wv, ["FECHA", "CAJA", "ARCHIVO", "LECTURA MOTOR", "DEPOSITOS LEIDOS", "MACROS HASTA", "ESTADO MACROS", "DETALLE",
                           "ARCHIVO VALIDADO", "FECHAS DE DEPOSITO QUE LEYO EL MOTOR"],
                      [13, 12, 26, 15, 16, 14, 30, 70, 30, 34])
            for i, it in enumerate(motor["items"], 2):
                f = datetime.date.fromisoformat(it["fecha"]) if it.get("fecha") else None
                _fecha_cel(wv, i, 1, f)
                wv.cell(i, 2, it["caja"].upper())
                wv.cell(i, 3, it["archivo"])
                wv.cell(i, 4, it["lectura_motor"])
                wv.cell(i, 5, it["depositos_motor"])
                wv.cell(i, 6, it["fecha_maxima_macros"])
                wv.cell(i, 7, it["codigo_bloqueo"] or it["estado_maestro"])
                detalle = it["error"] or "; ".join(x for x in [it["mensaje"] if it["estado_maestro"] not in ("MAESTRO_APTO", None) else None]
                                                   + it["observaciones"] if x)
                wv.cell(i, 8, detalle).alignment = Alignment(wrap_text=True, vertical="top")
                wv.cell(i, 9, {"copia_normalizada": "Copia normalizada (la que se entrega)",
                               "original_sin_cambios": "Copia temporal sin cambios (no necesitó normalizar)",
                               "original_con_cambios_pendientes": "Original: no se pudo generar la copia normalizada"}.get(
                                   it.get("archivo_validado"), it.get("archivo_validado")))
                wv.cell(i, 10, ", ".join(it.get("fechas_deposito_motor") or []))
            m = motor["motor"]
            wv.cell(len(motor["items"]) + 3, 1, "Motor: %s (excel_io %s, precheck_maestro %s)" % (m["dir"], m["excel_io_sha"], m["precheck_maestro_sha"]))

    wb.save(ruta)
    return ruta
