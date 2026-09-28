"""v3/normalizacion_fecha_deposito.py — Normalización operativa de FECHA DE
DEPOSITO, ANTES de v3/precheck_maestro.py (hallazgo real, CAJA AMÉRICA,
2026-09-28: cierres con la celda FECHA DE DEPOSITO en texto con año de 2
dígitos, p. ej. '28/09/26', que excel_io._fecha_iso() rechaza — el precheck
entonces no podía leer el cierre y lo reportaba, engañosamente, como
"Maestro sin cobertura" — ver v3/precheck_maestro.py, CIERRE_FECHA_INVALIDA).

REGLA REUTILIZADA, NO REINVENTADA: el regex y la expansión del año de 2
dígitos son EXTRACCIÓN LITERAL (mismo texto, mismo comportamiento) del
paso 3 de la regla ya aprobada en la rama `claude/auditor-cierres-skill`,
`.claude/skills/auditor-cierres/references/control5_regla.md` y
`.claude/skills/auditor-cierres/scripts/control5_fecha_deposito.py`
(`_RE_TEXTO_DMY`, y la rama `CONVERTIR_TEXTO_SIN_VOUCHER` de
`_clasificar_fila`, caso "texto válido sin contraste de voucher"): un
texto EXACTO `D/M/YYYY`, `DD/M/YYYY`, `DD/MM/YYYY`, `D/M/YY` o `DD/MM/YY`
(separador '/', sin espacios), fecha real en el calendario, y — si el año
es de 2 dígitos — coincide EXACTAMENTE con el año del cierre (nunca un
pivote arbitrario del tipo "20xx"). Si no coincide, o no se conoce el año
del cierre, NO se corrige nada: la celda queda intacta y seguirá fallando
exactamente igual que antes (fail-closed, nunca se adivina).

ALCANCE DELIBERADAMENTE MÁS ANGOSTO que el auditor completo: aquí NO se
hace contraste contra vouchers de MACROS (inversión DD/MM, tolerancia de
1 día, conflicto) — eso es Control 5 completo, un control de auditoría
humana aparte (ver esa skill). Este módulo solo resuelve el caso que
rompía el precheck automático de V3: el FORMATO de una fecha de texto ya
inequívoca por sí misma (año de 2 dígitos == año del cierre), el mismo
caso "sin voucher" de esa regla, sin necesitar MACROS para nada.

ESCRITURA SEGURA REUTILIZADA: nunca `openpyxl.save()` sobre un cierre
(prohibido explícitamente por esa misma skill, SKILL.md, "Reglas de
seguridad" — evita corromper vbaProject.bin/estilos/fórmulas de un
.xlsm real). Se usa v3._xlsm_xml (vendorizado tal cual desde la misma
rama) para parchear ÚNICAMENTE las celdas autorizadas y verificar, byte a
byte, que nada más cambió.

EL ORIGINAL NUNCA SE TOCA: este módulo jamás ve Drive (ni sabe que
existe) — opera sobre la copia YA materializada localmente por
v3/materializacion.py (`ruta_cierre_local`). Si hace falta normalizar
algo, escribe una copia ADICIONAL nueva (sufijo `.normalizado.xlsm`) y
nunca sobrescribe ni borra la copia materializada. Si no hace falta
normalizar nada (el caso normal — incluida TODA Caja Tiquipaya salvo que
alguna vez tenga el mismo problema real), no se crea ningún archivo
nuevo y `ruta_cierre_local` queda exactamente igual que hoy: cero costo,
cero cambio de comportamiento para los cierres que ya funcionan.
"""
import datetime
import os
import re

from v3 import _xlsm_xml as X

# Extracción literal de control5_fecha_deposito.py — MISMO regex, MISMA
# semántica (D/M/YY, DD/MM/YY, D/M/YYYY, DD/M/YYYY, DD/MM/YYYY; separador
# '/', sin espacios).
_RE_TEXTO_DMY = re.compile(r"^([0-9]{1,2})/([0-9]{1,2})/([0-9]{4}|[0-9]{2})$")

