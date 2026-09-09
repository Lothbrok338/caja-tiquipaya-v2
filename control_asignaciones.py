"""
control_asignaciones.py — CONTROL 1: auditoría de asignaciones (ZUONR)
duplicadas/históricas del SAP GLOBAL mensual de Caja Tiquipaya, con etapa
de validación humana en Excel y corrección autorizada del propio GLOBAL.

Este módulo es de solo lectura sobre el GLOBAL MIENTRAS haya alertas sin
validar: nunca lo modifica, nunca reinterpreta contabilidad, nunca decide
por sí mismo que una asignación es correcta o incorrecta. Solo después de
que TODAS las alertas de un periodo fueron revisadas por el auditor,
CONTROL 1 puede corregir ÚNICAMENTE la columna Asignacion (R) de las
filas explícitamente autorizadas y sobrescribir ese mismo GLOBAL — nunca
crea un archivo `_VALIDADO` ni una copia de respaldo productiva: el
GLOBAL corregido es el mismo archivo que luego se carga a SAP.

Layout del GLOBAL (idéntico al de sap_writer.py / consolidador_mensual.py,
nunca reinterpretado aquí — hoja EXACTA "1", partidas desde la fila 16):

    C = CuentaMayor   D = TextoPosicion (glosa)   E = Cargo   F = Haber
    O = FechaValor    R = Asignacion (ZUONR)

La hoja "1" es OBLIGATORIA (ERROR_TECNICO/GLOBAL_HOJA_1_NO_ENCONTRADA si
no existe, sin fallback a otra hoja) y el nombre del GLOBAL debe seguir
la convención canónica SAP_GLOBAL_TIQ_<MES>_<AÑO>.xlsx (ERROR_TECNICO/
GLOBAL_NOMBRE_NO_CANONICO si no, sin inferir un periodo de otra forma).

EXCLUSIONES (SIN CAMBIOS): SFC101, SFC102, "TIQUIPAYA <MES>" (12
abreviaturas oficiales), y CuentaMayor "110201008" (por cuenta, sin
importar el texto de Asignacion). "FORTALEZA" SIEMPRE se evalúa.

VALIDACIÓN HUMANA EN EXCEL:

    Cuando hay alertas se genera/actualiza:

        REVISION_ASIGNACIONES_<PERIODO>.xlsx    (hoja única "REVISION")

    con UNA FILA POR OCURRENCIA ACTUAL DEL GLOBAL involucrada en una
    alerta (nunca una fila agrupada por asignación): si "3P66536982"
    aparece en las filas 146 y 278, el Excel trae DOS filas, una por
    cada FILA_GLOBAL. `FILA_GLOBAL` la calcula Python leyendo el GLOBAL
    — el auditor NUNCA la digita.

    Columnas: PERIODO, FILA_GLOBAL, ASIGNACION_ORIGINAL, TIPO_ALERTA,
    FECHA_VALOR, CUENTA_MAYOR, GLOSA, IMPORTE, ANTECEDENTE_HISTORICO,
    VALIDACION_AUDITOR, ASIGNACION_CORRECTA, OBSERVACION_AUDITOR,
    FECHA_VALIDACION, SHA256_GLOBAL. El auditor solo completa
    VALIDACION_AUDITOR (lista desplegable CORRECTA/INCORRECTA),
    ASIGNACION_CORRECTA (obligatoria y distinta del original solo si
    INCORRECTA) y OBSERVACION_AUDITOR; FECHA_VALIDACION se autocompleta
    al cerrar si quedó vacía.

    CORRECTA = "la asignación observada es válida tal como está": no se
    toca esa fila del GLOBAL, la asignación final es la original.
    INCORRECTA sin ASIGNACION_CORRECTA válida (no vacía, distinta de la
    original) deja la fila PENDIENTE — nunca se asume una corrección.

    Las decisiones humanas ya escritas se preservan al reejecutar
    (emparejando por FILA_GLOBAL) y solo se reutilizan si su
    SHA256_GLOBAL coincide con el GLOBAL actual — un GLOBAL modificado
    nunca reutiliza en silencio una revisión de un SHA anterior. Si
    existe un CSV de revisión del esquema anterior (una fila por
    asignación) y todavía no existe el .xlsx, sus decisiones
    (VALIDACION_AUDITOR/OBSERVACION_AUDITOR/FECHA_VALIDACION) se
    importan como semilla — compatibilidad hacia atrás, nunca se vuelve
    a escribir ese CSV.

CIERRE Y CORRECCIÓN DEL GLOBAL:

    Mientras exista al menos una fila PENDIENTE: no se toca el GLOBAL,
    no se actualiza el histórico, no se cierra el mes — solo se
    regenera el .xlsx (preservando decisiones).

    Cuando TODAS las filas están resueltas, antes de cerrar se aplican
    las correcciones EN MEMORIA y se vuelve a evaluar duplicados con las
    asignaciones FINALES contra el propio GLOBAL y contra el histórico.
    Si esa reevaluación descubre una ocurrencia nueva no vista antes
    (una corrección que genera una duplicidad silenciosa), el cierre se
    aborta: se incorpora esa ocurrencia al .xlsx (preservando TODAS las
    decisiones anteriores) y el mes sigue PENDIENTE_VALIDACION_AUDITOR.

    Solo si la reevaluación no encuentra nada nuevo se aplican las
    correcciones: se reabre el GLOBAL (nunca en modo solo-lectura), se
    verifica que cada celda R[fila] siga conteniendo exactamente
    ASIGNACION_ORIGINAL, se reemplaza ÚNICAMENTE esa celda por
    ASIGNACION_CORRECTA y se guarda el MISMO archivo — nunca se crea un
    `_VALIDADO` ni una copia paralela. Si una sola verificación falla,
    NO se aplica ninguna corrección (todo o nada).

ESTADOS (`estado` mantiene la semántica previa a la validación humana):

    - OK_SIN_DUPLICADOS / REVISAR_DUPLICADOS_ENCONTRADOS (hay o no
      alertas, sin importar si ya se validaron).
    - `estado_validacion` (solo relevante si hay alertas): None,
      PENDIENTE_VALIDACION_AUDITOR o CERRADO_CON_VALIDACION_AUDITOR.
    - YA_PROCESADO_SIN_CAMBIOS / GLOBAL_MODIFICADO_REQUIERE_REVISION /
      ERROR_TECNICO — sin cambios de comportamiento. Idempotencia: el
      GLOBAL corregido por el propio CONTROL 1 (mismo SHA que
      sha256_global_final ya registrado) es YA_PROCESADO_SIN_CAMBIOS,
      nunca GLOBAL_MODIFICADO_REQUIERE_REVISION; un cambio posterior NO
      autorizado (SHA distinto al final registrado) sí lo dispara.

MEMORIA HISTÓRICA (HISTORICO_ASIGNACIONES.csv): la columna `asignacion`
guarda siempre la asignación FINAL (la que realmente quedó en el GLOBAL
que se carga a SAP), para que los meses siguientes comparen contra la
referencia válida; `asignacion_original`/`asignacion_final` documentan
por separado el valor de origen y el valor final. Esquema extendido de
forma compatible (columnas nuevas al final; un CSV con el esquema
anterior se sigue leyendo sin perder información).

TRANSPORTE: solo rutas de archivo locales ya materializadas. Nunca
Base64, nunca Google Drive.

Uso:
    python control_asignaciones.py \
        --global /ruta/SAP_GLOBAL_TIQ_AGOSTO_2026.xlsx \
        --historico /ruta/HISTORICO_ASIGNACIONES.csv \
        --salida-json /ruta/CONTROL_ASIGNACIONES_AGOSTO_2026.json

    Modo seguro (no escribe absolutamente nada):
    python control_asignaciones.py --global ... --historico ... --dry-run
"""

