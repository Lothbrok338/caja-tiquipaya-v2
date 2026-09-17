"""v3/materializacion.py — Módulo 02 · MATERIALIZACION / PREPARACION de Caja
Tiquipaya V3 (FASE 5, segunda etapa).

Responsabilidad ÚNICA: dado el resultado ya clasificado del módulo 01
INGESTA (v3.ingesta.ejecutar_ingesta), preparar el entorno LOCAL DEV que el
futuro módulo 03 MOTOR PYTHON necesitará: copiar (nunca mover, nunca
renombrar) los cierres ENCONTRADO a un directorio de trabajo, y preparar
maestro mensual + plantilla SAP + marcadores existentes. NO ejecuta
run_batch.py ni motor_tiquipaya.py, NO genera SAP, NO publica, NO corrige.

DISEÑO (principio V3 — ver PLAN_V3 de esta fase): n8n orquesta, Python
contiene la lógica determinística. A diferencia del módulo 01 (donde REGLA
G quedó duplicada en Python y en un nodo Code JS — ver
`v3/TECHNICAL_DEBT.md`), este módulo se invoca desde n8n EXCLUSIVAMENTE vía
`Execute Command` (mismo patrón que run_batch.py/aplicar_correccion.py/
publicar_cierre.py en V2): CERO lógica de negocio se reimplementa en
JavaScript aquí. El subworkflow de n8n solo arma el JSON de entrada, invoca
este módulo como CLI, y lee el JSON de salida.

REUTILIZACIÓN DELIBERADA DE V2 (ningún archivo de V2 se modifica):
  - run_batch.validar_maestro() se reutiliza tal cual para validar el
    maestro mensual (hoja "ATC TIQUIPAYA" + coincidencia de mes) ANTES de
    copiarlo — nunca se reinterpreta esa regla aquí.
  - run_batch.cargar_marcadores_procesados() se reutiliza tal cual para
    contar/validar los marcadores ya materializados (migración
    MARCADORES_PROCESAMIENTO/ + fallback legacy, sin cambios).

CONTRACT-005 (original inmutable): todas las copias usan shutil.copyfile()
sobre el origen (nunca se abre el origen en modo escritura, nunca se
mueve, nunca se renombra, nunca se borra). La limpieza del directorio DEV
opera EXCLUSIVAMENTE dentro de ese directorio (ver
`_verificar_contenido_en_base_dir`): nunca toca nada fuera de él, ni
siquiera por error de ruta relativa.
"""

import argparse
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import run_batch  # noqa: E402  (reutilizado tal cual, ver docstring)
from v3.ingesta import ENCONTRADO, SIN_ARCHIVO, AMBIGUO  # noqa: E402


MATERIALIZADO = "MATERIALIZADO"
ERROR_MATERIALIZACION = "ERROR_MATERIALIZACION"
# SIN_ARCHIVO / AMBIGUO se reexportan tal cual desde v3.ingesta: un cierre
# que no llegó ENCONTRADO nunca cambia de estado en este módulo, solo pasa.

_ESTADOS_SIN_MATERIALIZAR = (SIN_ARCHIVO, AMBIGUO)


class DirectorioForaDeBaseError(RuntimeError):
    """Defensa CONTRACT-005 / limpieza segura: nunca se opera fuera de base_dir."""


def _verificar_contenido_en_base_dir(ruta, base_dir):
    ruta_abs = os.path.abspath(ruta)
    base_abs = os.path.abspath(base_dir)
    if os.path.commonpath([ruta_abs, base_abs]) != base_abs:
        raise DirectorioForaDeBaseError(
            f"RUTA_FUERA_DE_BASE_DIR: {ruta_abs} no está dentro de {base_abs}; "
            "operación de limpieza/escritura rechazada."
        )


# ---------------------------------------------------------------------------
# 1) Preparar/limpiar el directorio temporal DEV
# ---------------------------------------------------------------------------

def preparar_directorio_dev(base_dir):
    """Crea (o limpia, si ya existe) la estructura de subcarpetas DEV bajo
    `base_dir` EXCLUSIVAMENTE: cierres/, maestro/, plantilla/, markers/.
    Nunca toca nada fuera de `base_dir` (ver DirectorioForaDeBaseError).
    Devuelve el dict de rutas locales resultante."""
    base_dir = os.path.abspath(base_dir)
    subcarpetas = {
        "cierres": os.path.join(base_dir, "cierres"),
        "maestro": os.path.join(base_dir, "maestro"),
        "plantilla": os.path.join(base_dir, "plantilla"),
        "markers": os.path.join(base_dir, "markers"),
    }
    for ruta in subcarpetas.values():
        _verificar_contenido_en_base_dir(ruta, base_dir)
        if os.path.isdir(ruta):
            shutil.rmtree(ruta)  # limpieza: SOLO subcarpetas propias dentro de base_dir
        os.makedirs(ruta, exist_ok=True)
    return subcarpetas


