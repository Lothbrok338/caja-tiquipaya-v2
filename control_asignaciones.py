"""
control_asignaciones.py — CONTROL 1: auditoría de asignaciones (ZUONR)
duplicadas/históricas del SAP GLOBAL mensual de Caja Tiquipaya.

Este módulo es de solo lectura sobre el GLOBAL que audita y es puramente
aditivo sobre su propia memoria histórica: nunca modifica el GLOBAL, nunca
reinterpreta contabilidad, nunca decide que un duplicado es un error, y
nunca vuelve a abrir un SAP GLOBAL de un mes anterior. Solo compara la
asignación (ZUONR) de cada partida del GLOBAL que se le pasa contra un
histórico compacto en CSV que él mismo mantiene.

Layout del GLOBAL (idéntico al de sap_writer.py / consolidador_mensual.py,
nunca reinterpretado aquí — hoja EXACTA "1", partidas desde la fila 16):

    C = CuentaMayor   D = TextoPosicion (glosa)   E = Cargo   F = Haber
    O = FechaValor    R = Asignacion (ZUONR)

La hoja "1" es OBLIGATORIA: si el GLOBAL no la trae, el control se detiene
con ERROR_TECNICO (GLOBAL_HOJA_1_NO_ENCONTRADA). Nunca hace fallback a
wb.sheetnames[0] ni a ninguna otra hoja.

EXCLUSIONES (nunca se marcan como duplicado aunque se repitan una y otra
vez dentro del mismo GLOBAL o contra el histórico):

    - "SFC101"
    - "SFC102"
    - "TIQUIPAYA <MES>" para cualquiera de las 12 abreviaturas oficiales
      usadas por motor_tiquipaya._asignacion_comision() (ENE..DIC)
    - CuentaMayor == "110201008" (comisión ATC), sin importar el texto de
      Asignacion (ZUONR) de esa partida — la comisión ATC puede llevar
      "REVISAR" u otro valor y sigue siendo una comisión.

Cualquier otra asignación —incluida "FORTALEZA", aunque se repita por una
razón legítima conocida— SIEMPRE se evalúa. Si se repite, se marca
REVISAR. No existen excepciones adicionales y este módulo nunca las
inventa ni las agrega por su cuenta.

MEMORIA HISTÓRICA (HISTORICO_ASIGNACIONES.csv):

    Una fila por cada ocurrencia NO EXCLUIDA de una asignación, en
    cualquier GLOBAL ya incorporado. La incorporación es SIEMPRE
    incremental: esta corrida SOLO agrega las filas del GLOBAL nuevo que
    se le pasa; nunca reescribe el significado de una fila ya existente y
    nunca vuelve a abrir el .xlsx de un GLOBAL anterior para reconstruir
    el histórico (toda la información necesaria ya vive en el CSV).

    Un GLOBAL con duplicados encontrados (REVISAR_DUPLICADOS_ENCONTRADOS)
    NUNCA se incorpora al histórico: solo se incorporan los GLOBAL sin
    duplicados (OK_SIN_DUPLICADOS) y solo si no es --dry-run. El detalle
    JSON siempre contiene todos los hallazgos, se incorpore o no.

IDEMPOTENCIA:

    CASO A — mismo SHA-256 ya existe en el histórico: la corrida se
    reporta como YA_PROCESADO_SIN_CAMBIOS y NO se incorpora nada de nuevo
    (ni siquiera se reabre el GLOBAL para leer sus partidas).

    CASO B — mismo archivo_global (mismo nombre/periodo mensual, ver
    convención SAP_GLOBAL_TIQ_<MES>_<AÑO>.xlsx) ya incorporado al
    histórico, pero con un SHA-256 distinto: la corrida se reporta como
    GLOBAL_MODIFICADO_REQUIERE_REVISION. Esto NO se trata automáticamente
    como un GLOBAL nuevo: no se leen partidas, no se incorpora nada al
    histórico y no se decide cuál versión es correcta — requiere decisión
    humana explícita antes de sustituir o incorporar información.

TRANSPORTE:

    Este módulo solo opera sobre rutas de archivo locales ya
    materializadas (el GLOBAL recién generado en la misma sesión, y un
    HISTORICO_ASIGNACIONES.csv ya descargado). Nunca recibe ni produce
    contenido Base64: la responsabilidad de materializar/publicar en
    Google Drive es de quien invoca este script (Cowork/auditor-caja-
    tiquipaya), nunca de este módulo.

Uso:
    python control_asignaciones.py \
        --global /ruta/SAP_GLOBAL_TIQ_AGOSTO_2026.xlsx \
        --historico /ruta/HISTORICO_ASIGNACIONES.csv \
        --salida-json /ruta/CONTROL_ASIGNACIONES_AGOSTO_2026.json

    Modo seguro (no incorpora nada al histórico, solo reporta qué haría):
    python control_asignaciones.py --global ... --historico ... --dry-run
"""

import argparse
import csv
import datetime
import hashlib
import json
import os
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

