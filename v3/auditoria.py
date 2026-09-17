"""v3/auditoria.py — Módulo 07 · AUDITORIA de Caja Tiquipaya V3 (FASE 5,
séptima etapa del flujo DIARIO; FASE 12 agrega el cierre MENSUAL).

PRINCIPIO: AUDITORÍA NO DECIDE. Solo observa, consolida y deja evidencia.
Este módulo NUNCA cambia diferencia, bloqueadores, clasificación,
correcciones, SAP ni estado de publicación — únicamente LEE lo que los
módulos 01-06 (diario) o GLOBAL (mensual) ya decidieron y lo consolida en
un registro trazable.

Reutiliza, sin modificar ni reinterpretar, exclusivamente:

  - control_asignaciones.aplicar_correcciones_global()  (CONTROL 1 —
    CONTRACT-015: corrección todo-o-nada sobre el GLOBAL, solo columna R)
  - control_asignaciones.ejecutar_control()             (CONTROL 1 completo:
    detección de duplicados/históricos + REVISION_ASIGNACIONES_<PERIODO>
    + corrección autorizada + HISTORICO_ASIGNACIONES.csv — FASE 12)
  - control_cxc_cxp._estado_idempotencia()              (CONTROL 3 —
    CONTRACT-017: idempotencia por periodo+SHA, nunca por campos mutables)
  - control_cxc_cxp.ejecutar_control()                  (CONTROL 3 completo:
    saldos CxC/CxP acumulados, ABIERTO/CERRADO/REVISAR, reporte Excel +
    histórico técnico — FASE 12)
  - consolidador_mensual.ejecutar_consolidacion()        (GLOBAL: SAP diarios
    oficiales -> SAP_GLOBAL_TIQ_<MES>_<AÑO>.xlsx, sin duplicar, sin tocar
    los SAP diarios — FASE 12)
  - pipeline_tiquipaya.calcular_sha256()                (solo lectura, para
    completar el SHA256 de trazabilidad cuando el item no lo trae ya)

Ninguna de estas funciones se reimplementa: v3.auditoria expone
delegados delgados que llaman exactamente a la función real de V2 y
devuelven su resultado tal cual, para que este módulo pueda dejar
constancia de "qué controles se ejecutaron" sin crear una segunda versión
paralela de GLOBAL, CONTROL 1 ni de CONTROL 3.

SEPARACIÓN DIARIO / MENSUAL (FASE 12, ver auditoria_v2/ y HANDOFF_CODE_V2.md
para el diseño original de V2):

  DIARIO   (cada cierre): 01 INGESTA -> ... -> 06 PUBLICACION -> aquí,
           `consolidar_auditoria_cierre`/`consolidar_auditoria_lote`.
           CONTROL 1 y CONTROL 3 NUNCA se ejecutan en este camino.

  MENSUAL  (una vez cerrado el mes): SAP_TIQ_DD-MM-YYYY.xlsx ya publicados
           -> `generar_global_mensual` -> `ejecutar_control1_mensual` ->
           `ejecutar_control3_mensual` -> `ejecutar_cierre_mensual` (los
           encadena y deja el consolidado final). Estas funciones solo se
           invocan cuando el auditor decide cerrar el mes — nunca desde el
           flujo diario.

CONTROL 2 (anulaciones/refacturaciones) NO vive en este archivo ni en este
repositorio: sigue funcionando por su flujo separado ya existente, fuera de
V3. Conceptualmente antecede a GLOBAL — cualquier anulación/refacturación
del mes debe quedar reflejada en el SAP diario correspondiente ANTES de
correr `generar_global_mensual`, porque `consolidador_mensual` copia las
partidas de cada SAP diario tal cual (nunca reinterpreta ni ajusta nada).
"""

import json
import os
import sys
import types
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pipeline_tiquipaya as pipeline  # noqa: E402  (reutilizado tal cual, solo lectura)
import consolidador_mensual  # noqa: E402  (reutilizado tal cual — GLOBAL mensual)
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
# CIERRE MENSUAL (FASE 12) — GLOBAL -> CONTROL 1 -> CONTROL 3 -> consolidado.
# Nada de esto se ejecuta desde el flujo DIARIO (ver docstring del módulo).
# ---------------------------------------------------------------------------

def generar_global_mensual(anio, mes, sap_dir, plantilla, salida,
                            archivos_lista=None, force=False):
    """GLOBAL — delega EXACTAMENTE en
    consolidador_mensual.ejecutar_consolidacion() (V2, sin cambios): usa
    solo los SAP_TIQ_DD-MM-YYYY.xlsx del periodo pedido, ignora los de
    otro mes, detecta duplicados (idénticos se ignoran en silencio,
    distintos BLOQUEAN la consolidación), valida estructura/cuadre de
    cada SAP diario, y nunca abre un SAP diario ni la plantilla en modo
    escritura. Este wrapper NO reinterpreta nada de eso.

    Único agregado de V3 (consolidador_mensual.py no lo calculaba):
    `fechas_faltantes` — compara los SAP realmente incluidos contra el
    calendario completo del mes y lista, en ISO, los días que no tienen
    un SAP_TIQ_DD-MM-YYYY.xlsx correspondiente. Es informativo: nunca
    bloquea la generación del GLOBAL (un mes puede cerrar legítimamente
    con días sin cierre — feriados, domingos, etc.) — el auditor decide
    si esas fechas faltantes son esperadas o requieren investigación.

    Único otro agregado: se asegura que exista el directorio destino de
    `salida` (consolidador_mensual.py asume que ya existe, igual que
    `--salida-json` implícito junto a ella); nunca crea ni toca nada
    dentro de `sap_dir` ni de la plantilla."""
    os.makedirs(os.path.dirname(os.path.abspath(salida)) or ".", exist_ok=True)
    args = types.SimpleNamespace(
        anio=anio, mes=mes, sap_dir=sap_dir, plantilla=plantilla,
        salida=salida, archivos_lista=archivos_lista, force=force,
    )
    resultado = consolidador_mensual.ejecutar_consolidacion(args)

    incluidos = set(resultado.get("sap_incluidos") or [])
    ultimo_dia = consolidador_mensual.ultimo_dia_mes(anio, mes).day
    fechas_faltantes = [
        f"{anio:04d}-{mes:02d}-{dia:02d}"
        for dia in range(1, ultimo_dia + 1)
        if f"SAP_TIQ_{dia:02d}-{mes:02d}-{anio}.xlsx" not in incluidos
    ]
    resultado["fechas_faltantes"] = fechas_faltantes
    return resultado