import argparse
import csv
import datetime
import hashlib
import json
import os
import re
import warnings
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

import openpyxl
from openpyxl.styles import Alignment, Font
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

# ---------------------------------------------------------------------------
# Constantes de layout del GLOBAL (ver sap_writer.py / consolidador_mensual.py
# — nunca se reinterpreta el motor aquí).
# ---------------------------------------------------------------------------

_HOJA_SAP = "1"
_FILA_PRIMERA_PARTIDA = 16

_COL_CUENTA = "C"
_COL_GLOSA = "D"
_COL_CARGO = "E"
_COL_HABER = "F"
_COL_FECHA_VALOR = "O"
_COL_ASIGNACION = "R"

_MESES_ABREV = (
    "ENE", "FEB", "MAR", "ABR", "MAY", "JUN",
    "JUL", "AGO", "SEP", "OCT", "NOV", "DIC",
)

# Únicas exclusiones autorizadas. NUNCA agregar nada aquí sin autorización
# explícita del usuario (ver reglas del proyecto CAJA TIQUIPAYA V2 CLOUD).
_ASIGNACIONES_EXCLUIDAS = {"SFC101", "SFC102"} | {
    f"TIQUIPAYA {mes}" for mes in _MESES_ABREV
}

# Cuenta de comisión ATC: se excluye POR CUENTA, sin importar Asignacion.
_CUENTA_COMISION_ATC = "110201008"

_ESTADO_REVISAR = "REVISAR"

# `estado` (semántica previa a la validación humana; se mantiene por
# compatibilidad con consumidores existentes).
_ESTADO_OK_SIN_DUPLICADOS = "OK_SIN_DUPLICADOS"
_ESTADO_REVISAR_DUPLICADOS = "REVISAR_DUPLICADOS_ENCONTRADOS"

# `estado_validacion` (nuevo; solo relevante cuando `estado ==
# REVISAR_DUPLICADOS_ENCONTRADOS`).
_ESTADO_PENDIENTE_VALIDACION = "PENDIENTE_VALIDACION_AUDITOR"
_ESTADO_CERRADO_CON_VALIDACION = "CERRADO_CON_VALIDACION_AUDITOR"

_SIN_ALERTA = "SIN_ALERTA"

_TIPO_ALERTA_MISMO_MES = "DUPLICADA_MISMO_MES"
_TIPO_ALERTA_HISTORICO = "DUPLICADA_CON_HISTORICO"
_TIPO_ALERTA_AMBAS = "AMBAS"

_VALIDACIONES_VALIDAS = {"CORRECTA", "INCORRECTA"}

# Esquema del histórico (extendido de forma compatible: columnas nuevas
# siempre al final, para que un CSV con el esquema anterior se siga
# leyendo sin perder ninguna fila).
_COLUMNAS_HISTORICO = [
    "asignacion", "fecha_valor", "cuenta_mayor", "glosa", "monto",
    "archivo_global", "fila_sap", "sha256_archivo", "fecha_incorporacion",
    "alerta_duplicado", "validacion_auditor", "observacion_auditor",
    "fecha_validacion",
    # Extensión de esta etapa (corrección autorizada del GLOBAL).
    "asignacion_original", "asignacion_final", "fila_global",
    "sha256_global_original", "sha256_global_final",
]

# Hoja y columnas del Excel de revisión — UNA FILA POR OCURRENCIA (nunca
# agrupada por asignación).
_HOJA_REVISION = "REVISION"
_COLUMNAS_REVISION_XLSX = [
    "PERIODO", "FILA_GLOBAL", "ASIGNACION_ORIGINAL", "TIPO_ALERTA",
    "FECHA_VALOR", "CUENTA_MAYOR", "GLOSA", "IMPORTE",
    "ANTECEDENTE_HISTORICO", "VALIDACION_AUDITOR", "ASIGNACION_CORRECTA",
    "OBSERVACION_AUDITOR", "FECHA_VALIDACION", "SHA256_GLOBAL",
]

_ANCHOS_COLUMNA_REVISION = {
    "PERIODO": 14, "FILA_GLOBAL": 12, "ASIGNACION_ORIGINAL": 18,
    "TIPO_ALERTA": 24, "FECHA_VALOR": 12, "CUENTA_MAYOR": 14,
    "GLOSA": 45, "IMPORTE": 14, "ANTECEDENTE_HISTORICO": 60,
    "VALIDACION_AUDITOR": 16, "ASIGNACION_CORRECTA": 18,
    "OBSERVACION_AUDITOR": 45, "FECHA_VALIDACION": 16, "SHA256_GLOBAL": 20,
}
_COLUMNAS_TEXTO_AJUSTADO = ("GLOSA", "OBSERVACION_AUDITOR", "ANTECEDENTE_HISTORICO")

# Convención canónica OBLIGATORIA del nombre del GLOBAL mensual. Sin esto
# no se puede derivar el periodo, y sin periodo el control se detiene.
_RE_NOMBRE_GLOBAL = re.compile(r"^SAP_GLOBAL_TIQ_([A-Za-z]+)_(\d{4})\.xlsx$", re.IGNORECASE)


class HojaNoEncontradaError(RuntimeError):
    """La hoja EXACTA "1" no existe en el GLOBAL. Nunca se hace fallback
    a otra hoja (ver ejecutar_control)."""


class CorreccionInvalidaError(RuntimeError):
    """Guardarraíl de aplicar_correcciones_global: la celda R[fila] del
    GLOBAL ya no contiene el ASIGNACION_ORIGINAL esperado. Nunca se
    aplica ninguna corrección si esto ocurre (todo o nada)."""


# ---------------------------------------------------------------------------
# Utilidades básicas
# ---------------------------------------------------------------------------

def _hash_archivo(ruta):
    hasher = hashlib.sha256()
    with open(ruta, "rb") as f:
        for bloque in iter(lambda: f.read(1 << 16), b""):
            hasher.update(bloque)
    return hasher.hexdigest()


def _abrir_libro(ruta, **kwargs):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        return openpyxl.load_workbook(ruta, **kwargs)


