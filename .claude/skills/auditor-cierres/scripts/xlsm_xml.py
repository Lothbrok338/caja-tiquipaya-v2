"""xlsm_xml.py — Mecanismo de escritura XML QUIRURGICO (aprobado) para .xlsm.

Principios (no negociables):
  * NO Excel COM. NO openpyxl.save(). Un .xlsm es un ZIP: se lee con
    zipfile y se reemplazan SOLO los bytes de las celdas autorizadas.
  * Todo lo demas (vbaProject.bin, otras hojas, tablas, calcChain,
    sharedStrings, formulas, caches) se copia SIN reinterpretar.
  * Solo biblioteca estandar de Python.

Este modulo NO decide CUANDO corregir una fecha: eso vive en
control5_fecha_deposito.py. Aqui solo se lee (estructura, celdas, estilos)
y se escribe (parche de celda, estilo de fecha, reempaquetado del ZIP).
"""
import datetime
import os
import re
import shutil
import tempfile
import unicodedata
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from typing import Optional

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
NS_R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
EPOCH_1900 = datetime.date(1899, 12, 30)

# numFmtId integrados de Excel que son fechas/horas.
_FMT_FECHA_INTEGRADOS = set(range(14, 23)) | set(range(27, 37)) | set(range(45, 48)) | set(range(50, 59))
FMT_FECHA_CORTA = 14  # el que ya usa el cierre (fecha corta segun regional del equipo)


class ErrorXlsm(Exception):
    """Estructura del paquete no soportada o inconsistente (falla cerrado)."""


def normalizar_texto(valor):
    """Mayusculas, sin tildes, espacios colapsados. None -> ''."""
    if valor is None:
        return ""
    t = unicodedata.normalize("NFKD", str(valor))
    t = "".join(c for c in t if not unicodedata.combining(c))
    return " ".join(t.upper().split())


def col_a_num(col):
    n = 0
    for ch in col:
        n = n * 26 + (ord(ch) - 64)
    return n


def dividir_ref(ref):
    m = re.fullmatch(r"([A-Z]+)(\d+)", ref)
    if not m:
        raise ErrorXlsm("referencia de celda invalida: %r" % ref)
    return m.group(1), int(m.group(2))


@dataclass
class Celda:
    ref: str
    col: int
    fila: int
    tipo: str            # 'vacia' | 'numero' | 'texto' | 'formula' | 'otro'
    valor: object = None  # Decimal-compatible str / texto / None
    estilo: Optional[int] = None
    t_xml: Optional[str] = None


