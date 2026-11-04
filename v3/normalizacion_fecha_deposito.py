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

SEGUNDA REGLA (hallazgo real, CAJA AMÉRICA, cierres 09, 10 y 11/09/2026):
FECHA EXCEL REAL CON DÍA/MES INVERTIDOS. Una celda FECHA DE DEPOSITO que ya
es una fecha Excel real (no texto) pero guardada con día↔mes invertidos
(p. ej. 09/10/2026 en vez de 10/09/2026) no la corrige el paso de texto de
arriba. Aquí se reutiliza LITERAL la clase `NORMALIZAR_INVERSION_DDMM` de
`control5_fecha_deposito.py` (`_swap` + rama final de `_clasificar_fila`),
regla aprobada en `control5_regla.md`: SOLO se normaliza si
  1. existe UN ÚNICO voucher en MACROS para (asignación normalizada +
     importe exacto a 2 decimales);
  2. la fecha invertida día↔mes existe (día <= 12 y día != mes);
  3. esa fecha invertida coincide EXACTAMENTE con la fecha del voucher.
La evidencia sale del MISMO maestro ya materializado (`ruta_maestro_local`),
leído con excel_io.leer_macros_bnb() (mismo lector que usa el precheck).
Nunca por cercanía al cierre ni por heurística: sin voucher único que lo
confirme NO se corrige (fail-closed). Igual que el auditor, una fecha que
ya coincide con el voucher o difiere en 1 día calendario (tolerancia) se
deja intacta antes de considerar cualquier inversión.

TERCERA REGLA (hallazgo real, Tiquipaya, cierre 28/10/2026): ENCABEZADO
`ASIGNACION` perdido en una hoja COMUNICACIONES INTERNAS. En Excel, una columna
de tabla sin título se llama `Columna1`, `Columna2`, ...; excel_io.leer_cierre()
exige la columna ASIGNACION y aborta, y el precheck lo informaba como
"maestro sin cobertura". Solo en la COPIA operativa se renombra ese
encabezado a `ASIGNACION` (celda + nombre de columna de la tabla, para que
Excel no pida reparar) cuando hay evidencia ESTRUCTURAL: la hoja no tiene
ninguna columna ASIGNACION, sí tiene todas las demás columnas obligatorias, y
el encabezado con nombre por defecto está justo a la derecha de
CUENTA CONTABLE BANCO. No es un error bloqueante: queda un AVISO visible
(`avisos_cierre`) para que la persona decida si publica el cierre.

El resto del Control 5 humano (tolerancia de 1 día como aviso, conflicto,
conversión de texto contra voucher) sigue siendo la auditoría aparte: este
módulo solo resuelve lo que rompía el precheck automático de V3 — el
FORMATO de un texto inequívoco y la INVERSIÓN confirmada por voucher único.

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
import posixpath
import re
from decimal import Decimal, InvalidOperation
from xml.sax.saxutils import escape as _xml_escape

import excel_io
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

# Mismos nombres que control5_fecha_deposito.py (NORMALIZAR_INVERSION,
# motivo "INVERSION_DD/MM_IGUAL_A_VOUCHER", tolerancia de 1 día calendario).
CLASE_INVERSION_DDMM = "NORMALIZAR_INVERSION_DDMM"
MOTIVO_INVERSION_DDMM = "INVERSION_DD/MM_IGUAL_A_VOUCHER"
TOLERANCIA_DIAS = 1

# Tercera regla: encabezado ASIGNACION perdido en COMUNICACIONES INTERNAS.
TIPO_ENCABEZADO_CI = "ENCABEZADO_CI_ASIGNACION"
CLASE_ENCABEZADO_CI = "REPARAR_ENCABEZADO_CI_ASIGNACION"
MOTIVO_ENCABEZADO_CI = "ENCABEZADO_POR_DEFECTO_JUNTO_A_CUENTA_CONTABLE_BANCO"
AVISO_CI_ENCABEZADO_REPARADO = "CI_ENCABEZADO_ASIGNACION_REPARADO_EN_COPIA"
ENCABEZADO_ASIGNACION = "ASIGNACION"
# Nombre que Excel da a una columna de tabla sin título: Columna1, Columna2, ...
_RE_ENCABEZADO_POR_DEFECTO = re.compile(r"^COLUMNA[0-9]+$")