CAJAS_SFC = {
    "tiquipaya": ("SFC101", "SFC102"),
    "america": ("SFC107", "SFC108"),
}

MOTIVO_ANIO_2_DIGITOS = "TEXTO_ANIO_2_DIGITOS_EXPANDIDO_CONTRA_ANIO_DEL_CIERRE"
MOTIVO_FORMATO_NORMALIZADO = "TEXTO_FECHA_FORMATO_NORMALIZADO"


def interpretar_fecha_texto(texto, anio_cierre):
    """(date, None) si `texto` es exactamente D/M/YYYY, DD/M/YYYY,
    DD/MM/YYYY, D/M/YY o DD/MM/YY, fecha real en el calendario, y — si el
    año es de 2 dígitos — coincide EXACTAMENTE con `anio_cierre % 100`.
    Si no, (None, motivo_rechazo) SIN inventar nada: misma regla exacta
    que control5_fecha_deposito.py paso 3 (ver docstring del módulo)."""
    m = _RE_TEXTO_DMY.match(texto or "")
    if not m:
        return None, "TEXTO_FORMATO_NO_ADMITIDO"
    dia, mes, anio_txt = m.groups()
    if len(anio_txt) == 2:
        if anio_cierre is None or int(anio_txt) != anio_cierre % 100:
            return None, "TEXTO_ANIO_2_DIGITOS_NO_COINCIDE_CON_ANIO_DEL_CIERRE"
        anio = anio_cierre
    else:
        anio = int(anio_txt)
    try:
        return datetime.date(anio, int(mes), int(dia)), None
    except ValueError:
        return None, "TEXTO_FECHA_INEXISTENTE_EN_CALENDARIO"


# ---------------------------------------------------------------------------
# Localización de la COMPOSICIÓN DE DEPÓSITOS — extraído literal de
# control5_fecha_deposito.py (misma lógica de búsqueda de encabezado, sin
# posiciones fijas).
# ---------------------------------------------------------------------------

def _localizar_columnas(filas):
    """(fila_encabezado, col_etiqueta, col_importe, col_fecha, col_asignacion)
    o None. Extraído literal de control5_fecha_deposito.py."""
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


# ---------------------------------------------------------------------------
# 1) CLASIFICAR — solo lectura, solo el caso "texto de fecha ambigua"
# ---------------------------------------------------------------------------

def clasificar_fechas_deposito(ruta_cierre, caja, fecha_cierre_iso):
    """Recorre las hojas SFC de `caja` y devuelve un `plan` (una entrada
    por celda a normalizar: hoja/celda/fecha_nueva/valor_actual) más su
    `trazabilidad` humana (hoja/celda/valor_original/valor_normalizado/
    motivo). Nunca escribe nada. `caja`: 'tiquipaya' | 'america'.
    `fecha_cierre_iso`: 'YYYY-MM-DD' del cierre (resuelve el año de 2
    dígitos); None si se desconoce (entonces ningún año de 2 dígitos se
    acepta, igual que la regla original)."""
    if caja not in CAJAS_SFC:
        raise ValueError("CAJA_DESCONOCIDA: %r (validas: %s)" % (caja, sorted(CAJAS_SFC)))
    anio_cierre = int(fecha_cierre_iso[:4]) if fecha_cierre_iso else None

    pq = X.Paquete(ruta_cierre)
    if pq.date1904:
        return {"plan": [], "trazabilidad": [], "omitido": "LIBRO_DATE1904_NO_SOPORTADO"}

    plan, trazabilidad = [], []
    compactos = {X.normalizar_texto(n).replace(" ", ""): n for n in pq.hojas}
    for sfc in CAJAS_SFC[caja]:
        nombre = compactos.get(sfc)
        if nombre is None:
            continue
        celdas = pq.celdas_de_hoja(nombre)
        loc = _localizar_columnas(celdas)
        if loc is None or None in loc[2:]:
            continue
        f_enc, c_etq, c_imp, c_fec, c_asg = loc
        for nfila in sorted(f for f in celdas if f > f_enc):
            fila = celdas[nfila]
            etq = fila.get(c_etq)
            texto_etq = X.normalizar_texto(etq.valor) if etq is not None and etq.tipo == "texto" else ""
            if not texto_etq:
                continue
            if "DEPOSITO" not in texto_etq:
                break  # fin determinístico del bloque (misma regla que excel_io/control5)
            celda_f = fila.get(c_fec)
            # Solo texto: una fecha Excel real, vacía, fórmula u "otro" tipo
            # no es el caso que este módulo resuelve (excel_io ya las lee
            # bien, o ya las bloquea por otro motivo que no es de formato).
            if celda_f is None or celda_f.tipo != "texto":
                continue
            fecha_nueva, motivo_rechazo = interpretar_fecha_texto(celda_f.valor, anio_cierre)
            if fecha_nueva is None:
                continue  # ambigua o no reconocida: NUNCA se autocorrige
            plan.append({
                "hoja": nombre, "celda": celda_f.ref,
                "valor_actual": "texto %r" % celda_f.valor, "fecha_nueva": fecha_nueva,
            })
            m = _RE_TEXTO_DMY.match(celda_f.valor)
            motivo = MOTIVO_ANIO_2_DIGITOS if len(m.group(3)) == 2 else MOTIVO_FORMATO_NORMALIZADO
            trazabilidad.append({
                "hoja": nombre, "celda": celda_f.ref,
                "valor_original": celda_f.valor, "valor_normalizado": fecha_nueva.isoformat(),
                "motivo": motivo,
            })

    return {"plan": plan, "trazabilidad": trazabilidad, "omitido": None}


