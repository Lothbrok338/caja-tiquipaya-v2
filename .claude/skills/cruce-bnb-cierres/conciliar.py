"""Cruce diario de depósitos declarados en cierres de cajeros vs abonos BNB.

Uso:
    python conciliar.py --cierres DIR --macro ARCHIVO.xlsm \
        --desde 27-10-2026 --hasta 28-10-2026 --salida DIR_SALIDA

--cierres  carpeta con los cierres, nombrados "... CIERRE dd-mm-aaaa.xlsm"
--macro    libro de macros con la hoja "Tablas Dinamicas Profesional" (detalle BNB)
--desde / --hasta  ventana por fecha de caja del cierre (incluye ambos extremos)

Genera en --salida:
    resultado.json
    TIQUIPAYA/reporte.html   (cajas SFC101 y SFC102)
    AMERICA/reporte.html     (cajas SFC107 y SFC108)
Solo se listan en el reporte los depósitos observados (no los que cuadran).
"""
import argparse
import datetime as dt
import glob
import html
import json
import os
import re

import openpyxl

HOJA_BNB = "Tablas Dinamicas Profesional"
ZONAS = {
    "TIQUIPAYA": ["SFC101", "SFC102"],
    "AMERICA": ["SFC107", "SFC108"],
}
CAJAS_DEFAULT = [c for cajas in ZONAS.values() for c in cajas]


def parse_fecha(valor):
    """Acepta datetime, date o texto dd/mm/aa(aa). Devuelve date o None."""
    if isinstance(valor, dt.datetime):
        return valor.date()
    if isinstance(valor, dt.date):
        return valor
    if isinstance(valor, str):
        m = re.match(r"\s*(\d{1,2})/(\d{1,2})/(\d{2,4})", valor)
        if m:
            anio = int(m.group(3))
            anio = anio + 2000 if anio < 100 else anio
            try:
                return dt.date(anio, int(m.group(2)), int(m.group(1)))
            except ValueError:
                return None
    return None


def fecha_desde_nombre(nombre):
    m = re.search(r"CIERRE (\d{2})-(\d{2})-(\d{4})", os.path.basename(nombre))
    if not m:
        return None
    return dt.date(int(m.group(3)), int(m.group(2)), int(m.group(1)))


def leer_bnb(ruta):
    """Devuelve abonos con asignación y monto, y la cobertura de fechas del detalle."""
    wb = openpyxl.load_workbook(ruta, data_only=True)
    ws = wb[HOJA_BNB]
    abonos = []
    for r in ws.iter_rows(min_row=2, values_only=True):
        asig, monto = r[2], r[3]
        if isinstance(asig, str) and asig.strip().startswith("3P") and isinstance(monto, (int, float)):
            abonos.append({
                "fecha": parse_fecha(r[0]),
                "asig": asig.strip(),
                "monto": float(monto),
                "caja": r[5],
            })
    fechas = [a["fecha"] for a in abonos if a["fecha"]]
    cobertura = (min(fechas), max(fechas)) if fechas else (None, None)
    return abonos, cobertura


def leer_depositos(ruta, cajas):
    """Depósitos con código de asignación en las hojas de caja del cierre."""
    wb = openpyxl.load_workbook(ruta, data_only=True)
    depositos = []
    for sn in cajas:
        if sn not in wb.sheetnames:
            continue
        ws = wb[sn]
        for row in ws.iter_rows():
            for c in row:
                if isinstance(c.value, str) and re.fullmatch(r"DEPOSITO \d", c.value.strip()):
                    importe = ws.cell(row=c.row, column=c.column + 1).value
                    fecha = ws.cell(row=c.row, column=c.column + 2).value
                    asig = ws.cell(row=c.row, column=c.column + 3).value
                    if isinstance(asig, str) and asig.strip() and isinstance(importe, (int, float)) and importe > 0:
                        depositos.append({
                            "caja": sn,
                            "importe": float(importe),
                            "fecha_dep": parse_fecha(fecha),
                            "fecha_dep_texto": fecha if isinstance(fecha, str) else (fecha.strftime("%d-%m-%Y") if fecha else None),
                            "asig": asig.strip(),
                        })
    return depositos


def es_dia_mes_invertido(declarada, real):
    return bool(declarada and real and declarada.day == real.month and declarada.month == real.day)


def clasificar(dep, bnb_por_asig, cobertura_hasta):
    """Devuelve (estado, detalle) para un depósito declarado."""
    abono = bnb_por_asig.get(dep["asig"])
    if abono:
        if abs(abono["monto"] - dep["importe"]) >= 0.01:
            return "MONTO_DISTINTO", f"El banco abonó {abono['monto']:,.2f}"
        if dep["fecha_dep"] == abono["fecha"]:
            return "OK", ""
        if es_dia_mes_invertido(dep["fecha_dep"], abono["fecha"]):
            return "FECHA_INVERTIDA", f"El banco abonó el {abono['fecha']:%d-%m-%Y}"
        return "FECHA_DISTINTA", f"El banco abonó el {abono['fecha']:%d-%m-%Y}"
    if dep["fecha_dep"] and cobertura_hasta and dep["fecha_dep"] > cobertura_hasta:
        return "PENDIENTE", f"Aún no hay extracto para esa fecha (el detalle llega hasta el {cobertura_hasta:%d-%m-%Y})"
    if dep["fecha_dep"] is None:
        return "REVISAR", "La fecha de depósito no se pudo leer en el cierre"
    return "SIN_ABONO", "El banco no tiene ningún abono con este código"


