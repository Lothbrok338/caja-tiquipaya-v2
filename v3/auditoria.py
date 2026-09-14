"""v3/auditoria.py — Módulo 07 · AUDITORIA de Caja Tiquipaya V3 (FASE 5,
séptima y última etapa funcional).

PRINCIPIO: AUDITORÍA NO DECIDE. Solo observa, consolida y deja evidencia.
Este módulo NUNCA cambia diferencia, bloqueadores, clasificación,
correcciones, SAP ni estado de publicación — únicamente LEE lo que los
módulos 01-06 ya decidieron y lo consolida en un registro trazable.

Reutiliza, sin modificar ni reinterpretar, exclusivamente:

  - control_asignaciones.aplicar_correcciones_global()  (CONTROL 1 —
    CONTRACT-015: corrección todo-o-nada sobre el GLOBAL, solo columna R)
  - control_cxc_cxp._estado_idempotencia()              (CONTROL 3 —
    CONTRACT-017: idempotencia por periodo+SHA, nunca por campos mutables)
  - pipeline_tiquipaya.calcular_sha256()                (solo lectura, para
    completar el SHA256 de trazabilidad cuando el item no lo trae ya)

Ninguna de estas funciones se reimplementa: v3.auditoria expone
delegados delgados (`ejecutar_control1_correccion`,
`evaluar_control3_idempotencia`) que llaman exactamente a la función real
de V2 y devuelven su resultado tal cual, para que este módulo pueda dejar
constancia de "qué controles se ejecutaron" sin crear una segunda versión
paralela de CONTROL 1 ni de CONTROL 3.
"""

import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pipeline_tiquipaya as pipeline  # noqa: E402  (reutilizado tal cual, solo lectura)
import control_asignaciones as ctrl1  # noqa: E402  (reutilizado tal cual — CONTROL 1)
import control_cxc_cxp as ctrl3  # noqa: E402  (reutilizado tal cual — CONTROL 3)
from v3.materializacion import _verificar_contenido_en_base_dir  # noqa: E402


# ---------------------------------------------------------------------------
# CONTROL 1 / CONTROL 3 — delegados tal cual, cero reinterpretacion.
# ---------------------------------------------------------------------------

def ejecutar_control1_correccion(ruta_global, correcciones):
    """CONTROL 1 (CONTRACT-015). Delega EXACTAMENTE en
    control_asignaciones.aplicar_correcciones_global(): todo-o-nada,
    verificacion celula por celula, solo columna R. Puede lanzar
    CorreccionInvalidaError — se propaga tal cual, sin capturarla aqui,
    porque decidir que hacer ante un rechazo es responsabilidad del
    llamador (auditoria no decide)."""
    return ctrl1.aplicar_correcciones_global(ruta_global, correcciones)


def evaluar_control3_idempotencia(historico_dict, libro_periodos, periodo, sha_actual):
    """CONTROL 3 (CONTRACT-017). Delega EXACTAMENTE en
    control_cxc_cxp._estado_idempotencia(): la decision de idempotencia
    es SIEMPRE periodo+SHA, nunca un campo mutable del historico."""
    return ctrl3._estado_idempotencia(historico_dict, libro_periodos, periodo, sha_actual)


def _consolidar_controles(control1_resultado=None, control3_resultado=None):
    """Empaqueta (sin modificar ni reinterpretar) los resultados que el
    llamador YA obtuvo de CONTROL 1/CONTROL 3, para dejarlos trazables en
    el consolidado del lote. No re-ejecuta nada."""
    controles = []
    if control1_resultado is not None:
        controles.append({"control": "CONTROL_1", "resultado": control1_resultado})
    if control3_resultado is not None:
        controles.append({"control": "CONTROL_3", "resultado": control3_resultado})
    return controles


# ---------------------------------------------------------------------------
# Consolidacion de auditoria por cierre / por lote.
# ---------------------------------------------------------------------------

_CAMPOS_TRAZABLES = (
    "fecha", "archivo_esperado", "estado_ingesta", "estado_materializacion",
    "estado_motor", "estado_final", "requiere_revision", "correccion_aplicada",
    "resultado_reproceso", "estado_publicacion", "publicado",
    "ruta_resultado", "ruta_sap", "ruta_marker",
)


def _recolectar_mensajes(item):
    """Reune, sin alterarlos, los mensajes/errores que cada etapa 01-06 ya
    haya dejado en el item combinado — nunca inventa ni resume nada."""
    mensajes = list(item.get("mensajes") or [])
    if item.get("mensaje") and item.get("mensaje") not in mensajes:
        mensajes.append(item["mensaje"])
    return mensajes