# ---------------------------------------------------------------------------
# 2) APLICAR (mecanismo XML aprobado) + VERIFICAR — extraído literal de
# control5_fecha_deposito.py (aplicar/ET_check/_celda_por_ref/
# verificar_integridad), sin depender de nada de voucher/MACROS: solo del
# `plan` que arma clasificar_fechas_deposito().
# ---------------------------------------------------------------------------

def _fmt(d):
    return d.strftime("%d/%m/%Y") if d else None


def aplicar(ruta_cierre, ruta_salida, plan):
    """Escribe ruta_salida aplicando SOLO `plan`. Si `plan` está vacío NO
    escribe (ni crea el archivo). Verifica la integridad byte a byte y, si
    algo no cuadra, borra la salida y relanza."""
    if not plan:
        return {"escrito": False, "cambios": []}
    pq = X.Paquete(ruta_cierre)
    reemplazos, cambios = {}, []
    styles = pq.texto_parte("xl/styles.xml")
    styles_orig = styles
    hojas_xml = {}
    for item in plan:
        parte = pq.hojas[item["hoja"]]
        xml = hojas_xml.get(parte) or pq.texto_parte(parte)
        celda = _celda_por_ref(pq, item["hoja"], item["celda"])
        estilo_nuevo = None
        if not pq.estilo_es_fecha(celda.estilo):
            styles, estilo_nuevo, _nota = X.estilo_de_fecha_para(styles, celda.estilo)
        xml, antes, despues = X.parche_celda(xml, item["celda"], X.fecha_a_serial(item["fecha_nueva"]), estilo_nuevo)
        ET_check(xml)
        hojas_xml[parte] = xml
        cambios.append({
            "hoja": item["hoja"], "celda": item["celda"],
            "de": item["valor_actual"], "a": _fmt(item["fecha_nueva"]),
        })
    for parte, xml in hojas_xml.items():
        reemplazos[parte] = xml.encode("utf-8")
    if styles != styles_orig:
        ET_check(styles)
        reemplazos["xl/styles.xml"] = styles.encode("utf-8")

    X.reescribir_zip(ruta_cierre, ruta_salida, reemplazos)
    try:
        verificar_integridad(ruta_cierre, ruta_salida, plan, reemplazos)
    except Exception:
        if os.path.exists(ruta_salida):
            os.remove(ruta_salida)
        raise
    return {"escrito": True, "cambios": cambios}