# Texto para una persona que no es técnica: qué pasó y qué hacer.
EXPLICACION = {
    "SIN_ABONO": ("No aparece en el banco", "Revisar el voucher físico y el depósito en el banco. Si el depósito es real, falta el abono. Si no lo es, corregir el cierre."),
    "FECHA_INVERTIDA": ("La fecha está al revés", "Corregir la fecha de depósito en el cierre: el día y el mes están invertidos. El dinero sí está bien."),
    "FECHA_DISTINTA": ("La fecha no coincide", "Verificar la fecha de depósito en el cierre contra el banco."),
    "MONTO_DISTINTO": ("El monto no coincide", "Comparar el voucher con el monto que abonó el banco y corregir el cierre o el abono."),
    "PENDIENTE": ("Pendiente de extracto", "No es un error. Se revisa cuando llegue el extracto de esa fecha."),
    "REVISAR": ("Revisar a mano", "El archivo tiene una fecha que no se pudo leer. Verificarla en el cierre."),
}
ORDEN = ["SIN_ABONO", "MONTO_DISTINTO", "FECHA_INVERTIDA", "FECHA_DISTINTA", "REVISAR", "PENDIENTE"]


def construir_resultado(cierres, macro, desde, hasta, cajas):
    abonos, (cob_desde, cob_hasta) = leer_bnb(macro)
    bnb_por_asig = {}
    for a in abonos:
        bnb_por_asig.setdefault(a["asig"], a)

    resultados = []
    usados = []
    for ruta in sorted(glob.glob(os.path.join(cierres, "*.xlsm"))):
        fecha_caja = fecha_desde_nombre(ruta)
        if fecha_caja is None or not (desde <= fecha_caja <= hasta):
            continue
        usados.append({"archivo": os.path.basename(ruta), "fecha_caja": fecha_caja.isoformat()})
        for dep in leer_depositos(ruta, cajas):
            estado, detalle = clasificar(dep, bnb_por_asig, cob_hasta)
            resultados.append({
                "cierre": os.path.basename(ruta),
                "fecha_caja": fecha_caja.isoformat(),
                **dep,
                "fecha_dep": dep["fecha_dep"].isoformat() if dep["fecha_dep"] else None,
                "estado": estado,
                "detalle": detalle,
            })
    return {
        "ventana": {"desde": desde.strftime("%d-%m-%Y"), "hasta": hasta.strftime("%d-%m-%Y")},
        "cobertura_bnb": {
            "desde": cob_desde.isoformat() if cob_desde else None,
            "hasta": cob_hasta.isoformat() if cob_hasta else None,
        },
        "cierres": usados,
        "conteo": {e: sum(1 for r in resultados if r["estado"] == e) for e in {r["estado"] for r in resultados}},
        "depositos": resultados,
    }


def html_zona(zona, cajas, s):
    depositos = [r for r in s["depositos"] if r["caja"] in cajas]
    observados = sorted(
        [r for r in depositos if r["estado"] != "OK"],
        key=lambda r: (ORDEN.index(r["estado"]) if r["estado"] in ORDEN else 99, r["fecha_caja"]),
    )
    ok = sum(1 for r in depositos if r["estado"] == "OK")
    graves = sum(1 for r in observados if r["estado"] not in ("PENDIENTE",))
    pend = sum(1 for r in observados if r["estado"] == "PENDIENTE")
    cob = s["cobertura_bnb"]
    cob_txt = f"{cob['desde']} a {cob['hasta']}" if cob["hasta"] else "sin datos"

    if observados:
        tarjetas = []
        for r in observados:
            titulo, accion = EXPLICACION.get(r["estado"], (r["estado"], ""))
            color = "warn" if r["estado"] == "PENDIENTE" else "bad"
            tarjetas.append(f"""
<div class="item {color}">
  <div class="item-top">
    <span class="pill {color}">{html.escape(titulo)}</span>
    <span class="monto">Bs {r['importe']:,.2f}</span>
  </div>
  <div class="grid">
    <div><small>Cierre</small><b>{html.escape(r['cierre'].replace('.xlsm', ''))}</b></div>
    <div><small>Caja</small><b>{html.escape(r['caja'])}</b></div>
    <div><small>Asignación</small><b>{html.escape(r['asig'])}</b></div>
    <div><small>Fecha en el cierre</small><b>{html.escape(str(r['fecha_dep_texto'] or r['fecha_dep'] or '—'))}</b></div>
  </div>
  <p class="que"><b>Qué pasó:</b> {html.escape(r['detalle'])}.</p>
  <p class="que"><b>Qué hacer:</b> {html.escape(accion)}</p>
</div>""")
        cuerpo = "".join(tarjetas)
    else:
        cuerpo = '<div class="ok-box">✅ No hay observaciones en este periodo. Todos los depósitos cuadran con el banco.</div>'

    return f"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<title>Observaciones {zona} {s['ventana']['desde']} al {s['ventana']['hasta']}</title>
