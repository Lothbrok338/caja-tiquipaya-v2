"""
control_asignaciones.py — CONTROL 1: auditoría de asignaciones (ZUONR)
duplicadas/históricas del SAP GLOBAL mensual de Caja Tiquipaya, con etapa
de validación humana antes de cerrar el mes.

Este módulo es de solo lectura sobre el GLOBAL que audita y es puramente
aditivo sobre su propia memoria histórica: nunca modifica el GLOBAL, nunca
reinterpreta contabilidad, nunca decide por sí mismo que un duplicado es
correcto o incorrecto, y nunca vuelve a abrir un SAP GLOBAL de un mes
anterior. Solo compara la asignación (ZUONR) de cada partida del GLOBAL
que se le pasa contra un histórico compacto en CSV que él mismo mantiene.

Layout del GLOBAL (idéntico al de sap_writer.py / consolidador_mensual.py,
nunca reinterpretado aquí — hoja EXACTA "1", partidas desde la fila 16):

    C = CuentaMayor   D = TextoPosicion (glosa)   E = Cargo   F = Haber
    O = FechaValor    R = Asignacion (ZUONR)

La hoja "1" es OBLIGATORIA: si el GLOBAL no la trae, el control se detiene
con ERROR_TECNICO (GLOBAL_HOJA_1_NO_ENCONTRADA). Nunca hace fallback a
wb.sheetnames[0] ni a ninguna otra hoja.

NOMBRE CANÓNICO DEL GLOBAL (OBLIGATORIO, sin fallback):

    SAP_GLOBAL_TIQ_<MES>_<AÑO>.xlsx

Si `archivo_global` (basename de --global, o --nombre-archivo si se
pasa explícito) no calza con esa convención, el control se detiene con
ERROR_TECNICO (GLOBAL_NOMBRE_NO_CANONICO) ANTES de leer partidas o de
tocar REVISION/HISTORICO. Nunca se infiere ni se inventa un periodo a
partir de otra cosa (p. ej. el nombre de archivo sin extensión).

EXCLUSIONES (nunca se marcan como duplicado aunque se repitan una y otra
vez dentro del mismo GLOBAL o contra el histórico) — SIN CAMBIOS:

    - "SFC101"
    - "SFC102"
    - "TIQUIPAYA <MES>" para cualquiera de las 12 abreviaturas oficiales
      usadas por motor_tiquipaya._asignacion_comision() (ENE..DIC)
    - CuentaMayor == "110201008" (comisión ATC), sin importar el texto de
      Asignacion (ZUONR) de esa partida.

Cualquier otra asignación —incluida "FORTALEZA", aunque se repita por una
razón legítima conocida— SIEMPRE se evalúa. La coincidencia de la
asignación por sí sola es suficiente para generar una alerta: una
validación humana anterior (CORRECTA o INCORRECTA) NUNCA evita que la
misma asignación vuelva a alertar en un periodo posterior.

ESTADOS (`estado` mantiene la semántica previa a la validación humana,
para no romper consumidores existentes como auditor-caja-tiquipaya):

    - OK_SIN_DUPLICADOS — no hay alertas.
    - REVISAR_DUPLICADOS_ENCONTRADOS — hay una o más alertas (mismo
      GLOBAL y/o contra histórico), HAYAN SIDO YA VALIDADAS POR EL
      AUDITOR O NO. Este campo por sí solo NO dice si el mes ya puede
      cerrarse — para eso está `estado_validacion`.
    - YA_PROCESADO_SIN_CAMBIOS / GLOBAL_MODIFICADO_REQUIERE_REVISION /
      ERROR_TECNICO — sin cambios (ver idempotencia más abajo).

    `estado_validacion` (nuevo, solo presente cuando `estado ==
    REVISAR_DUPLICADOS_ENCONTRADOS`; None en cualquier otro caso):

    - PENDIENTE_VALIDACION_AUDITOR — queda al menos una alerta sin
      VALIDACION_AUDITOR completa; el histórico NO se modifica.
    - CERRADO_CON_VALIDACION_AUDITOR — TODAS las alertas de este periodo
      están validadas (CORRECTA o INCORRECTA); se incorporan al
      histórico las ocurrencias evaluadas del GLOBAL actual, junto con
      esa validación/observación.

VALIDACIÓN HUMANA:

    Cuando se detectan asignaciones con alerta se crea/actualiza:

        REVISION_ASIGNACIONES_<PERIODO>.csv

    con UNA FILA POR ASIGNACION observada (nunca una fila por cada
    combinación/par). El auditor completa manualmente VALIDACION_AUDITOR
    ("CORRECTA"/"INCORRECTA") y, opcionalmente, OBSERVACION_AUDITOR. Este
    módulo nunca decide automáticamente esos valores.

    Las validaciones humanas ya escritas en el archivo REVISION nunca se
    pisan al regenerarlo: solo se reutilizan si corresponden al MISMO
    SHA-256 del GLOBAL actual (columna SHA256_GLOBAL) — si el GLOBAL
    cambió de contenido, una revisión previa nunca se aplica en
    silencio; la alerta vuelve a nacer sin validar.

MEMORIA HISTÓRICA (HISTORICO_ASIGNACIONES.csv):

    Una fila por cada ocurrencia NO EXCLUIDA de una asignación, en
    cualquier GLOBAL ya incorporado (incorporación siempre incremental,
    nunca se reescriben filas existentes ni se reabre un GLOBAL anterior).
    Esquema extendido de forma compatible con archivos históricos ya
    existentes (columnas nuevas al final; un CSV con el esquema anterior
    se sigue leyendo sin perder ninguna fila, y al reescribirse las
    columnas nuevas quedan vacías para esas filas viejas):

        asignacion, fecha_valor, cuenta_mayor, glosa, monto,
        archivo_global, fila_sap, sha256_archivo, fecha_incorporacion,
        alerta_duplicado, validacion_auditor, observacion_auditor,
        fecha_validacion

    Para una fila que no tuvo alerta, `alerta_duplicado` queda como
    "SIN_ALERTA" y los tres campos de validación quedan vacíos.

IDEMPOTENCIA (sin cambios respecto de la versión anterior):

    CASO A — mismo SHA-256 ya existe en el histórico: YA_PROCESADO_SIN_CAMBIOS,
    no se relee el GLOBAL ni se toca nada.

    CASO B — mismo archivo_global (mismo nombre/periodo mensual) ya
    incorporado al histórico, pero con SHA-256 distinto:
    GLOBAL_MODIFICADO_REQUIERE_REVISION, requiere decisión humana antes
    de sustituir o incorporar información.

TRANSPORTE:

    Este módulo solo opera sobre rutas de archivo locales ya
    materializadas. Nunca recibe ni produce contenido Base64 ni depende
    de Google Drive: esa responsabilidad es de quien invoca este script
    (Cowork/auditor-caja-tiquipaya), nunca de este módulo.

Uso:
    python control_asignaciones.py \
        --global /ruta/SAP_GLOBAL_TIQ_AGOSTO_2026.xlsx \
        --historico /ruta/HISTORICO_ASIGNACIONES.csv \
        --salida-json /ruta/CONTROL_ASIGNACIONES_AGOSTO_2026.json

    Modo seguro (no incorpora nada al histórico ni escribe REVISION,
    solo reporta qué encontraría):
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

# ---------------------------------------------------------------------------
# Constantes de layout (ver sap_writer.py / consolidador_mensual.py — nunca
# se reinterpreta el motor aquí, solo se lee lo ya escrito por ETAPA 6/
# consolidador_mensual.py).
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

# Cuenta de comisión ATC: se excluye POR CUENTA, independientemente del
# texto de Asignacion (ZUONR) de esa partida.
_CUENTA_COMISION_ATC = "110201008"

_ESTADO_REVISAR = "REVISAR"

# Estados de `estado` (semántica previa a la validación humana, se
# mantiene por compatibilidad).
_ESTADO_OK_SIN_DUPLICADOS = "OK_SIN_DUPLICADOS"
_ESTADO_REVISAR_DUPLICADOS = "REVISAR_DUPLICADOS_ENCONTRADOS"

# Estados de `estado_validacion` (nuevo, solo relevante cuando `estado ==
# REVISAR_DUPLICADOS_ENCONTRADOS`).
_ESTADO_PENDIENTE_VALIDACION = "PENDIENTE_VALIDACION_AUDITOR"
_ESTADO_CERRADO_CON_VALIDACION = "CERRADO_CON_VALIDACION_AUDITOR"

_COLUMNAS_HISTORICO = [
    "asignacion", "fecha_valor", "cuenta_mayor", "glosa", "monto",
    "archivo_global", "fila_sap", "sha256_archivo", "fecha_incorporacion",
    # Extensión (etapa de validación humana) — al final, para que un CSV
    # con el esquema anterior se siga leyendo sin perder información.
    "alerta_duplicado", "validacion_auditor", "observacion_auditor",
    "fecha_validacion",
]

_SIN_ALERTA = "SIN_ALERTA"

# Archivo de revisión: una fila por ASIGNACION observada (no por par).
_COLUMNAS_REVISION = [
    "PERIODO", "ASIGNACION", "TIPO_ALERTA", "DETALLE",
    "VALIDACION_AUDITOR", "OBSERVACION_AUDITOR", "FECHA_VALIDACION",
    # Guardarraíl: nunca reutilizar en silencio una validación escrita
    # para un GLOBAL distinto (ver fusionar_revision).
    "SHA256_GLOBAL",
]

_VALIDACIONES_VALIDAS = {"CORRECTA", "INCORRECTA"}

_TIPO_ALERTA_MISMO_MES = "DUPLICADA_MISMO_MES"
_TIPO_ALERTA_HISTORICO = "DUPLICADA_CON_HISTORICO"
_TIPO_ALERTA_AMBAS = "AMBAS"

# Convención canónica OBLIGATORIA del nombre del GLOBAL mensual. Sin esto
# no se puede derivar el periodo, y sin periodo el control se detiene
# (ver _derivar_periodo / GLOBAL_NOMBRE_NO_CANONICO).
_RE_NOMBRE_GLOBAL = re.compile(r"^SAP_GLOBAL_TIQ_([A-Za-z]+)_(\d{4})\.xlsx$", re.IGNORECASE)


class HojaNoEncontradaError(RuntimeError):
    """La hoja EXACTA "1" no existe en el GLOBAL. Nunca se hace fallback
    a otra hoja (ver ejecutar_control)."""


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
    —incluido "FORTALEZA"— NUNCA se excluye, aunque se repita por una
    razón legítima conocida. SIN CAMBIOS respecto de la versión anterior."""
    if asignacion in _ASIGNACIONES_EXCLUIDAS:
        return True
    return _normalizar_cuenta(cuenta_mayor) == _CUENTA_COMISION_ATC


