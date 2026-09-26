"""Reportes breves de auditor-cierres para Gabo y para cada caja.

Esta capa es solo de presentacion. Clasifica los hallazgos exclusivamente a
partir de sus metadatos estructurados (``datos``); nunca interpreta el texto de
``hallazgo`` ni vuelve a leer los cierres.
"""
import collections
import datetime
import os
from decimal import Decimal
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.platypus import BaseDocTemplate, Frame, KeepTogether, PageTemplate, Paragraph, Spacer, Table, TableStyle


NOMBRE_RESUMEN = "RESUMEN_GABO.pdf"
NOMBRE_AMERICA = "PARA_CAJA_AMERICA.pdf"
NOMBRE_TIQUIPAYA = "PARA_CAJA_TIQUIPAYA.pdf"
CAJAS = {"america": "América", "tiquipaya": "Tiquipaya"}


def _fecha(v):
    if isinstance(v, datetime.datetime):
        return v.date()
    if isinstance(v, datetime.date):
        return v
    if not v:
        return None
    for formato in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.datetime.strptime(str(v), formato).date()
        except ValueError:
            pass
    return None


def _dmy(v):
    f = _fecha(v)
    return f.strftime("%d/%m/%Y") if f else "Fecha no identificada"


def _dm(v):
    f = _fecha(v)
    return f.strftime("%d/%m") if f else "?"


def _importe(v):
    try:
        d = Decimal(str(v)).quantize(Decimal("0.01"))
    except Exception:  # noqa: BLE001
        return "importe no legible"
    signo = "-" if d < 0 else ""
    entero, dec = divmod(int(abs(d) * 100), 100)
    s = "{:,}".format(entero).replace(",", ".")
    return "Bs %s%s%s" % (signo, s, (",%02d" % dec) if dec else "")


def _periodo(cierres):
    fechas = sorted(f for f in (_fecha(c.get("fecha")) for c in cierres) if f)
    if not fechas:
        return "sin fechas identificadas"
    return _dmy(fechas[0]) if len(set(fechas)) == 1 else "%s al %s" % (_dmy(fechas[0]), _dmy(fechas[-1]))


def _es_pendiente_registros(datos):
    """True solo cuando el problema se explica por cobertura de registros bancarios."""
    tipo = datos.get("tipo")
    if tipo == "c5_sin_macros":
        return True
    if tipo == "motor_observaciones":
        if datos.get("codigo_bloqueo") == "MACROS_NO_CUBRE_FECHA_DEPOSITO":
            return True
        requerida = _fecha(datos.get("fecha_requerida_deposito")) or _fecha(datos.get("fecha_cierre"))
        maxima = _fecha(datos.get("fecha_maxima_macros"))
        return bool(requerida and maxima and requerida > maxima and not datos.get("observaciones"))
    if tipo != "c5":
        return False
    c = datos.get("candidatos") or {}
    declarado = c.get("declarado") or {}
    fecha_dep = _fecha(declarado.get("fecha")) or _fecha(datos.get("fecha_en_cierre"))
    maxima = _fecha(c.get("macros_hasta"))
    return bool(fecha_dep and maxima and fecha_dep > maxima)


