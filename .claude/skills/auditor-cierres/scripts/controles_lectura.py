"""controles_lectura.py — Controles 1, 2, 3, 4 y 6.

Estrictamente LEER -> VALIDAR -> REPORTAR. Nada se modifica ni se completa.
Todo sobre un Paquete ya cargado (cada hoja se parsea una sola vez).

  C1 Cuadre de recaudacion (por hoja SFC, Decimal, campos por etiqueta)
  C2 Comunicaciones Internas completas (BANCO / CUENTA CONTABLE / ASIGNACION)
  C3 BANCO <-> CUENTA CONTABLE (tabla oficial)
  C4 Formato de ASIGNACION por familia de banco
  C6 ALQUILERES (fecha, caja, SFC, importe)

Categorias especiales (OTROS INGRESOS, GASTO.ADM, POSGRADO.PLA): solo se exige
BANCO; no entran a C3/C4; siempre se listan (fecha, caja, SFC) para que el
usuario complete cuenta y asignacion manualmente. ALQUILERES esta exenta de
C2/C3/C4 y va a C6.
"""
import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

import catalogo_bancos as cb
import xlsm_xml as X

OK, REVISAR, NO_CUADRA, INFO = "OK", "REVISAR", "NO_CUADRA", "INFO"

CAMPOS_C1 = (
    "TOTAL EFECTIVO DISPONIBLE", "DOLARES", "CHEQUES", "COBROS ATC",
    "TOTAL COMUNICACIONES INTERNAS", "FACTURAS ANULADAS", "TOTAL MOVIMIENTO DEL DIA",
)
_CENT = Decimal("0.01")


def q2(d):
    return d.quantize(_CENT, rounding=ROUND_HALF_UP)


def bs(d):
    """Formato de importes: Bs 2.350 / Bs 2.350,50 (punto de miles, coma decimal)."""
    d = q2(d)
    signo = "-" if d < 0 else ""
    d = abs(d)
    entero, dec = divmod(int(d * 100), 100)
    txt = "{:,}".format(entero).replace(",", ".")
    return "%s%s%s" % (signo, txt, ("," + "%02d" % dec) if dec else "")


def _hallazgo(fecha, caja, sfc, control, resultado, texto, accion, fila=None, datos=None):
    """`datos`: metadatos estructurados (solo para redactar el informe humano; no intervienen en ninguna regla)."""
    return {"fecha": fecha, "caja": caja, "sfc": sfc, "control": control,
            "resultado": resultado, "hallazgo": texto, "accion": accion, "fila": fila, "datos": datos}


def _decimal(celda):
    if celda is None or celda.tipo not in ("numero", "formula") or celda.valor in (None, ""):
        return None
    try:
        return Decimal(celda.valor)
    except InvalidOperation:
        return None


def _texto(celda):
    """Texto limpio de una celda (numeros enteros sin '.0'), o None si esta vacia."""
    if celda is None or celda.tipo == "vacia" or celda.valor in (None, ""):
        return None
    if celda.tipo == "numero" or (celda.tipo == "formula" and celda.t_xml in (None, "n")):
        try:
            d = Decimal(celda.valor)
            return str(int(d)) if d == d.to_integral_value() else celda.valor
        except InvalidOperation:
            return None
    t = str(celda.valor).strip()
    return t or None


# ---------------------------------------------------------------------------
# Control 1
# ---------------------------------------------------------------------------

