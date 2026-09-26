"""macros_vouchers.py — Evidencia externa: vouchers bancarios de MACROS.

Lee (SOLO LECTURA, openpyxl read_only) la hoja "Tablas Dinamicas Profesional"
del MACROS mensual y arma un indice:

    (codigo_asignacion_normalizado, importe_2dec) -> [fecha_iso | None, ...]

Un voucher es UNICO solo si esa clave tiene exactamente UNA entrada. Misma
logica de lectura que CAJAS GABO (excel_io.leer_macros_bnb) reimplementada
aqui para que la Skill sea independiente: encabezados repetidos descartados
por contenido, solo filas con codigo y credito > 0.
"""
import datetime
import re
import warnings
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

import openpyxl

from xlsm_xml import normalizar_texto

HOJA_MACROS = "Tablas Dinamicas Profesional"
_RE_ISO = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_RE_DMY = re.compile(r"^(\d{2})/(\d{2})/(\d{4})$")


def normalizar_codigo(valor):
    if valor is None:
        return ""
    if isinstance(valor, float) and valor.is_integer():
        valor = int(valor)
    return normalizar_texto(valor).replace(" ", "")


def importe_2dec(valor):
    """str con 2 decimales, o None si no es un numero valido."""
    if valor is None or isinstance(valor, bool):
        return None
    try:
        d = Decimal(str(valor).strip().replace(" ", "")) if not isinstance(valor, float) else Decimal(str(valor))
    except InvalidOperation:
        return None
    return str(d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def fecha_voucher(valor):
    """date | None. Acepta fecha real, 'YYYY-MM-DD' o 'DD/MM/YYYY'. Nada mas."""
    if isinstance(valor, datetime.datetime):
        return valor.date()
    if isinstance(valor, datetime.date):
        return valor
    if isinstance(valor, str):
        t = valor.strip()
        try:
            m = _RE_ISO.match(t)
            if m:
                a, mo, d = map(int, m.groups())
                return datetime.date(a, mo, d)
            m = _RE_DMY.match(t)
            if m:
                d, mo, a = map(int, m.groups())
                return datetime.date(a, mo, d)
        except ValueError:
            return None
    return None


def leer_indice_macros(ruta):
    """Devuelve {"indice": {(codigo, importe): [date|None, ...]}, "movimientos": n, "registros": [...]}.

    `registros` (solo lectura, para buscar candidatos cuando un voucher no se encuentra; no interviene en el indice ni en
    ninguna regla): una entrada por movimiento {fecha, importe, codigo, cuenta, caja}; cuenta y caja salen de las columnas
    opcionales CUENTA CONTABLE y NUMERO DE CAJA (None si MACROS no las trae)."""
    indice = {}
    registros = []
    total = 0
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        wb = openpyxl.load_workbook(ruta, read_only=True, data_only=True, keep_vba=False)
    try:
        if HOJA_MACROS not in wb.sheetnames:
            raise ValueError("MACROS: no se encontro la hoja %r" % HOJA_MACROS)
        filas = wb[HOJA_MACROS].iter_rows(values_only=True)
        cab = next(filas, None)
        if cab is None:
            raise ValueError("MACROS: hoja vacia")
        idx = {normalizar_texto(h): j for j, h in enumerate(cab) if h is not None}
        faltan = [n for n in ("CODIGO DE ASIGNACION", "CREDITOS", "FECHA") if n not in idx]
        if faltan:
            raise ValueError("MACROS: faltan columnas %s" % faltan)
        ic, ik, ifh = idx["CODIGO DE ASIGNACION"], idx["CREDITOS"], idx["FECHA"]
        icta, icaja = idx.get("CUENTA CONTABLE"), idx.get("NUMERO DE CAJA")
        cab_fecha, cab_cod = normalizar_texto(cab[ifh]), normalizar_texto(cab[ic])
        for fila in filas:
            cod = fila[ic] if ic < len(fila) else None
            cre = fila[ik] if ik < len(fila) else None
            if cod is None or cre is None:
                continue
            fv = fila[ifh] if ifh < len(fila) else None
            if normalizar_texto(fv) == cab_fecha or normalizar_texto(cod) == cab_cod:
                continue  # encabezado repetido dentro del rango
            codigo = normalizar_codigo(cod)
            imp = importe_2dec(cre)
            if not codigo or imp is None or Decimal(imp) <= 0:
                continue
            fecha = fecha_voucher(fv)
            indice.setdefault((codigo, imp), []).append(fecha)
            cuenta = normalizar_codigo(fila[icta]) if icta is not None and icta < len(fila) else ""
            caja = normalizar_codigo(fila[icaja]) if icaja is not None and icaja < len(fila) else ""
            registros.append({"fecha": fecha, "importe": imp, "codigo": codigo, "cuenta": cuenta or None, "caja": caja or None})
            total += 1
    finally:
        wb.close()
    return {"indice": indice, "movimientos": total, "registros": registros}