<style>
  body {{ margin:0; font-family: Arial, Helvetica, sans-serif; color:#1d2433; font-size:13px; background:#fff; }}
  .page {{ padding:26px 30px; }}
  .head {{ background:#1d2433; color:#fff; border-radius:10px; padding:18px 20px; }}
  .head h1 {{ margin:0 0 4px; font-size:20px; }}
  .head .sub {{ color:#c9d1e0; font-size:12px; }}
  .stats {{ display:flex; gap:10px; margin:16px 0; }}
  .stat {{ flex:1; border-radius:10px; padding:12px 14px; background:#f4f6fa; }}
  .stat .n {{ font-size:26px; font-weight:800; }}
  .stat .t {{ font-size:11px; color:#5b6478; text-transform:uppercase; letter-spacing:.04em; }}
  .stat.ok .n {{ color:#17693f; }} .stat.bad .n {{ color:#c0392b; }} .stat.warn .n {{ color:#9a6b00; }}
  h2 {{ font-size:15px; margin:18px 0 8px; }}
  .item {{ border:1px solid #e3e6ee; border-left:6px solid #c0392b; border-radius:10px; padding:12px 14px; margin-bottom:10px; page-break-inside:avoid; }}
  .item.warn {{ border-left-color:#e0a100; }}
  .item-top {{ display:flex; justify-content:space-between; align-items:center; margin-bottom:8px; }}
  .pill {{ padding:4px 10px; border-radius:20px; font-weight:700; font-size:12px; color:#fff; }}
  .pill.bad {{ background:#c0392b; }} .pill.warn {{ background:#e0a100; }}
  .monto {{ font-size:18px; font-weight:800; }}
  .grid {{ display:grid; grid-template-columns: repeat(4, 1fr); gap:8px; background:#f7f8fb; border-radius:8px; padding:8px 10px; }}
  .grid small {{ display:block; color:#6b7385; font-size:10px; text-transform:uppercase; }}
  .grid b {{ font-size:13px; }}
  .que {{ margin:8px 0 0; line-height:1.4; }}
  .ok-box {{ background:#e8f7ee; border:1px solid #bfe6cf; border-radius:10px; padding:16px; font-size:14px; color:#17693f; }}
  .foot {{ color:#8a91a3; font-size:10.5px; margin-top:16px; border-top:1px solid #e3e6ee; padding-top:8px; }}
</style></head><body><div class="page">
  <div class="head">
    <h1>Observaciones de depósitos · {zona.title()}</h1>
    <div class="sub">Cierres del {s['ventana']['desde']} al {s['ventana']['hasta']} · Cajas {', '.join(cajas)} · Extracto BNB disponible: {cob_txt}</div>
  </div>
  <div class="stats">
    <div class="stat ok"><div class="n">{ok}</div><div class="t">Cuadran</div></div>
    <div class="stat bad"><div class="n">{graves}</div><div class="t">Con error</div></div>
    <div class="stat warn"><div class="n">{pend}</div><div class="t">Pendientes</div></div>
  </div>
  <h2>Detalle</h2>
  {cuerpo}
  <div class="foot">Generado automáticamente comparando los cierres de cajeros con el detalle de abonos del BNB. Los pendientes se revisan cuando llegue el extracto de su fecha.</div>
</div></body></html>"""


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--cierres", required=True)
    p.add_argument("--macro", required=True)
    p.add_argument("--desde", required=True)
    p.add_argument("--hasta", required=True)
    p.add_argument("--salida", required=True)
    args = p.parse_args()

    desde = dt.datetime.strptime(args.desde, "%d-%m-%Y").date()
    hasta = dt.datetime.strptime(args.hasta, "%d-%m-%Y").date()
    s = construir_resultado(args.cierres, args.macro, desde, hasta, CAJAS_DEFAULT)

    os.makedirs(args.salida, exist_ok=True)
    with open(os.path.join(args.salida, "resultado.json"), "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=2)

    for zona, cajas in ZONAS.items():
        carpeta = os.path.join(args.salida, zona)
        os.makedirs(carpeta, exist_ok=True)
        with open(os.path.join(carpeta, "reporte.html"), "w", encoding="utf-8") as f:
            f.write(html_zona(zona, cajas, s))
    print(json.dumps(s["conteo"], ensure_ascii=False))


if __name__ == "__main__":
    main()