def _accion_c5(h, datos):
    """Traduce un Control 5 pendiente sin exponer fechas que ya se normalizaron."""
    if datos.get("aplicado") or h.get("resultado") != "REVISAR":
        return None
    motivo = datos.get("motivo")
    sfc = h.get("sfc") or "SFC"
    dep = datos.get("deposito") or "Depósito"
    celda = datos.get("celda") or h.get("fila")
    lugar = "%s · %s%s" % (sfc, dep, " (celda %s)" % celda if celda else "")
    imposibles = {
        "TEXTO_FECHA_INEXISTENTE_EN_CALENDARIO",
        "NUMERO_FUERA_DE_RANGO_DE_FECHAS",
        "TIPO_DE_CELDA_NO_SOPORTADO",
        "TEXTO_FORMATO_NO_ADMITIDO",
        "FECHA_CON_HORA_NO_SE_MODIFICA",
    }
    if motivo in imposibles:
        valor = datos.get("valor_actual")
        mostrado = "«%s»" % valor if valor not in (None, "") else "un valor no válido"
        return {
            "orden": 1, "lugar": lugar,
            "mal": "La fecha del depósito está escrita como %s y no puede resolverse automáticamente." % mostrado,
            "hacer": "Mirar el comprobante bancario y escribir la fecha completa y correcta (DD/MM/AAAA).",
            "gabo": "%s: fecha de depósito %s no resoluble automáticamente." % (lugar, mostrado),
        }
    if motivo == "ASIGNACION_VACIA_SIN_VOUCHER":
        return {
            "orden": 0, "lugar": lugar,
            "mal": "El depósito no tiene número de asignación o voucher.",
            "hacer": "Completar la asignación usando el comprobante bancario.",
            "gabo": "%s: falta la asignación o voucher del depósito." % lugar,
        }

    candidatos = datos.get("candidatos") or {}
    declarado = candidatos.get("declarado") or {}
    asignacion = declarado.get("asignacion") or datos.get("asignacion") or "no indicada"
    importe = declarado.get("importe") or datos.get("importe")
    monto = _importe(importe)
    lista = candidatos.get("candidatos") or []
    probable = lista[0] if candidatos.get("veredicto") == "CANDIDATO PROBABLE" and lista else None
    mal = "La asignación/voucher %s del depósito de %s no coincide con los registros bancarios." % (asignacion, monto)
    hacer = "Con el comprobante bancario, confirmar la asignación correcta y corregirla en el cierre."
    gabo = "%s: asignación/voucher %s no coincide con %s en los registros bancarios." % (lugar, asignacion, monto)
    extra = None
    if probable:
        extra = {
            "asignacion": probable.get("asignacion") or "no indicada",
            "importe": _importe(probable.get("importe")),
            "asignacion_cierre": asignacion,
        }
        gabo += " Candidato probable: asignación %s, %s." % (extra["asignacion"], extra["importe"])
    elif motivo not in ("SIN_VOUCHER_EN_MACROS", "VOUCHER_SIN_FECHA_VALIDA"):
        mal = "La fecha del depósito no pudo validarse automáticamente."
        hacer = "Revisar la fecha con el comprobante bancario y corregirla si corresponde."
        gabo = "%s: fecha pendiente de revisión manual." % lugar
    return {"orden": 0, "lugar": lugar, "mal": mal, "hacer": hacer, "gabo": gabo, "candidato": extra}