class Paquete:
    """Vista de SOLO LECTURA de un .xlsm/.xlsx (zip en memoria)."""

    def __init__(self, ruta):
        self.ruta = ruta
        with zipfile.ZipFile(ruta) as z:
            self.infos = z.infolist()
            self.partes = {i.filename: z.read(i.filename) for i in self.infos}
        self._sst = None
        self._estilos = None
        self._hojas = None
        wb = ET.fromstring(self.partes["xl/workbook.xml"])
        pr = wb.find(NS + "workbookPr")
        self.date1904 = bool(pr is not None and pr.get("date1904") in ("1", "true"))

    # -- estructura --------------------------------------------------------
    @property
    def hojas(self):
        """nombre de hoja -> nombre de parte XML (p.ej. xl/worksheets/sheet1.xml)"""
        if self._hojas is None:
            wb = ET.fromstring(self.partes["xl/workbook.xml"])
            rels = ET.fromstring(self.partes["xl/_rels/workbook.xml.rels"])
            rid = {r.get("Id"): r.get("Target") for r in rels}
            out = {}
            for s in wb.find(NS + "sheets"):
                destino = rid[s.get(NS_R + "id")]
                out[s.get("name")] = destino.lstrip("/") if destino.startswith("/") else "xl/" + destino
            self._hojas = out
        return self._hojas

    def texto_parte(self, parte):
        datos = self.partes[parte]
        cab = datos[:200].decode("ascii", "ignore")
        m = re.search(r'encoding="([^"]+)"', cab)
        if m and m.group(1).lower().replace("-", "") != "utf8":
            raise ErrorXlsm("%s no esta en UTF-8 (%s): no soportado" % (parte, m.group(1)))
        return datos.decode("utf-8")

    @property
    def shared_strings(self):
        if self._sst is None:
            self._sst = []
            if "xl/sharedStrings.xml" in self.partes:
                raiz = ET.fromstring(self.partes["xl/sharedStrings.xml"])
                for si in raiz.findall(NS + "si"):
                    self._sst.append(_texto_si(si))
        return self._sst

    # -- estilos -----------------------------------------------------------
    @property
    def estilos(self):
        if self._estilos is None:
            raiz = ET.fromstring(self.partes["xl/styles.xml"])
            fmts = {}
            nf = raiz.find(NS + "numFmts")
            if nf is not None:
                for f in nf.findall(NS + "numFmt"):
                    fmts[int(f.get("numFmtId"))] = f.get("formatCode")
            xfs = []
            cx = raiz.find(NS + "cellXfs")
            for xf in cx.findall(NS + "xf"):
                xfs.append(int(xf.get("numFmtId", "0")))
            self._estilos = (fmts, xfs)
        return self._estilos

    def estilo_es_fecha(self, s):
        fmts, xfs = self.estilos
        idx = 0 if s is None else s
        if idx >= len(xfs):
            return False
        nid = xfs[idx]
        if nid in _FMT_FECHA_INTEGRADOS:
            return True
        codigo = fmts.get(nid)
        if not codigo:
            return False
        limpio = re.sub(r'"[^"]*"|\[[^\]]*\]|\\.', "", codigo).lower()
        return "d" in limpio or "y" in limpio

    # -- celdas ------------------------------------------------------------
    def celdas_de_hoja(self, nombre_hoja):
        """Devuelve dict {fila: {col_num: Celda}} de la hoja (memoizado: cada
        hoja se parsea una sola vez aunque varios controles la consulten)."""
        if not hasattr(self, "_cache_celdas"):
            self._cache_celdas = {}
        if nombre_hoja in self._cache_celdas:
            return self._cache_celdas[nombre_hoja]
        parte = self.hojas[nombre_hoja]
        raiz = ET.fromstring(self.partes[parte])
        sd = raiz.find(NS + "sheetData")
        out = {}
        for row in sd.findall(NS + "row"):
            for c in row.findall(NS + "c"):
                ref = c.get("r")
                letras, fila = dividir_ref(ref)
                celda = self._leer_celda(c, ref, col_a_num(letras), fila)
                out.setdefault(fila, {})[celda.col] = celda
        self._cache_celdas[nombre_hoja] = out
        return out

    def _leer_celda(self, c, ref, col, fila):
        t = c.get("t")
        s = c.get("s")
        estilo = int(s) if s is not None else None
        if c.find(NS + "f") is not None:
            v = c.find(NS + "v")
            return Celda(ref, col, fila, "formula", v.text if v is not None else None, estilo, t)
        v = c.find(NS + "v")
        if t == "inlineStr":
            is_ = c.find(NS + "is")
            return Celda(ref, col, fila, "texto", _texto_si(is_) if is_ is not None else "", estilo, t)
        if v is None or v.text is None or v.text == "":
            return Celda(ref, col, fila, "vacia", None, estilo, t)
        if t == "s":
            return Celda(ref, col, fila, "texto", self.shared_strings[int(v.text)], estilo, t)
        if t in (None, "n"):
            return Celda(ref, col, fila, "numero", v.text, estilo, t)
        return Celda(ref, col, fila, "otro", v.text, estilo, t)


def _texto_si(si):
    partes = []
    for hijo in si:
        if hijo.tag == NS + "t":
            partes.append(hijo.text or "")
        elif hijo.tag == NS + "r":
            for t in hijo.findall(NS + "t"):
                partes.append(t.text or "")
    return "".join(partes)


def serial_a_fecha(serial_txt, date1904=False):
    """Serial de Excel -> (date, tiene_hora). Solo sistema 1900."""
    if date1904:
        raise ErrorXlsm("libro con date1904: no soportado")
    x = float(serial_txt)
    entero = int(x)
    if entero < 61 or entero > 2958465:
        raise ValueError("serial fuera de rango: %s" % serial_txt)
    return EPOCH_1900 + datetime.timedelta(days=entero), abs(x - entero) > 1e-9


def fecha_a_serial(d):
    return (d - EPOCH_1900).days


# ---------------------------------------------------------------------------
# Escritura quirurgica
# ---------------------------------------------------------------------------

def parche_celda(xml, ref, serial, estilo_nuevo=None):
    """Reemplaza UNICAMENTE el elemento <c r="ref" ...>...</c> de la hoja
    por una celda numerica con `serial`. Conserva el orden y el valor de
    todos los atributos (salvo t, que se elimina; y s si `estilo_nuevo`).
    Devuelve (xml_nuevo, elemento_antes, elemento_despues)."""
    patron = re.compile(r'<c r="%s"([^>]*?)(?:/>|>(.*?)</c>)' % re.escape(ref), re.S)
    ms = list(patron.finditer(xml))
    if len(ms) != 1:
        raise ErrorXlsm("celda %s: %d coincidencias en el XML (se esperaba 1)" % (ref, len(ms)))
    m = ms[0]
    if m.group(2) and "<f" in m.group(2):
        raise ErrorXlsm("celda %s contiene formula: no se modifica" % ref)
    atributos = re.findall(r'\s([A-Za-z_:][\w:.-]*)="([^"]*)"', m.group(1))
    nuevos = []
    puesto_s = False
    for nombre, valor in atributos:
        if nombre == "t":
            continue
        if nombre == "s" and estilo_nuevo is not None:
            valor = str(estilo_nuevo)
            puesto_s = True
        nuevos.append((nombre, valor))
    if estilo_nuevo is not None and not puesto_s:
        nuevos.append(("s", str(estilo_nuevo)))
    attrs = "".join(' %s="%s"' % (n, v) for n, v in nuevos)
    despues = '<c r="%s"%s><v>%d</v></c>' % (ref, attrs, serial)
    return xml[:m.start()] + despues + xml[m.end():], m.group(0), despues