def _swap(d):
    """Extracción literal de control5_fecha_deposito._swap: fecha con día y
    mes invertidos, o None si no existe (día > 12) o es igual (día == mes)."""
    if d.day > 12 or d.day == d.month:
        return None
    try:
        return datetime.date(d.year, d.day, d.month)
    except ValueError:
        return None


def fecha_invertida_candidata(fecha):
    """Fecha con día↔mes invertidos (o None). API pública de `_swap` para
    quien solo quiere saber si una inversión DD/MM es POSIBLE (p. ej. el
    mensaje del precheck); nunca decide corregir nada."""
    return _swap(fecha)


def indice_vouchers_macros(ruta_maestro):
    """{(codigo_normalizado, importe_2dec): [date | None, ...]} desde la hoja
    "Tablas Dinamicas Profesional" del maestro, con el MISMO lector que el
    precheck (excel_io.leer_macros_bnb: mismos encabezados repetidos
    descartados, solo códigos con crédito > 0). Un voucher es ÚNICO solo si
    la clave tiene exactamente UNA entrada; una entrada None es un voucher
    sin fecha válida (no hay evidencia). Lanza si el maestro es ilegible."""
    por_codigo = excel_io.leer_macros_bnb(ruta_maestro)["por_codigo"]
    indice = {}
    for codigo, movimientos in por_codigo.items():
        for mov in movimientos:
            fecha_iso = mov.get("fecha")
            fecha = datetime.date.fromisoformat(fecha_iso) if fecha_iso else None
            indice.setdefault((codigo, mov["importe"]), []).append(fecha)
    return indice


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
# 1) CLASIFICAR — solo lectura: (a) texto de fecha ambigua pero resoluble,
# (b) fecha Excel real con día/mes invertidos confirmada por voucher único.
# ---------------------------------------------------------------------------

def _codigo_de_celda(celda):
    """Asignación normalizada de una celda del cierre, con la MISMA
    normalización que excel_io.leer_macros_bnb aplica a la clave de MACROS
    (excel_io.normalize_codigo). '' si no hay asignación."""
    if celda is None or celda.tipo == "vacia" or celda.valor is None:
        return ""
    valor = celda.valor
    if celda.tipo == "numero":
        try:
            d = Decimal(valor)
            valor = str(int(d)) if d == d.to_integral_value() else valor
        except InvalidOperation:
            return ""
    return excel_io.normalize_codigo(valor)


def _importe_de_celda(celda):
    """Importe a 2 decimales (mismo criterio que la clave de MACROS:
    excel_io.money_str) si la celda trae un número válido > 0; None si no
    hay importe auditable (vacío, no numérico o <= 0: no es un depósito a
    auditar, igual que control5_fecha_deposito.analizar)."""
    if celda is None or celda.tipo in ("vacia", "otro") or celda.valor is None:
        return None
    try:
        dec = excel_io.to_decimal(celda.valor)
    except ValueError:
        return None
    return excel_io.money_str(dec) if dec > 0 else None