def _decimal_celda(valor):
    """Convierte el valor de una celda de importe a Decimal con 2
    decimales, o None si la celda está vacía/no numérica. Nunca usa
    float para el resultado (ver regla Decimal del proyecto)."""
    if valor is None:
        return None
    if isinstance(valor, Decimal):
        dec = valor
    elif isinstance(valor, bool):
        return None
    elif isinstance(valor, int):
        dec = Decimal(valor)
    elif isinstance(valor, float):
        dec = Decimal(str(valor))
    else:
        texto = str(valor).strip()
        if not texto:
            return None
        try:
            dec = Decimal(texto)
        except InvalidOperation:
            return None
    return dec.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _texto_celda(valor):
    if valor is None:
        return None
    texto = str(valor).strip()
    return texto if texto else None


def _fecha_celda(valor):
    if valor is None:
        return None
    if isinstance(valor, datetime.datetime):
        return valor.date().isoformat()
    if isinstance(valor, datetime.date):
        return valor.isoformat()
    return str(valor).strip()


def _texto_o_vacio(valor):
    """Normaliza cualquier valor leído de Excel/CSV a texto, sin
    reinterpretarlo: None -> "", float entero -> sin ".0", el resto -> str."""
    if valor is None:
        return ""
    if isinstance(valor, float) and valor.is_integer():
        return str(int(valor))
    return str(valor)


def _normalizar_cuenta(valor):
    """Normaliza CuentaMayor a texto comparable de forma segura, sin
    asumir un tipo de origen fijo (Excel puede entregarla como str, int
    o float — p. ej. 110201008.0). Nunca reinterpreta el código en sí,
    solo lo lleva a una forma comparable contra _CUENTA_COMISION_ATC."""
    if valor is None:
        return None
    texto = str(valor).strip()
    if not texto:
        return None
    if texto.endswith(".0") and texto[:-2].isdigit():
        texto = texto[:-2]
    return texto


def es_excluida(asignacion, cuenta_mayor):
    """True para SFC101, SFC102, "TIQUIPAYA <MES>" (una de las 12
    abreviaturas oficiales), o cuando CuentaMayor es la cuenta de
    comisión ATC (110201008) — esta última exclusión es POR CUENTA,
    independientemente del texto de asignacion. Cualquier otro valor
    —incluido "FORTALEZA"— NUNCA se excluye. SIN CAMBIOS."""
    if asignacion in _ASIGNACIONES_EXCLUIDAS:
        return True
    return _normalizar_cuenta(cuenta_mayor) == _CUENTA_COMISION_ATC


# ---------------------------------------------------------------------------
# Lectura del GLOBAL (solo lectura; nunca se guarda nada sobre él aquí)
# ---------------------------------------------------------------------------

def leer_partidas_global(ruta_global):
    """Lee las partidas del SAP GLOBAL desde la fila 16 de la hoja EXACTA
    "1" (mismo layout que sap_writer.py). Si esa hoja no existe, lanza
    HojaNoEncontradaError — nunca hace fallback a wb.sheetnames[0]. Se
    detiene en la primera fila donde CuentaMayor (C) y Asignacion (R)
    están ambas vacías.

    Devuelve una lista de dicts: fila_sap, asignacion, fecha_valor,
    cuenta_mayor, glosa, monto."""
    wb = _abrir_libro(ruta_global, data_only=True, read_only=True)
    try:
        if _HOJA_SAP not in wb.sheetnames:
            raise HojaNoEncontradaError(_HOJA_SAP)
        ws = wb[_HOJA_SAP]

        partidas = []
        fila = _FILA_PRIMERA_PARTIDA
        while True:
            cuenta = ws[f"{_COL_CUENTA}{fila}"].value
            asignacion_raw = ws[f"{_COL_ASIGNACION}{fila}"].value
            if (cuenta in (None, "")) and (asignacion_raw in (None, "")):
                break

            cargo = _decimal_celda(ws[f"{_COL_CARGO}{fila}"].value)
            haber = _decimal_celda(ws[f"{_COL_HABER}{fila}"].value)
            monto = cargo if cargo not in (None, Decimal("0.00")) else haber
            if monto is None:
                monto = cargo if cargo is not None else haber

            partidas.append({
                "fila_sap": fila,
                "asignacion": _texto_celda(asignacion_raw),
                "fecha_valor": _fecha_celda(ws[f"{_COL_FECHA_VALOR}{fila}"].value),
                "cuenta_mayor": _texto_celda(cuenta),
                "glosa": _texto_celda(ws[f"{_COL_GLOSA}{fila}"].value),
                "monto": str(monto) if monto is not None else None,
            })
            fila += 1
        return partidas
    finally:
        wb.close()


def aplicar_correcciones_global(ruta_global, correcciones):
    """correcciones: lista de (fila_sap, asignacion_original, asignacion_nueva).

    Reabre el GLOBAL en modo escritura (NUNCA read_only, NUNCA data_only:
    así se conservan fórmulas/formato del resto del workbook). Verifica
    TODAS las celdas R[fila] antes de tocar ninguna; si una sola no
    coincide con el ASIGNACION_ORIGINAL esperado, no aplica NINGUNA
    corrección (todo o nada) y lanza CorreccionInvalidaError. Solo
    modifica la columna Asignacion (R) de las filas recibidas — ninguna
    otra celda del workbook se toca. Sobrescribe el MISMO archivo."""
    if not correcciones:
        return
    wb = _abrir_libro(ruta_global)
    try:
        ws = wb[_HOJA_SAP]

        for fila_sap, original, _nueva in correcciones:
            actual = _texto_celda(ws[f"{_COL_ASIGNACION}{fila_sap}"].value)
            if actual != original:
                raise CorreccionInvalidaError(
                    f"ASIGNACION_ORIGINAL_NO_COINCIDE:fila={fila_sap}:"
                    f"esperado={original!r}:actual={actual!r}"
                )

        for fila_sap, _original, nueva in correcciones:
            ws[f"{_COL_ASIGNACION}{fila_sap}"] = nueva

        ruta_tmp = f"{ruta_global}.tmp"
        wb.save(ruta_tmp)
    finally:
        wb.close()
    os.replace(ruta_tmp, ruta_global)


# ---------------------------------------------------------------------------
# Histórico (HISTORICO_ASIGNACIONES.csv)
# ---------------------------------------------------------------------------

def cargar_historico(ruta_historico):
    if not ruta_historico or not os.path.isfile(ruta_historico):
        return []
    with open(ruta_historico, "r", encoding="utf-8", newline="") as f:
        return [dict(fila) for fila in csv.DictReader(f)]


def guardar_historico(ruta_historico, filas):
    """Reescritura atómica del CSV completo, con el esquema EXTENDIDO
    (_COLUMNAS_HISTORICO). Una fila del esquema anterior simplemente no
    trae las claves nuevas: `fila.get(col, "")` las deja vacías al
    reescribir, sin perder ningún dato original."""
    directorio = os.path.dirname(os.path.abspath(ruta_historico))
    if directorio:
        os.makedirs(directorio, exist_ok=True)
    ruta_tmp = f"{ruta_historico}.tmp"
    with open(ruta_tmp, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=_COLUMNAS_HISTORICO)
        writer.writeheader()
        for fila in filas:
            writer.writerow({col: fila.get(col, "") for col in _COLUMNAS_HISTORICO})
    os.replace(ruta_tmp, ruta_historico)


