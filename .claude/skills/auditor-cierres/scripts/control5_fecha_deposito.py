"""control5_fecha_deposito.py — Control 5: FECHA DE DEPOSITO vs voucher MACROS.

REGLA DEFINITIVA (aprobada por el usuario). La UNICA evidencia es el voucher
bancario de MACROS, buscado por (codigo de asignacion + importe) y solo si es
UNICO y EXACTO. No hay ventana de dias ni proximidad al cierre.

    FECHA EXCEL = FECHA VOUCHER                 -> CORRECTA / SIN CAMBIO
    FECHA EXCEL con DD<->MM invertidos = VOUCHER -> NORMALIZAR AUTOMATICAMENTE
    TEXTO 'DD/MM/YYYY' valido = FECHA VOUCHER    -> CONVERTIR A FECHA EXCEL REAL
    |FECHA - VOUCHER| == 1 dia calendario        -> ACEPTABLE (tolerancia): NO se cambia el valor;
                                                    un texto valido se pasa a fecha real con el MISMO
                                                    valor; traza FECHA_DENTRO_TOLERANCIA_MACROS_1_DIA
    |FECHA - VOUCHER| > 1 dia                    -> REVISION MANUAL (no se corrige el valor)
    TEXTO valido SIN voucher en MACROS           -> CONVERTIR el FORMATO (mismo dia/mes/anio) y
                                                    registrar FECHA_NORMALIZADA_SIN_VOUCHER_MACROS
    FECHA VACIA                                  -> AVISAR / NO COMPLETAR
    CUALQUIER OTRO CASO                          -> AVISAR / NO MODIFICAR

Sin voucher, jamas se CORRIGE un valor (ni inversion DD/MM): solo se normaliza el
FORMATO de un texto valido e inequivoco, sin cambiar dia, mes ni anio (salvo expandir
el anio de 2 digitos con el anio del cierre). Un voucher NO UNICO o sin fecha valida no
es "voucher no encontrado": sigue siendo revision manual. Texto solo si es EXACTAMENTE D/M/YYYY,
DD/M/YYYY, DD/MM/YYYY, D/M/YY o DD/MM/YY (separador '/', sin espacios) y la fecha
existe en el calendario. El anio de 2 digitos se resuelve UNICAMENTE contra el
anio del cierre (15/09/26 en un cierre 2026 -> 15/09/2026); si no coincide, o si
no se conoce el anio del cierre, NO se corrige.

CANDIDATOS (solo evidencia adicional para el informe, no cambia ninguna regla anterior): cuando un deposito NO tiene voucher
exacto (revision por SIN_VOUCHER_EN_MACROS / ASIGNACION_VACIA_SIN_VOUCHER, o texto valido que se normaliza sin voucher) y se
dispone de los registros de MACROS, la fila lleva ademas `candidatos` (ver candidatos_voucher.py) para que una persona vea que
registros PODRIAN ser el deposito. La clasificacion, el plan y la normalizacion NO dependen de la busqueda (que ademas corre
aislada: si fallara, `candidatos` queda en None y todo lo demas sigue igual). Nunca se corrige nada a partir de un candidato.

Este modulo separa: (1) CLASIFICAR (puro, sin escribir), (2) APLICAR con el
mecanismo XML de xlsm_xml.py y VERIFICAR la integridad del resultado.
"""
import datetime
import os
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

import candidatos_voucher as cv
import macros_vouchers as mv
import xlsm_xml as X

CAJAS = {
    "tiquipaya": ("SFC101", "SFC102"),
    "america": ("SFC107", "SFC108"),
}

# Clases
CORRECTA = "CORRECTA"
NORMALIZAR_INVERSION = "NORMALIZAR_INVERSION_DDMM"
CONVERTIR_TEXTO = "CONVERTIR_TEXTO_A_FECHA"
CONVERTIR_TEXTO_SIN_VOUCHER = "CONVERTIR_TEXTO_SIN_VOUCHER_MACROS"
DENTRO_TOLERANCIA = "DENTRO_TOLERANCIA_1_DIA"
CONVERTIR_TEXTO_TOLERANCIA = "CONVERTIR_TEXTO_DENTRO_TOLERANCIA_1_DIA"
MOTIVO_TOLERANCIA = "FECHA_DENTRO_TOLERANCIA_MACROS_1_DIA"
TOLERANCIA_DIAS = 1  # dias CALENDARIO (diferencia de fechas, nunca de horas)
MOTIVO_SIN_VOUCHER = "FECHA_NORMALIZADA_SIN_VOUCHER_MACROS"
VACIA = "VACIA"
REQUIERE_REVISION = "REQUIERE_REVISION"

