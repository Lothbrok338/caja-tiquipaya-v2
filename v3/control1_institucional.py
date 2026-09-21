"""v3/control1_institucional.py — adaptador CONTROL 1 institucional.

Analiza SIMULTÁNEAMENTE los dos GLOBAL por caja (SAP_GLOBAL_TIQ_<MES>_<AÑO>.xlsx
y SAP_GLOBAL_AME_<MES>_<AÑO>.xlsx) SIN fusionarlos en un tercer SAP: los
combina solo EN MEMORIA para detectar asignaciones duplicadas/históricas de
forma institucional (TIQ↔TIQ, AME↔AME, TIQ↔AME y contra un histórico
institucional único).

NUNCA reescribe control_asignaciones.py (CONTROL 1 V2): reutiliza sus
funciones existentes tal cual (leer_partidas_global, es_excluida,
aplicar_correcciones_global, _fila_historico, _hash_archivo,
_derivar_periodo). La única lógica nueva aquí es la combinación TIQ+AME en
memoria, el etiquetado de origen (CAJA/ARCHIVO_ORIGEN/FILA_ORIGEN) y la
idempotencia por PAR de SHA. Cada corrección autorizada se aplica
ÚNICAMENTE al GLOBAL de la caja donde vive esa fila — jamás a un archivo
combinado, que no existe."""

import csv
import datetime
import json
import os
import shutil

import config_cajas as cfg
import control_asignaciones as ctrl1

CAJA_TIQ = cfg.TIQUIPAYA.codigo
CAJA_AME = cfg.AMERICA.codigo

_COLUMNAS_HISTORICO_INSTITUCIONAL = list(ctrl1._COLUMNAS_HISTORICO) + [
    "caja", "archivo_origen", "fila_origen",
]

_ESTADO_OK_SIN_DUPLICADOS = "OK_SIN_DUPLICADOS"
_ESTADO_REVISAR_DUPLICADOS = "REVISAR_DUPLICADOS_ENCONTRADOS"
_ESTADO_YA_PROCESADO = "YA_PROCESADO_SIN_CAMBIOS"
_ESTADO_GLOBAL_MODIFICADO = "GLOBAL_MODIFICADO_REQUIERE_REVISION"

# ---------------------------------------------------------------------------
# Modo — igual espíritu que v3/control1_modos.py (PRELIMINAR/CERRAR), pero
# aplicado al par institucional TIQ+AME en vez de a un único GLOBAL por caja.
# ---------------------------------------------------------------------------

PRELIMINAR = "preliminar"
CERRAR = "cerrar"


def validar_modo_institucional(modo, confirmacion_cierre=False):
    """PRELIMINAR por defecto (mes abierto: nunca escribe el histórico
    institucional ni sella el periodo). CERRAR exige modo='cerrar' Y
    confirmacion_cierre=True explícito (tras confirmación humana) — nunca se
    infiere el cierre solo porque no hay hallazgos."""
    modo = PRELIMINAR if modo in (None, "") else modo
    if modo not in (PRELIMINAR, CERRAR):
        raise ValueError(f"MODO_CONTROL1_INSTITUCIONAL_INVALIDO: {modo!r} (use 'preliminar' o 'cerrar')")
    if modo == CERRAR and confirmacion_cierre is not True:
        raise ValueError(
            "ERROR_CONFIRMACION_CIERRE_REQUERIDA: el cierre institucional requiere confirmacion_cierre=true explícito"
        )
    return modo


def nombre_estado_institucional(periodo):
    return f"ESTADO_CONTROL1_INSTITUCIONAL_{periodo}.json"


def nombre_reporte_institucional(periodo):
    return f"CONTROL_ASIGNACIONES_INSTITUCIONAL_{periodo}.json"


def nombre_historico_institucional():
    return "HISTORICO_ASIGNACIONES_INSTITUCIONAL.csv"


# ---------------------------------------------------------------------------
# Histórico institucional (extiende el esquema V2 con caja/archivo_origen/
# fila_origen — la identidad de una alerta NUNCA es solo FILA_GLOBAL).
# ---------------------------------------------------------------------------