def _accion(h):
    """Devuelve el texto humano de un hallazgo accionable, usando solo campos estructurados."""
    d = h.get("datos") or {}
    t = d.get("tipo")
    sfc = h.get("sfc") or "Cierre"
    fila = h.get("fila")
    lugar_fila = "%s · Comunicaciones Internas%s" % (sfc, " · fila %s" % fila if fila else "")
    if t == "c1_no_cuadra":
        dif = _importe(d.get("diferencia"))
        return {"orden": 2, "lugar": sfc, "mal": "La recaudación tiene una diferencia de %s." % dif,
                "hacer": "Revisar los importes del SFC antes de procesar el cierre.",
                "gabo": "%s: la recaudación no cuadra; diferencia %s." % (sfc, dif)}
    if t == "c1_faltan_campos":
        campos = ", ".join(d.get("campos") or [])
        return {"orden": 2, "lugar": sfc, "mal": "Faltan datos para verificar la recaudación: %s." % campos,
                "hacer": "Completar esos datos y volver a revisar el cierre.",
                "gabo": "%s: faltan datos de recaudación (%s)." % (sfc, campos)}
    if t in ("c1_hoja_no_encontrada", "c2_hoja_no_encontrada", "c2_encabezado_no_reconocido", "c5_hoja_no_reconocida"):
        return {"orden": 3, "lugar": sfc, "mal": "No se pudo leer una sección necesaria del cierre.",
                "hacer": "Revisar que la hoja y sus encabezados estén completos.",
                "gabo": "%s: sección del cierre ausente o no reconocida (%s)." % (sfc, t)}
    if t == "c2_faltan":
        faltan = ", ".join(d.get("faltan") or [])
        return {"orden": 2, "lugar": lugar_fila, "mal": "Falta completar: %s." % faltan,
                "hacer": "Completar esos campos en la fila indicada.",
                "gabo": "%s: faltan %s." % (lugar_fila, faltan)}
    if t == "c2_especiales" and not d.get("completo"):
        cat = d.get("categoria") or "categoría especial"
        filas = ", ".join(str(x) for x in (d.get("filas") or ([fila] if fila else [])))
        lugar = "%s · Comunicaciones Internas · %s%s" % (sfc, cat, " · filas %s" % filas if filas else "")
        return {"orden": 3, "lugar": lugar, "mal": "Faltan la cuenta contable y/o la asignación.",
                "hacer": "Completar manualmente la cuenta contable y la asignación.",
                "gabo": "%s: completar cuenta contable y asignación (%s)." % (lugar, _importe(d.get("importe")))}
    if t == "c3_cuenta_distinta":
        return {"orden": 2, "lugar": lugar_fila,
                "mal": "La cuenta %s no corresponde a %s; se esperaba %s." % (d.get("registrada"), d.get("banco"), d.get("esperada")),
                "hacer": "Revisar y corregir la cuenta contable.",
                "gabo": "%s: cuenta %s; esperada %s para %s." % (lugar_fila, d.get("registrada"), d.get("esperada"), d.get("banco"))}
    if t in ("c3_banco_no_reconocido", "c3_sufijo_no_reconocido"):
        return {"orden": 2, "lugar": lugar_fila, "mal": "El banco «%s» no coincide con el catálogo vigente." % d.get("banco"),
                "hacer": "Revisar el banco y la cuenta contable.",
                "gabo": "%s: banco «%s» no reconocido." % (lugar_fila, d.get("banco"))}
    if t == "c4_formato_asignacion":
        return {"orden": 2, "lugar": lugar_fila,
                "mal": "La asignación %s de %s no cumple el formato esperado (%s)." % (d.get("asignacion"), d.get("banco"), d.get("esperado")),
                "hacer": "Revisar la asignación con el comprobante y corregirla.",
                "gabo": "%s: asignación %s de %s; se esperaba %s." % (lugar_fila, d.get("asignacion"), d.get("banco"), d.get("esperado"))}
    if t == "c5":
        return _accion_c5(h, d)
    if t == "c6_alquiler_sin_importe":
        return {"orden": 3, "lugar": lugar_fila, "mal": "Hay un alquiler sin importe legible.",
                "hacer": "Completar o corregir el importe del alquiler.",
                "gabo": "%s: alquiler sin importe legible." % lugar_fila}
    if t == "cierre_ilegible":
        return {"orden": 3, "lugar": "Archivo del cierre", "mal": "El archivo no pudo leerse.",
                "hacer": "Revisar que el archivo esté completo y volver a enviarlo.",
                "gabo": "El archivo del cierre no pudo leerse."}
    return None


def construir_modelo(ejecucion, cierres, hallazgos, alquileres, macros=None):
    """Clasifica acciones de caja, pendientes bancarios y notas técnicas."""
    acciones, pendientes, tecnicos = [], set(), []
    sin_registros = {(h.get("caja"), _fecha(h.get("fecha"))) for h in hallazgos
                     if (h.get("datos") or {}).get("tipo") == "c5_sin_macros"}
    for h in hallazgos:
        if h.get("resultado") not in ("REVISAR", "NO_CUADRA"):
            continue
        d = h.get("datos") or {}
        clave = (h.get("caja"), _fecha(h.get("fecha")))
        if _es_pendiente_registros(d):
            pendientes.add(clave)
            continue
        if d.get("tipo") == "c5" and d.get("motivo") == "SIN_VOUCHER_EN_MACROS" and clave in sin_registros:
            pendientes.add(clave)
            continue
        a = _accion(h)
        if a:
            a.update({"caja": h.get("caja"), "fecha": _fecha(h.get("fecha")), "tipo": d.get("tipo")})
            acciones.append(a)
        elif d.get("tipo") in ("motor_no_lee", "motor_observaciones"):
            tecnicos.append({"caja": h.get("caja"), "fecha": _fecha(h.get("fecha")), "tipo": d.get("tipo")})

    acciones.sort(key=lambda x: (x["caja"] or "", x["fecha"] or datetime.date.min, x["orden"], x["lugar"]))
    cierres_accion = {(a["caja"], a["fecha"]) for a in acciones}
    solo_pendientes = pendientes - cierres_accion
    revisados = collections.Counter(c.get("caja") for c in cierres)
    grupos_alq = collections.OrderedDict()
    for a in sorted(alquileres, key=lambda x: (x.get("caja") or "", _fecha(x.get("fecha")) or datetime.date.min,
                                                x.get("sfc") or "", x.get("fila") or 0)):
        k = (a.get("caja"), _fecha(a.get("fecha")), a.get("sfc"), a.get("marcado_en"))
        g = grupos_alq.setdefault(k, {"filas": 0, "importe": Decimal("0")})
        g["filas"] += 1
        g["importe"] += Decimal(str(a.get("importe") or 0))
    return {
        "ejecucion": ejecucion,
        "periodo": _periodo(cierres),
        "macros": [os.path.basename(m) for m in (macros or [])],
        "revisados": dict(revisados),
        "total_revisados": len(cierres),
        "acciones": acciones,
        "cierres_accion": cierres_accion,
        "pendientes": pendientes,
        "solo_pendientes": solo_pendientes,
        "tecnicos": tecnicos,
        "alquileres": grupos_alq,
        "nota_motor_alquileres": any(k[3] == "asignacion" for k in grupos_alq),
    }