def consolidar_auditoria_cierre(item, base_dir_dev, usuario_auditor=None):
    """`item`: registro combinado de los módulos 01-06 para UN cierre (lo
    que cada módulo ya calculó — nunca se recalcula ni se reinterpreta
    aquí). Escribe AUDITORIA_<fecha>_<sha256>.json en
    base_dir_dev/auditoria/ y devuelve el mismo registro.

    Si el item no trae ya un `sha256` (p. ej. Módulo 06 lo expone en su
    salida), se completa leyendo el .xlsm original SOLO por hash
    (pipeline.calcular_sha256, jamas escritura) cuando hay
    `ruta_cierre_local` disponible — nunca se fabrica un hash.

    Nunca lanza: cualquier problema se refleja en el registro de ESTE
    cierre (ver consolidar_auditoria_lote para el aislamiento de lote)."""
    fecha = item.get("fecha")
    sha256 = item.get("sha256")
    if not sha256 and item.get("ruta_cierre_local") and os.path.isfile(item["ruta_cierre_local"]):
        sha256 = pipeline.calcular_sha256(item["ruta_cierre_local"])

    registro = {campo: item.get(campo) for campo in _CAMPOS_TRAZABLES}
    registro["sha256"] = sha256
    registro["usuario_auditor"] = item.get("usuario_auditor") or usuario_auditor
    registro["mensajes"] = _recolectar_mensajes(item)
    registro["timestamp_auditoria"] = datetime.now(timezone.utc).isoformat()

    nombre = f"AUDITORIA_{fecha or 'SIN_FECHA'}_{sha256 or 'SIN_HASH'}.json"
    ruta_auditoria = os.path.join(base_dir_dev, "auditoria", nombre)
    _verificar_contenido_en_base_dir(ruta_auditoria, base_dir_dev)
    os.makedirs(os.path.dirname(ruta_auditoria), exist_ok=True)
    with open(ruta_auditoria, "w", encoding="utf-8") as f:
        json.dump(registro, f, ensure_ascii=False, indent=2)

    registro["ruta_auditoria"] = ruta_auditoria
    return registro


def consolidar_auditoria_lote(cierres, base_dir_dev, usuario_auditor=None,
                               control1_resultado=None, control3_resultado=None):
    """Aplica consolidar_auditoria_cierre() a cada item del lote y escribe
    ademas un consolidado AUDITORIA_LOTE_<timestamp>.json con TODOS los
    cierres. Un error en UNO nunca detiene el resto (mismo criterio de
    aislamiento que los modulos 01-06)."""
    registros = []
    for item in cierres:
        try:
            registros.append(consolidar_auditoria_cierre(item, base_dir_dev, usuario_auditor))
        except Exception as exc:  # aislamiento tecnico: nunca se propaga fuera de este cierre
            registros.append({
                "fecha": item.get("fecha"), "sha256": item.get("sha256"),
                "error_auditoria": f"{type(exc).__name__}: {exc}",
            })

    ahora = datetime.now(timezone.utc)
    consolidado = {
        "timestamp_lote": ahora.isoformat(),
        "total_cierres": len(cierres),
        "controles_ejecutados": _consolidar_controles(control1_resultado, control3_resultado),
        "cierres": registros,
    }
    nombre_lote = f"AUDITORIA_LOTE_{ahora.strftime('%Y%m%dT%H%M%S%f')}.json"
    ruta_lote = os.path.join(base_dir_dev, "auditoria", nombre_lote)
    _verificar_contenido_en_base_dir(ruta_lote, base_dir_dev)
    os.makedirs(os.path.dirname(ruta_lote), exist_ok=True)
    with open(ruta_lote, "w", encoding="utf-8") as f:
        json.dump(consolidado, f, ensure_ascii=False, indent=2)

    return {"ruta_lote": ruta_lote, "cierres": registros, "total_cierres": len(cierres)}


# ---------------------------------------------------------------------------
# CLI — mismo patrón Python-es-la-unica-autoridad de los módulos anteriores.
# ---------------------------------------------------------------------------

def main(argv=None):
    import argparse

    parser = argparse.ArgumentParser(description="Modulo 07 AUDITORIA de V3 (DEV, adaptador sobre V2).")
    parser.add_argument("--input", required=True,
                         help="JSON {'cierres':[...], 'base_dir_dev':str, 'usuario_auditor':str|null, "
                              "'control1_resultado':object|null, 'control3_resultado':object|null}")
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)

    with open(args.input, "r", encoding="utf-8") as f:
        datos = json.load(f)

    resultado = consolidar_auditoria_lote(
        datos["cierres"], datos["base_dir_dev"], datos.get("usuario_auditor"),
        datos.get("control1_resultado"), datos.get("control3_resultado"),
    )
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump({"resultado": "OK", **resultado}, f, ensure_ascii=False, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