def cargar_historico_institucional(ruta_historico):
    if not ruta_historico or not os.path.isfile(ruta_historico):
        return []
    with open(ruta_historico, "r", encoding="utf-8", newline="") as f:
        return [dict(fila) for fila in csv.DictReader(f)]


def guardar_historico_institucional(ruta_historico, filas):
    directorio = os.path.dirname(os.path.abspath(ruta_historico))
    if directorio:
        os.makedirs(directorio, exist_ok=True)
    ruta_tmp = f"{ruta_historico}.tmp"
    with open(ruta_tmp, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=_COLUMNAS_HISTORICO_INSTITUCIONAL)
        writer.writeheader()
        for fila in filas:
            writer.writerow({col: fila.get(col, "") for col in _COLUMNAS_HISTORICO_INSTITUCIONAL})
    os.replace(ruta_tmp, ruta_historico)


def _cargar_estado(ruta_estado):
    if not ruta_estado or not os.path.isfile(ruta_estado):
        return {}
    with open(ruta_estado, "r", encoding="utf-8") as f:
        return json.load(f)


def _guardar_estado(ruta_estado, datos):
    directorio = os.path.dirname(os.path.abspath(ruta_estado))
    if directorio:
        os.makedirs(directorio, exist_ok=True)
    ruta_tmp = f"{ruta_estado}.tmp"
    with open(ruta_tmp, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=2)
    os.replace(ruta_tmp, ruta_estado)


# ---------------------------------------------------------------------------
# Lectura combinada (en memoria) de ambos GLOBAL.
# ---------------------------------------------------------------------------

def _leer_candidatas_tagged(ruta_global, caja_codigo):
    """Lee un GLOBAL con control_asignaciones.leer_partidas_global (sin
    cambios), aplica las mismas exclusiones (es_excluida) y etiqueta cada
    partida NO excluida con CAJA/ARCHIVO_ORIGEN/FILA_ORIGEN. Nunca decide
    nada nuevo sobre qué se excluye."""
    nombre = os.path.basename(ruta_global)
    partidas = ctrl1.leer_partidas_global(ruta_global)
    candidatas = []
    excluidas = 0
    sin_asignacion = 0
    for p in partidas:
        if ctrl1.es_excluida(p["asignacion"], p["cuenta_mayor"]):
            excluidas += 1
            continue
        if p["asignacion"] is None:
            sin_asignacion += 1
            continue
        etiquetada = dict(p)
        etiquetada["caja"] = caja_codigo
        etiquetada["archivo_origen"] = nombre
        etiquetada["fila_origen"] = p["fila_sap"]
        candidatas.append(etiquetada)
    return candidatas, excluidas, sin_asignacion


def _construir_hallazgo_institucional(actual, relacionado, origen_relacionado):
    return {
        "asignacion": actual["asignacion"],
        "caja": actual["caja"],
        "archivo_origen": actual["archivo_origen"],
        "fila_origen": actual["fila_origen"],
        "fecha": actual["fecha_valor"],
        "cuenta": actual["cuenta_mayor"],
        "glosa": actual["glosa"],
        "monto": actual["monto"],
        "caja_relacionada": relacionado.get("caja"),
        "archivo_relacionado": relacionado.get("archivo_origen") or relacionado.get("archivo_global"),
        "fila_relacionada": relacionado.get("fila_origen") or relacionado.get("fila_sap"),
        "origen_relacionado": origen_relacionado,  # HISTORICO | MISMO_PERIODO
    }


def detectar_duplicados_institucional(candidatas, historico):
    """Igual espíritu que control_asignaciones.detectar_duplicados, pero
    generalizado: cada partida (TIQ o AME) trae su propio ARCHIVO_ORIGEN/
    CAJA/FILA_ORIGEN, así que un TIQ↔AME se detecta exactamente igual que
    un TIQ↔TIQ o AME↔AME — todo se agrupa por `asignacion`."""
    idx_historico = {}
    for fila in historico:
        idx_historico.setdefault(fila.get("asignacion"), []).append(fila)

    idx_nuevas = {}
    for p in candidatas:
        idx_nuevas.setdefault(p["asignacion"], []).append(p)

    hallazgos = []
    for asignacion, ocurrencias in idx_nuevas.items():
        for previa in idx_historico.get(asignacion, []):
            for nueva in ocurrencias:
                hallazgos.append(_construir_hallazgo_institucional(nueva, previa, "HISTORICO"))
        if len(ocurrencias) > 1:
            for i in range(len(ocurrencias)):
                for j in range(i + 1, len(ocurrencias)):
                    hallazgos.append(
                        _construir_hallazgo_institucional(ocurrencias[i], ocurrencias[j], "MISMO_PERIODO")
                    )
    return hallazgos