NEGRO = colors.HexColor("#1a1a1a")
ROJO, ROJO_T = colors.HexColor("#9b1c1c"), colors.HexColor("#fbeaea")
AMBAR, AMBAR_T = colors.HexColor("#8a5a00"), colors.HexColor("#fdf3dc")
VERDE, VERDE_T = colors.HexColor("#1f6b3a"), colors.HexColor("#e9f5ec")
GRIS = colors.HexColor("#555555")
BASE = ParagraphStyle("base_corto", fontName="Helvetica", fontSize=9.5, leading=12.5, textColor=NEGRO)


def _st(nombre, **kw):
    return ParagraphStyle(nombre, parent=BASE, **kw)


S = {
    "titulo": _st("titulo_corto", fontName="Helvetica-Bold", fontSize=17, leading=21),
    "sub": _st("sub_corto", fontSize=9, leading=12, textColor=GRIS),
    "banda": _st("banda_corto", fontName="Helvetica-Bold", fontSize=10.5, leading=13, textColor=colors.white),
    "cel": _st("cel_corto", fontSize=9, leading=11.6),
    "cab": _st("cab_corto", fontName="Helvetica-Bold", fontSize=8.5, leading=11),
    "peq": _st("peq_corto", fontSize=8.3, leading=10.6, textColor=GRIS),
    "lugar": _st("lugar_corto", fontName="Helvetica-Bold", fontSize=9.5, leading=12.4),
    "lbl": _st("lbl_corto", fontName="Helvetica-Bold", fontSize=8.5, leading=11, textColor=GRIS),
    "gran": _st("gran_corto", fontSize=11, leading=15),
}
W = A4[0] - 30 * mm


def _p(texto, estilo="cel"):
    return Paragraph(escape(str(texto)), S[estilo])


def _banda(texto, color):
    t = Table([[_p(texto, "banda")]], colWidths=[W])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), color), ("LEFTPADDING", (0, 0), (-1, -1), 7),
                           ("RIGHTPADDING", (0, 0), (-1, -1), 7), ("TOPPADDING", (0, 0), (-1, -1), 5),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
    return t


def _tabla(cab, filas, anchos, color=GRIS, tinte=colors.HexColor("#eeeeee")):
    datos = [[_p(c, "cab") for c in cab]] + filas
    t = Table(datos, colWidths=anchos, repeatRows=1)
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), tinte), ("BOX", (0, 0), (-1, -1), 1, color),
                           ("INNERGRID", (0, 1), (-1, -1), 0.35, colors.HexColor("#bdbdbd")),
                           ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 5),
                           ("RIGHTPADDING", (0, 0), (-1, -1), 5), ("TOPPADDING", (0, 0), (-1, -1), 4),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
    return t