# Tipo de revision: no se pudo verificar vs. la evidencia contradice el valor
NO_VERIFICABLE = "NO_VERIFICABLE"
CONFLICTO = "CONFLICTO"

_RE_TEXTO_DMY = re.compile(r"^([0-9]{1,2})/([0-9]{1,2})/([0-9]{4}|[0-9]{2})$")  # D/M/YY, DD/MM/YY, D/M/YYYY, DD/M/YYYY, DD/MM/YYYY


def _fmt(d):
    return d.strftime("%d/%m/%Y") if d else None


def _swap(d):
    """Fecha con dia y mes invertidos, o None si no existe / es igual."""
    if d.day > 12 or d.day == d.month:
        return None
    try:
        return datetime.date(d.year, d.day, d.month)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Localizacion de la composicion de depositos (sin posiciones fijas)
# ---------------------------------------------------------------------------

def _localizar_columnas(filas):
    """(fila_encabezado, col_etiqueta, col_importe, col_fecha, col_asignacion) o None."""
    for nfila in sorted(filas):
        for col in sorted(filas[nfila]):
            t = X.normalizar_texto(filas[nfila][col].valor) if filas[nfila][col].tipo == "texto" else ""
            if "COMPOSICION" in t and "DEPOSITO" in t:
                imp = fec = asg = None
                for c2 in sorted(filas[nfila]):
                    if c2 <= col or filas[nfila][c2].tipo != "texto":
                        continue
                    tx = X.normalizar_texto(filas[nfila][c2].valor)
                    if imp is None and "IMPORTE" in tx:
                        imp = c2
                    elif fec is None and "FECHA" in tx and "DEPOSITO" in tx:
                        fec = c2
                    elif asg is None and "ASIGNACION" in tx:
                        asg = c2
                return nfila, col, imp, fec, asg
    return None


def _celda_a_texto_codigo(celda):
    if celda is None or celda.tipo in ("vacia",):
        return ""
    if celda.tipo == "numero":
        try:
            d = Decimal(celda.valor)
            return mv.normalizar_codigo(int(d) if d == d.to_integral_value() else celda.valor)
        except InvalidOperation:
            return ""
    return mv.normalizar_codigo(celda.valor)


def _col_banco(fila_enc, col_etiqueta):
    """Columna BANCO del encabezado de la composicion de depositos (a la derecha de la etiqueta), o None."""
    for c in sorted(fila_enc):
        if c <= col_etiqueta or fila_enc[c].tipo != "texto":
            continue
        t = X.normalizar_texto(fila_enc[c].valor)
        if "BANCO" in t and "CUENTA" not in t:
            return c
    return None


def _banco_de_celda(celda):
    """Texto/numero escrito en BANCO tal cual (str) o None."""
    if celda is None or celda.tipo in ("vacia", "formula", "otro") or celda.valor is None:
        return None
    if celda.tipo == "numero":
        try:
            d = Decimal(celda.valor)
        except InvalidOperation:
            return None
        return str(int(d)) if d == d.to_integral_value() else str(celda.valor)
    return str(celda.valor).strip() or None


def _importe_de_celda(celda):
    """(importe_2dec_str | None, problema | None)."""
    if celda is None or celda.tipo == "vacia":
        return None, None
    if celda.tipo in ("numero", "formula"):
        if celda.valor is None:
            return None, None
        imp = mv.importe_2dec(celda.valor)
        return imp, (None if imp else "IMPORTE_NO_NUMERICO")
    if celda.tipo == "texto":
        imp = mv.importe_2dec(celda.valor)
        return imp, (None if imp else "IMPORTE_NO_NUMERICO")
    return None, "IMPORTE_NO_NUMERICO"


# ---------------------------------------------------------------------------
# 1) CLASIFICAR (solo lectura)
# ---------------------------------------------------------------------------