def _evaluar_inversion_ddmm(celda_f, fila, c_imp, c_asg, pq, obtener_indice):
    """Regla `NORMALIZAR_INVERSION_DDMM` de control5_fecha_deposito.py para
    UNA celda FECHA DE DEPOSITO que es fecha Excel real. Devuelve
    (plan_item | None, revision | None): `plan_item` solo si la inversión
    está CONFIRMADA por voucher único; `revision` describe, sin corregir,
    una inversión posible que NO se pudo confirmar. Ninguna otra clase del
    auditor se aplica aquí (ver docstring del módulo)."""
    try:
        fecha_celda, con_hora = X.serial_a_fecha(celda_f.valor, pq.date1904)
    except ValueError:
        return None, None  # número fuera de rango de fechas: no es el caso de esta regla
    if not pq.estilo_es_fecha(celda_f.estilo):
        return None, None  # número sin formato de fecha: el auditor lo manda a revisión, aquí nunca se toca
    inv = _swap(fecha_celda)
    if inv is None:
        return None, None  # sin inversión posible (día > 12 o día == mes): nada que evaluar

    importe = _importe_de_celda(fila.get(c_imp))
    if importe is None:
        return None, None  # no es un depósito con importe a auditar
    base = {"hoja": None, "celda": celda_f.ref, "fecha_excel": fecha_celda.isoformat(),
            "fecha_invertida_candidata": inv.isoformat(), "importe": importe, "asignacion": None,
            "fecha_voucher": None}

    def revision(motivo):
        base["motivo"] = motivo
        return None, base

    codigo = _codigo_de_celda(fila.get(c_asg))
    base["asignacion"] = codigo or None
    if not codigo:
        return revision("ASIGNACION_VACIA_SIN_VOUCHER")
    try:
        indice = obtener_indice()
    except Exception as exc:  # noqa: BLE001 — sin evidencia legible de MACROS: NUNCA se corrige
        return revision("MACROS_ILEGIBLE:%s" % type(exc).__name__)
    if indice is None:
        return revision("MACROS_NO_DISPONIBLE_PARA_CONFIRMAR")
    vouchers = indice.get((codigo, importe), [])
    if not vouchers:
        return revision("SIN_VOUCHER_EN_MACROS")
    if len(vouchers) > 1:
        return revision("VOUCHER_NO_UNICO_%d_COINCIDENCIAS" % len(vouchers))
    fv = vouchers[0]
    if fv is None:
        return revision("VOUCHER_SIN_FECHA_VALIDA")
    base["fecha_voucher"] = fv.isoformat()
    dif_dias = abs((fecha_celda - fv).days)  # días calendario entre FECHAS, no horas
    if dif_dias <= TOLERANCIA_DIAS:
        return None, None  # CORRECTA / DENTRO_TOLERANCIA_1_DIA: el valor no se toca
    if con_hora:
        return revision("FECHA_CON_HORA_NO_SE_MODIFICA")
    if inv != fv:
        return revision("FECHA_DISTINTA_A_VOUCHER_Y_SU_INVERSION_TAMPOCO_COINCIDE")
    return {
        "celda": celda_f.ref, "valor_actual": "fecha Excel real %s" % fecha_celda.isoformat(),
        "fecha_nueva": fv, "asignacion": codigo, "importe": importe,
        "fecha_excel": fecha_celda, "fecha_voucher": fv,
    }, None


def clasificar_fechas_deposito(ruta_cierre, caja, fecha_cierre_iso, indice_vouchers=None):
    """Recorre las hojas SFC de `caja` y devuelve un `plan` (una entrada
    por celda a normalizar: hoja/celda/fecha_nueva/valor_actual) más su
    `trazabilidad` humana (hoja/celda/valor_original/valor_normalizado/
    motivo) y `revision` (inversiones DD/MM posibles NO confirmadas, que
    NO se corrigen). Nunca escribe nada. `caja`: 'tiquipaya' | 'america'.
    `fecha_cierre_iso`: 'YYYY-MM-DD' del cierre (resuelve el año de 2
    dígitos); None si se desconoce (entonces ningún año de 2 dígitos se
    acepta, igual que la regla original).

    `indice_vouchers`: la evidencia de MACROS para la regla de inversión
    DD/MM — dict `indice_vouchers_macros()` o un callable sin argumentos que
    lo devuelve (se invoca de forma PEREZOSA, solo cuando alguna celda
    FECHA DE DEPOSITO real tiene una inversión posible; un cierre normal no
    fuerza ninguna lectura de MACROS). None = sin evidencia: la inversión
    DD/MM nunca se corrige, solo se reporta en `revision`."""
    if caja not in CAJAS_SFC:
        raise ValueError("CAJA_DESCONOCIDA: %r (validas: %s)" % (caja, sorted(CAJAS_SFC)))
    anio_cierre = int(fecha_cierre_iso[:4]) if fecha_cierre_iso else None

    if callable(indice_vouchers):
        obtener_indice = indice_vouchers
    else:
        def obtener_indice():
            return indice_vouchers

    pq = X.Paquete(ruta_cierre)
    if pq.date1904:
        return {"plan": [], "trazabilidad": [], "revision": [], "omitido": "LIBRO_DATE1904_NO_SOPORTADO"}

    plan, trazabilidad, revision = [], [], []
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
            if celda_f is None:
                continue
            if celda_f.tipo == "numero":
                # Fecha Excel real: la única corrección posible es la
                # inversión DD/MM confirmada por voucher único (2ª regla).
                item, rev = _evaluar_inversion_ddmm(celda_f, fila, c_imp, c_asg, pq, obtener_indice)
                if rev is not None:
                    rev["hoja"] = nombre
                    revision.append(rev)
                if item is not None:
                    item["hoja"] = nombre
                    plan.append(item)
                    trazabilidad.append({
                        "hoja": nombre, "celda": item["celda"],
                        "valor_original": item["fecha_excel"].isoformat(),
                        "valor_normalizado": item["fecha_nueva"].isoformat(),
                        "motivo": MOTIVO_INVERSION_DDMM, "clase": CLASE_INVERSION_DDMM,
                        "asignacion": item["asignacion"], "importe": item["importe"],
                        "fecha_voucher": item["fecha_voucher"].isoformat(),
                    })
                continue
            # Texto (1ª regla). Una celda vacía, fórmula u "otro" tipo no es
            # el caso que este módulo resuelve (excel_io ya las lee bien, o
            # ya las bloquea por otro motivo que no es de formato).
            if celda_f.tipo != "texto":
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

    return {"plan": plan, "trazabilidad": trazabilidad, "revision": revision, "omitido": None}