class _Canvas(rl_canvas.Canvas):
    pie = ""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._paginas = []

    def showPage(self):
        self._paginas.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._paginas)
        for estado in self._paginas:
            self.__dict__.update(estado)
            self.setFont("Helvetica", 7.5)
            self.setFillColor(GRIS)
            self.drawString(15 * mm, 9 * mm, self.pie)
            self.drawRightString(A4[0] - 15 * mm, 9 * mm, "Página %d de %d" % (self._pageNumber, total))
            super().showPage()
        super().save()


def _escribir(ruta, historia, pie, titulo):
    class C(_Canvas):
        pass
    C.pie = pie
    doc = BaseDocTemplate(ruta, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm,
                          topMargin=13 * mm, bottomMargin=16 * mm, title=titulo, author="CAJAS GABO")
    doc.addPageTemplates([PageTemplate(id="pagina", frames=[Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height,
                                                                   leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)])])
    doc.build(historia, canvasmaker=C)


def _historia_resumen(m):
    n_accion = len(m["cierres_accion"])
    n_pend = len(m["solo_pendientes"])
    sin_accion = m["total_revisados"] - n_accion
    fecha_ejec = m["ejecucion"].strftime("%d/%m/%Y %H:%M") if isinstance(m["ejecucion"], datetime.datetime) else str(m["ejecucion"])
    s = [_p("Resumen de auditoría de cierres", "titulo"),
         _p("CAJAS GABO · Periodo %s · Ejecutado el %s" % (m["periodo"], fecha_ejec), "sub"), Spacer(1, 8)]
    filas = [[_p("Cierres revisados"), _p(m["total_revisados"]), _p("Con acción de caja"), _p(n_accion)],
             [_p("Sin acción de caja"), _p(sin_accion), _p("Solo registros bancarios pendientes"), _p(n_pend)]]
    s += [_tabla(["Indicador", "Cantidad", "Indicador", "Cantidad"], filas, [W * .34, W * .16, W * .34, W * .16]), Spacer(1, 9)]
    s.append(_banda("CORREGIR EN EL CIERRE", ROJO))
    if m["acciones"]:
        s.append(_tabla(["Caja", "Cierre", "Qué corregir"],
                        [[_p(CAJAS.get(a["caja"], a["caja"])), _p(_dmy(a["fecha"])), _p(a["gabo"])] for a in m["acciones"]],
                        [W * .14, W * .16, W * .70], ROJO, ROJO_T))
    else:
        s += [Spacer(1, 4), _p("No hay correcciones que deban realizar las cajas.", "gran")]
    s += [Spacer(1, 9), _banda("PENDIENTE DE ACTUALIZACIÓN DE REGISTROS BANCARIOS", AMBAR)]
    if m["pendientes"]:
        filas = [[_p(CAJAS.get(c, c)), _p(_dmy(f)), _p("La validación depende de que se actualicen los registros bancarios; no es una acción para la caja.")]
                 for c, f in sorted(m["pendientes"], key=lambda x: (x[0] or "", x[1] or datetime.date.min))]
        s.append(_tabla(["Caja", "Cierre", "Motivo"], filas, [W * .14, W * .16, W * .70], AMBAR, AMBAR_T))
    else:
        s += [Spacer(1, 4), _p("No hay validaciones pendientes por actualización de registros bancarios.")]
    s += [Spacer(1, 9), _banda("ALQUILERES DEL PERIODO (INFORMATIVO)", VERDE)]
    if m["alquileres"]:
        filas = []
        for (c, f, sfc, marcado), g in m["alquileres"].items():
            filas.append([_p(CAJAS.get(c, c)), _p(_dmy(f)), _p(sfc), _p(g["filas"]), _p(_importe(g["importe"]))])
        s.append(_tabla(["Caja", "Fecha", "SFC", "Filas", "Importe"], filas,
                        [W * .16, W * .18, W * .18, W * .12, W * .36], VERDE, VERDE_T))
        s.append(Spacer(1, 4))
        s.append(_p("No se consideran errores de banco ni de cuenta contable.", "peq"))
        if m["nota_motor_alquileres"]:
            s.append(_p("Nota para Gabo: hay alquileres marcados en ASIGNACION con BANCO vacío; el auditor los reconoce, pero conviene verificarlos antes de procesar con el motor.", "peq"))
    else:
        s += [Spacer(1, 4), _p("No se registraron alquileres.")]
    if m["tecnicos"]:
        s += [Spacer(1, 9), _p("Hay %d observación(es) técnicas del motor en el detalle incluido dentro del ZIP." % len(m["tecnicos"]), "peq")]
    return s