def analizar(ruta_cierre, indice_macros, caja, paquete=None, fecha_cierre=None, registros_macros=None):
    """Clasifica cada deposito con importe de las hojas SFC de la caja.

    Devuelve un informe con `filas` (una por deposito con importe), `plan`
    (cambios autorizados por la regla) y `resumen`. NO escribe nada.
    `paquete` (opcional): Paquete ya cargado, para no releer el archivo.
    `fecha_cierre` (opcional, date): su anio resuelve los textos con anio de 2 digitos.
    `registros_macros` (opcional): movimientos de MACROS (macros_vouchers.leer_indice_macros()["registros"]); si se pasan,
    los depositos sin voucher exacto llevan `candidatos` (solo informativo)."""
    if caja not in CAJAS:
        raise ValueError("CAJA_DESCONOCIDA: %r (validas: %s)" % (caja, sorted(CAJAS)))
    pq = paquete or X.Paquete(ruta_cierre)
    if pq.date1904:
        raise X.ErrorXlsm("libro con date1904: no soportado")
    anio_cierre = fecha_cierre.year if fecha_cierre else None
    filas_inf, plan, hojas_problema = [], [], []
    compactos = {X.normalizar_texto(n).replace(" ", ""): n for n in pq.hojas}

    for sfc in CAJAS[caja]:
        nombre = compactos.get(sfc)
        if nombre is None:
            hojas_problema.append({"hoja": sfc, "motivo": "HOJA_NO_ENCONTRADA"})
            continue
        celdas = pq.celdas_de_hoja(nombre)
        loc = _localizar_columnas(celdas)
        if loc is None or None in loc[2:]:
            hojas_problema.append({"hoja": nombre, "motivo": "ESTRUCTURA_COMPOSICION_DEPOSITOS_NO_RECONOCIDA"})
            continue
        f_enc, c_etq, c_imp, c_fec, c_asg = loc
        c_banco = _col_banco(celdas[f_enc], c_etq)
        for nfila in sorted(f for f in celdas if f > f_enc):
            fila = celdas[nfila]
            etq = fila.get(c_etq)
            texto_etq = X.normalizar_texto(etq.valor) if etq is not None and etq.tipo == "texto" else ""
            if not texto_etq:
                continue
            if "DEPOSITO" not in texto_etq:
                break
            imp, prob_imp = _importe_de_celda(fila.get(c_imp))
            if imp is None and prob_imp is None:
                continue  # sin importe: no es un deposito a auditar
            if prob_imp is None and Decimal(imp) <= 0:
                continue
            busqueda = None
            if registros_macros is not None:
                busqueda = {"registros": registros_macros, "sfc": sfc, "fecha_cierre": fecha_cierre,
                            "banco": _banco_de_celda(fila.get(c_banco)) if c_banco is not None else None}
            inf = _clasificar_fila(pq, nombre, nfila, texto_etq, fila, c_fec, c_asg, imp, prob_imp, indice_macros, anio_cierre,
                                   busqueda)
            filas_inf.append(inf)
            if inf["accion"] in ("NORMALIZAR", "CONVERTIR"):
                plan.append(inf)

    resumen = {}
    for f in filas_inf:
        resumen[f["clase"]] = resumen.get(f["clase"], 0) + 1
    return {
        "caja": caja,
        "filas": filas_inf,
        "plan": plan,
        "hojas_con_problema": hojas_problema,
        "resumen": resumen,
    }