# ---------------------------------------------------------------------------
# 1b) CLASIFICAR encabezados de COMUNICACIONES INTERNAS (tercera regla)
# ---------------------------------------------------------------------------

def _hojas_ci(pq, caja):
    """[(sfc, nombre_hoja)] — MISMO criterio que excel_io._find_ci_sheet:
    nombre compacto con 'COMUNICACIONESINTERNAS' y el sufijo del SFC."""
    hojas = []
    for sfc in CAJAS_SFC[caja]:
        sufijo = sfc[len("SFC"):]
        for nombre in pq.hojas:
            compacto = X.normalizar_texto(nombre).replace(" ", "")
            if "COMUNICACIONESINTERNAS" in compacto and sufijo in compacto:
                hojas.append((sfc, nombre))
                break
    return hojas


def _columnas_ci(fila_encabezado):
    """Posiciones de las columnas que excel_io._leer_comunicaciones_internas
    exige, con las MISMAS reglas y orden de coincidencia que ese lector."""
    pos = {"n": None, "factura": None, "total": None, "cuenta": None, "asignacion": None, "banco": None}
    for col in sorted(fila_encabezado):
        celda = fila_encabezado[col]
        if celda.tipo != "texto":
            continue
        texto = X.normalizar_texto(celda.valor)
        if not texto:
            continue
        compacto = texto.replace("°", "").replace("º", "").strip()
        if pos["n"] is None and compacto == "N":
            pos["n"] = col
        elif pos["factura"] is None and "FACTURA" in texto:
            pos["factura"] = col
        elif pos["total"] is None and "TOTAL C.I" in texto:
            pos["total"] = col
        elif pos["cuenta"] is None and "CUENTA CONTABLE" in texto:
            pos["cuenta"] = col
        elif pos["asignacion"] is None and "ASIGNACION" in texto:
            pos["asignacion"] = col
        elif pos["banco"] is None and texto == "BANCO":
            pos["banco"] = col
    return pos


def clasificar_encabezados_ci(ruta_cierre, caja, paquete=None):
    """Tercera regla (ver docstring del módulo). Devuelve {"plan": [...],
    "avisos": [...]}: un item por hoja COMUNICACIONES INTERNAS cuyo
    encabezado ASIGNACION se perdió y quedó con nombre por defecto
    (Columna1, ...) justo a la derecha de CUENTA CONTABLE BANCO. Si falta
    cualquier OTRA columna obligatoria, o no hay un único candidato
    estructural, NO se toca nada: el error exacto lo reportará el precheck.
    Solo lectura."""
    if caja not in CAJAS_SFC:
        raise ValueError("CAJA_DESCONOCIDA: %r (validas: %s)" % (caja, sorted(CAJAS_SFC)))
    pq = paquete or X.Paquete(ruta_cierre)
    plan, avisos = [], []
    for _sfc, nombre in _hojas_ci(pq, caja):
        fila_enc = pq.celdas_de_hoja(nombre).get(1)   # excel_io lee el encabezado en la primera fila
        if not fila_enc:
            continue
        pos = _columnas_ci(fila_enc)
        if pos["asignacion"] is not None:
            continue                                   # la columna existe: nada que reparar
        if any(pos[k] is None for k in ("factura", "total", "cuenta", "banco")):
            continue                                   # falta algo más: no es este caso, se informa tal cual
        candidata = fila_enc.get(pos["cuenta"] + 1)
        if candidata is None or candidata.tipo != "texto":
            continue
        if not _RE_ENCABEZADO_POR_DEFECTO.match(X.normalizar_texto(candidata.valor)):
            continue
        letras = X.dividir_ref(candidata.ref)[0]
        plan.append({
            "tipo": TIPO_ENCABEZADO_CI, "hoja": nombre, "celda": candidata.ref,
            "valor_actual": "texto %r" % candidata.valor,
            "texto_original": candidata.valor, "texto_nuevo": ENCABEZADO_ASIGNACION,
        })
        avisos.append({
            "codigo": AVISO_CI_ENCABEZADO_REPARADO, "hoja": nombre, "celda": candidata.ref,
            "valor_original": candidata.valor, "valor_nuevo": ENCABEZADO_ASIGNACION,
            "mensaje": (
                f"{AVISO_CI_ENCABEZADO_REPARADO}: en la hoja '{nombre}' el encabezado de la columna {letras} "
                f"({candidata.ref}) dice '{candidata.valor}' en lugar de '{ENCABEZADO_ASIGNACION}'. Para poder leer el "
                f"cierre se usó una COPIA operativa con ese encabezado renombrado a '{ENCABEZADO_ASIGNACION}' (el archivo "
                "original no se modificó). Verifique que esa columna sea la asignación de las comunicaciones "
                "internas y corrija el encabezado en el original; usted decide si publica este cierre con este aviso."
            ),
        })
    return {"plan": plan, "avisos": avisos}