_COLUMNAS_HISTORICO = [
    "asignacion", "fecha_valor", "cuenta_mayor", "glosa", "monto",
    "archivo_global", "fila_sap", "sha256_archivo", "fecha_incorporacion",
]


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
    razón legítima conocida."""
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
    CuentaMayor (C) como Asignacion (R) están vacías —mismo criterio de
    corte que _contar_filas_escritas en sap_writer.py, aplicado aquí a
    C/R en vez de B/C porque el GLOBAL es una concatenación de partidas,
    no un asiento con cabecera propia por bloque.

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
    completo. "Incremental" se refiere al CONTENIDO —solo se agregan
    filas del GLOBAL nuevo, nunca se tocan ni se recalculan las
    existentes—, no a la mecánica de escritura del CSV en sí."""
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
    Devuelve ese sha256 existente, o None si no hay conflicto. Nunca se
    invoca si ya_procesado() fue True (ese caso es YA_PROCESADO_SIN_CAMBIOS,
    no un conflicto)."""
    for fila in historico:
        if fila.get("archivo_global") != nombre_archivo_global:
            continue
        sha_existente = fila.get("sha256_archivo")
        if sha_existente and sha_existente != sha256_archivo:
            return sha_existente
    return None


# ---------------------------------------------------------------------------
# Detección de duplicados
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
    anteriores (nunca se relee el .xlsx de esos GLOBAL, solo estas
    filas). Devuelve la lista de hallazgos (uno por par
    ocurrencia-nueva/ocurrencia-relacionada)."""
    idx_historico = {}
    for fila in historico:
        idx_historico.setdefault(fila["asignacion"], []).append(fila)

    idx_nuevas = {}
    for p in candidatas_nuevas:
        idx_nuevas.setdefault(p["asignacion"], []).append(p)

    hallazgos = []
    for asignacion, ocurrencias in idx_nuevas.items():
        # 1) contra el histórico de GLOBAL anteriores
        for previa in idx_historico.get(asignacion, []):
            for nueva in ocurrencias:
                hallazgos.append(_construir_hallazgo(
                    nueva, nombre_archivo_global, previa, "HISTORICO"
                ))
        # 2) repetida más de una vez dentro del propio GLOBAL nuevo
        if len(ocurrencias) > 1:
            for i in range(len(ocurrencias)):
                for j in range(i + 1, len(ocurrencias)):
                    relacionado = {**ocurrencias[j], "archivo_global": nombre_archivo_global}
                    hallazgos.append(_construir_hallazgo(
                        ocurrencias[i], nombre_archivo_global, relacionado, "MISMO_GLOBAL"
                    ))

    return hallazgos


# ---------------------------------------------------------------------------
# Orquestador
# ---------------------------------------------------------------------------

def ejecutar_control(ruta_global, ruta_historico, nombre_archivo_global=None,
                      dry_run=False, ruta_detalle_json=None):
    if not ruta_global or not os.path.isfile(ruta_global):
        return {"estado": "ERROR_TECNICO", "problemas": ["GLOBAL_NO_ENCONTRADO"],
                "ruta_global": ruta_global}

    nombre_archivo_global = nombre_archivo_global or os.path.basename(ruta_global)
    sha256_global = _hash_archivo(ruta_global)
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

    hallazgos = detectar_duplicados(candidatas_nuevas, historico, nombre_archivo_global)
    asignaciones_duplicadas = sorted({h["asignacion"] for h in hallazgos})
    estado = "REVISAR_DUPLICADOS_ENCONTRADOS" if hallazgos else "OK_SIN_DUPLICADOS"

    ahora = datetime.datetime.now().isoformat(timespec="seconds")
    filas_incorporadas = 0
    # Un GLOBAL con duplicados encontrados queda pendiente de revisión
    # humana: NUNCA se incorpora al histórico, aunque no sea --dry-run.
    if not dry_run and estado == "OK_SIN_DUPLICADOS":
        nuevas_filas_historico = [
            {
                "asignacion": p["asignacion"],
                "fecha_valor": p["fecha_valor"] or "",
                "cuenta_mayor": p["cuenta_mayor"] or "",
                "glosa": p["glosa"] or "",
                "monto": p["monto"] or "",
                "archivo_global": nombre_archivo_global,
                "fila_sap": p["fila_sap"],
                "sha256_archivo": sha256_global,
                "fecha_incorporacion": ahora,
            }
            for p in candidatas_nuevas
        ]
        guardar_historico(ruta_historico, historico + nuevas_filas_historico)
        filas_incorporadas = len(nuevas_filas_historico)

    resumen = {
        "estado": estado,
        "archivo_global": nombre_archivo_global,
        "sha256_archivo": sha256_global,
        "fecha_ejecucion": ahora,
        "filas_leidas_global": len(partidas),
        "asignaciones_evaluadas": len(candidatas_nuevas),
        "asignaciones_excluidas": excluidas,
        "partidas_sin_asignacion": sin_asignacion,
        "asignaciones_duplicadas": asignaciones_duplicadas,
        "cantidad_hallazgos": len(hallazgos),
        "dry_run": dry_run,
        "historico_actualizado": (not dry_run and estado == "OK_SIN_DUPLICADOS"),
        "filas_incorporadas_historico": filas_incorporadas,
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
                         help="Nombre a registrar como archivo_global (por defecto, basename de --global).")
    parser.add_argument("--salida-json", dest="ruta_detalle_json", default=None,
                         help="Ruta donde escribir el detalle técnico completo (JSON).")
    parser.add_argument("--dry-run", action="store_true",
                         help="No incorpora nada al histórico; solo reporta qué encontraría.")
    return parser.parse_args(argv)


def main(argv=None):
    args = _parse_args(argv)
    resumen = ejecutar_control(
        ruta_global=args.ruta_global,
        ruta_historico=args.ruta_historico,
        nombre_archivo_global=args.nombre_archivo_global,
        dry_run=args.dry_run,
        ruta_detalle_json=args.ruta_detalle_json,
    )
    print(json.dumps(resumen, ensure_ascii=False))
    return 0 if resumen.get("estado") != "ERROR_TECNICO" else 1


if __name__ == "__main__":
    raise SystemExit(main())