def ya_procesado(historico, sha256_archivo):
    """CASO A de idempotencia. `sha256_archivo` en el histórico guarda el
    SHA-256 FINAL del GLOBAL (post-corrección si la hubo): un rerun sobre
    el GLOBAL ya corregido por este mismo CONTROL 1 coincide aquí, nunca
    dispara GLOBAL_MODIFICADO_REQUIERE_REVISION."""
    return any(fila.get("sha256_archivo") == sha256_archivo for fila in historico)


def _sha_global_modificado(historico, nombre_archivo_global, sha256_archivo):
    """CASO B de idempotencia: una fila del histórico con el MISMO
    archivo_global pero un sha256_archivo (FINAL) distinto al actual."""
    for fila in historico:
        if fila.get("archivo_global") != nombre_archivo_global:
            continue
        sha_existente = fila.get("sha256_archivo")
        if sha_existente and sha_existente != sha256_archivo:
            return sha_existente
    return None


def _fila_historico(partida, alerta, resolucion, nombre_archivo_global,
                     sha_original, sha_final, ahora,
                     fecha_validacion=None, observacion=None):
    """Construye una fila del histórico para `partida`. `resolucion`
    (o None si la ocurrencia nunca tuvo alerta) trae `final`/
    `validacion`/`observacion`/`fecha_validacion`. La columna
    `asignacion` SIEMPRE guarda la asignación FINAL — la que realmente
    quedó en el GLOBAL que se carga a SAP."""
    asignacion_final = resolucion["final"] if resolucion else partida["asignacion"]
    validacion = resolucion["validacion"] if resolucion else ""
    obs = observacion if observacion is not None else (resolucion["observacion"] if resolucion else "")
    fecha_val = fecha_validacion if fecha_validacion is not None else (
        resolucion["fecha_validacion"] if resolucion else ""
    )
    return {
        "asignacion": asignacion_final or "",
        "fecha_valor": partida["fecha_valor"] or "",
        "cuenta_mayor": partida["cuenta_mayor"] or "",
        "glosa": partida["glosa"] or "",
        "monto": partida["monto"] or "",
        "archivo_global": nombre_archivo_global,
        "fila_sap": partida["fila_sap"],
        "sha256_archivo": sha_final,
        "fecha_incorporacion": ahora,
        "alerta_duplicado": alerta,
        "validacion_auditor": validacion,
        "observacion_auditor": obs,
        "fecha_validacion": fecha_val,
        "asignacion_original": partida["asignacion"] or "",
        "asignacion_final": asignacion_final or "",
        "fila_global": partida["fila_sap"],
        "sha256_global_original": sha_original,
        "sha256_global_final": sha_final,
    }


# ---------------------------------------------------------------------------
# Detección de duplicados — formato "por par" (compatibilidad del JSON de
# detalle; basado SIEMPRE en las asignaciones ORIGINALES del GLOBAL).
# ---------------------------------------------------------------------------

def _construir_hallazgo(actual, archivo_actual, relacionado, origen_relacionado):
    return {
        "asignacion": actual["asignacion"],
        "fecha": actual["fecha_valor"],
        "cuenta": actual["cuenta_mayor"],
        "glosa": actual["glosa"],
        "monto": actual["monto"],
        "archivo_global": archivo_actual,
        "fila_sap": actual["fila_sap"],
        "fecha_relacionada": relacionado.get("fecha_valor"),
        "glosa_relacionada": relacionado.get("glosa"),
        "monto_relacionado": relacionado.get("monto"),
        "archivo_relacionado": relacionado.get("archivo_global"),
        "fila_sap_relacionada": relacionado.get("fila_sap"),
        "origen_relacionado": origen_relacionado,  # HISTORICO | MISMO_GLOBAL
        "estado": _ESTADO_REVISAR,
    }


def detectar_duplicados(candidatas_nuevas, historico, nombre_archivo_global):
    """Hallazgos "por par" (uno por ocurrencia-nueva/ocurrencia-
    relacionada) — se conserva por compatibilidad en el JSON de detalle.
    La etapa de validación humana usa detectar_ocurrencias_alertadas()
    (una entrada por ocurrencia real del GLOBAL)."""
    idx_historico = {}
    for fila in historico:
        idx_historico.setdefault(fila["asignacion"], []).append(fila)

    idx_nuevas = {}
    for p in candidatas_nuevas:
        idx_nuevas.setdefault(p["asignacion"], []).append(p)

    hallazgos = []
    for asignacion, ocurrencias in idx_nuevas.items():
        for previa in idx_historico.get(asignacion, []):
            for nueva in ocurrencias:
                hallazgos.append(_construir_hallazgo(
                    nueva, nombre_archivo_global, previa, "HISTORICO"
                ))
        if len(ocurrencias) > 1:
            for i in range(len(ocurrencias)):
                for j in range(i + 1, len(ocurrencias)):
                    relacionado = {**ocurrencias[j], "archivo_global": nombre_archivo_global}
                    hallazgos.append(_construir_hallazgo(
                        ocurrencias[i], nombre_archivo_global, relacionado, "MISMO_GLOBAL"
                    ))

    return hallazgos


# ---------------------------------------------------------------------------
# Periodo (para REVISION_ASIGNACIONES_<PERIODO>.xlsx). OBLIGATORIO a
# partir del nombre canónico del GLOBAL — SIN fallback.
# ---------------------------------------------------------------------------

def _derivar_periodo(nombre_archivo_global):
    """Convención canónica OBLIGATORIA: SAP_GLOBAL_TIQ_<MES>_<AÑO>.xlsx.
    Devuelve "<MES>_<AÑO>" en mayúsculas, o None si el nombre no calza —
    SIN fallback: un nombre no canónico detiene el control."""
    if not nombre_archivo_global:
        return None
    m = _RE_NOMBRE_GLOBAL.match(nombre_archivo_global)
    if not m:
        return None
    mes, anio = m.groups()
    return f"{mes.upper()}_{anio}"


def _periodo_para_mostrar(nombre_archivo_global):
    """Variante NO estricta, solo para mostrar el periodo de un
    antecedente histórico de forma legible (puede referenciar un
    archivo_global grabado antes de exigir el nombre canónico). Nunca se
    usa para decidir el periodo del GLOBAL que se audita ahora."""
    periodo = _derivar_periodo(nombre_archivo_global)
    if periodo:
        return periodo
    if not nombre_archivo_global:
        return "PERIODO_DESCONOCIDO"
    return os.path.splitext(nombre_archivo_global)[0]


def ruta_revision_asignaciones(directorio, periodo):
    """Ruta del CSV de revisión LEGADO (esquema anterior, una fila por
    asignación) — se sigue leyendo para importar decisiones si el .xlsx
    todavía no existe; nunca se vuelve a escribir."""
    return os.path.join(directorio, f"REVISION_ASIGNACIONES_{periodo}.csv")