# ---------------------------------------------------------------------------
# 2) APLICAR (mecanismo XML aprobado) + VERIFICAR — extraído literal de
# control5_fecha_deposito.py (aplicar/ET_check/_celda_por_ref/
# verificar_integridad), sin depender de nada de voucher/MACROS: solo del
# `plan` que arma clasificar_fechas_deposito().
# ---------------------------------------------------------------------------

def _fmt(d):
    return d.strftime("%d/%m/%Y") if d else None


def _parche_texto_inline(xml, ref, texto):
    """Reemplaza UNICAMENTE la celda `ref` por una celda de texto inline,
    conservando su estilo y demás atributos (menos `t`). Misma disciplina que
    X.parche_celda (una sola coincidencia, nunca una fórmula).
    Devuelve (xml_nuevo, elemento_antes, elemento_despues)."""
    patron = re.compile(r'<c r="%s"([^>]*?)(?:/>|>(.*?)</c>)' % re.escape(ref), re.S)
    ms = list(patron.finditer(xml))
    if len(ms) != 1:
        raise X.ErrorXlsm("celda %s: %d coincidencias en el XML (se esperaba 1)" % (ref, len(ms)))
    m = ms[0]
    if m.group(2) and "<f" in m.group(2):
        raise X.ErrorXlsm("celda %s contiene formula: no se modifica" % ref)
    atributos = [(n, v) for n, v in re.findall(r'\s([A-Za-z_:][\w:.-]*)="([^"]*)"', m.group(1)) if n != "t"]
    atributos.append(("t", "inlineStr"))
    attrs = "".join(' %s="%s"' % (n, v) for n, v in atributos)
    despues = '<c r="%s"%s><is><t>%s</t></is></c>' % (ref, attrs, _xml_escape(texto))
    return xml[:m.start()] + despues + xml[m.end():], m.group(0), despues


_RE_TABLE_COLUMN_NAME = re.compile(r'(<tableColumn\b[^>]*?\bname=")([^"]*)(")')


def _partes_tabla_de_hoja(pq, parte_hoja):
    """Partes xl/tables/*.xml relacionadas con una hoja (vía su .rels)."""
    rels = posixpath.join(posixpath.dirname(parte_hoja), "_rels", posixpath.basename(parte_hoja) + ".rels")
    if rels not in pq.partes:
        return []
    destinos = re.findall(r'Target="([^"]*)"', pq.partes[rels].decode("utf-8"))
    partes = []
    for destino in destinos:
        ruta = destino.lstrip("/") if destino.startswith("/") else posixpath.normpath(posixpath.join(posixpath.dirname(parte_hoja), destino))
        if ruta.startswith("xl/tables/") and ruta in pq.partes:
            partes.append(ruta)
    return partes


