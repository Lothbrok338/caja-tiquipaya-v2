"""run_batch.py — RUNNER BATCH CANÓNICO Y GENÉRICO (mejora operativa).

Elimina la necesidad de que Cowork escriba scripts ad hoc por corrida.
Este runner NO reinterpreta contabilidad, NO cambia ninguna regla de
excel_io.py / motor_tiquipaya.py / sap_writer.py, y NO se conecta a
Google Drive: solo orquesta pipeline_tiquipaya.procesar_cierre_completo()
sobre un rango de fechas de UN MISMO MES, usando archivos YA
MATERIALIZADOS localmente por Cowork.

Responsabilidad de Cowork (fuera de este script):
  - localizar en Drive los cierres del rango y materializarlos localmente;
  - materializar UNA VEZ el maestro mensual y la plantilla SAP;
  - obtener/materializar los marcadores PROCESADO_<SHA256>.json existentes;
  - publicar SAP/RESULTADO/CONTROL en Drive tras confirmación del usuario.

Responsabilidad de run_batch.py:
  - recorrer el rango de fechas y detectar "CIERRE DD-MM-YYYY.xlsm" por día;
  - derivar el texto de cabecera SAP (G10) a partir del mes de cada cierre;
  - resolver idempotencia leyendo PROCESADO_<SHA256>.json de --controles-dir;
  - llamar pipeline_tiquipaya.procesar_cierre_completo() por cada cierre;
  - escribir resultado_batch.json con el resumen de la corrida.

Este script NUNCA mueve cierres, NUNCA publica SAP, NUNCA crea marcadores
PROCESADO, NUNCA escribe en Google Drive, NUNCA modifica archivos fuente,
NUNCA corrige blockers y NUNCA inventa cuentas/asignaciones: solo genera
salidas locales pendientes de publicación.

Uso:
    python run_batch.py \\
        --fecha-inicio 2026-09-01 \\
        --fecha-fin 2026-09-03 \\
        --cierres-dir /ruta/cierres \\
        --maestro /ruta/MACROS_SEPTIEMBRE.xlsm \\
        --plantilla /ruta/Plantilla_SAP_maestra.xlsx \\
        --salidas-dir /ruta/salidas \\
        --resultados-dir /ruta/resultados \\
        --controles-dir /ruta/controles
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import date, timedelta

import openpyxl

import pipeline_tiquipaya as pipeline
from excel_io import normalize_compact


# ---------------------------------------------------------------------------
# 1. Rango dinámico (sin fechas hardcodeadas)
# ---------------------------------------------------------------------------

def generar_rango_fechas(fecha_inicio, fecha_fin):
    """Devuelve la lista ISO ('YYYY-MM-DD') de todos los días entre
    `fecha_inicio` y `fecha_fin`, ambos inclusive. Exige que pertenezcan
    al MISMO MES: nunca combina maestros mensuales distintos."""
    d0 = date.fromisoformat(fecha_inicio)
    d1 = date.fromisoformat(fecha_fin)
    if d1 < d0:
        raise ValueError(
            f"RANGO_INVALIDO: fecha_fin ({fecha_fin}) es anterior a "
            f"fecha_inicio ({fecha_inicio})."
        )
    if (d0.year, d0.month) != (d1.year, d1.month):
        raise ValueError(
            f"RANGO_CRUZA_MES: fecha_inicio ({fecha_inicio}) y fecha_fin "
            f"({fecha_fin}) deben pertenecer al mismo mes. Este runner no "
            f"combina maestros mensuales automáticamente: ejecútalo una "
            f"vez por cada mes del rango."
        )
    fechas = []
    actual = d0
    while actual <= d1:
        fechas.append(actual.isoformat())
        actual += timedelta(days=1)
    return fechas


def nombre_cierre_esperado(fecha_iso):
    """'CIERRE DD-MM-YYYY.xlsm' a partir de una fecha ISO 'YYYY-MM-DD'."""
    anio, mes, dia = fecha_iso.split("-")
    return f"CIERRE {dia}-{mes}-{anio}.xlsm"


# ---------------------------------------------------------------------------
# 2. Texto cabecera automático (G10) — derivado del mes del cierre
# ---------------------------------------------------------------------------

_MES_ABREV = {
    "01": "ENE", "02": "FEB", "03": "MAR", "04": "ABR",
    "05": "MAY", "06": "JUN", "07": "JUL", "08": "AGO",
    "09": "SEP", "10": "OCT", "11": "NOV", "12": "DIC",
}


def texto_cabecera_ingresos(fecha_iso):
    """'INGRESOS <MES_ABREV> CBBA' a partir de la fecha ISO del cierre."""
    _, mes, _ = fecha_iso.split("-")
    return f"INGRESOS {_MES_ABREV[mes]} CBBA"


# Cabecera fija de referencia (L10): no lleva fecha, ver especificación.
_TIPO_ASIENTO = "SA"
_REFERENCIA_FIJA = "CAJA TIQUIPAYA"


def construir_metadata_cabecera(fecha_iso):
    """Campos de cabecera que decide run_batch.py (tipo_asiento,
    texto_cabecera, referencia). Las fechas de cabecera (FechaRegistro/
    FechaContabilizacion/Mes) NO se incluyen aquí: pipeline_tiquipaya las
    sobrescribe siempre con la fecha real del cierre
    (`derivar_cabecera_fecha_cierre`)."""
    return {
        "tipo_asiento": _TIPO_ASIENTO,
        "texto_cabecera": texto_cabecera_ingresos(fecha_iso),
        "referencia": _REFERENCIA_FIJA,
    }


# ---------------------------------------------------------------------------
# 3. Maestro — recibido por ruta local, reutilizado durante todo el batch
# ---------------------------------------------------------------------------

_MESES_NOMBRE = {
    1: "ENERO", 2: "FEBRERO", 3: "MARZO", 4: "ABRIL",
    5: "MAYO", 6: "JUNIO", 7: "JULIO", 8: "AGOSTO",
    9: "SEPTIEMBRE", 10: "OCTUBRE", 11: "NOVIEMBRE", 12: "DICIEMBRE",
}

_HOJA_ATC_TIQUIPAYA = "ATC TIQUIPAYA"


def _detectar_mes_en_nombre(nombre_archivo):
    """Busca un nombre de mes en español (palabra completa) dentro del
    nombre de archivo. None si no es determinable: en ese caso no se
    bloquea la corrida (el maestro puede no traer el mes en el nombre)."""
    # "_"/"-"/"." separan palabras igual que un espacio (p. ej.
    # "MACROS_SEPTIEMBRE.xlsm"), pero \b por sí solo no corta ahí porque
    # "_" es un carácter de palabra en regex.
    nombre_norm = re.sub(r"[^A-ZÁÉÍÓÚÑ0-9]+", " ", nombre_archivo.upper())
    for numero, nombre_mes in _MESES_NOMBRE.items():
        if re.search(rf"\b{nombre_mes}\b", nombre_norm):
            return numero
    return None


def validar_maestro(ruta_maestro, mes_rango):
    """Valida que el maestro exista, contenga la hoja "ATC TIQUIPAYA" y,
    cuando sea determinable por el nombre de archivo, corresponda al mes
    del rango. Lanza RuntimeError con detalle claro si algo falla; nunca
    intenta adivinar/corregir el maestro."""
    if not os.path.isfile(ruta_maestro):
        raise RuntimeError(f"MAESTRO_NO_ENCONTRADO: {ruta_maestro}")

    mes_detectado = _detectar_mes_en_nombre(os.path.basename(ruta_maestro))
    if mes_detectado is not None and mes_detectado != mes_rango:
        raise RuntimeError(
            f"MAESTRO_MES_NO_COINCIDE: el nombre de '{os.path.basename(ruta_maestro)}' "
            f"corresponde al mes {mes_detectado:02d} pero el rango pedido es del mes "
            f"{mes_rango:02d}. No se combina/ajusta automáticamente."
        )

    wb = openpyxl.load_workbook(ruta_maestro, read_only=True, data_only=True)
    try:
        objetivo = normalize_compact(_HOJA_ATC_TIQUIPAYA)
        tiene_hoja_atc = any(normalize_compact(h) == objetivo for h in wb.sheetnames)
    finally:
        wb.close()
    if not tiene_hoja_atc:
        raise RuntimeError(
            f"MAESTRO_SIN_HOJA_ATC_TIQUIPAYA: {ruta_maestro} no contiene la "
            f"hoja '{_HOJA_ATC_TIQUIPAYA}'."
        )
    return mes_detectado


# ---------------------------------------------------------------------------
# 5. Idempotencia — lectura dinámica de PROCESADO_<SHA256>.json
# ---------------------------------------------------------------------------

def cargar_marcadores_procesados(controles_dir):
    """Lee todos los PROCESADO_<SHA256>.json de `controles_dir` y devuelve
    (hashes_procesados, registros_control, advertencias, usado_controles_dir).

    Solo se consideran válidos los marcadores con HashOrigen no vacío y
    Estado == "PROCESADO"; cualquier otro se descarta con advertencia, sin
    detener la carga. Si `controles_dir` es None, devuelve un set vacío de
    forma EXPLÍCITA (nunca un supuesto fijo de producción): el llamador
    debe dejarlo indicado en el resumen del batch."""
    if not controles_dir:
        return set(), [], [], False

    if not os.path.isdir(controles_dir):
        return set(), [], [f"CONTROLES_DIR_NO_ENCONTRADO: {controles_dir}"], False

    hashes = set()
    registros = []
    advertencias = []
    for nombre in sorted(os.listdir(controles_dir)):
        if not (nombre.startswith("PROCESADO_") and nombre.endswith(".json")):
            continue
        ruta = os.path.join(controles_dir, nombre)
        try:
            with open(ruta, "r", encoding="utf-8") as f:
                contenido = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            advertencias.append(f"MARCADOR_ILEGIBLE_{nombre}: {exc}")
            continue

        if not isinstance(contenido, dict):
            advertencias.append(f"MARCADOR_FORMATO_INVALIDO_{nombre}")
            continue

        hash_origen = contenido.get("HashOrigen")
        estado = contenido.get("Estado")
        if not hash_origen or estado != "PROCESADO":
            advertencias.append(f"MARCADOR_INCOMPLETO_{nombre}")
            continue

        hashes.add(hash_origen)
        registros.append(contenido)

    return hashes, registros, advertencias, True


# ---------------------------------------------------------------------------
# 7-9. Ejecución por cierre — exclusivamente vía
# pipeline_tiquipaya.procesar_cierre_completo(), con métricas y blockers
# que nunca detienen el batch.
# ---------------------------------------------------------------------------

_ESTADO_MAP = {
    pipeline.ESTADO_YA_PROCESADO: "YA_PROCESADO",
    pipeline.ESTADO_VALIDADO_PENDIENTE: "LISTO_PARA_PUBLICAR",
    pipeline.ESTADO_BLOQUEADO: "ERROR_REVISAR",
    pipeline.ESTADO_ERROR: "ERROR_REVISAR",
}


def _nombre_sap_esperado(fecha_iso):
    anio, mes, dia = fecha_iso.split("-")
    return f"SAP_{dia}-{mes}-{anio}.xlsx"


def procesar_cierre(fecha_iso, ruta_cierre, ruta_maestro, ruta_plantilla,
                     salidas_dir, resultados_dir, version_codigo,
                     hashes_procesados, registros_control):
    """Procesa UN cierre ya materializado, exclusivamente vía
    pipeline_tiquipaya.procesar_cierre_completo(). Nunca reimplementa
    lógica contable ni llama funciones privadas del motor. Un blocker
    individual se refleja como ERROR_REVISAR y se devuelve normalmente
    (no lanza excepción); solo un fallo técnico inesperado se captura
    aquí para no detener el resto del batch."""
    ruta_sap_salida = os.path.join(salidas_dir, _nombre_sap_esperado(fecha_iso))
    ruta_resultado = os.path.join(resultados_dir, pipeline.nombre_resultado_json(fecha_iso))
    metadata_cabecera = construir_metadata_cabecera(fecha_iso)

    t0 = time.perf_counter()
    try:
        resultado = pipeline.procesar_cierre_completo(
            ruta_cierre=ruta_cierre,
            ruta_maestro=ruta_maestro,
            ruta_plantilla_sap=ruta_plantilla,
            ruta_sap_salida=ruta_sap_salida,
            metadata_cabecera=metadata_cabecera,
            version_codigo=version_codigo,
            ruta_control=None,
            ruta_resultado=ruta_resultado,
            hashes_procesados=hashes_procesados,
            registros_control=registros_control,
        )
    except Exception as exc:  # fallo técnico real (archivo corrupto, etc.)
        tiempo = time.perf_counter() - t0
        return {
            "fecha": fecha_iso,
            "archivo": os.path.basename(ruta_cierre),
            "hash": None,
            "estado": "ERROR_TECNICO",
            "diferencia": None,
            "blockers": None,
            "lineas_sap": None,
            "tiempo_automatico_s": round(tiempo, 3),
            "tiempo_generacion_sap_s": None,
            "tiempo_validacion_sap_s": None,
            "ruta_sap": None,
            "ruta_resultado": None,
            "detalle_error": f"{type(exc).__name__}: {exc}",
        }
    tiempo = time.perf_counter() - t0

    resultado_json = resultado.get("resultado_json") or {}
    sap_resumen = resultado.get("sap") or {}
    estado_final = _ESTADO_MAP.get(resultado["estado"], "ERROR_REVISAR")

    detalle_error = None
    if estado_final == "ERROR_REVISAR":
        advertencias = resultado_json.get("advertencias") or []
        detalle_error = "; ".join(advertencias) if advertencias else resultado["estado"]

    return {
        "fecha": fecha_iso,
        "archivo": resultado.get("archivo_origen") or os.path.basename(ruta_cierre),
        "hash": resultado.get("hash_origen"),
        "estado": estado_final,
        "diferencia": resultado_json.get("diferencia_asiento") or resultado_json.get("diferencia"),
        "blockers": resultado_json.get("blockers"),
        "lineas_sap": resultado_json.get("cantidad_partidas"),
        "tiempo_automatico_s": round(tiempo, 3),
        "tiempo_generacion_sap_s": sap_resumen.get("tiempo_generacion_s"),
        "tiempo_validacion_sap_s": sap_resumen.get("tiempo_validacion_s"),
        "ruta_sap": resultado_json.get("sap_archivo"),
        "ruta_resultado": ruta_resultado if resultado.get("resultado_json") is not None else None,
        "detalle_error": detalle_error,
    }


def _entrada_sin_archivo(fecha_iso, nombre_archivo):
    return {
        "fecha": fecha_iso,
        "archivo": nombre_archivo,
        "hash": None,
        "estado": "SIN_ARCHIVO",
        "diferencia": None,
        "blockers": None,
        "lineas_sap": None,
        "tiempo_automatico_s": 0.0,
        "tiempo_generacion_sap_s": None,
        "tiempo_validacion_sap_s": None,
        "ruta_sap": None,
        "ruta_resultado": None,
        "detalle_error": None,
    }


# ---------------------------------------------------------------------------
# version_codigo — nunca se inventa: si no se pasa por CLI, se intenta leer
# del propio repo (git); si eso falla, queda explícito como "DESCONOCIDO".
# ---------------------------------------------------------------------------

def _resolver_version_codigo(version_codigo_arg):
    if version_codigo_arg:
        return version_codigo_arg
    try:
        salida = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=os.path.dirname(os.path.abspath(__file__)),
            capture_output=True, text=True, timeout=5, check=True,
        )
        version = salida.stdout.strip()
        if version:
            return version
    except Exception:
        pass
    return "DESCONOCIDO"


# ---------------------------------------------------------------------------
# Orquestación del batch completo
# ---------------------------------------------------------------------------

def ejecutar_batch(args):
    fechas = generar_rango_fechas(args.fecha_inicio, args.fecha_fin)
    mes_rango = int(fechas[0][5:7])

    if not os.path.isfile(args.plantilla):
        raise RuntimeError(f"PLANTILLA_NO_ENCONTRADA: {args.plantilla}")

    validar_maestro(args.maestro, mes_rango)

    os.makedirs(args.salidas_dir, exist_ok=True)
    os.makedirs(args.resultados_dir, exist_ok=True)

    hashes_procesados, registros_control, advertencias_control, uso_controles_dir = \
        cargar_marcadores_procesados(args.controles_dir)

    version_codigo = _resolver_version_codigo(args.version_codigo)

    t_batch_inicio = time.perf_counter()
    cierres = []
    for fecha_iso in fechas:
        nombre_archivo = nombre_cierre_esperado(fecha_iso)
        ruta_cierre = os.path.join(args.cierres_dir, nombre_archivo)

        if not os.path.isfile(ruta_cierre):
            cierres.append(_entrada_sin_archivo(fecha_iso, nombre_archivo))
            continue

        # --maestro y --plantilla se reutilizan tal cual, sin re-materializar
        # ni volver a buscarlos, en cada iteración del rango.
        entrada = procesar_cierre(
            fecha_iso, ruta_cierre, args.maestro, args.plantilla,
            args.salidas_dir, args.resultados_dir, version_codigo,
            hashes_procesados, registros_control,
        )
        cierres.append(entrada)
    tiempo_total = time.perf_counter() - t_batch_inicio

    resumen_estados = {}
    for c in cierres:
        resumen_estados[c["estado"]] = resumen_estados.get(c["estado"], 0) + 1

    resultado_batch = {
        "parametros": {
            "fecha_inicio": args.fecha_inicio,
            "fecha_fin": args.fecha_fin,
            "cierres_dir": args.cierres_dir,
            "maestro": args.maestro,
            "plantilla": args.plantilla,
            "salidas_dir": args.salidas_dir,
            "resultados_dir": args.resultados_dir,
            "controles_dir": args.controles_dir,
            "version_codigo": version_codigo,
        },
        "idempotencia": {
            "fuente": "controles_dir" if uso_controles_dir else "SIN_CONTROLES_DIR (set vacio explicito)",
            "hashes_cargados": len(hashes_procesados),
            "advertencias": advertencias_control,
        },
        "tiempo_total_batch_s": round(tiempo_total, 3),
        "total_cierres_rango": len(fechas),
        "resumen_estados": resumen_estados,
        "cierres": cierres,
    }

    ruta_resultado_batch = os.path.join(args.resultados_dir, "resultado_batch.json")
    with open(ruta_resultado_batch, "w", encoding="utf-8") as f:
        json.dump(resultado_batch, f, ensure_ascii=False, indent=2)

    resultado_batch["ruta_resultado_batch"] = ruta_resultado_batch
    return resultado_batch


def construir_parser():
    parser = argparse.ArgumentParser(
        description="Runner batch canónico y genérico — Caja Tiquipaya V2. "
                     "Procesa un rango de cierres YA MATERIALIZADOS localmente "
                     "(nunca se conecta a Google Drive)."
    )
    parser.add_argument("--fecha-inicio", required=True, help="YYYY-MM-DD")
    parser.add_argument("--fecha-fin", required=True, help="YYYY-MM-DD (mismo mes que --fecha-inicio)")
    parser.add_argument("--cierres-dir", required=True, help="Directorio local con los CIERRE DD-MM-YYYY.xlsm")
    parser.add_argument("--maestro", required=True, help="Ruta local al maestro mensual (MACROS + ATC TIQUIPAYA)")
    parser.add_argument("--plantilla", required=True, help="Ruta local a la plantilla SAP maestra")
    parser.add_argument("--salidas-dir", required=True, help="Directorio local donde escribir los SAP generados")
    parser.add_argument("--resultados-dir", required=True, help="Directorio local donde escribir RESULTADO_TIQ_*.json y resultado_batch.json")
    parser.add_argument("--controles-dir", default=None, help="Directorio local con PROCESADO_<SHA256>.json existentes (opcional)")
    parser.add_argument("--version-codigo", default=None, help="Identificador de versión de código (por defecto: git rev-parse --short HEAD)")
    return parser


def main(argv=None):
    parser = construir_parser()
    args = parser.parse_args(argv)

    try:
        resultado_batch = ejecutar_batch(args)
    except (ValueError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    print(
        f"Batch {args.fecha_inicio}..{args.fecha_fin} "
        f"({resultado_batch['total_cierres_rango']} días en rango): "
        f"{resultado_batch['resumen_estados']}"
    )
    print(f"resultado_batch.json: {resultado_batch['ruta_resultado_batch']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