def ruta_revision_xlsx(directorio, periodo):
    """Ruta del Excel de revisión — formato PRINCIPAL de esta etapa."""
    return os.path.join(directorio, f"REVISION_ASIGNACIONES_{periodo}.xlsx")


# ---------------------------------------------------------------------------
# Detección de ocurrencias alertadas (una entrada por FILA_GLOBAL)
# ---------------------------------------------------------------------------

def _resumen_antecedente_historico(fila_hist):
    periodo_previo = _periodo_para_mostrar(fila_hist.get("archivo_global") or "")
    validacion = fila_hist.get("validacion_auditor") or "SIN_VALIDACION"
    observacion = fila_hist.get("observacion_auditor") or ""
    texto = (
        f"periodo {periodo_previo}, archivo {fila_hist.get('archivo_global', '')}, "
        f"fila {fila_hist.get('fila_sap', '')}, {fila_hist.get('fecha_valor', '')}, "
        f"cuenta {fila_hist.get('cuenta_mayor', '')}, \"{fila_hist.get('glosa', '')}\", "
        f"monto {fila_hist.get('monto', '')}, validación previa={validacion}"
    )
    if observacion:
        texto += f", observación previa: \"{observacion}\""
    return texto


def _texto_antecedentes(antecedentes):
    if not antecedentes:
        return ""
    return " | ".join(_resumen_antecedente_historico(a) for a in antecedentes)


def detectar_ocurrencias_alertadas(candidatas, historico):
    """Devuelve {fila_sap: {"tipo": TIPO_ALERTA, "antecedentes": [...]}}
    para toda ocurrencia de `candidatas` cuya `asignacion` (el valor que
    trae cada dict — original o final, según lo que reciba el llamador)
    se repite dentro de `candidatas` y/o ya existe en `historico`
    (columna "asignacion", que guarda la asignación FINAL de cada
    periodo anterior). La coincidencia por sí sola basta: una validación
    histórica anterior nunca evita una alerta nueva."""
    idx_actual = {}
    for occ in candidatas:
        idx_actual.setdefault(occ["asignacion"], []).append(occ)

    idx_hist = {}
    for fila in historico:
        idx_hist.setdefault(fila.get("asignacion"), []).append(fila)

    resultado = {}
    for valor, ocurrencias in idx_actual.items():
        antecedentes = idx_hist.get(valor, [])
        mismo_mes = len(ocurrencias) > 1
        con_historico = bool(antecedentes)
        if not mismo_mes and not con_historico:
            continue
        if mismo_mes and con_historico:
            tipo = _TIPO_ALERTA_AMBAS
        elif mismo_mes:
            tipo = _TIPO_ALERTA_MISMO_MES
        else:
            tipo = _TIPO_ALERTA_HISTORICO
        for occ in ocurrencias:
            resultado[occ["fila_sap"]] = {"tipo": tipo, "antecedentes": antecedentes}
    return resultado


def construir_filas_revision(candidatas, historico, periodo, sha256_global):
    """Una fila por OCURRENCIA (no por asignación agrupada) para toda
    ocurrencia de `candidatas` que participe en una alerta."""
    alertas = detectar_ocurrencias_alertadas(candidatas, historico)
    filas = []
    for occ in candidatas:
        info = alertas.get(occ["fila_sap"])
        if not info:
            continue
        filas.append({
            "PERIODO": periodo,
            "FILA_GLOBAL": occ["fila_sap"],
            "ASIGNACION_ORIGINAL": occ["asignacion"],
            "TIPO_ALERTA": info["tipo"],
            "FECHA_VALOR": occ["fecha_valor"] or "",
            "CUENTA_MAYOR": occ["cuenta_mayor"] or "",
            "GLOSA": occ["glosa"] or "",
            "IMPORTE": occ["monto"] or "",
            "ANTECEDENTE_HISTORICO": _texto_antecedentes(info["antecedentes"]),
            "VALIDACION_AUDITOR": "",
            "ASIGNACION_CORRECTA": "",
            "OBSERVACION_AUDITOR": "",
            "FECHA_VALIDACION": "",
            "SHA256_GLOBAL": sha256_global,
        })
    return filas


# ---------------------------------------------------------------------------
# Excel de revisión (REVISION_ASIGNACIONES_<PERIODO>.xlsx)
# ---------------------------------------------------------------------------

def guardar_revision_xlsx(ruta, filas):
    """Escribe el Excel de revisión: hoja única "REVISION", encabezados
    en negrita, autofiltro, fila superior congelada, texto ajustado en
    GLOSA/OBSERVACION_AUDITOR/ANTECEDENTE_HISTORICO, anchos razonables,
    y lista desplegable CORRECTA/INCORRECTA en VALIDACION_AUDITOR."""
    directorio = os.path.dirname(os.path.abspath(ruta))
    if directorio:
        os.makedirs(directorio, exist_ok=True)

    filas_ordenadas = sorted(filas, key=lambda f: int(f["FILA_GLOBAL"]))

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = _HOJA_REVISION

    ws.append(_COLUMNAS_REVISION_XLSX)
    for celda in ws[1]:
        celda.font = Font(bold=True)

    for fila in filas_ordenadas:
        ws.append([fila.get(col, "") for col in _COLUMNAS_REVISION_XLSX])

    ultima_fila = ws.max_row
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(_COLUMNAS_REVISION_XLSX))}{ultima_fila}"

    for idx, col in enumerate(_COLUMNAS_REVISION_XLSX, start=1):
        ws.column_dimensions[get_column_letter(idx)].width = _ANCHOS_COLUMNA_REVISION.get(col, 16)

    if ultima_fila > 1:
        for col in _COLUMNAS_TEXTO_AJUSTADO:
            letra = get_column_letter(_COLUMNAS_REVISION_XLSX.index(col) + 1)
            for fila_idx in range(2, ultima_fila + 1):
                ws[f"{letra}{fila_idx}"].alignment = Alignment(wrap_text=True, vertical="top")

        col_val = get_column_letter(_COLUMNAS_REVISION_XLSX.index("VALIDACION_AUDITOR") + 1)
        dv = DataValidation(type="list", formula1='"CORRECTA,INCORRECTA"', allow_blank=True)
        ws.add_data_validation(dv)
        dv.add(f"{col_val}2:{col_val}{ultima_fila}")

    ruta_tmp = f"{ruta}.tmp"
    wb.save(ruta_tmp)
    os.replace(ruta_tmp, ruta)


def cargar_revision_xlsx(ruta):
    if not ruta or not os.path.isfile(ruta):
        return []
    wb = _abrir_libro(ruta, data_only=True)
    try:
        if _HOJA_REVISION not in wb.sheetnames:
            return []
        ws = wb[_HOJA_REVISION]
        encabezado = [c.value for c in next(ws.iter_rows(min_row=1, max_row=1))]

        filas = []
        for fila_celdas in ws.iter_rows(min_row=2):
            valores = {}
            hay_datos = False
            for idx, celda in enumerate(fila_celdas):
                nombre_col = encabezado[idx] if idx < len(encabezado) else None
                if not nombre_col:
                    continue
                if celda.value not in (None, ""):
                    hay_datos = True
                valores[nombre_col] = celda.value
            if not hay_datos:
                continue
            fila_normalizada = {col: _texto_o_vacio(valores.get(col)) for col in _COLUMNAS_REVISION_XLSX}
            try:
                fila_normalizada["FILA_GLOBAL"] = int(float(fila_normalizada["FILA_GLOBAL"]))
            except (TypeError, ValueError):
                continue  # fila sin FILA_GLOBAL utilizable: se ignora, nunca se adivina.
            filas.append(fila_normalizada)
        return filas
    finally:
        wb.close()