def ET_check(xml):
    import xml.etree.ElementTree as ET
    ET.fromstring(xml.encode("utf-8"))


def _celda_por_ref(pq, hoja, ref):
    letras, fila = X.dividir_ref(ref)
    return pq.celdas_de_hoja(hoja)[fila][X.col_a_num(letras)]


def verificar_integridad(ruta_in, ruta_out, plan, reemplazos):
    """Falla (X.ErrorXlsm) si la salida difiere del original en algo más
    que las celdas de `plan`."""
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
        for it in plan:
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
    return True


# ---------------------------------------------------------------------------
# Orquestación — se inserta entre v3.materializacion.ejecutar_materializacion()
# y v3.precheck_maestro.aplicar_precheck_maestro() (ver v3/dev_api.py).
# ---------------------------------------------------------------------------

def normalizar_cierre_para_precheck(ruta_cierre_local, fecha_cierre_iso, caja):
    """Para UN cierre ya materializado localmente: si tiene alguna FECHA DE
    DEPOSITO en texto ambiguo-pero-resoluble, escribe una copia NUEVA
    normalizada (nunca sobrescribe `ruta_cierre_local`) y devuelve su ruta;
    si no hace falta nada, devuelve `ruta_cierre_local` tal cual (cero
    archivos nuevos, cero cambio de comportamiento).

    Nunca lanza por un cierre individual: un problema técnico (archivo
    corrupto, hoja no reconocida, libro date1904) simplemente no normaliza
    nada y deja `ruta_cierre_local` intacto — el cierre seguirá su curso
    normal (y, si corresponde, precheck_maestro lo bloqueará con su propio
    diagnóstico, igual que hoy)."""
    try:
        resultado = clasificar_fechas_deposito(ruta_cierre_local, caja, fecha_cierre_iso)
    except Exception as exc:  # aislamiento: nunca detiene el resto del lote
        return {
            "ruta_cierre_local": ruta_cierre_local, "normalizado": False,
            "cambios": [], "mensaje": f"{type(exc).__name__}: {exc}",
        }
    if resultado.get("omitido") or not resultado["plan"]:
        return {"ruta_cierre_local": ruta_cierre_local, "normalizado": False, "cambios": [], "mensaje": None}

    base, ext = os.path.splitext(ruta_cierre_local)
    ruta_salida = base + ".normalizado" + ext
    try:
        aplicar(ruta_cierre_local, ruta_salida, resultado["plan"])
    except Exception as exc:  # nunca deja una copia a medio escribir en uso
        return {
            "ruta_cierre_local": ruta_cierre_local, "normalizado": False,
            "cambios": [], "mensaje": f"NORMALIZACION_FALLIDA:{type(exc).__name__}: {exc}",
        }
    return {
        "ruta_cierre_local": ruta_salida, "normalizado": True,
        "cambios": resultado["trazabilidad"], "mensaje": None,
    }


def normalizar_cierres_materializados(cierres_materializados, caja=None):
    """Aplica normalizar_cierre_para_precheck() a cada item MATERIALIZADO
    de la lista que devuelve v3.materializacion.ejecutar_materializacion().
    Los demás items (SIN_ARCHIVO/AMBIGUO/ERROR_MATERIALIZACION) pasan
    intactos. Actualiza `ruta_cierre_local` in place cuando corresponde y
    agrega `normalizacion_fecha_deposito` (trazabilidad) a cada item."""
    caja_codigo = caja if isinstance(caja, str) else getattr(caja, "codigo", "tiquipaya")
    resultados = []
    for item in cierres_materializados:
        if item.get("estado_materializacion") != "MATERIALIZADO" or not item.get("ruta_cierre_local"):
            resultados.append(dict(item))
            continue
        norm = normalizar_cierre_para_precheck(item["ruta_cierre_local"], item.get("fecha"), caja_codigo)
        salida = dict(item)
        salida["ruta_cierre_local"] = norm["ruta_cierre_local"]
        salida["normalizacion_fecha_deposito"] = norm["cambios"]
        resultados.append(salida)
    return resultados