def _clasificar_fila(pq, hoja, nfila, etiqueta, fila, c_fec, c_asg, importe, prob_imp, indice, anio_cierre=None, busqueda=None):
    celda_f = fila.get(c_fec)
    ref = celda_f.ref if celda_f is not None else "%s%d" % (_num_a_col(c_fec), nfila)
    base = {
        "hoja": hoja, "celda": ref, "deposito": etiqueta, "importe": importe,
        "asignacion": None, "valor_actual": None, "fecha_voucher": None,
        "clase": None, "accion": None, "tipo_revision": None, "motivo": None,
        "fecha_nueva": None, "fecha_cierre": None, "fecha_macros": None, "candidatos": None,
    }
    codigo = _celda_a_texto_codigo(fila.get(c_asg))
    base["asignacion"] = codigo or None

    def revision(tipo, motivo):
        base.update(clase=REQUIERE_REVISION, accion="NINGUNA", tipo_revision=tipo, motivo=motivo)
        return base

    def buscar_candidatos(fecha_declarada):
        """Evidencia adicional para el informe. Aislada: nunca altera ni interrumpe la clasificacion."""
        if busqueda is None:
            return
        try:
            base["candidatos"] = cv.buscar(busqueda["registros"], importe, cv.cuenta_de_banco(busqueda["banco"]), busqueda["sfc"],
                                           fecha_declarada, busqueda["fecha_cierre"], codigo)
        except Exception:  # noqa: BLE001
            base["candidatos"] = None

    def revision_sin_voucher(motivo):
        """Sin voucher exacto: revision manual (no se corrige nada) + candidatos posibles de MACROS, solo informativos."""
        r = revision(NO_VERIFICABLE, motivo)
        buscar_candidatos(fecha_celda)
        return r

    # --- 4. FECHA VACIA: avisar, nunca completar ------------------------------
    if celda_f is None or celda_f.tipo == "vacia":
        base.update(clase=VACIA, accion="NINGUNA", motivo="FECHA_DE_DEPOSITO_VACIA_NO_SE_COMPLETA")
        return base

    # --- lectura del valor de la celda ---------------------------------------
    if celda_f.tipo == "formula":
        base["valor_actual"] = "formula"
        return revision(NO_VERIFICABLE, "CELDA_CON_FORMULA_NO_SE_MODIFICA")
    if celda_f.tipo == "otro":
        base["valor_actual"] = "tipo t=%s" % celda_f.t_xml
        return revision(NO_VERIFICABLE, "TIPO_DE_CELDA_NO_SOPORTADO")

    fecha_celda = None
    con_hora = False
    es_texto = celda_f.tipo == "texto"
    if es_texto:
        base["valor_actual"] = "texto %r" % celda_f.valor
        m = _RE_TEXTO_DMY.match(celda_f.valor)
        if not m:
            return revision(NO_VERIFICABLE, "TEXTO_FORMATO_NO_ADMITIDO")
        dia, mes, anio_txt = m.groups()
        if len(anio_txt) == 2:
            if anio_cierre is None or int(anio_txt) != anio_cierre % 100:
                return revision(NO_VERIFICABLE, "TEXTO_ANIO_2_DIGITOS_NO_COINCIDE_CON_ANIO_DEL_CIERRE")
            anio = anio_cierre
        else:
            anio = int(anio_txt)
        try:
            fecha_celda = datetime.date(anio, int(mes), int(dia))
        except ValueError:
            return revision(NO_VERIFICABLE, "TEXTO_FECHA_INEXISTENTE_EN_CALENDARIO")
    else:
        try:
            fecha_celda, con_hora = X.serial_a_fecha(celda_f.valor, pq.date1904)
        except ValueError:
            base["valor_actual"] = "numero %s" % celda_f.valor
            return revision(NO_VERIFICABLE, "NUMERO_FUERA_DE_RANGO_DE_FECHAS")
        base["valor_actual"] = _fmt(fecha_celda)
        if not pq.estilo_es_fecha(celda_f.estilo):
            return revision(NO_VERIFICABLE, "NUMERO_SIN_FORMATO_DE_FECHA")

    base["fecha_cierre"] = _fmt(fecha_celda)

    # --- evidencia: voucher UNICO por (asignacion + importe) ------------------
    if prob_imp:
        return revision(NO_VERIFICABLE, prob_imp)
    # Texto valido SIN voucher en MACROS (o MACROS sin cobertura): se normaliza solo el
    # formato -> fecha Excel real, mismo dia/mes/anio. Siempre con traza.
    if es_texto and (not codigo or not indice.get((codigo, importe))):
        base.update(clase=CONVERTIR_TEXTO_SIN_VOUCHER, accion="CONVERTIR", fecha_nueva=fecha_celda,
                    motivo=MOTIVO_SIN_VOUCHER)
        buscar_candidatos(fecha_celda)      # solo evidencia para el informe: la conversion ya esta decidida
        return base
    if not codigo:
        return revision_sin_voucher("ASIGNACION_VACIA_SIN_VOUCHER")
    vouchers = indice.get((codigo, importe), [])
    if not vouchers:
        return revision_sin_voucher("SIN_VOUCHER_EN_MACROS")
    if len(vouchers) > 1:
        return revision(NO_VERIFICABLE, "VOUCHER_NO_UNICO_%d_COINCIDENCIAS" % len(vouchers))
    fv = vouchers[0]
    if fv is None:
        return revision(NO_VERIFICABLE, "VOUCHER_SIN_FECHA_VALIDA")
    base["fecha_voucher"] = base["fecha_macros"] = _fmt(fv)
    dif_dias = abs((fecha_celda - fv).days)   # dias calendario entre FECHAS (date - date), no horas

    # --- regla ---------------------------------------------------------------
    if es_texto:
        if dif_dias == 0:
            base.update(clase=CONVERTIR_TEXTO, accion="CONVERTIR", fecha_nueva=fv,
                        motivo="TEXTO_DD/MM/YYYY_IGUAL_A_VOUCHER")
            return base
        if dif_dias == TOLERANCIA_DIAS:
            # aceptable: se conserva EXACTAMENTE el valor escrito, solo pasa a fecha Excel real
            base.update(clase=CONVERTIR_TEXTO_TOLERANCIA, accion="CONVERTIR", fecha_nueva=fecha_celda,
                        motivo=MOTIVO_TOLERANCIA)
            return base
        return revision(CONFLICTO, "TEXTO_DISTINTO_A_VOUCHER")

    if dif_dias == 0:
        base.update(clase=CORRECTA, accion="NINGUNA", motivo="FECHA_IGUAL_A_VOUCHER")
        return base
    if dif_dias == TOLERANCIA_DIAS:
        base.update(clase=DENTRO_TOLERANCIA, accion="NINGUNA", motivo=MOTIVO_TOLERANCIA)
        return base
    if con_hora:
        return revision(NO_VERIFICABLE, "FECHA_CON_HORA_NO_SE_MODIFICA")
    inv = _swap(fecha_celda)
    if inv is not None and inv == fv:
        base.update(clase=NORMALIZAR_INVERSION, accion="NORMALIZAR", fecha_nueva=fv,
                    motivo="INVERSION_DD/MM_IGUAL_A_VOUCHER")
        return base
    return revision(CONFLICTO, "FECHA_DISTINTA_A_VOUCHER_Y_SU_INVERSION_TAMPOCO_COINCIDE")