def control1(pq, hoja, fecha, caja, sfc):
    celdas = pq.celdas_de_hoja(hoja)
    valores, vistos = {}, set()
    for nfila in sorted(celdas):
        for col in sorted(celdas[nfila]):
            c = celdas[nfila][col]
            if c.tipo != "texto":
                continue
            et = X.normalizar_texto(c.valor)
            if et in CAMPOS_C1 and et not in valores:
                v = _decimal(celdas[nfila].get(col + 1))
                if v is not None:
                    valores[et] = v
    faltan = [c for c in CAMPOS_C1 if c not in valores]
    if faltan:
        return _hallazgo(fecha, caja, sfc, 1, REVISAR,
                         "⚠️ No se pudo verificar el cuadre — falta %s." % ", ".join(faltan),
                         "Completar el dato en el cierre y volver a auditar",
                         datos={"tipo": "c1_faltan_campos", "campos": list(faltan)})
    suma = (valores["TOTAL EFECTIVO DISPONIBLE"] + valores["DOLARES"] + valores["CHEQUES"]
            + valores["COBROS ATC"] + valores["TOTAL COMUNICACIONES INTERNAS"]
            - valores["FACTURAS ANULADAS"])
    total = valores["TOTAL MOVIMIENTO DEL DIA"]
    dif = q2(total) - q2(suma)
    if dif == 0:
        return _hallazgo(fecha, caja, sfc, 1, OK, "✅ Recaudación cuadra: Bs %s" % bs(total), "Ninguna")
    return _hallazgo(fecha, caja, sfc, 1, NO_CUADRA,
                     "❌ Recaudación no cuadra — diferencia Bs %s" % bs(dif),
                     "Revisar los importes del SFC antes de procesar",
                     datos={"tipo": "c1_no_cuadra", "diferencia": str(dif), "total_registrado": str(q2(total)), "total_calculado": str(q2(suma))})


# ---------------------------------------------------------------------------
# Lectura de la hoja de Comunicaciones Internas
# ---------------------------------------------------------------------------

_FECHA_FALLBACK = ("FECHA", "FECHA CI", "FECHA COMUNICACION INTERNA")


def _cols_ci(celdas):
    """(fila_encabezado, columnas) buscando el encabezado por contenido, no por fila fija."""
    for nfila in sorted(celdas):
        cols = {}
        for col in sorted(celdas[nfila]):
            c = celdas[nfila][col]
            if c.tipo != "texto":
                continue
            t = X.normalizar_texto(c.valor)
            compacto = t.replace("°", "").replace("º", "").strip()
            if "n" not in cols and compacto == "N":
                cols["n"] = col
            elif "factura" not in cols and "FACTURA" in t:
                cols["factura"] = col
            elif "total" not in cols and "TOTAL C.I" in t:
                cols["total"] = col
            elif "cuenta" not in cols and "CUENTA CONTABLE" in t:
                cols["cuenta"] = col
            elif "asignacion" not in cols and "ASIGNACION" in t:
                cols["asignacion"] = col
            elif "banco" not in cols and t == "BANCO":
                cols["banco"] = col
            elif "fecha2" not in cols and t == "FECHA2":
                cols["fecha2"] = col
            elif "fecha_fb" not in cols and t in _FECHA_FALLBACK:
                cols["fecha_fb"] = col
        if all(k in cols for k in ("banco", "cuenta", "asignacion", "total")) and ("n" in cols or "factura" in cols):
            return nfila, cols
    return None, None


def _fecha_ci(pq, celda):
    """date | None (solo fecha Excel real con formato de fecha; nunca se inventa)."""
    if celda is None or celda.tipo != "numero":
        return None
    try:
        d, hora = X.serial_a_fecha(celda.valor, pq.date1904)
    except (ValueError, X.ErrorXlsm):
        return None
    return d if pq.estilo_es_fecha(celda.estilo) else None


def leer_ci(pq, hoja):
    celdas = pq.celdas_de_hoja(hoja)
    f_enc, cols = _cols_ci(celdas)
    if cols is None:
        return None
    marcador = cols.get("n", cols.get("factura"))
    col_fecha = cols.get("fecha2", cols.get("fecha_fb"))
    filas = []
    for nfila in sorted(f for f in celdas if f > f_enc):
        fila = celdas[nfila]
        if _texto(fila.get(marcador)) is None:
            continue  # fila en blanco / de total: no es una CI real
        filas.append({
            "fila": nfila,
            "banco": _texto(fila.get(cols["banco"])),
            "cuenta": _texto(fila.get(cols["cuenta"])),
            "asignacion": _texto(fila.get(cols["asignacion"])),
            "importe": _decimal(fila.get(cols["total"])),
            "fecha": _fecha_ci(pq, fila.get(col_fecha)) if col_fecha else None,
        })
    return filas