def _validar_periodos(nombre_tiq, nombre_ame):
    periodo_tiq = ctrl1._derivar_periodo(nombre_tiq, cfg.TIQUIPAYA)
    periodo_ame = ctrl1._derivar_periodo(nombre_ame, cfg.AMERICA)
    if periodo_tiq is None or periodo_ame is None:
        return None, {
            "estado": "ERROR_TECNICO",
            "problemas": ["GLOBAL_NOMBRE_NO_CANONICO"],
            "archivo_global_tiq": nombre_tiq,
            "archivo_global_ame": nombre_ame,
        }
    if periodo_tiq != periodo_ame:
        return None, {
            "estado": "ERROR_TECNICO",
            "problemas": ["PERIODOS_DISTINTOS_TIQ_AME"],
            "periodo_tiq": periodo_tiq,
            "periodo_ame": periodo_ame,
        }
    return periodo_tiq, None


def ejecutar_control1_institucional(ruta_global_tiq, ruta_global_ame, ruta_historico_institucional,
                                     directorio_revision=None, ruta_detalle_json=None, dry_run=False,
                                     modo=PRELIMINAR, confirmacion_cierre=False):
    """CONTROL 1 institucional: lee ambos GLOBAL, valida mismo periodo,
    combina candidatas EN MEMORIA (orden fijo TIQ→AME) y detecta
    duplicados TIQ↔TIQ, AME↔AME y TIQ↔AME contra un único histórico
    institucional. Nunca crea ni modifica un GLOBAL combinado.

    PRELIMINAR (por defecto, mes abierto): SOLO calcula y, si se pasa
    `ruta_detalle_json`, escribe la revisión institucional (alertas) — NUNCA
    escribe el histórico institucional ni sella el periodo. Repetible las
    veces que haga falta mientras el GLOBAL siga cambiando.

    CERRAR (`modo='cerrar'` + `confirmacion_cierre=True`): recalcula sobre el
    GLOBAL actual (revalida que no queden alertas pendientes: si las hay,
    bloquea el cierre sin tocar nada) y SOLO entonces incorpora el histórico
    institucional y sella el PAR de SHA-256 del periodo. Un cierre repetido
    con el mismo PAR es idempotente (YA_PROCESADO_SIN_CAMBIOS); si el PAR
    cambió tras el cierre, se bloquea (GLOBAL_MODIFICADO_REQUIERE_REVISION)."""
    modo = validar_modo_institucional(modo, confirmacion_cierre)

    if not ruta_global_tiq or not os.path.isfile(ruta_global_tiq):
        return {"estado": "ERROR_TECNICO", "problemas": ["GLOBAL_TIQ_NO_ENCONTRADO"], "modo_control1": modo}
    if not ruta_global_ame or not os.path.isfile(ruta_global_ame):
        return {"estado": "ERROR_TECNICO", "problemas": ["GLOBAL_AME_NO_ENCONTRADO"], "modo_control1": modo}

    nombre_tiq = os.path.basename(ruta_global_tiq)
    nombre_ame = os.path.basename(ruta_global_ame)
    periodo, error = _validar_periodos(nombre_tiq, nombre_ame)
    if error:
        return {**error, "modo_control1": modo}

    sha_tiq = ctrl1._hash_archivo(ruta_global_tiq)
    sha_ame = ctrl1._hash_archivo(ruta_global_ame)
    sha_par = f"{sha_tiq}|{sha_ame}"  # orden fijo TIQ->AME

    directorio_revision = directorio_revision or os.path.dirname(os.path.abspath(ruta_historico_institucional)) or "."
    ruta_estado = os.path.join(directorio_revision, nombre_estado_institucional(periodo))
    estado_previo = _cargar_estado(ruta_estado)
    cerrado_previo = estado_previo.get("periodo") == periodo and estado_previo.get("cerrado") is True

    if cerrado_previo:
        if estado_previo.get("sha_par") == sha_par:
            return {
                "estado": _ESTADO_YA_PROCESADO,
                "modo_control1": modo,
                "periodo": periodo,
                "sha_par": sha_par,
                "periodo_cerrado": True,
                "dry_run": dry_run,
                "historico_actualizado": False,
                "mensaje": "Este periodo institucional ya está cerrado con este mismo PAR GLOBAL TIQ/AME; no se hizo nada.",
            }
        return {
            "estado": _ESTADO_GLOBAL_MODIFICADO,
            "modo_control1": modo,
            "periodo": periodo,
            "sha_par": sha_par,
            "sha_par_cerrado": estado_previo.get("sha_par"),
            "periodo_cerrado": True,
            "dry_run": dry_run,
            "historico_actualizado": False,
            "mensaje": (
                "El periodo institucional ya está cerrado con un PAR de SHA-256 (TIQ,AME) "
                "distinto al actual. Requiere decisión humana; no se modificó nada."
            ),
        }

    try:
        candidatas_tiq, excluidas_tiq, sin_asig_tiq = _leer_candidatas_tagged(ruta_global_tiq, CAJA_TIQ)
        candidatas_ame, excluidas_ame, sin_asig_ame = _leer_candidatas_tagged(ruta_global_ame, CAJA_AME)
    except ctrl1.HojaNoEncontradaError:
        return {"estado": "ERROR_TECNICO", "problemas": ["GLOBAL_HOJA_1_NO_ENCONTRADA"], "modo_control1": modo}
    except Exception as exc:  # noqa: BLE001 — GLOBAL ilegible, se reporta y se detiene
        return {"estado": "ERROR_TECNICO", "problemas": [f"GLOBAL_ILEGIBLE:{exc}"], "modo_control1": modo}

    combinadas = candidatas_tiq + candidatas_ame  # orden fijo TIQ->AME

    historico = cargar_historico_institucional(ruta_historico_institucional)
    hallazgos = detectar_duplicados_institucional(combinadas, historico)

    ahora = datetime.datetime.now().isoformat(timespec="seconds")
    resumen = {
        "estado": _ESTADO_OK_SIN_DUPLICADOS if not hallazgos else _ESTADO_REVISAR_DUPLICADOS,
        "modo_control1": modo,
        "periodo": periodo,
        "sha_par": sha_par,
        "periodo_cerrado": False,
        "archivo_global_tiq": nombre_tiq,
        "archivo_global_ame": nombre_ame,
        "candidatas_tiq": len(candidatas_tiq),
        "candidatas_ame": len(candidatas_ame),
        "excluidas_tiq": excluidas_tiq,
        "excluidas_ame": excluidas_ame,
        "sin_asignacion_tiq": sin_asig_tiq,
        "sin_asignacion_ame": sin_asig_ame,
        "alertas": hallazgos,
        "dry_run": dry_run,
        "historico_actualizado": False,
    }

    if ruta_detalle_json:
        with open(ruta_detalle_json, "w", encoding="utf-8") as f:
            json.dump(resumen, f, ensure_ascii=False, indent=2, default=str)
        resumen["ruta_detalle_json"] = ruta_detalle_json

    if modo == PRELIMINAR:
        return resumen

    # CERRAR: revalida que no queden alertas pendientes antes de sellar nada.
    if hallazgos:
        resumen["estado"] = "CIERRE_BLOQUEADO_PENDIENTES"
        resumen["mensaje"] = (
            "No se cerró: hay alertas de duplicados sin resolver. Corrija el GLOBAL de "
            "origen de cada alerta (ver corregir_control1_institucional) y vuelva a "
            "intentar el cierre. El histórico institucional no se tocó."
        )
        return resumen

    if dry_run:
        resumen["estado"] = "CIERRE_SIMULACRO"
        return resumen

    sha_por_archivo = {nombre_tiq: sha_tiq, nombre_ame: sha_ame}
    nuevas_filas = []
    for p in combinadas:
        fila = ctrl1._fila_historico(
            p, ctrl1._SIN_ALERTA, None, p["archivo_origen"],
            sha_por_archivo[p["archivo_origen"]], sha_por_archivo[p["archivo_origen"]], ahora,
        )
        fila["caja"] = p["caja"]
        fila["archivo_origen"] = p["archivo_origen"]
        fila["fila_origen"] = p["fila_origen"]
        nuevas_filas.append(fila)
    guardar_historico_institucional(ruta_historico_institucional, historico + nuevas_filas)
    _guardar_estado(ruta_estado, {"periodo": periodo, "sha_par": sha_par, "cerrado": True, "fecha": ahora})
    resumen["estado"] = "CERRADO"
    resumen["periodo_cerrado"] = True
    resumen["historico_actualizado"] = True
    resumen["filas_incorporadas_historico"] = len(nuevas_filas)

    return resumen