def _renombrar_columna_de_tabla(pq, hoja, nombre_actual, nombre_nuevo):
    """{parte_tabla: xml_nuevo} renombrando la columna de tabla `nombre_actual`
    de las tablas de la hoja, para que el nombre de la columna siga igual al
    texto de la celda de encabezado (si no, Excel pide reparar el archivo).
    Solo si la coincidencia es única en esa tabla y el nombre nuevo no existe."""
    cambios = {}
    for parte in _partes_tabla_de_hoja(pq, pq.hojas[hoja]):
        xml = pq.texto_parte(parte)
        nombres = [m.group(2) for m in _RE_TABLE_COLUMN_NAME.finditer(xml)]
        if nombres.count(nombre_actual) != 1 or nombre_nuevo in nombres:
            continue
        cambios[parte] = _RE_TABLE_COLUMN_NAME.sub(
            lambda m: m.group(1) + (nombre_nuevo if m.group(2) == nombre_actual else m.group(2)) + m.group(3), xml)
    return cambios


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
    tablas_nuevas = {}
    for item in plan:
        parte = pq.hojas[item["hoja"]]
        xml = hojas_xml.get(parte) or pq.texto_parte(parte)
        if item.get("tipo") == TIPO_ENCABEZADO_CI:
            xml, _antes, _despues = _parche_texto_inline(xml, item["celda"], item["texto_nuevo"])
            ET_check(xml)
            hojas_xml[parte] = xml
            for parte_tabla, xml_tabla in _renombrar_columna_de_tabla(pq, item["hoja"], item["texto_original"], item["texto_nuevo"]).items():
                ET_check(xml_tabla)
                tablas_nuevas[parte_tabla] = xml_tabla
            cambios.append({"hoja": item["hoja"], "celda": item["celda"], "de": item["valor_actual"], "a": item["texto_nuevo"]})
            continue
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
    for parte, xml in tablas_nuevas.items():
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
        renombres = {(it["texto_original"], it["texto_nuevo"]) for it in plan if it.get("tipo") == TIPO_ENCABEZADO_CI}
        for parte in reemplazos:
            if not parte.startswith("xl/tables/"):
                continue
            ta, tb = a.read(parte).decode("utf-8"), b.read(parte).decode("utf-8")
            enmascarar = lambda t: _RE_TABLE_COLUMN_NAME.sub(lambda m: m.group(1) + m.group(3), t)
            na_, nb_ = [m.group(2) for m in _RE_TABLE_COLUMN_NAME.finditer(ta)], [m.group(2) for m in _RE_TABLE_COLUMN_NAME.finditer(tb)]
            cambiados = {(x, y) for x, y in zip(na_, nb_) if x != y}
            if enmascarar(ta) != enmascarar(tb) or len(na_) != len(nb_) or not cambiados or not cambiados <= renombres:
                raise X.ErrorXlsm("VERIFICACION: %s cambio mas alla del nombre de la columna autorizada" % parte)
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

def normalizar_cierre_para_precheck(ruta_cierre_local, fecha_cierre_iso, caja, indice_vouchers=None):
    """Para UN cierre ya materializado localmente: si tiene alguna FECHA DE
    DEPOSITO normalizable (texto ambiguo-pero-resoluble, o fecha Excel real
    con día/mes invertidos CONFIRMADA por voucher único de MACROS — ver
    `indice_vouchers` en clasificar_fechas_deposito) o un encabezado
    ASIGNACION perdido en COMUNICACIONES INTERNAS (tercera regla), escribe
    una copia NUEVA normalizada (nunca sobrescribe `ruta_cierre_local`) y
    devuelve su ruta; si no hace falta nada, devuelve `ruta_cierre_local` tal
    cual (cero archivos nuevos, cero cambio de comportamiento).

    Nunca lanza por un cierre individual: un problema técnico (archivo
    corrupto, hoja no reconocida, libro date1904) simplemente no normaliza
    nada y deja `ruta_cierre_local` intacto — el cierre seguirá su curso
    normal (y, si corresponde, precheck_maestro lo bloqueará con su propio
    diagnóstico, igual que hoy). `revision` lista las inversiones DD/MM
    posibles que NO se pudieron confirmar (no se corrigen). `avisos` lista lo
    que SÍ se reparó en la copia y la persona debe poder ver (no bloquea)."""
    try:
        resultado = clasificar_fechas_deposito(ruta_cierre_local, caja, fecha_cierre_iso, indice_vouchers=indice_vouchers)
        encabezados = clasificar_encabezados_ci(ruta_cierre_local, caja)
    except Exception as exc:  # aislamiento: nunca detiene el resto del lote
        return {
            "ruta_cierre_local": ruta_cierre_local, "normalizado": False,
            "cambios": [], "revision": [], "avisos": [], "mensaje": f"{type(exc).__name__}: {exc}",
        }
    revision = resultado.get("revision", [])
    plan = resultado["plan"] + encabezados["plan"]
    if not plan:
        return {"ruta_cierre_local": ruta_cierre_local, "normalizado": False, "cambios": [],
                "revision": revision, "avisos": [], "mensaje": None}

    base, ext = os.path.splitext(ruta_cierre_local)
    ruta_salida = base + ".normalizado" + ext
    try:
        aplicar(ruta_cierre_local, ruta_salida, plan)
    except Exception as exc:  # nunca deja una copia a medio escribir en uso
        return {
            "ruta_cierre_local": ruta_cierre_local, "normalizado": False,
            "cambios": [], "revision": revision, "avisos": [], "mensaje": f"NORMALIZACION_FALLIDA:{type(exc).__name__}: {exc}",
        }
    trazabilidad = resultado["trazabilidad"] + [{
        "hoja": it["hoja"], "celda": it["celda"], "valor_original": it["texto_original"],
        "valor_normalizado": it["texto_nuevo"], "motivo": MOTIVO_ENCABEZADO_CI, "clase": CLASE_ENCABEZADO_CI,
    } for it in encabezados["plan"]]
    return {
        "ruta_cierre_local": ruta_salida, "normalizado": True,
        "cambios": trazabilidad, "revision": revision, "avisos": encabezados["avisos"], "mensaje": None,
    }