# ---------------------------------------------------------------------------
# 2/3) Materializar (o no) cada cierre segun su estado_ingesta
# ---------------------------------------------------------------------------

def materializar_cierre(item_ingesta, origen_dir, destino_dir):
    """`item_ingesta`: dict con al menos fecha/archivo_esperado/estado_ingesta
    (salida de v3.ingesta.ejecutar_ingesta). `origen_dir`: carpeta LOCAL de
    solo lectura que representa lo que Drive ya puso a disposición (en DEV,
    un fixture; en producción, lo que un paso previo de descarga de Drive
    haya materializado — este módulo NUNCA descarga de Drive por sí mismo).

    Nunca abre `origen_dir` en modo escritura: solo `shutil.copyfile()`
    lee el origen. Nunca mueve, renombra ni borra el origen."""
    estado_ingesta = item_ingesta.get("estado_ingesta")
    archivo_esperado = item_ingesta.get("archivo_esperado")

    if estado_ingesta in _ESTADOS_SIN_MATERIALIZAR:
        return {
            "estado_materializacion": estado_ingesta,
            "ruta_cierre_local": None,
            "mensaje": f"No se intenta materializar: ingesta reportó {estado_ingesta}.",
        }
    if estado_ingesta != ENCONTRADO:
        # Cualquier otro estado de ingesta (p. ej. ERROR_INGESTA) tampoco
        # intenta materializar: se refleja tal cual, nunca se reinterpreta.
        return {
            "estado_materializacion": estado_ingesta,
            "ruta_cierre_local": None,
            "mensaje": f"No se intenta materializar: ingesta reportó {estado_ingesta}.",
        }

    ruta_origen = os.path.join(origen_dir, archivo_esperado)
    ruta_destino = os.path.join(destino_dir, archivo_esperado)
    try:
        if not os.path.isfile(ruta_origen):
            raise FileNotFoundError(
                f"ingesta reportó ENCONTRADO pero {ruta_origen} no existe en origen_dir"
            )
        shutil.copyfile(ruta_origen, ruta_destino)  # solo lectura del origen
        return {
            "estado_materializacion": MATERIALIZADO,
            "ruta_cierre_local": ruta_destino,
            "mensaje": "Cierre copiado a directorio DEV local.",
        }
    except Exception as exc:  # aislamiento: un cierre no detiene el resto del lote
        return {
            "estado_materializacion": ERROR_MATERIALIZACION,
            "ruta_cierre_local": None,
            "mensaje": f"{type(exc).__name__}: {exc}",
        }


# ---------------------------------------------------------------------------
# 4) Maestro mensual — reutiliza run_batch.validar_maestro() tal cual
# ---------------------------------------------------------------------------

def preparar_maestro(ruta_maestro_origen, destino_dir, mes_rango):
    """Valida (solo lectura, vía run_batch.validar_maestro — sin cambios)
    y copia el maestro mensual a destino_dir. Nunca abre el origen en modo
    escritura."""
    try:
        run_batch.validar_maestro(ruta_maestro_origen, mes_rango)
    except RuntimeError as exc:
        return {"estado_maestro": ERROR_MATERIALIZACION, "ruta_maestro_local": None, "mensaje": str(exc)}

    nombre = os.path.basename(ruta_maestro_origen)
    ruta_destino = os.path.join(destino_dir, nombre)
    shutil.copyfile(ruta_maestro_origen, ruta_destino)
    return {"estado_maestro": MATERIALIZADO, "ruta_maestro_local": ruta_destino, "mensaje": "Maestro validado y copiado."}


# ---------------------------------------------------------------------------
# 5) Plantilla SAP — validación mínima + copia (nunca se abre en escritura)
# ---------------------------------------------------------------------------

def preparar_plantilla_sap(ruta_plantilla_origen, destino_dir):
    if not os.path.isfile(ruta_plantilla_origen):
        return {
            "estado_plantilla": ERROR_MATERIALIZACION, "ruta_template_sap_local": None,
            "mensaje": f"PLANTILLA_NO_ENCONTRADA: {ruta_plantilla_origen}",
        }
    nombre = os.path.basename(ruta_plantilla_origen)
    ruta_destino = os.path.join(destino_dir, nombre)
    shutil.copyfile(ruta_plantilla_origen, ruta_destino)
    return {
        "estado_plantilla": MATERIALIZADO, "ruta_template_sap_local": ruta_destino,
        "mensaje": "Plantilla SAP copiada (sin abrir en modo escritura).",
    }


# ---------------------------------------------------------------------------
# 6) Marcadores — copia + reutiliza run_batch.cargar_marcadores_procesados()
# ---------------------------------------------------------------------------