def ejecutar_control1_mensual(ruta_global, ruta_historico, **kwargs):
    """CONTROL 1 — delega EXACTAMENTE en control_asignaciones.ejecutar_control()
    (V2, sin cambios): detecta asignaciones (ZUONR) duplicadas/históricas
    en el GLOBAL, genera/actualiza REVISION_ASIGNACIONES_<PERIODO>.xlsx
    para que el auditor valide cada alerta, y SOLO corrige el GLOBAL
    (columna R, todo-o-nada) cuando todas las alertas del periodo ya
    fueron resueltas. Deja trazabilidad completa en
    HISTORICO_ASIGNACIONES.csv. `**kwargs` acepta los mismos parámetros
    opcionales que la función de V2 (nombre_archivo_global,
    directorio_revision, ruta_revision_json, dry_run, ...)."""
    return ctrl1.ejecutar_control(ruta_global, ruta_historico, **kwargs)


def ejecutar_control3_mensual(ruta_global, ruta_historico, **kwargs):
    """CONTROL 3 — delega EXACTAMENTE en control_cxc_cxp.ejecutar_control()
    (V2, sin cambios): lee el MISMO GLOBAL (ya corregido por CONTROL 1 si
    aplicó), acumula saldos CxC/CxP transitorios, clasifica cada llave
    ABIERTO/CERRADO/REVISAR, y genera el reporte Excel + histórico
    técnico para el auditor. Nunca modifica el GLOBAL. `**kwargs` acepta
    los mismos parámetros opcionales que la función de V2
    (nombre_archivo_global, ruta_salida_xlsx, ruta_observaciones_json,
    dry_run, ...)."""
    return ctrl3.ejecutar_control(ruta_global, ruta_historico, **kwargs)


def ejecutar_cierre_mensual(anio, mes, sap_dir, plantilla, salida_global,
                             ruta_historico_control1, ruta_historico_control3,
                             base_dir_dev, archivos_lista=None, force=False,
                             control1_kwargs=None, control3_kwargs=None):
    """Orquesta el CIERRE MENSUAL completo: GLOBAL -> CONTROL 1 -> CONTROL 3
    -> consolidado final. Cada paso delega en el módulo V2 ya validado
    (ver funciones de arriba); este orquestador solo encadena resultados
    y deja evidencia — AUDITORIA NO DECIDE, igual que en el flujo diario.

    CONTROL 1 y CONTROL 3 SOLO se ejecutan si GLOBAL se generó sin
    blockers (`estado == 'VALIDADO_PENDIENTE_PUBLICACION'`): nunca se
    corre un control de auditoría sobre un GLOBAL descuadrado, incompleto
    o con un duplicado sin resolver. CONTROL 3 lee el MISMO archivo que
    generó GLOBAL — si CONTROL 1 lo corrigió in-place (columna R),
    CONTROL 3 ya ve esa corrección, igual que un auditor humano en V2."""
    resultado_global = generar_global_mensual(
        anio, mes, sap_dir, plantilla, salida_global, archivos_lista, force
    )

    resultado_control1 = None
    resultado_control3 = None

    if resultado_global.get("estado") == "VALIDADO_PENDIENTE_PUBLICACION":
        resultado_control1 = ejecutar_control1_mensual(
            resultado_global["ruta_global_generado"], ruta_historico_control1,
            **(control1_kwargs or {}),
        )
        resultado_control3 = ejecutar_control3_mensual(
            resultado_global["ruta_global_generado"], ruta_historico_control3,
            **(control3_kwargs or {}),
        )

    ahora = datetime.now(timezone.utc)
    consolidado = {
        "anio": anio, "mes": mes,
        "timestamp_cierre_mensual": ahora.isoformat(),
        "global": resultado_global,
        "control1": resultado_control1,
        "control3": resultado_control3,
    }
    nombre = f"AUDITORIA_MENSUAL_{anio:04d}-{mes:02d}_{ahora.strftime('%Y%m%dT%H%M%S%f')}.json"
    ruta_consolidado = os.path.join(base_dir_dev, "auditoria_mensual", nombre)
    _verificar_contenido_en_base_dir(ruta_consolidado, base_dir_dev)
    os.makedirs(os.path.dirname(ruta_consolidado), exist_ok=True)
    with open(ruta_consolidado, "w", encoding="utf-8") as f:
        json.dump(consolidado, f, ensure_ascii=False, indent=2, default=str)

    consolidado["ruta_consolidado"] = ruta_consolidado
    return consolidado


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