def _hoja_ci(pq, sfc):
    suf = sfc[len("SFC"):]
    for n in pq.hojas:
        c = X.normalizar_texto(n).replace(" ", "")
        if "COMUNICACIONESINTERNAS" in c and suf in c:
            return n
    return None


def _hoja_sfc(pq, sfc):
    for n in pq.hojas:
        if X.normalizar_texto(n).replace(" ", "") == sfc:
            return n
    return None


# ---------------------------------------------------------------------------
# Controles 2, 3, 4 y 6 (una sola pasada por las filas de CI)
# ---------------------------------------------------------------------------

def controles_ci(pq, hoja, fecha, caja, sfc):
    """Devuelve (hallazgos, alquileres, especiales)."""
    filas = leer_ci(pq, hoja)
    if filas is None:
        return ([_hallazgo(fecha, caja, sfc, 2, REVISAR,
                           "⚠️ No se pudo revisar Comunicaciones Internas: no se reconoció el encabezado.",
                           "Revisar la hoja manualmente",
                           datos={"tipo": "c2_encabezado_no_reconocido"})], [], [])
    hall, alq, esp = [], [], []
    for r in filas:
        n = r["fila"]
        banco = r["banco"]
        cat = cb.categoria_especial(banco) if banco else None
        marcado_en = "banco" if cat == "ALQUILERES" else None
        if not banco and cb.categoria_especial(r["asignacion"] or "") == "ALQUILERES":
            cat = "ALQUILERES"  # alquiler marcado en ASIGNACION con BANCO vacio
            marcado_en = "asignacion"

        if cat == "ALQUILERES":
            if r["importe"] is None:
                hall.append(_hallazgo(fecha, caja, sfc, 6, REVISAR,
                                      "⚠️ Alquiler sin importe legible (fila %d)." % n,
                                      "Revisar el importe manualmente", n, datos={"tipo": "c6_alquiler_sin_importe"}))
                continue
            usa_cierre = r["fecha"] is None
            alq.append({"fecha": r["fecha"] or fecha, "fecha_del_cierre": usa_cierre,
                        "caja": caja, "sfc": sfc, "importe": r["importe"], "fila": n,
                        "marcado_en": marcado_en})
            continue  # exento de C2/C3/C4

        if cat:  # OTROS INGRESOS / GASTO.ADM / POSGRADO.PLA
            falta = [c for c, v in (("CUENTA CONTABLE", r["cuenta"]), ("ASIGNACION", r["asignacion"])) if not v]
            esp.append({"fecha": fecha, "caja": caja, "sfc": sfc, "categoria": cat, "fila": n,
                        "importe": r["importe"], "falta": falta})
            continue

        if not banco:
            faltan = ["BANCO"] + [c for c, v in (("CUENTA CONTABLE", r["cuenta"]), ("ASIGNACION", r["asignacion"])) if not v]
            hall.append(_hallazgo(fecha, caja, sfc, 2, REVISAR,
                                  "⚠️ %s — fila %d: falta %s." % (sfc, n, _unir(faltan)),
                                  "Completar en el cierre", n, datos={"tipo": "c2_faltan", "faltan": list(faltan)}))
            continue

        faltan = [c for c, v in (("CUENTA CONTABLE", r["cuenta"]), ("ASIGNACION", r["asignacion"])) if not v]
        if faltan:
            hall.append(_hallazgo(fecha, caja, sfc, 2, REVISAR,
                                  "⚠️ %s — fila %d: falta %s." % (sfc, n, _unir(faltan)),
                                  "Completar en el cierre", n, datos={"tipo": "c2_faltan", "faltan": list(faltan)}))

        info = cb.interpretar_banco(banco)
        # Control 3 (solo si hay cuenta registrada)
        if r["cuenta"]:
            if info["estado"] == "BANCO_NO_RECONOCIDO":
                hall.append(_hallazgo(fecha, caja, sfc, 3, REVISAR,
                                      "⚠️ %s — fila %d: el banco «%s» no figura en la tabla oficial." % (sfc, n, banco),
                                      "Revisar el banco y la cuenta (no se corrige)", n,
                                      datos={"tipo": "c3_banco_no_reconocido", "banco": banco}))
            elif info["estado"] == "SUFIJO_NO_RECONOCIDO":
                hall.append(_hallazgo(fecha, caja, sfc, 3, REVISAR,
                                      "⚠️ %s — fila %d: «%s» no corresponde a una cuenta de la tabla oficial." % (sfc, n, banco),
                                      "Revisar el banco y la cuenta (no se corrige)", n,
                                      datos={"tipo": "c3_sufijo_no_reconocido", "banco": banco}))
            elif r["cuenta"] != info["cuenta_esperada"]:
                hall.append(_hallazgo(fecha, caja, sfc, 3, REVISAR,
                                      "⚠️ Revisar cuenta contable\n%s — fila %d\nBanco: %s\nCuenta registrada: %s\nCuenta esperada: %s"
                                      % (sfc, n, banco, r["cuenta"], info["cuenta_esperada"]),
                                      "Revisar la cuenta (no se corrige)", n,
                                      datos={"tipo": "c3_cuenta_distinta", "banco": banco, "registrada": r["cuenta"],
                                             "esperada": info["cuenta_esperada"]}))
        # Control 4 (solo si hay asignacion y se conoce la familia)
        if r["asignacion"] and info["familia"]:
            esperado = cb.FORMATO_ASIGNACION[info["familia"]]
            if not cb.formato_valido(r["asignacion"], esperado):
                pedido = "código numérico" if esperado == "NUMERICO" else "código alfanumérico (con letras)"
                hall.append(_hallazgo(fecha, caja, sfc, 4, REVISAR,
                                      "⚠️ REVISAR ASIGNACIÓN\n%s — fila %d\nBanco: %s\nAsignación: %s\nEsperado: %s"
                                      % (sfc, n, banco, r["asignacion"], pedido),
                                      "Revisar la asignación (no se corrige)", n,
                                      datos={"tipo": "c4_formato_asignacion", "banco": banco, "asignacion": r["asignacion"],
                                             "esperado": pedido}))
    return hall, alq, esp