def preparar_markers(markers_origen_dir, destino_dir):
    """Copia los PROCESADO_<SHA256>.json de `markers_origen_dir` (si existe)
    a `destino_dir`, y luego reutiliza run_batch.cargar_marcadores_procesados()
    (sin cambios) sobre la copia local para validarlos/contarlos. Nunca
    toca el directorio de origen."""
    copiados = 0
    if markers_origen_dir and os.path.isdir(markers_origen_dir):
        for nombre in sorted(os.listdir(markers_origen_dir)):
            if nombre.startswith("PROCESADO_") and nombre.endswith(".json"):
                shutil.copyfile(os.path.join(markers_origen_dir, nombre), os.path.join(destino_dir, nombre))
                copiados += 1

    hashes_procesados, registros_control, advertencias, _ = run_batch.cargar_marcadores_procesados(destino_dir)
    return {
        "ruta_markers_local": destino_dir,
        "markers_copiados": copiados,
        "markers_validos": len(hashes_procesados),
        "advertencias_markers": advertencias,
    }


# ---------------------------------------------------------------------------
# Orquestación del módulo 02
# ---------------------------------------------------------------------------

def ejecutar_materializacion(cierres_ingesta, params):
    """`cierres_ingesta`: lista de dicts (salida de v3.ingesta.ejecutar_ingesta).
    `params`: {
      "base_dir_dev": str,           # directorio DEV a preparar/limpiar
      "origen_cierres_dir": str,     # carpeta LOCAL de solo lectura con los .xlsm "ya en Drive" (DEV: fixture)
      "ruta_maestro_origen": str,
      "ruta_plantilla_origen": str,
      "markers_origen_dir": str | None,
      "mes_rango": int,              # 1-12, para validar_maestro()
    }

    Devuelve una lista de dicts, uno por cierre, con EXACTAMENTE las claves
    pedidas: fecha, archivo_esperado, estado_ingesta, estado_materializacion,
    ruta_cierre_local, ruta_maestro_local, ruta_template_sap_local,
    ruta_markers_local, mensaje. maestro/plantilla/markers se preparan UNA
    SOLA VEZ para todo el lote (nunca una vez por cierre — mismo principio
    que V2: HANDOFF sección 12).
    """
    dirs = preparar_directorio_dev(params["base_dir_dev"])

    maestro = preparar_maestro(params["ruta_maestro_origen"], dirs["maestro"], params["mes_rango"])
    plantilla = preparar_plantilla_sap(params["ruta_plantilla_origen"], dirs["plantilla"])
    markers = preparar_markers(params.get("markers_origen_dir"), dirs["markers"])

    resultados = []
    for item in cierres_ingesta:
        mat = materializar_cierre(item, params["origen_cierres_dir"], dirs["cierres"])
        mensajes = [mat["mensaje"]]
        if maestro["estado_maestro"] != MATERIALIZADO:
            mensajes.append(f"MAESTRO: {maestro['mensaje']}")
        if plantilla["estado_plantilla"] != MATERIALIZADO:
            mensajes.append(f"PLANTILLA: {plantilla['mensaje']}")

        resultados.append({
            "fecha": item.get("fecha"),
            "archivo_esperado": item.get("archivo_esperado"),
            "estado_ingesta": item.get("estado_ingesta"),
            # FASE 11A.1: drive_file_id (y coincidencias) ya los calculaba
            # v3.ingesta.ejecutar_ingesta() desde FASE 10A, pero este dict
            # explícito los descartaba en silencio -- el Modulo 06B
            # necesita el fileId ORIGINAL de ingesta como identificador
            # primario para mover el cierre en Drive (nunca una busqueda
            # nueva por nombre como mecanismo principal). None en modo
            # fixture (sin Drive real), tal como ya lo entrega ingesta.
            "drive_file_id": item.get("drive_file_id"),
            "estado_materializacion": mat["estado_materializacion"],
            "ruta_cierre_local": mat["ruta_cierre_local"],
            "ruta_maestro_local": maestro["ruta_maestro_local"],
            "ruta_template_sap_local": plantilla["ruta_template_sap_local"],
            "ruta_markers_local": markers["ruta_markers_local"],
            "mensaje": " | ".join(mensajes),
        })

    return resultados


# ---------------------------------------------------------------------------
# CLI — mismo patrón que aplicar_correccion.py/publicar_cierre.py de V2:
# Python es la única autoridad; n8n solo invoca este script (Execute
# Command) y lee el JSON de salida. Nunca se reimplementa esta lógica en
# JavaScript (ver v3/TECHNICAL_DEBT.md sobre el gap YA EXISTENTE en 01
# INGESTA, que este módulo evita repetir).
# ---------------------------------------------------------------------------

def main(argv=None):
    parser = argparse.ArgumentParser(description="Modulo 02 MATERIALIZACION/PREPARACION de V3 (DEV).")
    parser.add_argument("--input", required=True, help="Ruta a un JSON {'cierres_ingesta':[...], 'params':{...}}")
    parser.add_argument("--output", required=True, help="Ruta donde escribir el JSON de resultado")
    args = parser.parse_args(argv)

    with open(args.input, "r", encoding="utf-8") as f:
        datos = json.load(f)

    resultado = ejecutar_materializacion(datos["cierres_ingesta"], datos["params"])

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump({"resultado": "OK", "cierres": resultado}, f, ensure_ascii=False, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