def _xf_lista(styles_xml):
    m = re.search(r'<cellXfs count="(\d+)">(.*?)</cellXfs>', styles_xml, re.S)
    if not m:
        raise ErrorXlsm("styles.xml sin cellXfs")
    xfs = re.findall(r"<xf\b[^>]*?(?:/>|>.*?</xf>)", m.group(2), re.S)
    if len(xfs) != int(m.group(1)):
        raise ErrorXlsm("cellXfs count no coincide con la cantidad de <xf>")
    return m, xfs


def _con_formato_fecha(xf):
    """Copia del <xf> con numFmtId=14 y applyNumberFormat=1 (todo lo demas igual)."""
    m = re.match(r"<xf\b([^>]*?)(/?>)", xf)
    attrs = dict(re.findall(r'\s([A-Za-z_:][\w:.-]*)="([^"]*)"', m.group(1)))
    attrs["numFmtId"] = str(FMT_FECHA_CORTA)
    attrs["applyNumberFormat"] = "1"
    orden = [k for k in re.findall(r'\s([A-Za-z_:][\w:.-]*)=', m.group(1))]
    for k in ("numFmtId", "applyNumberFormat"):
        if k not in orden:
            orden.append(k)
    nuevo_attrs = "".join(' %s="%s"' % (k, attrs[k]) for k in orden)
    return "<xf" + nuevo_attrs + xf[m.end(1):]


def estilo_de_fecha_para(styles_xml, s_actual):
    """Estilo para una celda que pasa de texto a fecha real.

    Devuelve (styles_xml_resultante, indice_estilo, nota|None). Si el estilo
    actual ya es de fecha se conserva (nota None y styles sin cambio). Si no,
    se REUTILIZA un xf identico pero con numFmtId=14 si existe; si no existe
    se AGREGA uno al final de cellXfs. Nunca se modifica un xf existente."""
    m, xfs = _xf_lista(styles_xml)
    base = xfs[0 if s_actual is None else s_actual]
    obj = _con_formato_fecha(base)
    if obj == base:
        return styles_xml, (0 if s_actual is None else s_actual), None
    for i, xf in enumerate(xfs):
        if xf == obj:
            return styles_xml, i, "reutiliza xf[%d] (fecha, mismo estilo que xf[%d])" % (i, 0 if s_actual is None else s_actual)
    n = len(xfs)
    nuevo = '<cellXfs count="%d">%s%s</cellXfs>' % (n + 1, m.group(2), obj)
    return (styles_xml[:m.start()] + nuevo + styles_xml[m.end():], n,
            "agrega xf[%d] al final de cellXfs (copia de xf[%d] con numFmtId=%d); count %d->%d" % (
                n, 0 if s_actual is None else s_actual, FMT_FECHA_CORTA, n, n + 1))


def reescribir_zip(ruta_in, ruta_out, reemplazos):
    """Escribe ruta_out = ruta_in con `reemplazos` {parte: bytes}. Conserva
    orden, nombres, tipo de compresion y metadatos de cada entrada. La
    escritura es atomica (temporal + move)."""
    if os.path.abspath(ruta_in) == os.path.abspath(ruta_out):
        raise ErrorXlsm("la salida no puede ser el mismo archivo de entrada")
    carpeta = os.path.dirname(os.path.abspath(ruta_out)) or "."
    fd, tmp = tempfile.mkstemp(suffix=".tmp", dir=carpeta)
    os.close(fd)
    try:
        with zipfile.ZipFile(ruta_in) as z, zipfile.ZipFile(tmp, "w") as zo:
            for info in z.infolist():
                datos = reemplazos.get(info.filename)
                if datos is None:
                    datos = z.read(info.filename)
                ni = zipfile.ZipInfo(info.filename, info.date_time)
                ni.compress_type = info.compress_type
                ni.external_attr = info.external_attr
                ni.create_system = info.create_system
                zo.writestr(ni, datos)
        shutil.move(tmp, ruta_out)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def quitar_celdas(xml, refs):
    """Texto de la hoja SIN los elementos <c> indicados (para comparar 'todo lo demas')."""
    for ref in refs:
        xml = re.sub(r'<c r="%s"[^>]*?(?:/>|>.*?</c>)' % re.escape(ref), "", xml, flags=re.S)
    return xml