# ---------------------------------------------------------------------------
# Lectura del GLOBAL (solo lectura, nunca se guarda nada sobre él)
# ---------------------------------------------------------------------------

def leer_partidas_global(ruta_global):
    """Lee las partidas del SAP GLOBAL desde la fila 16 de la hoja EXACTA
    "1" (mismo layout que sap_writer.py). Si esa hoja no existe, lanza
    HojaNoEncontradaError — nunca hace fallback a wb.sheetnames[0] ni
    adivina otra hoja. Se detiene en la primera fila donde tanto
    CuentaMayor (C) como Asignacion (R) están vacías.

    Devuelve una lista de dicts con: fila_sap, asignacion, fecha_valor,
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


# ---------------------------------------------------------------------------
# Histórico (05_CONTROLES/HISTORICO_ASIGNACIONES.csv o donde se indique)
# ---------------------------------------------------------------------------

def cargar_historico(ruta_historico):
    if not ruta_historico or not os.path.isfile(ruta_historico):
        return []
    with open(ruta_historico, "r", encoding="utf-8", newline="") as f:
        return [dict(fila) for fila in csv.DictReader(f)]


def guardar_historico(ruta_historico, filas):
    """Reescritura atómica (archivo temporal + reemplazo) del CSV
    completo, con el esquema EXTENDIDO (_COLUMNAS_HISTORICO). Una fila
    cargada desde un CSV con el esquema anterior (sin las columnas de
    validación humana) simplemente no trae esas claves: `fila.get(col,
    "")` las deja vacías al reescribir, sin perder ningún dato original."""
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
    return any(fila.get("sha256_archivo") == sha256_archivo for fila in historico)


def _sha_global_modificado(historico, nombre_archivo_global, sha256_archivo):
    """Busca en el histórico una fila del MISMO archivo_global (mismo
    nombre/periodo mensual) con un sha256_archivo DISTINTO al actual.
    Devuelve ese sha256 existente, o None si no hay conflicto."""
    for fila in historico:
        if fila.get("archivo_global") != nombre_archivo_global:
            continue
        sha_existente = fila.get("sha256_archivo")
        if sha_existente and sha_existente != sha256_archivo:
            return sha_existente
    return None


# ---------------------------------------------------------------------------
# Detección de duplicados — formato histórico "por par" (compatibilidad)
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
    """candidatas_nuevas: partidas NO excluidas del GLOBAL que se está
    auditando ahora. historico: filas ya incorporadas de GLOBAL
    anteriores. Devuelve la lista de hallazgos "por par" (uno por
    ocurrencia-nueva/ocurrencia-relacionada) — se conserva por
    compatibilidad en el JSON de detalle; la etapa de validación humana
    usa construir_alertas_asignaciones() (una fila por asignación)."""
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
# Periodo (para nombrar REVISION_ASIGNACIONES_<PERIODO>.csv). OBLIGATORIO
# a partir del nombre canónico del GLOBAL — SIN fallback.
# ---------------------------------------------------------------------------

def _derivar_periodo(nombre_archivo_global):
    """Convención canónica OBLIGATORIA: SAP_GLOBAL_TIQ_<MES>_<AÑO>.xlsx.
    Devuelve "<MES>_<AÑO>" en mayúsculas, o None si el nombre no calza
    con esa convención. SIN fallback: un nombre no canónico detiene el
    control (ver GLOBAL_NOMBRE_NO_CANONICO en ejecutar_control) — nunca
    se infiere ni se inventa un periodo a partir de otra cosa."""
    if not nombre_archivo_global:
        return None
    m = _RE_NOMBRE_GLOBAL.match(nombre_archivo_global)
    if not m:
        return None
    mes, anio = m.groups()
    return f"{mes.upper()}_{anio}"


def _periodo_para_mostrar(nombre_archivo_global):
    """Variante NO estricta, usada ÚNICAMENTE para mostrar contexto
    legible de un antecedente histórico (una fila de HISTORICO puede
    referenciar un archivo_global grabado antes de exigir el nombre
    canónico). Nunca se usa para decidir el periodo/nombre de REVISION
    del GLOBAL que se está auditando ahora — eso siempre exige
    _derivar_periodo(), sin excepción."""
    periodo = _derivar_periodo(nombre_archivo_global)
    if periodo:
        return periodo
    if not nombre_archivo_global:
        return "PERIODO_DESCONOCIDO"
    return os.path.splitext(nombre_archivo_global)[0]


def ruta_revision_asignaciones(directorio, periodo):
    return os.path.join(directorio, f"REVISION_ASIGNACIONES_{periodo}.csv")


# ---------------------------------------------------------------------------
# Alertas por asignación (una fila por ASIGNACION, nunca por combinación)
# ---------------------------------------------------------------------------

def _resumen_ocurrencia_actual(p):
    return (
        f"fila {p['fila_sap']} ({p['fecha_valor'] or 's/f'}, "
        f"cuenta {p['cuenta_mayor'] or 's/c'}, \"{p['glosa'] or ''}\", "
        f"monto {p['monto'] or '0.00'})"
    )


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


def construir_alertas_asignaciones(candidatas_nuevas, historico, nombre_archivo_global,
                                    periodo, sha256_global):
    """Devuelve una lista con UNA FILA POR ASIGNACION observada (nunca
    una fila por cada par/combinación) para toda asignacion que:
    (a) aparezca más de una vez dentro de candidatas_nuevas, y/o
    (b) ya exista en `historico` (sin importar si esa aparición anterior
    fue validada como CORRECTA: la coincidencia de la asignación por sí
    sola es suficiente para alertar de nuevo)."""
    idx_nuevas = {}
    for p in candidatas_nuevas:
        idx_nuevas.setdefault(p["asignacion"], []).append(p)

    idx_historico = {}
    for fila in historico:
        idx_historico.setdefault(fila.get("asignacion"), []).append(fila)

    alertas = []
    for asignacion, ocurrencias in idx_nuevas.items():
        antecedentes = idx_historico.get(asignacion, [])
        mismo_mes = len(ocurrencias) > 1
        con_historico = bool(antecedentes)
        if not mismo_mes and not con_historico:
            continue

        if mismo_mes and con_historico:
            tipo_alerta = _TIPO_ALERTA_AMBAS
        elif mismo_mes:
            tipo_alerta = _TIPO_ALERTA_MISMO_MES
        else:
            tipo_alerta = _TIPO_ALERTA_HISTORICO

        partes = [
            "GLOBAL actual (" + nombre_archivo_global + "): "
            + "; ".join(_resumen_ocurrencia_actual(p) for p in ocurrencias)
        ]
        if antecedentes:
            partes.append(
                "Antecedente(s) histórico: "
                + " | ".join(_resumen_antecedente_historico(a) for a in antecedentes)
            )

        alertas.append({
            "PERIODO": periodo,
            "ASIGNACION": asignacion,
            "TIPO_ALERTA": tipo_alerta,
            "DETALLE": " || ".join(partes),
            "VALIDACION_AUDITOR": "",
            "OBSERVACION_AUDITOR": "",
            "FECHA_VALIDACION": "",
            "SHA256_GLOBAL": sha256_global,
        })

    return alertas


# ---------------------------------------------------------------------------
# Archivo REVISION_ASIGNACIONES_<PERIODO>.csv
# ---------------------------------------------------------------------------

def cargar_revision(ruta_revision):
    if not ruta_revision or not os.path.isfile(ruta_revision):
        return []
    with open(ruta_revision, "r", encoding="utf-8", newline="") as f:
        return [dict(fila) for fila in csv.DictReader(f)]


def guardar_revision(ruta_revision, filas):
    directorio = os.path.dirname(os.path.abspath(ruta_revision))
    if directorio:
        os.makedirs(directorio, exist_ok=True)
    ruta_tmp = f"{ruta_revision}.tmp"
    with open(ruta_tmp, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=_COLUMNAS_REVISION)
        writer.writeheader()
        for fila in filas:
            writer.writerow({col: fila.get(col, "") for col in _COLUMNAS_REVISION})
    os.replace(ruta_tmp, ruta_revision)


def fusionar_revision(alertas_nuevas, filas_existentes, sha256_global):
    """Preserva VALIDACION_AUDITOR/OBSERVACION_AUDITOR/FECHA_VALIDACION ya
    escritas por el auditor, emparejando por ASIGNACION. Una fila
    existente SOLO se reutiliza si su SHA256_GLOBAL coincide con el
    GLOBAL actual: si el GLOBAL cambió de contenido, esa validación
    previa queda obsoleta y NUNCA se aplica en silencio — la alerta
    nace de nuevo sin validar."""
    reutilizables = {
        fila.get("ASIGNACION"): fila
        for fila in filas_existentes
        if fila.get("SHA256_GLOBAL") == sha256_global
    }

    fusionadas = []
    for alerta in alertas_nuevas:
        previa = reutilizables.get(alerta["ASIGNACION"])
        fila = dict(alerta)
        if previa:
            fila["VALIDACION_AUDITOR"] = previa.get("VALIDACION_AUDITOR", "")
            fila["OBSERVACION_AUDITOR"] = previa.get("OBSERVACION_AUDITOR", "")
            fila["FECHA_VALIDACION"] = previa.get("FECHA_VALIDACION", "")
        fusionadas.append(fila)
    return fusionadas


def _validacion_normalizada(valor):
    return (valor or "").strip().upper()


def _todas_validadas(filas_revision):
    return all(
        _validacion_normalizada(fila.get("VALIDACION_AUDITOR")) in _VALIDACIONES_VALIDAS
        for fila in filas_revision
    )


# ---------------------------------------------------------------------------
# Orquestador
# ---------------------------------------------------------------------------

def ejecutar_control(ruta_global, ruta_historico, nombre_archivo_global=None,
                      dry_run=False, ruta_detalle_json=None, directorio_revision=None):
    if not ruta_global or not os.path.isfile(ruta_global):
        return {"estado": "ERROR_TECNICO", "problemas": ["GLOBAL_NO_ENCONTRADO"],
                "ruta_global": ruta_global}

    nombre_archivo_global = nombre_archivo_global or os.path.basename(ruta_global)
    sha256_global = _hash_archivo(ruta_global)

    # Nombre canónico OBLIGATORIO, sin fallback: se detiene ANTES de leer
    # historico/partidas y antes de tocar REVISION/HISTORICO.
    periodo = _derivar_periodo(nombre_archivo_global)
    if periodo is None:
        return {
            "estado": "ERROR_TECNICO",
            "problemas": ["GLOBAL_NOMBRE_NO_CANONICO"],
            "archivo_global": nombre_archivo_global,
            "sha256_archivo": sha256_global,
            "mensaje": (
                f"'{nombre_archivo_global}' no sigue la convención canónica "
                "SAP_GLOBAL_TIQ_<MES>_<AÑO>.xlsx; no se puede derivar el "
                "periodo de forma segura. El control se detiene sin leer "
                "partidas ni tocar REVISION/HISTORICO."
            ),
        }

    historico = cargar_historico(ruta_historico)

    if ya_procesado(historico, sha256_global):
        return {
            "estado": "YA_PROCESADO_SIN_CAMBIOS",
            "archivo_global": nombre_archivo_global,
            "sha256_archivo": sha256_global,
            "mensaje": (
                "Este GLOBAL ya fue incorporado al histórico (mismo SHA-256). "
                "No se releyó el GLOBAL ni se volvió a incorporar nada."
            ),
            "filas_historico_totales": len(historico),
            "dry_run": dry_run,
        }

    sha256_historico_existente = _sha_global_modificado(
        historico, nombre_archivo_global, sha256_global
    )
    if sha256_historico_existente:
        return {
            "estado": "GLOBAL_MODIFICADO_REQUIERE_REVISION",
            "archivo_global": nombre_archivo_global,
            "sha256_archivo": sha256_global,
            "sha256_historico_existente": sha256_historico_existente,
            "mensaje": (
                "Existe un GLOBAL del mismo periodo/nombre ya incorporado al "
                "histórico, pero el archivo actual tiene un SHA-256 diferente. "
                "Requiere decisión humana antes de sustituir o incorporar "
                "información."
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
                "archivo_global": nombre_archivo_global, "sha256_archivo": sha256_global}
    except Exception as exc:  # noqa: BLE001 — GLOBAL ilegible, se reporta y se detiene
        return {"estado": "ERROR_TECNICO", "problemas": [f"GLOBAL_ILEGIBLE:{exc}"],
                "archivo_global": nombre_archivo_global, "sha256_archivo": sha256_global}

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
    ruta_revision = ruta_revision_asignaciones(directorio_revision, periodo)

    alertas_nuevas = construir_alertas_asignaciones(
        candidatas_nuevas, historico, nombre_archivo_global, periodo, sha256_global
    )

    ahora = datetime.datetime.now().isoformat(timespec="seconds")
    filas_incorporadas = 0
    revision_actualizada = False
    alertas_pendientes = alertas_correctas = alertas_incorrectas = 0
    alertas_mismo_mes = alertas_contra_historico = 0
    decisiones_por_asignacion = {}
    estado_validacion = None

    if not alertas_nuevas:
        estado = _ESTADO_OK_SIN_DUPLICADOS
    else:
        # `estado` conserva la semántica previa a la validación humana:
        # "hay alertas" es independiente de si ya se validaron o no.
        estado = _ESTADO_REVISAR_DUPLICADOS

        for alerta in alertas_nuevas:
            if alerta["TIPO_ALERTA"] in (_TIPO_ALERTA_MISMO_MES, _TIPO_ALERTA_AMBAS):
                alertas_mismo_mes += 1
            if alerta["TIPO_ALERTA"] in (_TIPO_ALERTA_HISTORICO, _TIPO_ALERTA_AMBAS):
                alertas_contra_historico += 1

        filas_revision_existentes = cargar_revision(ruta_revision)
        filas_revision = fusionar_revision(alertas_nuevas, filas_revision_existentes, sha256_global)

        for fila in filas_revision:
            estado_fila = _validacion_normalizada(fila.get("VALIDACION_AUDITOR"))
            if estado_fila == "CORRECTA":
                alertas_correctas += 1
            elif estado_fila == "INCORRECTA":
                alertas_incorrectas += 1
            else:
                alertas_pendientes += 1

        if not dry_run:
            guardar_revision(ruta_revision, filas_revision)
            revision_actualizada = True

        if alertas_pendientes > 0:
            estado_validacion = _ESTADO_PENDIENTE_VALIDACION
        else:
            estado_validacion = _ESTADO_CERRADO_CON_VALIDACION
            decisiones_por_asignacion = {
                fila["ASIGNACION"]: {
                    "alerta_duplicado": fila["TIPO_ALERTA"],
                    "validacion_auditor": fila.get("VALIDACION_AUDITOR", ""),
                    "observacion_auditor": fila.get("OBSERVACION_AUDITOR", ""),
                    "fecha_validacion": fila.get("FECHA_VALIDACION", ""),
                }
                for fila in filas_revision
            }

    puede_incorporar_historico = (
        estado == _ESTADO_OK_SIN_DUPLICADOS or estado_validacion == _ESTADO_CERRADO_CON_VALIDACION
    )

    if not dry_run and puede_incorporar_historico:
        nuevas_filas_historico = []
        for p in candidatas_nuevas:
            decision = decisiones_por_asignacion.get(p["asignacion"])
            nuevas_filas_historico.append({
                "asignacion": p["asignacion"],
                "fecha_valor": p["fecha_valor"] or "",
                "cuenta_mayor": p["cuenta_mayor"] or "",
                "glosa": p["glosa"] or "",
                "monto": p["monto"] or "",
                "archivo_global": nombre_archivo_global,
                "fila_sap": p["fila_sap"],
                "sha256_archivo": sha256_global,
                "fecha_incorporacion": ahora,
                "alerta_duplicado": decision["alerta_duplicado"] if decision else _SIN_ALERTA,
                "validacion_auditor": decision["validacion_auditor"] if decision else "",
                "observacion_auditor": decision["observacion_auditor"] if decision else "",
                "fecha_validacion": decision["fecha_validacion"] if decision else "",
            })
        guardar_historico(ruta_historico, historico + nuevas_filas_historico)
        filas_incorporadas = len(nuevas_filas_historico)

    historico_actualizado = (not dry_run) and puede_incorporar_historico

    resumen = {
        "estado": estado,
        "estado_validacion": estado_validacion,
        "archivo_global": nombre_archivo_global,
        "sha256_archivo": sha256_global,
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
        "alertas_pendientes_validacion": alertas_pendientes,
        "alertas_correctas": alertas_correctas,
        "alertas_incorrectas": alertas_incorrectas,
        "dry_run": dry_run,
        "historico_actualizado": historico_actualizado,
        "filas_incorporadas_historico": filas_incorporadas,
        "ruta_revision": ruta_revision if alertas_nuevas else None,
        "revision_actualizada": revision_actualizada,
        "detalle_json": None,
    }

    if ruta_detalle_json:
        directorio = os.path.dirname(os.path.abspath(ruta_detalle_json))
        if directorio:
            os.makedirs(directorio, exist_ok=True)
        detalle = {**resumen, "hallazgos": hallazgos, "alertas": alertas_nuevas}
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
                         help="Directorio donde leer/escribir REVISION_ASIGNACIONES_<PERIODO>.csv "
                              "(por defecto, el mismo directorio de --historico).")
    parser.add_argument("--dry-run", action="store_true",
                         help="No incorpora nada al histórico ni escribe REVISION; solo reporta.")
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
