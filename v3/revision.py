"""v3/revision.py — Módulo 05 · REVISION/CORRECCION de Caja Tiquipaya V3
(FASE 5, quinta etapa).

Adaptador delgado, NO un motor de corrección paralelo. Toda la lógica de
qué es corregible, cómo se aplica en memoria y cómo se reprocesa sigue
viviendo EXCLUSIVAMENTE en el código ya validado de V2 — ninguno de estos
archivos se modifica ni se reinterpreta desde aquí:

  - correcciones_tiquipaya.py  (schema, campos corregibles, aplicación EN
                                 MEMORIA sobre una copia — nunca el original)
  - pipeline_tiquipaya.py      (procesar_cierre_con_correccion(): reproceso
                                 completo ETAPA 3-6 con la corrección aplicada)
  - aplicar_correccion.py      (_rutas_reproceso(): convención de nombres
                                 bajo REPROCESOS/, reutilizada tal cual)
  - run_batch.py               (construir_metadata_cabecera(),
                                 cargar_marcadores_procesados(),
                                 _resolver_version_codigo())
  - v3.clasificacion           (reutilizado para decidir si el reproceso
                                 queda LISTO_PARA_PUBLICAR o sigue
                                 ERROR_REVISAR — MISMO criterio del Módulo
                                 04, no una segunda clasificación paralela)

V3 NUNCA decide POR SU CUENTA qué corrección aplicar: `correccion` llega
siempre ya decidida por el auditor humano (mismo principio que V2, HANDOFF
§16.2). Este módulo únicamente: valida la solicitud, la rechaza si toca un
campo no autorizado o un importe, la aplica técnicamente si es válida, y
reprocesa — nunca inventa ni elige.

CONTRACT-005/013 (original inmutable / reprocesos trazables): el .xlsm
original nunca se abre en modo escritura (correcciones_tiquipaya.
aplicar_correccion_en_memoria trabaja sobre una copia profunda); el
reproceso SIEMPRE se escribe a rutas nuevas dentro de `REPROCESOS/` del
directorio DEV (`aplicar_correccion._rutas_reproceso`, reutilizada tal
cual), nunca sobre el resultado/SAP originales.

CONTRACT-011 (procesar y publicar separados): este módulo reprocesa y
clasifica el resultado — jamás publica, jamás sube nada, jamás genera un
marcador PROCESADO. Esa es responsabilidad exclusiva del futuro Módulo 06.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config_cajas as cfg  # noqa: E402  (reutilizado tal cual)
import pipeline_tiquipaya as pipeline  # noqa: E402  (reutilizado tal cual)
import run_batch  # noqa: E402  (reutilizado tal cual)
import correcciones_tiquipaya as correcciones  # noqa: E402  (reutilizado tal cual)
import aplicar_correccion as aplicar_cli  # noqa: E402  (reutilizado tal cual: _rutas_reproceso)
from v3.materializacion import _verificar_contenido_en_base_dir  # noqa: E402
from v3.motor import _ESTADO_MOTOR_MAP_RESULTADO, PROCESADO as MOTOR_PROCESADO  # noqa: E402
from v3.clasificacion import clasificar_cierre  # noqa: E402


def revisar_y_corregir_cierre(item, base_dir_dev, version_codigo=None, controles_dir_dev=None, caja=None):
    """`item`: registro combinado de los módulos 01+02+03+04 para UN cierre
    con estado_final == ERROR_REVISAR, MÁS una clave "correccion": el
    schema completo de HANDOFF §16.3 (dict) autorizado por el auditor
    humano, o None si todavía no se aportó ninguna decisión (el cierre
    sigue pendiente, sin reprocesar — nunca se inventa una corrección).

    `caja`: igual criterio que v3.motor.ejecutar_motor_cierre — si el item
    ya trae `"caja"` (típicamente propagada por el Módulo 03/MOTOR), esa
    identidad gana sobre el parámetro del lote: una corrección sobre un
    cierre de América SIEMPRE se reprocesa como América, nunca cae
    silenciosamente a TIQUIPAYA. Sin `caja` (ni en el item ni en el
    parámetro), comportamiento histórico exacto (TIQUIPAYA).

    Nunca lanza: cualquier problema se refleja en el resultado de ESTE
    cierre, sin afectar al resto del lote (ver ejecutar_revision)."""
    fecha = item.get("fecha")
    correccion = item.get("correccion")
    caja_resuelta = cfg.resolver_caja(item.get("caja") or caja)

    def _salida(correccion_aplicada, correccion_valida, campos_corregidos,
                resultado_reproceso, mensaje, **extra):
        # Preserva TODO lo que el item ya traía de los Módulos 01-04
        # (archivo_esperado, estado_ingesta, estado_materializacion,
        # ruta_cierre_local/ruta_maestro_local/ruta_template_sap_local/
        # ruta_markers_local) — sin este "carry-forward", el Módulo 06
        # (PUBLICACION) no tendría ruta_cierre_local para calcular el
        # SHA256 del reproceso (incompatibilidad real encontrada en
        # FASE 8, corregida aquí y no en el llamador).
        mensajes = list(item.get("mensajes") or [])
        mensajes.append(mensaje)
        # "quién corrigió": viene del propio schema de la corrección
        # (correccion["usuario_auditor"], HANDOFF §16.3) cuando SÍ se
        # aplicó una corrección — nunca se inventa un usuario.
        usuario_auditor = (correccion.get("usuario_auditor") if isinstance(correccion, dict) else None) \
            or item.get("usuario_auditor")

        base = dict(item)
        base.pop("correccion", None)  # ya se consumió; no tiene sentido reenviarla aguas abajo
        base.update({
            "fecha": fecha, "correccion_aplicada": correccion_aplicada,
            "correccion_valida": correccion_valida, "campos_corregidos": campos_corregidos,
            "resultado_reproceso": resultado_reproceso, "diferencia": None, "bloqueadores": None,
            "ruta_resultado": None, "ruta_sap": None, "cargo": None, "haber": None,
            "version_correccion": None, "ruta_correccion_guardada": None,
            "usuario_auditor": usuario_auditor, "mensaje": mensaje, "mensajes": mensajes,
            "caja": caja_resuelta.codigo,
        })
        base.update(extra)
        return base

    if correccion is None:
        return _salida(False, None, [], None, "Sin corrección aportada: el cierre permanece en ERROR_REVISAR, pendiente de decisión del auditor.")

    campo_solicitado = [correccion.get("campo_corregido")] if isinstance(correccion, dict) else []

    # 1) Validar SCHEMA (campos permitidos por categoría, importe NUNCA
    #    corregible, version_correccion consistente) — REUTILIZADO tal
    #    cual. Rechaza aquí cualquier campo no autorizado o un importe.
    try:
        version_correccion = correcciones.validar_schema_correccion(correccion)
    except ValueError as exc:
        codigo, _, detalle = str(exc).partition(":")
        return _salida(False, False, campo_solicitado, None, f"{codigo}: {detalle or exc}")

    ruta_cierre = item.get("ruta_cierre_local")
    ruta_maestro = item.get("ruta_maestro_local")
    ruta_plantilla = item.get("ruta_template_sap_local")
    if not ruta_cierre or not ruta_maestro or not ruta_plantilla:
        return _salida(False, False, campo_solicitado, None,
                        "MATERIALIZACION_INCOMPLETA: faltan rutas locales para reprocesar.")

    # 2) SHA256 del .xlsm ACTUAL debe coincidir con el declarado en la
    #    corrección (CORRECCION_HUERFANA si no) — REUTILIZADO tal cual.
    #    Esta llamada solo LEE el archivo (hashlib), nunca lo abre en
    #    modo escritura.
    try:
        hash_actual = correcciones.validar_sha256_origen(ruta_cierre, correccion.get("sha256_origen"))
    except ValueError as exc:
        codigo, _, detalle = str(exc).partition(":")
        return _salida(False, False, campo_solicitado, None, f"{codigo}: {detalle or exc}")

    # 3) CONTRACT-014: un cierre ya publicado nunca admite corrección
    #    nueva — reutiliza run_batch.cargar_marcadores_procesados() sobre
    #    los marcadores YA materializados en DEV por el Módulo 02.
    ya_publicado = False
    ruta_markers = item.get("ruta_markers_local")
    if ruta_markers:
        hashes_procesados, _registros, _adv, _usado = run_batch.cargar_marcadores_procesados(ruta_markers)
        ya_publicado = hash_actual in hashes_procesados

    # 4) Rutas de reproceso SIEMPRE bajo REPROCESOS/ del directorio DEV
    #    (nunca sobre el resultado/SAP originales) — REUTILIZADO tal cual
    #    de aplicar_correccion.py.
    fecha_correccion = correccion.get("fecha_cierre") or fecha
    ruta_resultado_reproceso, ruta_sap_reproceso = aplicar_cli._rutas_reproceso(
        os.path.join(base_dir_dev, "resultados"), os.path.join(base_dir_dev, "salidas"),
        fecha_correccion, version_correccion,
    )
    _verificar_contenido_en_base_dir(ruta_resultado_reproceso, base_dir_dev)
    _verificar_contenido_en_base_dir(ruta_sap_reproceso, base_dir_dev)
    os.makedirs(os.path.dirname(ruta_resultado_reproceso), exist_ok=True)
    os.makedirs(os.path.dirname(ruta_sap_reproceso), exist_ok=True)

    metadata_cabecera = run_batch.construir_metadata_cabecera(fecha_correccion, caja_resuelta)
    version_codigo = version_codigo or run_batch._resolver_version_codigo(None)

    try:
        resultado = pipeline.procesar_cierre_con_correccion(  # LA MISMA funcion que usa aplicar_correccion.py
            ruta_cierre=ruta_cierre, ruta_maestro=ruta_maestro, ruta_plantilla_sap=ruta_plantilla,
            ruta_sap_salida=ruta_sap_reproceso, metadata_cabecera=metadata_cabecera,
            version_codigo=version_codigo, correccion=correccion,
            ruta_resultado=ruta_resultado_reproceso, ya_publicado=ya_publicado,
            caja=caja_resuelta,
        )
    except ValueError as exc:  # CIERRE_YA_PUBLICADO_NO_CORREGIBLE, CORRECCION_*, etc.
        codigo, _, detalle = str(exc).partition(":")
        return _salida(False, False, campo_solicitado, None, f"{codigo}: {detalle or exc}")
    except Exception as exc:  # aislamiento tecnico: nunca se propaga fuera de este cierre
        return _salida(False, False, campo_solicitado, None, f"{type(exc).__name__}: {exc}")

    resultado_json = resultado.get("resultado_json") or {}

    # 5) Reutiliza el MISMO clasificador del Módulo 04 (no una segunda
    #    clasificación paralela) para decidir si el reproceso queda
    #    LISTO_PARA_PUBLICAR o sigue ERROR_REVISAR/ERROR_TECNICO — esa
    #    es la metadata que el futuro Módulo 06 necesita.
    item_para_clasificar = {
        "fecha": fecha, "estado_ingesta": "ENCONTRADO", "estado_materializacion": "MATERIALIZADO",
        "estado_motor": MOTOR_PROCESADO,
        "resultado": _ESTADO_MOTOR_MAP_RESULTADO.get(resultado["estado"], resultado["estado"]),
        "diferencia": resultado_json.get("diferencia_asiento") or resultado_json.get("diferencia"),
        "bloqueadores": resultado_json.get("blockers"),
        "ruta_resultado": resultado.get("ruta_resultado_json"),
        "ruta_sap": resultado_json.get("sap_archivo"),
        "cargo": resultado_json.get("cargo"),
        "haber": resultado_json.get("haber"),
    }
    clasificacion = clasificar_cierre(item_para_clasificar)

    # 6) Trazabilidad: registra la corrección APARTE del resultado/SAP del
    #    reproceso (CORRECCION_<hash>_<version>.json + fila append-only en
    #    HISTORICO_CORRECCIONES.csv) — REUTILIZADO tal cual de
    #    aplicar_correccion.py. Opcional (si no se pasa controles_dir_dev,
    #    simplemente no se registra, igual que aplicar_correccion.py sin
    #    --controles-dir).
    ruta_correccion_guardada = None
    if controles_dir_dev:
        _verificar_contenido_en_base_dir(controles_dir_dev, base_dir_dev)
        ruta_correccion_guardada, _nueva = aplicar_cli._registrar_trazabilidad(
            controles_dir_dev, correccion, hash_actual, version_correccion,
            clasificacion["estado_final"], item_para_clasificar["ruta_resultado"],
            item_para_clasificar["ruta_sap"],
        )

    return _salida(
        True, True, campo_solicitado, clasificacion["estado_final"],
        f"Corrección aplicada y reprocesada: {clasificacion['estado_final']}.",
        diferencia=item_para_clasificar["diferencia"], bloqueadores=item_para_clasificar["bloqueadores"],
        ruta_resultado=item_para_clasificar["ruta_resultado"], ruta_sap=item_para_clasificar["ruta_sap"],
        cargo=item_para_clasificar["cargo"], haber=item_para_clasificar["haber"],
        version_correccion=version_correccion, ruta_correccion_guardada=ruta_correccion_guardada,
    )


def ejecutar_revision(cierres_con_correccion, base_dir_dev, version_codigo=None, controles_dir_dev=None, caja=None):
    """Aplica revisar_y_corregir_cierre() a cada item del lote. Un error en
    UNA corrección nunca detiene el resto (mismo criterio de aislamiento
    que los módulos 01-03).

    `caja`: default de lote (propagado a cada item que no traiga ya su
    propia `caja`); ver revisar_y_corregir_cierre()."""
    resultados = []
    for item in cierres_con_correccion:
        try:
            resultados.append(revisar_y_corregir_cierre(item, base_dir_dev, version_codigo, controles_dir_dev, caja))
        except Exception as exc:  # red de seguridad adicional a nivel de lote
            caja_resuelta = cfg.resolver_caja(item.get("caja") or caja)
            resultados.append({
                "fecha": item.get("fecha"), "correccion_aplicada": False, "correccion_valida": False,
                "campos_corregidos": [], "resultado_reproceso": None, "diferencia": None,
                "bloqueadores": None, "ruta_resultado": None, "ruta_sap": None, "cargo": None,
                "haber": None, "version_correccion": None, "ruta_correccion_guardada": None,
                "mensaje": f"{type(exc).__name__}: {exc}", "caja": caja_resuelta.codigo,
            })
    return resultados


# ---------------------------------------------------------------------------
# CLI — mismo patrón Python-es-la-unica-autoridad de los módulos anteriores.
# ---------------------------------------------------------------------------

def main(argv=None):
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Modulo 05 REVISION/CORRECCION de V3 (DEV, adaptador sobre V2).")
    parser.add_argument("--input", required=True, help="JSON {'cierres_con_correccion':[...], 'base_dir_dev':str, 'version_codigo':str|null, 'controles_dir_dev':str|null, 'caja':str|null}")
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)

    with open(args.input, "r", encoding="utf-8") as f:
        datos = json.load(f)

    resultado = ejecutar_revision(
        datos["cierres_con_correccion"], datos["base_dir_dev"], datos.get("version_codigo"),
        datos.get("controles_dir_dev"), datos.get("caja"),
    )
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump({"resultado": "OK", "cierres": resultado}, f, ensure_ascii=False, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