def cargar_decisiones_csv_legado(ruta_csv, sha256_global):
    """Compatibilidad hacia atrás: si existe un CSV de revisión del
    esquema anterior (una fila por ASIGNACION, sin FILA_GLOBAL ni
    ASIGNACION_CORRECTA) para el MISMO SHA del GLOBAL actual, devuelve
    {ASIGNACION: {VALIDACION_AUDITOR, OBSERVACION_AUDITOR,
    FECHA_VALIDACION}} para sembrar las decisiones ya tomadas. Nunca se
    vuelve a escribir ese CSV."""
    if not ruta_csv or not os.path.isfile(ruta_csv):
        return {}
    decisiones = {}
    with open(ruta_csv, "r", encoding="utf-8", newline="") as f:
        for fila in csv.DictReader(f):
            if fila.get("SHA256_GLOBAL") != sha256_global:
                continue
            asignacion = fila.get("ASIGNACION")
            if not asignacion:
                continue
            decisiones[asignacion] = {
                "VALIDACION_AUDITOR": fila.get("VALIDACION_AUDITOR", "") or "",
                "OBSERVACION_AUDITOR": fila.get("OBSERVACION_AUDITOR", "") or "",
                "FECHA_VALIDACION": fila.get("FECHA_VALIDACION", "") or "",
            }
    return decisiones


def fusionar_filas_revision(filas_nuevas, filas_existentes_xlsx, decisiones_legado, sha256_global):
    """Preserva VALIDACION_AUDITOR/ASIGNACION_CORRECTA/OBSERVACION_AUDITOR/
    FECHA_VALIDACION ya escritas por el auditor, emparejando por
    FILA_GLOBAL. Una fila existente SOLO se reutiliza si su
    SHA256_GLOBAL coincide con el GLOBAL actual — si el GLOBAL cambió de
    contenido, esa validación previa NUNCA se aplica en silencio. Si no
    hay .xlsx previo, intenta sembrar desde `decisiones_legado` (CSV del
    esquema anterior, emparejando por ASIGNACION_ORIGINAL)."""
    reutilizables = {}
    for f in filas_existentes_xlsx:
        if f.get("SHA256_GLOBAL") != sha256_global:
            continue
        reutilizables[f["FILA_GLOBAL"]] = f

    fusionadas = []
    for nueva in filas_nuevas:
        fila = dict(nueva)
        previa = reutilizables.get(nueva["FILA_GLOBAL"])
        if previa:
            fila["VALIDACION_AUDITOR"] = previa.get("VALIDACION_AUDITOR", "")
            fila["ASIGNACION_CORRECTA"] = previa.get("ASIGNACION_CORRECTA", "")
            fila["OBSERVACION_AUDITOR"] = previa.get("OBSERVACION_AUDITOR", "")
            fila["FECHA_VALIDACION"] = previa.get("FECHA_VALIDACION", "")
        elif not filas_existentes_xlsx and decisiones_legado:
            legado = decisiones_legado.get(nueva["ASIGNACION_ORIGINAL"])
            if legado:
                fila["VALIDACION_AUDITOR"] = legado.get("VALIDACION_AUDITOR", "")
                fila["OBSERVACION_AUDITOR"] = legado.get("OBSERVACION_AUDITOR", "")
                fila["FECHA_VALIDACION"] = legado.get("FECHA_VALIDACION", "")
        fusionadas.append(fila)
    return fusionadas


def _validacion_normalizada(valor):
    return _texto_o_vacio(valor).strip().upper()


def _fila_resuelta(fila):
    """CORRECTA siempre resuelve. INCORRECTA solo resuelve si
    ASIGNACION_CORRECTA no está vacía y es distinta de ASIGNACION_ORIGINAL
    — si falta, la fila sigue PENDIENTE (nunca se asume una corrección)."""
    v = _validacion_normalizada(fila.get("VALIDACION_AUDITOR"))
    if v == "CORRECTA":
        return True
    if v == "INCORRECTA":
        correcta = _texto_o_vacio(fila.get("ASIGNACION_CORRECTA")).strip()
        original = _texto_o_vacio(fila.get("ASIGNACION_ORIGINAL")).strip()
        return bool(correcta) and correcta != original
    return False


def _asignacion_final_de_fila(fila):
    v = _validacion_normalizada(fila.get("VALIDACION_AUDITOR"))
    if v == "INCORRECTA":
        correcta = _texto_o_vacio(fila.get("ASIGNACION_CORRECTA")).strip()
        if correcta:
            return correcta
    return fila.get("ASIGNACION_ORIGINAL")


def _resoluciones_por_fila(filas):
    resoluciones = {}
    for f in filas:
        resoluciones[f["FILA_GLOBAL"]] = {
            "resuelta": _fila_resuelta(f),
            "validacion": _validacion_normalizada(f.get("VALIDACION_AUDITOR")),
            "final": _asignacion_final_de_fila(f),
            "observacion": _texto_o_vacio(f.get("OBSERVACION_AUDITOR")),
            "fecha_validacion": _texto_o_vacio(f.get("FECHA_VALIDACION")),
        }
    return resoluciones


# ---------------------------------------------------------------------------
# Orquestador
# ---------------------------------------------------------------------------

