"""v3/motor.py — Módulo 03 · MOTOR PYTHON de Caja Tiquipaya V3 (FASE 5,
tercera etapa).

Este módulo es DELIBERADAMENTE un adaptador delgado, NO un motor nuevo.
Toda regla contable (ALQUILERES, comisión ATC 110201003/110201008,
Cargo=Haber, autocorrección 0<->O, reglas SAP, idempotencia) sigue viviendo
EXCLUSIVAMENTE en el código ya validado de V2 — ninguno de estos archivos
se modifica ni se reinterpreta desde aquí:

  - motor_tiquipaya.py   (ETAPAS 1-5: cruces, cuadre, asiento)
  - sap_writer.py        (ETAPA 6: generación y validación del SAP)
  - pipeline_tiquipaya.py (ETAPA 7: orquestación, idempotencia)
  - run_batch.py         (metadata de cabecera, resolución de version_codigo,
                           carga de marcadores — TODO reutilizado tal cual)

v3.motor.ejecutar_motor_cierre() únicamente:
  1. decide, a partir de estado_materializacion, si corresponde invocar
     el motor (solo si MATERIALIZADO — nunca para SIN_ARCHIVO/AMBIGUO/
     ERROR_MATERIALIZACION);
  2. arma las rutas de salida DEV (siempre dentro de base_dir_dev, nunca
     en una carpeta productiva) y la metadata de cabecera reutilizando
     run_batch.construir_metadata_cabecera();
  3. llama a pipeline_tiquipaya.procesar_cierre_completo() — LA MISMA
     función que usa run_batch.py en producción — sin tocar su código;
  4. reempaqueta el resultado en la forma pedida por el Módulo 04
     (estado_motor/resultado/diferencia/bloqueadores/...), SIN decidir
     todavía si el cierre queda LISTO, en REVISIÓN o con ERROR final —
     esa es responsabilidad exclusiva del Módulo 04 CLASIFICACIÓN.

CONTRACT-005 (original inmutable): ni este módulo ni nada que invoque
abren el .xlsm/maestro/plantilla en modo escritura (excel_io.leer_cierre,
leer_macros_bnb, leer_atc_mensual siempre read_only=True; sap_writer copia
la plantilla y solo escribe sobre la COPIA nueva). Este módulo tampoco
mueve, renombra ni borra ninguno de los archivos que recibe del Módulo 02.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config_cajas as cfg  # noqa: E402  (reutilizado tal cual)
import pipeline_tiquipaya as pipeline  # noqa: E402  (reutilizado tal cual)
import run_batch  # noqa: E402  (reutilizado tal cual)
from v3.materializacion import MATERIALIZADO, _verificar_contenido_en_base_dir  # noqa: E402


PROCESADO = "PROCESADO"
NO_PROCESADO = "NO_PROCESADO"
ERROR_MOTOR = "ERROR_MOTOR"

_ESTADO_MOTOR_MAP_RESULTADO = {
    pipeline.ESTADO_YA_PROCESADO: "YA_PROCESADO",
    pipeline.ESTADO_VALIDADO_PENDIENTE: "VALIDADO_PENDIENTE_PUBLICACION",
    pipeline.ESTADO_BLOQUEADO: "BLOQUEADO_EXCEPCION",
    pipeline.ESTADO_ERROR: "ERROR",
}


def _propagar(item_materializacion, estado_motor, resultado, mensaje, **extra):
    """Preserva TODOS los campos que el item ya traía de los Módulos 01/02
    (fecha, archivo_esperado, estado_ingesta, estado_materializacion,
    ruta_cierre_local, ruta_maestro_local, ruta_template_sap_local,
    ruta_markers_local) y agrega/sobrescribe únicamente los campos propios
    de este módulo. Sin este "carry-forward" explícito, el Módulo 04
    (CLASIFICACION) perdería estado_ingesta/estado_materializacion —
    necesarios para distinguir SIN_ARCHIVO/AMBIGUO de un simple
    ERROR_TECNICO — y el Módulo 05 (REVISION) perdería las rutas locales
    que necesita para reprocesar (incompatibilidad real encontrada en
    FASE 8, corregida aquí y no en el llamador)."""
    mensajes = list(item_materializacion.get("mensajes") or [])
    mensajes.append(mensaje)
    salida = dict(item_materializacion)
    salida.update({
        "estado_motor": estado_motor, "resultado": resultado, "diferencia": None,
        "bloqueadores": None, "ruta_resultado": None, "ruta_sap": None,
        "cargo": None, "haber": None, "mensaje": mensaje, "mensajes": mensajes,
    })
    salida.update(extra)
    return salida


def ejecutar_motor_cierre(item_materializacion, base_dir_dev, version_codigo=None, caja=None):
    """Ejecuta (o no) el motor determinístico de V2 sobre UN cierre ya
    materializado. `item_materializacion`: dict con la forma que produce
    v3.materializacion.ejecutar_materializacion() (fecha, archivo_esperado,
    estado_ingesta, estado_materializacion, ruta_cierre_local,
    ruta_maestro_local, ruta_template_sap_local, ruta_markers_local).

    `caja`: config_cajas.CajaConfig (o su `codigo`) de ESTE cierre. Si el
    item ya trae una `caja` (p. ej. propagada por un módulo anterior), esa
    identidad gana sobre el parámetro del lote — nunca se convierte
    silenciosamente un cierre de una caja en otro. Sin `caja` (ni en el
    item ni en el parámetro) el comportamiento es EXACTAMENTE el
    histórico: TIQUIPAYA. El resultado siempre trae `"caja"` con el
    código ya resuelto ("tiquipaya"/"america"), para que los módulos 05/06
    lo propaguen sin volver a decidirlo.

    Nunca lanza: cualquier problema técnico se refleja como ERROR_MOTOR en
    el resultado de ESTE cierre, sin afectar a los demás (ver
    ejecutar_motor() para el aislamiento a nivel de lote)."""
    fecha = item_materializacion.get("fecha")
    estado_mat = item_materializacion.get("estado_materializacion")
    caja_resuelta = cfg.resolver_caja(item_materializacion.get("caja") or caja)

    if estado_mat != MATERIALIZADO:
        return _propagar(
            item_materializacion, NO_PROCESADO, estado_mat,
            f"No se ejecuta el motor: estado_materializacion={estado_mat}.",
            caja=caja_resuelta.codigo,
        )

    try:
        ruta_cierre = item_materializacion["ruta_cierre_local"]
        ruta_maestro = item_materializacion["ruta_maestro_local"]
        ruta_plantilla = item_materializacion["ruta_template_sap_local"]
        ruta_markers = item_materializacion.get("ruta_markers_local")

        if not ruta_cierre or not ruta_maestro or not ruta_plantilla:
            raise ValueError(
                "MATERIALIZACION_INCOMPLETA: faltan rutas locales requeridas "
                "(ruta_cierre_local/ruta_maestro_local/ruta_template_sap_local)."
            )

        # Salidas SIEMPRE dentro de base_dir_dev (nunca una carpeta
        # productiva): mismo guardarraíl del Módulo 02, reutilizado tal
        # cual en vez de reimplementarse.
        salidas_dir = os.path.join(base_dir_dev, "salidas")
        resultados_dir = os.path.join(base_dir_dev, "resultados")
        _verificar_contenido_en_base_dir(salidas_dir, base_dir_dev)
        _verificar_contenido_en_base_dir(resultados_dir, base_dir_dev)
        os.makedirs(salidas_dir, exist_ok=True)
        os.makedirs(resultados_dir, exist_ok=True)

        ruta_sap_salida = os.path.join(salidas_dir, run_batch._nombre_sap_esperado(fecha))
        ruta_resultado = os.path.join(
            resultados_dir, pipeline.nombre_resultado_json(fecha, caja_resuelta)
        )

        metadata_cabecera = run_batch.construir_metadata_cabecera(fecha, caja_resuelta)  # reutilizado tal cual
        version_codigo = version_codigo or run_batch._resolver_version_codigo(None)

        hashes_procesados, registros_control = set(), []
        if ruta_markers:
            hashes_procesados, registros_control, _adv, _usado = (
                run_batch.cargar_marcadores_procesados(ruta_markers)
            )

        resultado = pipeline.procesar_cierre_completo(  # LA MISMA funcion que usa run_batch.py
            ruta_cierre=ruta_cierre, ruta_maestro=ruta_maestro, ruta_plantilla_sap=ruta_plantilla,
            ruta_sap_salida=ruta_sap_salida, metadata_cabecera=metadata_cabecera,
            version_codigo=version_codigo, ruta_resultado=ruta_resultado,
            hashes_procesados=hashes_procesados, registros_control=registros_control,
            caja=caja_resuelta,
        )
        resultado_json = resultado.get("resultado_json") or {}

        return _propagar(
            item_materializacion, PROCESADO,
            _ESTADO_MOTOR_MAP_RESULTADO.get(resultado["estado"], resultado["estado"]),
            f"Motor ejecutado: {resultado['estado']}.",
            diferencia=resultado_json.get("diferencia_asiento") or resultado_json.get("diferencia"),
            bloqueadores=resultado_json.get("blockers"),
            ruta_resultado=resultado.get("ruta_resultado_json"),
            ruta_sap=resultado_json.get("sap_archivo"),
            cargo=resultado_json.get("cargo"),
            haber=resultado_json.get("haber"),
            caja=caja_resuelta.codigo,
        )
    except Exception as exc:  # aislamiento: nunca se propaga fuera de este cierre
        return _propagar(
            item_materializacion, ERROR_MOTOR, None, f"{type(exc).__name__}: {exc}",
            caja=caja_resuelta.codigo,
        )


def ejecutar_motor(cierres_materializados, base_dir_dev, version_codigo=None, caja=None):
    """Aplica ejecutar_motor_cierre() a cada cierre del lote. Un problema
    técnico inesperado en UN cierre nunca detiene el resto (mismo criterio
    de aislamiento que run_batch.py y v3.ingesta/v3.materializacion).

    `caja`: default de lote (propagado a cada cierre que no traiga ya su
    propia `caja`); ver ejecutar_motor_cierre()."""
    resultados = []
    for item in cierres_materializados:
        try:
            resultados.append(ejecutar_motor_cierre(item, base_dir_dev, version_codigo, caja))
        except Exception as exc:  # red de seguridad adicional a nivel de lote
            caja_resuelta = cfg.resolver_caja(item.get("caja") or caja)
            resultados.append(_propagar(
                item, ERROR_MOTOR, None, f"{type(exc).__name__}: {exc}", caja=caja_resuelta.codigo,
            ))
    return resultados


# ---------------------------------------------------------------------------
# CLI — mismo patrón Python-es-la-unica-autoridad de v3/materializacion.py.
# ---------------------------------------------------------------------------

def main(argv=None):
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Modulo 03 MOTOR PYTHON de V3 (DEV, adaptador sobre V2).")
    parser.add_argument("--input", required=True, help="JSON {'cierres_materializados':[...], 'base_dir_dev':str, 'version_codigo':str|null, 'caja':str|null}")
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)

    with open(args.input, "r", encoding="utf-8") as f:
        datos = json.load(f)

    resultado = ejecutar_motor(
        datos["cierres_materializados"], datos["base_dir_dev"], datos.get("version_codigo"),
        datos.get("caja"),
    )
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump({"resultado": "OK", "cierres": resultado}, f, ensure_ascii=False, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