def _historia_caja(m, caja):
    nombre = CAJAS[caja]
    items = [a for a in m["acciones"] if a["caja"] == caja]
    s = [_p("Caja %s — Puntos a revisar en sus cierres" % nombre, "titulo"),
         _p("Periodo %s" % m["periodo"], "sub"), Spacer(1, 8)]
    if not items:
        s.append(_p("No hay nada que corregir en sus cierres.", "gran"))
    por_fecha = collections.OrderedDict()
    for a in items:
        por_fecha.setdefault(a["fecha"], []).append(a)
    for fecha, acciones in por_fecha.items():
        bloque = [_banda("CIERRE DEL %s — CORREGIR / REVISAR POR CAJA" % _dmy(fecha), ROJO)]
        for a in acciones:
            contenido = [[_p(a["lugar"], "lugar")],
                         [_p("QUÉ ESTÁ MAL", "lbl"), _p(a["mal"], "gran")],
                         [_p("QUÉ DEBEN REVISAR/CORREGIR", "lbl"), _p(a["hacer"], "gran")]]
            if a.get("candidato"):
                c = a["candidato"]
                contenido.append([_p("POSIBLE COINCIDENCIA", "lbl"),
                                  _p("Asignación %s, %s. En el cierre figura %s; confirmen con el comprobante antes de corregir."
                                     % (c["asignacion"], c["importe"], c["asignacion_cierre"]))])
            t = Table(contenido, colWidths=[W * .29, W * .71])
            t.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 1, ROJO), ("BACKGROUND", (0, 0), (-1, 0), ROJO_T),
                                   ("SPAN", (0, 0), (-1, 0)), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                                   ("LINEBELOW", (0, 0), (-1, -2), .35, colors.HexColor("#bdbdbd")),
                                   ("LEFTPADDING", (0, 0), (-1, -1), 7), ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                                   ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
            bloque += [Spacer(1, 3), t]
        s += [KeepTogether(bloque), Spacer(1, 8)]
    # Los problemas que dependen solo de registros bancarios se omiten deliberadamente:
    # no son tareas para la caja.
    return s


def generar(reporte_dir, ejecucion, cierres, hallazgos, alquileres, macros=None):
    """Genera los tres PDF y devuelve sus rutas absolutas."""
    modelo = construir_modelo(ejecucion, cierres, hallazgos, alquileres, macros)
    os.makedirs(reporte_dir, exist_ok=True)
    rutas = {
        "resumen_gabo": os.path.join(reporte_dir, NOMBRE_RESUMEN),
        "para_caja_america": os.path.join(reporte_dir, NOMBRE_AMERICA),
        "para_caja_tiquipaya": os.path.join(reporte_dir, NOMBRE_TIQUIPAYA),
    }
    historias = {
        "resumen_gabo": _historia_resumen(modelo),
        "para_caja_america": _historia_caja(modelo, "america"),
        "para_caja_tiquipaya": _historia_caja(modelo, "tiquipaya"),
    }
    # Invariante contractual: los PDF destinados a cajas nunca exponen el nombre interno.
    for clave in ("para_caja_america", "para_caja_tiquipaya"):
        textos = []
        for a in modelo["acciones"]:
            if a["caja"] == ("america" if clave.endswith("america") else "tiquipaya"):
                textos += [a["lugar"], a["mal"], a["hacer"]]
        if "MACROS" in " ".join(textos).upper():
            raise AssertionError("MACROS aparece en un PDF para caja")
    _escribir(rutas["resumen_gabo"], historias["resumen_gabo"], "CAJAS GABO — Resumen de auditoría", "Resumen Gabo")
    _escribir(rutas["para_caja_america"], historias["para_caja_america"], "Caja América — Puntos a revisar", "Para Caja América")
    _escribir(rutas["para_caja_tiquipaya"], historias["para_caja_tiquipaya"], "Caja Tiquipaya — Puntos a revisar", "Para Caja Tiquipaya")
    return {k: os.path.abspath(v) for k, v in rutas.items()} | {"modelo": modelo}