def ejecutar_control(ruta_global, ruta_historico, nombre_archivo_global=None,
                      dry_run=False, ruta_detalle_json=None, directorio_revision=None):
    if not ruta_global or not os.path.isfile(ruta_global):
        return {"estado": "ERROR_TECNICO", "problemas": ["GLOBAL_NO_ENCONTRADO"],
                "ruta_global": ruta_global}

    nombre_archivo_global = nombre_archivo_global or os.path.basename(ruta_global)
    sha256_actual = _hash_archivo(ruta_global)

    # Nombre canónico OBLIGATORIO, sin fallback: se detiene ANTES de leer
    # historico/partidas y antes de tocar REVISION/HISTORICO/GLOBAL.
    periodo = _derivar_periodo(nombre_archivo_global)
    if periodo is None:
        return {
            "estado": "ERROR_TECNICO",
            "problemas": ["GLOBAL_NOMBRE_NO_CANONICO"],
            "archivo_global": nombre_archivo_global,
            "sha256_archivo": sha256_actual,
            "mensaje": (
                f"'{nombre_archivo_global}' no sigue la convención canónica "
                "SAP_GLOBAL_TIQ_<MES>_<AÑO>.xlsx; no se puede derivar el "
                "periodo de forma segura. El control se detiene sin leer "
                "partidas ni tocar REVISION/HISTORICO/GLOBAL."
            ),
        }

    historico = cargar_historico(ruta_historico)

    if ya_procesado(historico, sha256_actual):
        return {
            "estado": "YA_PROCESADO_SIN_CAMBIOS",
            "archivo_global": nombre_archivo_global,
            "sha256_archivo": sha256_actual,
            "mensaje": (
                "Este GLOBAL ya fue incorporado al histórico (mismo SHA-256 "
                "final, incluida una corrección ya aplicada por este mismo "
                "CONTROL 1). No se releyó el GLOBAL ni se volvió a incorporar nada."
            ),
            "filas_historico_totales": len(historico),
            "dry_run": dry_run,
        }

    sha256_historico_existente = _sha_global_modificado(
        historico, nombre_archivo_global, sha256_actual
    )
    if sha256_historico_existente:
        return {
            "estado": "GLOBAL_MODIFICADO_REQUIERE_REVISION",
            "archivo_global": nombre_archivo_global,
            "sha256_archivo": sha256_actual,
            "sha256_historico_existente": sha256_historico_existente,
            "mensaje": (
                "Existe un GLOBAL del mismo periodo/nombre ya incorporado al "
                "histórico, pero el archivo actual tiene un SHA-256 diferente "
                "al registrado como final. Requiere decisión humana antes de "
                "sustituir o incorporar información."
            ),
            "filas_historico_totales": len(historico),
            "dry_run": dry_run,
            "historico_actualizado": False,
            "filas_incorporadas_historico": 0,
        }

    try:
        partidas = leer_partidas_global(ruta_global)
    except HojaNoEncontradaError:
        return {"estado": "ERROR_TECNICO", "problemas": ["GLOBAL_HOJA_1_NO_ENCONTRADA"],
                "archivo_global": nombre_archivo_global, "sha256_archivo": sha256_actual}
    except Exception as exc:  # noqa: BLE001 — GLOBAL ilegible, se reporta y se detiene
        return {"estado": "ERROR_TECNICO", "problemas": [f"GLOBAL_ILEGIBLE:{exc}"],
                "archivo_global": nombre_archivo_global, "sha256_archivo": sha256_actual}

    candidatas_nuevas = []
    excluidas = 0
    sin_asignacion = 0
    for p in partidas:
        if es_excluida(p["asignacion"], p["cuenta_mayor"]):
            excluidas += 1
        elif p["asignacion"] is None:
            sin_asignacion += 1
        else:
            candidatas_nuevas.append(p)

    # JSON de detalle "por par" (compatibilidad con el formato anterior).
    hallazgos = detectar_duplicados(candidatas_nuevas, historico, nombre_archivo_global)
    asignaciones_duplicadas = sorted({h["asignacion"] for h in hallazgos})

    directorio_revision = directorio_revision or os.path.dirname(os.path.abspath(ruta_historico)) or "."
    ruta_xlsx = ruta_revision_xlsx(directorio_revision, periodo)
    ruta_csv_legado = ruta_revision_asignaciones(directorio_revision, periodo)

    filas_pass1 = construir_filas_revision(candidatas_nuevas, historico, periodo, sha256_actual)

    ahora = datetime.datetime.now().isoformat(timespec="seconds")
    filas_incorporadas = 0
    revision_actualizada = False
    correcciones_aplicadas = 0
    global_modificado = False
    sha256_global_original = sha256_actual
    sha256_global_final = sha256_actual
    estado_validacion = None
    ruta_revision_reportada = None
    filas_correctas = filas_incorrectas = filas_pendientes = 0
    alertas_mismo_mes = sum(1 for f in filas_pass1 if f["TIPO_ALERTA"] in (_TIPO_ALERTA_MISMO_MES, _TIPO_ALERTA_AMBAS))
    alertas_contra_historico = sum(1 for f in filas_pass1 if f["TIPO_ALERTA"] in (_TIPO_ALERTA_HISTORICO, _TIPO_ALERTA_AMBAS))

    if not filas_pass1:
        estado = _ESTADO_OK_SIN_DUPLICADOS
        if not dry_run:
            nuevas_filas_historico = [
                _fila_historico(p, _SIN_ALERTA, None, nombre_archivo_global,
                                 sha256_actual, sha256_actual, ahora)
                for p in candidatas_nuevas
            ]
            guardar_historico(ruta_historico, historico + nuevas_filas_historico)
            filas_incorporadas = len(nuevas_filas_historico)
    else:
        estado = _ESTADO_REVISAR_DUPLICADOS
        ruta_revision_reportada = ruta_xlsx

        filas_existentes_xlsx = cargar_revision_xlsx(ruta_xlsx)
        decisiones_legado = (
            {} if filas_existentes_xlsx else cargar_decisiones_csv_legado(ruta_csv_legado, sha256_actual)
        )
        filas_merged = fusionar_filas_revision(
            filas_pass1, filas_existentes_xlsx, decisiones_legado, sha256_actual
        )

        resoluciones = _resoluciones_por_fila(filas_merged)
        filas_pendientes = sum(1 for r in resoluciones.values() if not r["resuelta"])
        filas_correctas = sum(1 for r in resoluciones.values() if r["validacion"] == "CORRECTA")
        filas_incorrectas = sum(
            1 for r in resoluciones.values() if r["validacion"] == "INCORRECTA" and r["resuelta"]
        )

        filas_a_escribir = filas_merged
        cerrar = filas_pendientes == 0

        if cerrar:
            # Reevaluar con las asignaciones FINALES antes de comprometerse
            # a cerrar: una corrección no puede introducir silenciosamente
            # otra duplicidad.
            candidatas_finales = []
            for p in candidatas_nuevas:
                resolucion = resoluciones.get(p["fila_sap"])
                valor_final = resolucion["final"] if resolucion else p["asignacion"]
                if es_excluida(valor_final, p["cuenta_mayor"]):
                    continue
                nueva = dict(p)
                nueva["asignacion"] = valor_final
                candidatas_finales.append(nueva)

            alertas_finales = detectar_ocurrencias_alertadas(candidatas_finales, historico)
            fila_globales_conocidas = set(resoluciones.keys())
            occ_original_por_fila = {p["fila_sap"]: p for p in candidatas_nuevas}

            nuevas_filas_pass2 = []
            for fila_sap, info in alertas_finales.items():
                if fila_sap in fila_globales_conocidas:
                    continue
                occ_original = occ_original_por_fila.get(fila_sap)
                if occ_original is None:
                    continue
                antecedente_txt = _texto_antecedentes(info["antecedentes"])
                if not antecedente_txt:
                    antecedente_txt = (
                        "(alerta generada tras aplicar una corrección: coincide "
                        "con otra ocurrencia corregida en este mismo GLOBAL)"
                    )
                nuevas_filas_pass2.append({
                    "PERIODO": periodo,
                    "FILA_GLOBAL": fila_sap,
                    "ASIGNACION_ORIGINAL": occ_original["asignacion"],
                    "TIPO_ALERTA": info["tipo"],
                    "FECHA_VALOR": occ_original["fecha_valor"] or "",
                    "CUENTA_MAYOR": occ_original["cuenta_mayor"] or "",
                    "GLOSA": occ_original["glosa"] or "",
                    "IMPORTE": occ_original["monto"] or "",
                    "ANTECEDENTE_HISTORICO": antecedente_txt,
                    "VALIDACION_AUDITOR": "",
                    "ASIGNACION_CORRECTA": "",
                    "OBSERVACION_AUDITOR": "",
                    "FECHA_VALIDACION": "",
                    "SHA256_GLOBAL": sha256_actual,
                })

            if nuevas_filas_pass2:
                cerrar = False
                filas_a_escribir = filas_merged + nuevas_filas_pass2
                filas_pendientes += len(nuevas_filas_pass2)

        if cerrar:
            correcciones = []
            for f in filas_merged:
                r = resoluciones[f["FILA_GLOBAL"]]
                if r["validacion"] == "INCORRECTA":
                    correcciones.append((f["FILA_GLOBAL"], f["ASIGNACION_ORIGINAL"], r["final"]))

            if not dry_run:
                if correcciones:
                    aplicar_correcciones_global(ruta_global, correcciones)
                    sha256_global_final = _hash_archivo(ruta_global)
                    global_modificado = True
                correcciones_aplicadas = len(correcciones)

                for f in filas_a_escribir:
                    if not _texto_o_vacio(f.get("FECHA_VALIDACION")).strip():
                        f["FECHA_VALIDACION"] = ahora

                filas_por_global = {f["FILA_GLOBAL"]: f for f in filas_a_escribir}
                nuevas_filas_historico = []
                for p in candidatas_nuevas:
                    r = resoluciones.get(p["fila_sap"])
                    fila_rev = filas_por_global.get(p["fila_sap"])
                    if r and fila_rev:
                        nuevas_filas_historico.append(_fila_historico(
                            p, fila_rev["TIPO_ALERTA"], r, nombre_archivo_global,
                            sha256_global_original, sha256_global_final, ahora,
                            fecha_validacion=fila_rev["FECHA_VALIDACION"],
                            observacion=fila_rev["OBSERVACION_AUDITOR"],
                        ))
                    else:
                        nuevas_filas_historico.append(_fila_historico(
                            p, _SIN_ALERTA, None, nombre_archivo_global,
                            sha256_global_original, sha256_global_final, ahora,
                        ))
                guardar_historico(ruta_historico, historico + nuevas_filas_historico)
                filas_incorporadas = len(nuevas_filas_historico)

                guardar_revision_xlsx(ruta_xlsx, filas_a_escribir)
                revision_actualizada = True

            estado_validacion = _ESTADO_CERRADO_CON_VALIDACION
        else:
            estado_validacion = _ESTADO_PENDIENTE_VALIDACION
            if not dry_run:
                guardar_revision_xlsx(ruta_xlsx, filas_a_escribir)
                revision_actualizada = True

    puede_incorporar = (
        estado == _ESTADO_OK_SIN_DUPLICADOS or estado_validacion == _ESTADO_CERRADO_CON_VALIDACION
    )
    historico_actualizado = (not dry_run) and puede_incorporar

    resumen = {
        "estado": estado,
        "estado_validacion": estado_validacion,
        "archivo_global": nombre_archivo_global,
        "sha256_archivo": sha256_actual,
        "sha256_global_original": sha256_global_original,
        "sha256_global_final": sha256_global_final,
        "global_modificado": global_modificado,
        "correcciones_aplicadas": correcciones_aplicadas,
        "periodo": periodo,
        "fecha_ejecucion": ahora,
        "filas_leidas_global": len(partidas),
        "asignaciones_evaluadas": len(candidatas_nuevas),
        "asignaciones_excluidas": excluidas,
        "partidas_sin_asignacion": sin_asignacion,
        "asignaciones_duplicadas": asignaciones_duplicadas,
        "cantidad_hallazgos": len(hallazgos),
        "alertas_mismo_mes": alertas_mismo_mes,
        "alertas_contra_historico": alertas_contra_historico,
        "filas_revisadas": len(filas_pass1),
        "filas_correctas": filas_correctas,
        "filas_incorrectas": filas_incorrectas,
        "filas_pendientes": filas_pendientes,
        # Alias retrocompatibles (misma información, nombre de la etapa anterior).
        "alertas_pendientes_validacion": filas_pendientes,
        "alertas_correctas": filas_correctas,
        "alertas_incorrectas": filas_incorrectas,
        "dry_run": dry_run,
        "historico_actualizado": historico_actualizado,
        "filas_incorporadas_historico": filas_incorporadas,
        "ruta_revision": ruta_revision_reportada,
        "revision_actualizada": revision_actualizada,
        "detalle_json": None,
    }

    if ruta_detalle_json:
        directorio = os.path.dirname(os.path.abspath(ruta_detalle_json))
        if directorio:
            os.makedirs(directorio, exist_ok=True)
        detalle = {**resumen, "hallazgos": hallazgos}
        with open(ruta_detalle_json, "w", encoding="utf-8") as f:
            json.dump(detalle, f, ensure_ascii=False, indent=2)
        resumen["detalle_json"] = ruta_detalle_json

    return resumen


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--global", dest="ruta_global", required=True,
                         help="Ruta local al SAP GLOBAL (.xlsx) ya generado.")
    parser.add_argument("--historico", dest="ruta_historico", required=True,
                         help="Ruta local a HISTORICO_ASIGNACIONES.csv (se crea si no existe).")
    parser.add_argument("--nombre-archivo", dest="nombre_archivo_global", default=None,
                         help="Nombre a registrar como archivo_global (por defecto, basename de --global). "
                              "Debe seguir SAP_GLOBAL_TIQ_<MES>_<AÑO>.xlsx.")
    parser.add_argument("--salida-json", dest="ruta_detalle_json", default=None,
                         help="Ruta donde escribir el detalle técnico completo (JSON).")
    parser.add_argument("--revision-dir", dest="directorio_revision", default=None,
                         help="Directorio donde leer/escribir REVISION_ASIGNACIONES_<PERIODO>.xlsx "
                              "(por defecto, el mismo directorio de --historico).")
    parser.add_argument("--dry-run", action="store_true",
                         help="No incorpora nada al histórico, no corrige el GLOBAL ni escribe REVISION; solo reporta.")
    return parser.parse_args(argv)


def main(argv=None):
    args = _parse_args(argv)
    resumen = ejecutar_control(
        ruta_global=args.ruta_global,
        ruta_historico=args.ruta_historico,
        nombre_archivo_global=args.nombre_archivo_global,
        dry_run=args.dry_run,
        ruta_detalle_json=args.ruta_detalle_json,
        directorio_revision=args.directorio_revision,
    )
    print(json.dumps(resumen, ensure_ascii=False))
    return 0 if resumen.get("estado") != "ERROR_TECNICO" else 1


if __name__ == "__main__":
    raise SystemExit(main())