def _unir(items):
    """['A','B','C'] -> 'A, B y C'"""
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " y " + items[-1]


# ---------------------------------------------------------------------------
# Punto de entrada por cierre
# ---------------------------------------------------------------------------

def auditar_lectura(pq, sfcs, fecha, caja):
    """Controles 1, 2, 3, 4 y 6 de un cierre. Devuelve (hallazgos, alquileres, especiales)."""
    hall, alq, esp = [], [], []
    for sfc in sfcs:
        h_sfc = _hoja_sfc(pq, sfc)
        if h_sfc is None:
            hall.append(_hallazgo(fecha, caja, sfc, 1, REVISAR,
                                  "⚠️ No se pudo verificar el cuadre — no se encontró la hoja %s." % sfc,
                                  "Revisar que el cierre tenga la hoja", datos={"tipo": "c1_hoja_no_encontrada"}))
        else:
            hall.append(control1(pq, h_sfc, fecha, caja, sfc))
        h_ci = _hoja_ci(pq, sfc)
        if h_ci is None:
            hall.append(_hallazgo(fecha, caja, sfc, 2, REVISAR,
                                  "⚠️ No se pudo revisar Comunicaciones Internas — no se encontró la hoja de %s." % sfc,
                                  "Revisar que el cierre tenga la hoja", datos={"tipo": "c2_hoja_no_encontrada"}))
            continue
        h, a, e = controles_ci(pq, h_ci, fecha, caja, sfc)
        hall += h
        alq += a
        esp += e
    return hall, alq, esp