# ---------------------------------------------------------------------------
# Corrección atómica: cada corrección toca SOLO el GLOBAL de su caja de
# origen; si cualquiera falla, ninguno de los dos GLOBAL queda modificado.
# ---------------------------------------------------------------------------

def _validar_correcciones_previas(ruta_global, correcciones):
    """Verifica, usando SOLO control_asignaciones.leer_partidas_global
    (público, sin cambios), que cada ASIGNACION_ORIGINAL esperada siga
    vigente en esa fila del GLOBAL — sin escribir nada todavía."""
    actuales = {p["fila_sap"]: p["asignacion"] for p in ctrl1.leer_partidas_global(ruta_global)}
    for fila_sap, original, _nueva in correcciones:
        if actuales.get(fila_sap) != original:
            raise ctrl1.CorreccionInvalidaError(
                f"ASIGNACION_ORIGINAL_NO_COINCIDE:archivo={os.path.basename(ruta_global)}:"
                f"fila={fila_sap}:esperado={original!r}:actual={actuales.get(fila_sap)!r}"
            )


def aplicar_correcciones_institucional(ruta_global_tiq, ruta_global_ame,
                                        correcciones_tiq, correcciones_ame):
    """Aplica correcciones autorizadas a CADA GLOBAL de origen (nunca a un
    archivo combinado, que no existe). Todo o nada ENTRE AMBOS archivos:

    1) Valida TODAS las correcciones de AMBOS archivos antes de escribir
       ninguna (si cualquiera falla, ningún archivo se toca — sin backups
       de por medio, porque nada se escribió todavía).
    2) Respalda una copia de cada archivo que vaya a modificarse ANTES de
       tocarlo (staging por archivo: `ctrl1.aplicar_correcciones_global` ya
       escribe a un `.tmp` y solo lo sustituye con `os.replace` — atómico
       para ESE archivo).
    3) Si el reemplazo del SEGUNDO archivo falla DESPUÉS de que el primero ya
       se sustituyó, se restaura el primero desde su backup: ambos
       terminan idénticos al estado inicial, nunca solo uno modificado."""
    correcciones_tiq = correcciones_tiq or []
    correcciones_ame = correcciones_ame or []
    if correcciones_tiq:
        _validar_correcciones_previas(ruta_global_tiq, correcciones_tiq)
    if correcciones_ame:
        _validar_correcciones_previas(ruta_global_ame, correcciones_ame)

    backup_tiq = f"{ruta_global_tiq}.institucional.bak" if correcciones_tiq else None
    backup_ame = f"{ruta_global_ame}.institucional.bak" if correcciones_ame else None
    if backup_tiq:
        shutil.copy2(ruta_global_tiq, backup_tiq)
    if backup_ame:
        shutil.copy2(ruta_global_ame, backup_ame)

    tiq_aplicado = False
    try:
        if correcciones_tiq:
            ctrl1.aplicar_correcciones_global(ruta_global_tiq, correcciones_tiq)
            tiq_aplicado = True
        if correcciones_ame:
            ctrl1.aplicar_correcciones_global(ruta_global_ame, correcciones_ame)
    except Exception:
        if tiq_aplicado and backup_tiq:
            shutil.copy2(backup_tiq, ruta_global_tiq)
        raise
    finally:
        for backup in (backup_tiq, backup_ame):
            if backup and os.path.isfile(backup):
                os.remove(backup)

    return {
        "correcciones_aplicadas_tiq": len(correcciones_tiq),
        "correcciones_aplicadas_ame": len(correcciones_ame),
    }