def _num_a_col(n):
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


# ---------------------------------------------------------------------------
# 2) APLICAR (mecanismo XML aprobado) + VERIFICAR
# ---------------------------------------------------------------------------

def aplicar(ruta_cierre, ruta_salida, informe):
    """Escribe ruta_salida aplicando SOLO el plan del informe. Si el plan esta
    vacio NO escribe. Verifica la integridad y, si algo no cuadra, borra la
    salida y lanza ErrorXlsm."""
    plan = informe["plan"]
    if not plan:
        return {"escrito": False, "cambios": [], "estilo": None}
    pq = X.Paquete(ruta_cierre)
    reemplazos, cambios, notas_estilo = {}, [], []
    styles = pq.texto_parte("xl/styles.xml")
    styles_orig = styles
    hojas_xml = {}
    for item in plan:
        parte = pq.hojas[item["hoja"]]
        xml = hojas_xml.get(parte) or pq.texto_parte(parte)
        estilo_nuevo = None
        if item["accion"] == "CONVERTIR":
            celda = _celda_por_ref(pq, item["hoja"], item["celda"])
            if not pq.estilo_es_fecha(celda.estilo):  # si ya es de fecha, se conserva su estilo
                styles, estilo_nuevo, nota = X.estilo_de_fecha_para(styles, celda.estilo)
                if nota and nota not in notas_estilo:
                    notas_estilo.append(nota)
        xml, antes, despues = X.parche_celda(xml, item["celda"], X.fecha_a_serial(item["fecha_nueva"]), estilo_nuevo)
        ET_check(xml)
        hojas_xml[parte] = xml
        cambios.append({"hoja": item["hoja"], "celda": item["celda"], "accion": item["accion"],
                        "de": item["valor_actual"], "a": _fmt(item["fecha_nueva"]),
                        "xml_antes": antes, "xml_despues": despues})
    for parte, xml in hojas_xml.items():
        reemplazos[parte] = xml.encode("utf-8")
    if styles != styles_orig:
        ET_check(styles)
        reemplazos["xl/styles.xml"] = styles.encode("utf-8")

    X.reescribir_zip(ruta_cierre, ruta_salida, reemplazos)
    try:
        verificar_integridad(ruta_cierre, ruta_salida, informe, reemplazos)
    except Exception:
        if os.path.exists(ruta_salida):
            os.remove(ruta_salida)
        raise
    return {"escrito": True, "cambios": cambios, "estilo": "; ".join(notas_estilo) or None,
            "partes_modificadas": sorted(reemplazos)}