def _proveedor_indice_vouchers(ruta_maestro):
    """Callable perezoso y memoizado: lee el maestro UNA sola vez, y solo si
    alguna celda lo necesita. Un maestro ausente o ilegible da None (sin
    evidencia => la inversión DD/MM nunca se corrige); el precheck reportará
    el problema del maestro con su propio diagnóstico."""
    cache = {}

    def obtener():
        if "indice" not in cache:
            if not ruta_maestro:
                cache["indice"] = None
            else:
                try:
                    cache["indice"] = indice_vouchers_macros(ruta_maestro)
                except Exception:  # noqa: BLE001 — sin evidencia legible: no se corrige
                    cache["indice"] = None
        return cache["indice"]

    return obtener


def normalizar_cierres_materializados(cierres_materializados, caja=None):
    """Aplica normalizar_cierre_para_precheck() a cada item MATERIALIZADO
    de la lista que devuelve v3.materializacion.ejecutar_materializacion().
    Los demás items (SIN_ARCHIVO/AMBIGUO/ERROR_MATERIALIZACION) pasan
    intactos. Actualiza `ruta_cierre_local` in place cuando corresponde y
    agrega `normalizacion_fecha_deposito` (trazabilidad) a cada item; si
    quedó alguna inversión DD/MM posible sin confirmar, además
    `normalizacion_fecha_deposito_revision`; si se reparó algo visible para la
    persona (p. ej. el encabezado ASIGNACION), `avisos_cierre`. La evidencia de MACROS sale del
    `ruta_maestro_local` ya materializado de cada item (misma copia que
    usará el precheck), leído una sola vez por maestro distinto."""
    caja_codigo = caja if isinstance(caja, str) else getattr(caja, "codigo", "tiquipaya")
    proveedores = {}
    resultados = []
    for item in cierres_materializados:
        if item.get("estado_materializacion") != "MATERIALIZADO" or not item.get("ruta_cierre_local"):
            resultados.append(dict(item))
            continue
        ruta_maestro = item.get("ruta_maestro_local")
        if ruta_maestro not in proveedores:
            proveedores[ruta_maestro] = _proveedor_indice_vouchers(ruta_maestro)
        norm = normalizar_cierre_para_precheck(
            item["ruta_cierre_local"], item.get("fecha"), caja_codigo, indice_vouchers=proveedores[ruta_maestro],
        )
        salida = dict(item)
        salida["ruta_cierre_local"] = norm["ruta_cierre_local"]
        salida["normalizacion_fecha_deposito"] = norm["cambios"]
        if norm.get("revision"):
            salida["normalizacion_fecha_deposito_revision"] = norm["revision"]
        if norm.get("avisos"):
            salida["avisos_cierre"] = norm["avisos"]
        resultados.append(salida)
    return resultados