def ET_check(xml):
    import xml.etree.ElementTree as ET
    ET.fromstring(xml.encode("utf-8"))


def _celda_por_ref(pq, hoja, ref):
    letras, fila = X.dividir_ref(ref)
    return pq.celdas_de_hoja(hoja)[fila][X.col_a_num(letras)]


def verificar_integridad(ruta_in, ruta_out, informe, reemplazos):
    """Falla (ErrorXlsm) si la salida difiere del original en algo mas que lo
    autorizado por el plan."""
    import zipfile
    with zipfile.ZipFile(ruta_in) as a, zipfile.ZipFile(ruta_out) as b:
        na, nb = [i.filename for i in a.infolist()], [i.filename for i in b.infolist()]
        if na != nb:
            raise X.ErrorXlsm("VERIFICACION: cambia el conjunto/orden de partes del ZIP")
        for n in na:
            if n not in reemplazos and a.read(n) != b.read(n):
                raise X.ErrorXlsm("VERIFICACION: parte no autorizada modificada: %s" % n)
        pq_a = X.Paquete(ruta_in)
        por_parte = {}
        for it in informe["plan"]:
            por_parte.setdefault(pq_a.hojas[it["hoja"]], []).append(it["celda"])
        for parte, refs in por_parte.items():
            antes = X.quitar_celdas(a.read(parte).decode("utf-8"), refs)
            despues = X.quitar_celdas(b.read(parte).decode("utf-8"), refs)
            if antes != despues:
                raise X.ErrorXlsm("VERIFICACION: %s cambio fuera de las celdas autorizadas" % parte)
        if "xl/styles.xml" in reemplazos:
            sa, sb = a.read("xl/styles.xml").decode(), b.read("xl/styles.xml").decode()
            ma, xa = X._xf_lista(sa)
            mb, xb = X._xf_lista(sb)
            if xb[:len(xa)] != xa or sa[:ma.start()] != sb[:mb.start()] or sa[ma.end():] != sb[mb.end():]:
                raise X.ErrorXlsm("VERIFICACION: styles.xml cambio mas alla de agregar xf al final")
    # relectura: lo planificado ahora es CORRECTA, el resto no cambia de clase
    return True


def reanalizar_y_comparar(ruta_salida, indice_macros, caja, informe_previo, fecha_cierre=None):
    """Segunda pasada sobre el archivo ya normalizado: debe quedar todo lo
    planificado como CORRECTA y ninguna otra fila cambia de clase."""
    nuevo = analizar(ruta_salida, indice_macros, caja, fecha_cierre=fecha_cierre)
    planificadas = {(p["hoja"], p["celda"]) for p in informe_previo["plan"]}
    problemas = []
    prev = {(f["hoja"], f["celda"]): f for f in informe_previo["filas"]}
    for f in nuevo["filas"]:
        k = (f["hoja"], f["celda"])
        if k in planificadas:
            item = next(p for p in informe_previo["plan"] if (p["hoja"], p["celda"]) == k)
            if item["clase"] == CONVERTIR_TEXTO_SIN_VOUCHER:
                # sigue sin voucher para contrastar, pero ya es la fecha Excel real esperada
                if f["valor_actual"] != _fmt(item["fecha_nueva"]) or f["motivo"] not in (
                        "SIN_VOUCHER_EN_MACROS", "ASIGNACION_VACIA_SIN_VOUCHER"):
                    problemas.append("fila %s no quedo como fecha real %s" % (k, _fmt(item["fecha_nueva"])))
            elif item["clase"] == CONVERTIR_TEXTO_TOLERANCIA:
                if f["clase"] != DENTRO_TOLERANCIA or f["valor_actual"] != _fmt(item["fecha_nueva"]):
                    problemas.append("fila %s no quedo como fecha real dentro de tolerancia" % (k,))
            elif f["clase"] != CORRECTA:
                problemas.append("fila %s no quedo CORRECTA: %s" % (k, f["clase"]))
        elif prev.get(k, {}).get("clase") != f["clase"]:
            problemas.append("fila %s cambio de clase" % (k,))
    return problemas, nuevo
