"""v3/dev_api.py — Backend DEV (API de lotes) de Caja Tiquipaya V3 (FASE 9).

Conecta n8n_frontend/v3_control_cierres.html con los 7 módulos v3.* ya
construidos (FASE 5-8), detrás de un contrato JSON estable por LOTE.
NINGUNA regla de negocio nueva vive aquí: este módulo únicamente

  1. encadena las funciones YA EXISTENTES (ejecutar_ingesta,
     ejecutar_materializacion, ejecutar_motor, ejecutar_clasificacion,
     revisar_y_corregir_cierre, publicar_lote, consolidar_auditoria_lote)
     exactamente como ya lo hace el workflow principal de n8n (FASE 8);
  2. persiste el estado de un lote en `base_dir_dev/lotes/LOTE_<id>.json`
     para que llamadas HTTP separadas (procesar → estado → datos →
     corregir → publicar) puedan referirse al mismo lote entre requests;
  3. completa, del lado servidor, los campos TÉCNICOS de una corrección
     (sha256_origen, version_correccion, fecha_hora) que el navegador
     NUNCA debe calcular — reutiliza `correcciones_tiquipaya.
     calcular_sha256_archivo()`/`calcular_version_correccion()` tal cual.

n8n invoca cada acción de este módulo con el MISMO patrón Execute-Command
+ base64 que ya usan los 7 subworkflows: cada webhook bajo
`/webhook/tiq-v3-dev/*` arma un JSON mínimo desde el body/query del
request (sin lógica de negocio en ese Code node), lo pasa por aquí como
CLI, y devuelve la salida tal cual.

CONTRACT-011 (procesar y publicar separados): `crear_lote_pendiente()` y
`procesar_lote()` nunca publican nada. `publicar_seleccionados()` es la
ÚNICA función de este módulo que puede terminar en un cierre PUBLICADO,
y solo publica fechas que ya llegaron a un estado publicable — cualquier
fecha pedida que no lo esté se reporta en `omitidos`, nunca se publica.
"""

import json
import os
import shutil
import sys
import uuid
from datetime import datetime, timezone
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import run_batch  # noqa: E402  (reutilizado tal cual: generar_rango_fechas)
import excel_io  # noqa: E402  (reutilizado tal cual: money_str)
import correcciones_tiquipaya as correcciones  # noqa: E402  (reutilizado tal cual)
from v3.materializacion import _verificar_contenido_en_base_dir  # noqa: E402
from v3.ingesta import ejecutar_ingesta, ENCONTRADO as _INGESTA_ENCONTRADO  # noqa: E402
from v3.materializacion import ejecutar_materializacion  # noqa: E402
from v3.motor import ejecutar_motor  # noqa: E402
from v3.precheck_maestro import aplicar_precheck_maestro, filtrar_aptos_para_motor  # noqa: E402
from v3.clasificacion import ejecutar_clasificacion, LISTO_PARA_PUBLICAR, ERROR_REVISAR  # noqa: E402
from v3.revision import revisar_y_corregir_cierre  # noqa: E402
from v3.publicacion import publicar_lote  # noqa: E402
from v3.auditoria import (  # noqa: E402
    consolidar_auditoria_lote,
    generar_global_mensual, ejecutar_control1_mensual, ejecutar_control3_mensual,
)
import consolidador_mensual  # noqa: E402  (reutilizado tal cual — solo para nombre_sap_global)
import control_asignaciones as _ctrl1_v2  # noqa: E402  (V2, sin cambios — solo lectura del historico para la guardia de cierre)
from v3 import control1_modos  # noqa: E402


PROCESANDO = "PROCESANDO"
LISTO_LOTE = "LISTO_PARA_REVISION_O_PUBLICACION"
ERROR_LOTE = "ERROR"


class LoteNoEncontradoError(ValueError):
    pass


class CierreNoEnLoteError(ValueError):
    pass


class IngestaDriveRequeridaError(ValueError):
    """FASE 11A.3 — en modo oficial (`requiere_ingesta_drive=True`), /procesar
    NUNCA cae al listado local (os.listdir) si la ingesta Drive real no
    llegó o algún cierre ENCONTRADO no trae drive_file_id: se rechaza el
    lote entero con un mensaje claro para el auditor, en vez de procesar
    con un origen no verificado."""
    pass


# ---------------------------------------------------------------------------
# Persistencia del lote — el único estado que sobrevive entre llamadas HTTP.
# ---------------------------------------------------------------------------

def _ruta_lote(lote_id, base_dir_dev):
    ruta = os.path.join(base_dir_dev, "lotes", f"LOTE_{lote_id}.json")
    _verificar_contenido_en_base_dir(ruta, base_dir_dev)
    return ruta


def _leer_lote(lote_id, base_dir_dev):
    ruta = _ruta_lote(lote_id, base_dir_dev)
    if not os.path.isfile(ruta):
        raise LoteNoEncontradoError(f"LOTE_NO_ENCONTRADO:{lote_id}")
    with open(ruta, "r", encoding="utf-8") as f:
        return json.load(f)


def _escribir_lote(lote, base_dir_dev):
    ruta = _ruta_lote(lote["lote_id"], base_dir_dev)
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    lote["actualizado_en"] = datetime.now(timezone.utc).isoformat()
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(lote, f, ensure_ascii=False, indent=2)
    return lote


def _buscar_indice(lote, fecha):
    for i, c in enumerate(lote["cierres"]):
        if c.get("fecha") == fecha:
            return i
    raise CierreNoEnLoteError(f"CIERRE_NO_ENCONTRADO_EN_LOTE:{fecha}")


# ---------------------------------------------------------------------------
# PROCESAR — en 2 pasos, para no bloquear al front esperando 01→04 completo.
# ---------------------------------------------------------------------------

def crear_lote_pendiente(fecha_inicio, fecha_fin, usuario_auditor, base_dir_dev):
    """Paso 1 (rápido): registra el lote en PROCESANDO y devuelve su id de
    inmediato. n8n responde al navegador con este resultado ANTES de
    ejecutar la cadena 01→04 (ver `procesar_lote`), que sigue corriendo
    en segundo plano en la misma ejecución de n8n (nodo "Respond to
    Webhook" + nodos posteriores)."""
    lote_id = uuid.uuid4().hex[:12]
    lote = {
        "lote_id": lote_id, "fecha_inicio": fecha_inicio, "fecha_fin": fecha_fin,
        "usuario_auditor": usuario_auditor, "estado_lote": PROCESANDO,
        "creado_en": datetime.now(timezone.utc).isoformat(), "cierres": [],
    }
    _escribir_lote(lote, base_dir_dev)
    return {"lote_id": lote_id, "estado_lote": PROCESANDO}


def procesar_lote(lote_id, base_dir_dev, origen_cierres_dir, ruta_maestro_origen,
                   ruta_plantilla_origen, markers_origen_dir=None, version_codigo=None,
                   ingesta_precomputada=None, requiere_ingesta_drive=False):
    """Paso 2 (el que puede tardar): ejecuta 01 INGESTA → 02 MATERIALIZACION
    → 03 MOTOR → 04 CLASIFICACION para el rango ya registrado en el lote,
    reutilizando exactamente las mismas funciones que el resto de V3 (sin
    reimplementar nada).

    `ingesta_precomputada`: FASE 11A.2 — si se provee, DEBE ser exactamente
    la lista que devuelve v3.ingesta.ejecutar_ingesta() (fecha/
    archivo_esperado/estado_ingesta/drive_file_id/coincidencias/mensaje).
    En producción la arma el subworkflow n8n "TIQ V3 · 01 INGESTA · DEV"
    en source_mode=drive_readonly (mismo Módulo 01, nunca reimplementado
    aquí: este módulo no vuelve a decidir REGLA G ni ENCONTRADO/SIN_ARCHIVO/
    AMBIGUO, solo recibe lo que ese subworkflow ya decidió) — así
    drive_file_id llega real desde Drive en vez de None. Si es None
    (compatibilidad DEV/fixture, sin cambios de comportamiento), este
    módulo sigue construyendo `candidatos_por_fecha` listando el contenido
    de `origen_cierres_dir` (fixture DEV local) tal como hacía antes.

    `requiere_ingesta_drive`: FASE 11A.3 — cuando el backend está en modo
    oficial (publication_mode=official), el llamador (n8n) pasa True aquí.
    En ese caso el fallback local (os.listdir) queda DESHABILITADO: si
    `ingesta_precomputada` no llegó, o algún cierre en estado ENCONTRADO no
    trae `drive_file_id`, se rechaza el lote entero (IngestaDriveRequeridaError)
    ANTES de tocar materialización/motor — nunca se procesa localmente un
    cierre cuyo origen en Drive no se pudo verificar. Default False para no
    alterar el comportamiento ya validado en DEV/tests (fixture local)."""
    lote = _leer_lote(lote_id, base_dir_dev)
    try:
        mes_rango = int(lote["fecha_inicio"].split("-")[1])

        if ingesta_precomputada is not None:
            ingesta = ingesta_precomputada
        elif requiere_ingesta_drive:
            raise IngestaDriveRequeridaError(
                "INGESTA_DRIVE_REQUERIDA:No se pudo identificar el cierre original en "
                "Google Drive. Verifique la conexión y vuelva a procesar."
            )
        else:
            # origen_cierres_dir es una carpeta plana DEV (sin indexar por
            # fecha): se ofrece el MISMO listado completo a cada fecha del
            # rango — REGLA G decide con coincidencia EXACTA de nombre cuál
            # corresponde a cuál (nunca "el primero"; ver v3.ingesta).
            candidatos = sorted(os.listdir(origen_cierres_dir)) if os.path.isdir(origen_cierres_dir) else []
            fechas_rango = run_batch.generar_rango_fechas(lote["fecha_inicio"], lote["fecha_fin"])
            candidatos_por_fecha = {fecha: candidatos for fecha in fechas_rango}
            ingesta = ejecutar_ingesta(lote["fecha_inicio"], lote["fecha_fin"], candidatos_por_fecha)

        if requiere_ingesta_drive:
            sin_file_id = [
                c.get("fecha") for c in ingesta
                if c.get("estado_ingesta") == _INGESTA_ENCONTRADO and not c.get("drive_file_id")
            ]
            if sin_file_id:
                raise IngestaDriveRequeridaError(
                    "INGESTA_DRIVE_REQUERIDA:No se pudo identificar el cierre original en "
                    "Google Drive. Verifique la conexión y vuelva a procesar. "
                    f"(fechas sin drive_file_id: {', '.join(sin_file_id)})"
                )

        materializados = ejecutar_materializacion(ingesta, {
            "base_dir_dev": base_dir_dev, "origen_cierres_dir": origen_cierres_dir,
            "ruta_maestro_origen": ruta_maestro_origen, "ruta_plantilla_origen": ruta_plantilla_origen,
            "markers_origen_dir": markers_origen_dir, "mes_rango": mes_rango,
        })

        # FASE 10C: precheck de cobertura del maestro, ANTES del motor (ver
        # v3/precheck_maestro.py) — v3.motor.ejecutar_motor() JAMAS recibe
        # un cierre BLOQUEADO_MAESTRO_COBERTURA_NO_CONFIRMADA (filtrado
        # aqui, no solo "no procesado" dentro del motor).
        anotados_precheck = aplicar_precheck_maestro(materializados)
        aptos_para_motor = filtrar_aptos_para_motor(anotados_precheck)
        procesados_motor = ejecutar_motor(aptos_para_motor, base_dir_dev, version_codigo)
        procesados_motor_por_fecha = {c["fecha"]: c for c in procesados_motor}
        procesados = [procesados_motor_por_fecha.get(item["fecha"], item) for item in anotados_precheck]

        clasificados = ejecutar_clasificacion(procesados)

        lote["cierres"] = clasificados
        lote["estado_lote"] = LISTO_LOTE
    except Exception as exc:  # nunca deja el lote en un estado indefinido
        lote["estado_lote"] = ERROR_LOTE
        lote["mensaje_error"] = f"{type(exc).__name__}: {exc}"

    return _escribir_lote(lote, base_dir_dev)


# ---------------------------------------------------------------------------
# ESTADO / DATOS — solo lectura del lote ya persistido.
# ---------------------------------------------------------------------------

def obtener_estado(lote_id, base_dir_dev):
    lote = _leer_lote(lote_id, base_dir_dev)
    cierres = lote.get("cierres", [])
    return {
        "lote_id": lote_id, "estado_lote": lote["estado_lote"],
        "total_cierres": len(cierres),
        "listos": sum(1 for c in cierres if c.get("estado_final") == LISTO_PARA_PUBLICAR),
        "publicados": sum(1 for c in cierres if c.get("publicado")),
        "en_revision": sum(1 for c in cierres if c.get("estado_final") == ERROR_REVISAR and c.get("resultado_reproceso") != LISTO_PARA_PUBLICAR),
        "mensaje_error": lote.get("mensaje_error"),
    }


def _leer_resultado_json(ruta_resultado):
    if not ruta_resultado or not os.path.isfile(ruta_resultado):
        return None
    with open(ruta_resultado, "r", encoding="utf-8") as f:
        return json.load(f)


def _construir_cuadre_real(resultado_json):
    """Cuadre REAL ya calculado por V2 (pipeline_tiquipaya._construir_resultado_json),
    reexpuesto tal cual — nunca se inventa ni se recalcula ningún importe
    aquí. La única excepción es `recaudacion_explicada`: V2 SÍ la calcula
    (motor_tiquipaya.ejecutar_v2, ETAPA 4 — `recaudacion_explicada` es un
    campo real de ese resultado) pero `pipeline_tiquipaya._construir_resultado_json`
    (V2, sin cambios) no la copia al `resultado_json` final. Se deriva aquí
    invirtiendo la MISMA identidad que V2 ya aplicó internamente
    (`diferencia = universo_ajustado - recaudacion_explicada`, ver
    motor_tiquipaya.py línea ~726) usando los dos valores que V2 SÍ expone
    (`universo_ajustado`, `diferencia`) — no es una regla contable nueva,
    es una resta que despeja una fórmula ya aplicada por V2."""
    if not resultado_json:
        return {}
    universo_ajustado = resultado_json.get("universo_ajustado")
    diferencia = resultado_json.get("diferencia")
    recaudacion_explicada = None
    if universo_ajustado is not None and diferencia is not None:
        recaudacion_explicada = excel_io.money_str(Decimal(universo_ajustado) - Decimal(diferencia))
    return {
        "universo_original": resultado_json.get("universo_original"),
        "alquileres": resultado_json.get("alquileres"),
        "universo_ajustado": universo_ajustado,
        "recaudacion_explicada": recaudacion_explicada,
        "diferencia": diferencia,
        "total_vouchers": resultado_json.get("total_vouchers"),
        "cantidad_vouchers": resultado_json.get("cantidad_vouchers"),
        "total_ci": resultado_json.get("total_ci"),
        "cantidad_ci": resultado_json.get("cantidad_ci"),
        "atc_bruto": resultado_json.get("atc_bruto"),
        "atc_neto": resultado_json.get("atc_neto"),
        "atc_comision": resultado_json.get("atc_comision"),
    }


def obtener_datos(lote_id, base_dir_dev):
    lote = _leer_lote(lote_id, base_dir_dev)
    cierres = lote.get("cierres", [])
    # Cuadre real (Universo/Recaudación explicada/Diferencia) por cierre,
    # para que el panel de detalle lo muestre sin volver a pedir /revisar
    # (que solo aplica a cierres que requieren revisión) — solo lectura del
    # resultado_json ya generado por el motor, nunca se recalcula nada más.
    cierres_con_cuadre = [
        dict(c, cuadre=_construir_cuadre_real(_leer_resultado_json(c.get("ruta_resultado"))))
        for c in cierres
    ]
    return {"lote_id": lote_id, "estado_lote": lote["estado_lote"], "cierres": cierres_con_cuadre}


# ---------------------------------------------------------------------------
# REVISAR — detalle de un cierre ERROR_REVISAR: excepciones REALES del
# motor V2 (resultado_json["excepciones"], nunca reinterpretadas) + los
# campos corregibles REALES (correcciones_tiquipaya.CAMPOS_CORREGIBLES,
# reutilizado tal cual, nunca retipeado en el frontend).
# ---------------------------------------------------------------------------

# CI: motor_tiquipaya.validar_ci() ya decide el "tipo" bloqueante con un
# orden de prioridad fijo (cuenta_contable primero, asignacion despues —
# ver motor_tiquipaya.py líneas 387-393: "if not cuenta_contable: ...
# elif not asignacion: ..."). Reutilizamos ese mismo código estructurado
# (nunca texto libre / motivo_legible) para señalar EXACTAMENTE el campo
# que el motor reportó como problema de ESTA excepción puntual — así, si
# una fila tuviera ambos campos vacíos a la vez, se ofrece solo el que el
# motor efectivamente evaluó primero (el otro podría volver a aparecer
# recién en un futuro reproceso, si sigue vacío tras corregir el primero).
_CI_TIPO_CAMPO = {
    "CI_CUENTA_FALTANTE": "cuenta_contable",
    "CI_ASIGNACION_FALTANTE": "asignacion",
}


def _campos_aplicables(exc, campos_permitidos):
    """Dentro de los campos PERMITIDOS por categoría (correcciones_tiquipaya.
    CAMPOS_CORREGIBLES, sin cambios), calcula cuáles corresponden a un
    problema REAL de ESTA excepción puntual — nunca interpreta texto libre
    (motivo_legible ni ningún otro): usa señales estructuradas que el motor
    ya calcula (el "tipo" de excepción para CI, ver _CI_TIPO_CAMPO; el mismo
    criterio de "faltante" que motor_tiquipaya usa para decidir el bloqueo
    de CI para cualquier otra categoría — los 4 campos de ATC son None
    cuando esa columna genuinamente no está definida para esa fila).

    VOUCHER es la única categoría que NO se filtra así: `codigo_informado`
    es siempre el campo en cuestión para cualquier tipo de excepción de
    voucher — el valor SIEMPRE está presente (es el código cuestionado),
    lo dudoso es que sea el correcto, no que falte."""
    categoria = exc.get("categoria")
    if categoria == "VOUCHER":
        return list(campos_permitidos)
    if categoria == "COMUNICACION_INTERNA":
        campo = _CI_TIPO_CAMPO.get(exc.get("tipo"))
        return [campo] if campo and campo in campos_permitidos else []
    return [campo for campo in campos_permitidos if not exc.get(campo)]


def obtener_detalle_revision(lote_id, fecha, base_dir_dev):
    """Siempre lee el resultado del reproceso MAS RECIENTE (item["ruta_resultado"]
    ya apunta a REPROCESOS/... tras una corrección aplicada — ver
    v3.revision) — nunca datos de una revisión anterior: el llamador debe
    volver a pedir este endpoint después de cada /corregir para obtener el
    estado POST-REPROCESO real, nunca reutilizar una respuesta vieja."""
    lote = _leer_lote(lote_id, base_dir_dev)
    item = lote["cierres"][_buscar_indice(lote, fecha)]

    campos_por_categoria = {cat: sorted(campos) for cat, campos in correcciones.CAMPOS_CORREGIBLES.items()}
    excepciones = []
    resultado_json = _leer_resultado_json(item.get("ruta_resultado"))
    if resultado_json:
        # Cada excepción se enriquece con `campos_corregibles_aplicables`
        # (subconjunto de los campos PERMITIDOS por categoría que realmente
        # corresponden al problema de ESA excepción puntual — ver
        # _campos_aplicables). El frontend NUNCA decide esto por su cuenta.
        excepciones = [
            dict(exc, campos_corregibles_aplicables=_campos_aplicables(exc, campos_por_categoria.get(exc.get("categoria"), [])))
            for exc in resultado_json.get("excepciones", [])
        ]
    # Cuadre REAL (Universo/Recaudación explicada/Diferencia + desglose) —
    # ver _construir_cuadre_real: nunca se inventa ni se recalcula ningún
    # importe salvo recaudacion_explicada, derivada de una identidad que V2
    # ya aplicó.
    cuadre = _construir_cuadre_real(resultado_json)

    return {
        "fecha": fecha, "estado_final": item.get("estado_final"),
        "requiere_revision": item.get("requiere_revision"), "mensaje": item.get("mensaje"),
        "diferencia": item.get("diferencia"), "bloqueadores": item.get("bloqueadores"),
        "resultado_reproceso": item.get("resultado_reproceso"),
        "correccion_aplicada": item.get("correccion_aplicada"),
        "excepciones": excepciones,
        "cuadre": cuadre,
        # CAMPOS_CORREGIBLES por categoría (referencia general, límites V2
        # sin cambios). Para el formulario, usar SIEMPRE
        # excepciones[i].campos_corregibles_aplicables — el subconjunto
        # real para esa excepción puntual.
        "campos_corregibles": campos_por_categoria,
    }


# ---------------------------------------------------------------------------
# CORREGIR — el humano decide QUÉ corregir; este módulo completa los
# campos técnicos y delega en v3.revision (que a su vez delega en
# correcciones_tiquipaya.py/pipeline_tiquipaya.py de V2, sin cambios).
# ---------------------------------------------------------------------------

def aplicar_correccion(lote_id, fecha, correccion_parcial, base_dir_dev):
    """`correccion_parcial`: lo que el auditor humano decide/observa desde
    el frontend — categoria, tipo, identificadores, campo_corregido,
    valor_original (el valor que el auditor ve en la excepción antes de
    corregir), valor_autorizado, motivo (justificación en texto libre) y
    usuario_auditor. NUNCA incluye sha256_origen, fecha_cierre, fecha_hora
    ni version_correccion — esos son responsabilidad EXCLUSIVA del
    servidor (ver abajo), para que el navegador jamás tenga que
    implementar (ni pueda falsear) el algoritmo de hashing/versionado.
    Si falta cualquier campo obligatorio (incluido valor_original/motivo),
    correcciones_tiquipaya.validar_schema_correccion() la rechaza tal cual
    lo haría para V2 — este módulo no relaja ni completa esos campos."""
    lote = _leer_lote(lote_id, base_dir_dev)
    idx = _buscar_indice(lote, fecha)
    item = lote["cierres"][idx]

    ruta_cierre = item.get("ruta_cierre_local")
    if not ruta_cierre or not os.path.isfile(ruta_cierre):
        raise ValueError("CORRECCION_SIN_CIERRE_LOCAL:no hay ruta_cierre_local materializada para esta fecha")

    correccion = dict(correccion_parcial)
    correccion.setdefault("fecha_cierre", fecha)
    correccion.setdefault("fecha_hora", datetime.now(timezone.utc).isoformat())
    correccion["sha256_origen"] = correcciones.calcular_sha256_archivo(ruta_cierre)  # SIEMPRE servidor, nunca el navegador
    correccion["version_correccion"] = correcciones.calcular_version_correccion(correccion)  # idem

    item_con_correccion = dict(item, correccion=correccion)
    resultado = revisar_y_corregir_cierre(item_con_correccion, base_dir_dev, controles_dir_dev=lote.get("controles_dir_dev"))
    lote["cierres"][idx] = resultado
    _escribir_lote(lote, base_dir_dev)
    # Cuadre real del reproceso (Universo/Recaudación explicada/Diferencia),
    # para que el frontend lo muestre de inmediato incluso cuando el
    # reproceso quedó LISTO_PARA_PUBLICAR (caso en el que nunca se vuelve a
    # pedir /revisar — ver v3_control_cierres.html::seleccionar()).
    cuadre = _construir_cuadre_real(_leer_resultado_json(resultado.get("ruta_resultado")))
    return dict(resultado, cuadre=cuadre)


# ---------------------------------------------------------------------------
# PUBLICAR — solo fechas ya publicables; cualquier otra se omite (nunca
# se publica sin que el Módulo 04/05 ya lo haya habilitado).
# ---------------------------------------------------------------------------

def publicar_seleccionados(lote_id, fechas, base_dir_dev, usuario_auditor):
    lote = _leer_lote(lote_id, base_dir_dev)
    fechas = set(fechas)
    elegibles, omitidos, indices = [], [], {}

    for i, c in enumerate(lote["cierres"]):
        if c.get("fecha") not in fechas:
            continue
        estado = c.get("resultado_reproceso") or c.get("estado_final")
        if estado == LISTO_PARA_PUBLICAR:
            elegibles.append(c)
            indices[c["fecha"]] = i
        else:
            omitidos.append({"fecha": c.get("fecha"), "motivo": f"Estado '{estado}' no habilita publicación (CONTRACT-011)."})

    publicados = publicar_lote(elegibles, base_dir_dev, usuario_auditor) if elegibles else []
    for p in publicados:
        lote["cierres"][indices[p["fecha"]]] = p

    auditoria = consolidar_auditoria_lote(lote["cierres"], base_dir_dev, usuario_auditor)
    _escribir_lote(lote, base_dir_dev)
    return {"publicados": publicados, "omitidos": omitidos, "ruta_auditoria_lote": auditoria["ruta_lote"]}


# ---------------------------------------------------------------------------
# CIERRE MENSUAL (FASE 12) — GLOBAL / CONTROL 1 / CONTROL 3. Completamente
# separado del flujo DIARIO de arriba: nada de esto se llama desde
# procesar_lote()/publicar_seleccionados(). El navegador NUNCA elige rutas
# de archivo: solo envía año/mes (y, para los controles, el JSON de
# decisiones/observaciones del auditor cuando corresponda) — las rutas
# reales (SAP oficiales ya publicados, plantilla, históricos de control)
# son constantes fijas del lado servidor, mismo criterio que el resto de
# este archivo.
# ---------------------------------------------------------------------------

def _ruta_global(base_dir_dev, anio, mes):
    return os.path.join(base_dir_dev, "global", consolidador_mensual.nombre_sap_global(anio, mes))


def _periodo(anio, mes):
    """PERIODO canonico (p.ej. 'SEPTIEMBRE_2026'), derivado del mismo nombre
    que consolidador_mensual.nombre_sap_global() ya produce — nunca una
    tabla de meses duplicada aparte."""
    nombre = consolidador_mensual.nombre_sap_global(anio, mes)
    return nombre[len("SAP_GLOBAL_TIQ_"):-len(".xlsx")]


def _validar_anio_mes(anio, mes):
    """El navegador solo manda año/mes; nunca una ruta. Se validan como
    enteros acotados antes de usarlos para construir cualquier ruta."""
    if isinstance(anio, bool) or isinstance(mes, bool) or not isinstance(anio, int) or not isinstance(mes, int):
        raise ValueError(f"PERIODO_INVALIDO: anio/mes deben ser enteros (recibido anio={anio!r}, mes={mes!r})")
    if not (2000 <= anio <= 2100) or not (1 <= mes <= 12):
        raise ValueError(f"PERIODO_INVALIDO: anio={anio}, mes={mes} fuera de rango")


def global_entrada_dir(base_dir_dev, anio, mes):
    """Snapshot temporal, AISLADO, de la carpeta SAP oficial del periodo en
    Drive: `base_dir_dev/global_entrada/<YYYY-MM>/`. Es la ÚNICA fuente de
    entrada de GLOBAL. `publicacion/sap/` (artefactos locales del flujo
    diario, con residuos de pruebas DEV) nunca se usa como entrada."""
    _validar_anio_mes(anio, mes)
    return os.path.join(base_dir_dev, "global_entrada", f"{anio:04d}-{mes:02d}")


def _limpiar_y_crear_dir_periodo(destino, base_dir_dev, etiqueta):
    """Borra ÚNICAMENTE `destino` (un directorio de materialización de UN
    periodo, creado por este backend) y lo recrea vacío. Nunca toca otro
    directorio ni Drive."""
    _verificar_contenido_en_base_dir(os.path.join(destino, "_"), base_dir_dev)
    if os.path.lexists(destino):
        if os.path.islink(destino) or not os.path.isdir(destino):
            raise RuntimeError(f"{etiqueta}_INVALIDA: {destino} no es un directorio normal")
        shutil.rmtree(destino)
    os.makedirs(destino)


def preparar_global_entrada(anio, mes, base_dir_dev):
    """Deja `global_entrada/<periodo>/` VACÍO y listo para materializar la
    carpeta SAP oficial desde Drive. Borra únicamente esa carpeta del
    periodo (nunca `publicacion/sap`, nunca otros periodos, nunca Drive):
    así ningún archivo de una corrida anterior puede contaminar GLOBAL."""
    destino = global_entrada_dir(base_dir_dev, anio, mes)
    _limpiar_y_crear_dir_periodo(destino, base_dir_dev, "GLOBAL_ENTRADA")
    return {"dir_entrada": os.path.abspath(destino), "periodo": f"{anio:04d}-{mes:02d}"}


def control1_entrada_dir(base_dir_dev, anio, mes):
    """Materialización AISLADA de las entradas de CONTROL 1 para UN periodo:
    `base_dir_dev/control1_entrada/<YYYY-MM>/`. Contiene, y solo contiene,
    lo que el backend descargó de Drive en ESA corrida (SAP_GLOBAL oficial,
    HISTORICO_ASIGNACIONES.csv si existe, REVISION_ASIGNACIONES_<periodo>.xlsx
    si existe) y lo que CONTROL 1 escribe encima (revisión, histórico,
    GLOBAL corregido). Nunca `dev_workdir/global/` ni `publicacion/`."""
    _validar_anio_mes(anio, mes)
    return os.path.join(base_dir_dev, "control1_entrada", f"{anio:04d}-{mes:02d}")


def preparar_control1_entrada(anio, mes, base_dir_dev):
    """Deja `control1_entrada/<periodo>/` VACÍO antes de materializar desde
    Drive: ningún histórico, revisión o GLOBAL local de una corrida anterior
    puede colarse en CONTROL 1."""
    destino = control1_entrada_dir(base_dir_dev, anio, mes)
    _limpiar_y_crear_dir_periodo(destino, base_dir_dev, "CONTROL1_ENTRADA")
    return {"dir_entrada": os.path.abspath(destino), "periodo": f"{anio:04d}-{mes:02d}"}


def _verificar_periodo_no_cerrado(entrada_dir, anio, mes):
    """Protección de GLOBAL tras el CIERRE DEFINITIVO de la Auditoría de
    Asignaciones. El backend descarga el histórico maestro (raíz de
    05_CONTROLES) a `global_entrada/<periodo>/HISTORICO_ASIGNACIONES.csv`
    justo antes de generar; si ese histórico ya contiene filas de
    `SAP_GLOBAL_TIQ_<MES>_<AÑO>.xlsx`, CONTROL 1 cerró el periodo y
    regenerar GLOBAL podría borrar correcciones autorizadas: se BLOQUEA (no
    hay reapertura implementada). Mientras el mes está abierto no hay filas
    de ese GLOBAL en el histórico y GLOBAL sigue siendo regenerable."""
    ruta = os.path.join(entrada_dir, "HISTORICO_ASIGNACIONES.csv")
    if not os.path.isfile(ruta):
        return
    nombre = consolidador_mensual.nombre_sap_global(anio, mes)
    if control1_modos.periodo_cerrado(_ctrl1_v2.cargar_historico(ruta), nombre):
        raise RuntimeError(
            f"PERIODO_CERRADO_CONTROL1: la Auditoría de Asignaciones de {anio:04d}-{mes:02d} ya fue cerrada "
            f"definitivamente; GENERAR GLOBAL queda bloqueado para no perder correcciones autorizadas. "
            f"La reapertura del periodo no está implementada."
        )


def generar_global(anio, mes, base_dir_dev, ruta_plantilla_origen, sap_dir=None):
    """Cierre MENSUAL — paso 1 (GENERAR GLOBAL). `sap_dir` por defecto es
    `base_dir_dev/global_entrada/<YYYY-MM>/` (ver global_entrada_dir): el
    snapshot que el backend materializó desde la carpeta SAP OFICIAL de
    Drive justo antes de esta llamada. NUNCA `publicacion/sap/`: ese
    directorio son artefactos locales del flujo diario y no representa la
    carpeta oficial (FASE 12E.3). Delega en
    v3.auditoria.generar_global_mensual() (que a su vez delega en
    v3.consolidador_mensual_v3, sobre consolidador_mensual.py V2 sin
    cambios).

    REGENERABLE mientras el mes esté abierto (decisión del auditor,
    2026-09-18): a diferencia de CONTROL 1/CONTROL 3 (persistentes, ver
    ejecutar_control1()/ejecutar_control3()), GLOBAL no tiene histórico
    propio que proteger — es un resumen recalculable de los SAP diarios
    oficiales. Por eso esta capa V3 siempre pasa `force=True`: una segunda
    llamada para el mismo año/mes reemplaza `SAP_GLOBAL_TIQ_<MES>_<AÑO>.xlsx`
    (y su JSON) con una versión recalculada, en vez de bloquear con
    SALIDA_YA_EXISTE_SIN_FORCE. La ruta de salida es determinística por
    periodo, así que nunca puede crear un duplicado."""
    sap_dir = sap_dir or global_entrada_dir(base_dir_dev, anio, mes)
    if not os.path.isdir(sap_dir):
        raise RuntimeError(
            f"GLOBAL_ENTRADA_NO_MATERIALIZADA: {sap_dir} no existe; el backend debe "
            f"materializar la carpeta SAP oficial de Drive antes de generar GLOBAL."
        )
    _verificar_periodo_no_cerrado(sap_dir, anio, mes)
    global_dir = os.path.join(base_dir_dev, "global")
    _verificar_contenido_en_base_dir(os.path.join(global_dir, "_"), base_dir_dev)
    os.makedirs(global_dir, exist_ok=True)
    ruta_salida = _ruta_global(base_dir_dev, anio, mes)
    return generar_global_mensual(anio, mes, sap_dir, ruta_plantilla_origen, ruta_salida, force=True)


def ejecutar_control1(anio, mes, base_dir_dev, ruta_revision_json=None, dry_run=False,
                      modo_control1=None, confirmacion_cierre=False):
    """Cierre MENSUAL — paso 2 (AUDITORÍA DE ASIGNACIONES / CONTROL 1).

    DRIVE OFICIAL = fuente de verdad; LOCAL = materialización temporal de la
    corrida (FASE 12E.4). Lee ÚNICAMENTE `control1_entrada/<YYYY-MM>/`, que el
    backend limpió y llenó justo antes desde Drive:
      - SAP_GLOBAL_TIQ_<MES>_<AÑO>.xlsx  (OBLIGATORIO: el GLOBAL oficial);
      - HISTORICO_ASIGNACIONES.csv       (si no está, es una primera ejecución
        legítima con histórico vacío — el backend ya verificó que tampoco
        existe en Drive; aquí nunca hay un histórico "local viejo" porque el
        directorio se limpió);
      - REVISION_ASIGNACIONES_<PERIODO>.xlsx (si existe en Drive, para
        preservar las decisiones previas del auditor).
    Nunca usa `global/`, `publicacion/` ni otra corrida. Revisión, histórico,
    detalle (`CONTROL_ASIGNACIONES_<PERIODO>.json`) y (si el auditor autorizó
    correcciones) el GLOBAL corregido quedan en ese mismo directorio para que
    el backend los publique a Drive.

    MODOS (FASE 12E.6, ver v3/control1_modos.py): `modo_control1` = "preliminar"
    (por defecto, mes abierto: conserva decisiones entre corridas aunque GLOBAL
    se regenere, NO toca histórico ni GLOBAL, NO cierra el periodo) o "cerrar"
    (cierre definitivo: exige `confirmacion_cierre=True` explícito; corrige el
    GLOBAL autorizado, actualiza el histórico maestro y marca el periodo como
    cerrado; idempotente: un segundo cierre responde YA_CERRADO).

    ESTRUCTURA EN DRIVE (decisión del auditor, 2026-09-18): el histórico
    CANÓNICO/acumulativo es `05_CONTROLES/HISTORICO_ASIGNACIONES.csv` (raíz);
    la revisión, el detalle y una copia-snapshot del histórico al cierre viven
    en `05_CONTROLES/CONTROL_1_ASIGNACIONES/<YYYY-MM>/`. Esa copia por periodo
    es solo evidencia: nunca es la fuente maestra (aquí nunca se lee)."""
    entrada = control1_entrada_dir(base_dir_dev, anio, mes)
    if not os.path.isdir(entrada):
        raise RuntimeError(
            f"CONTROL1_ENTRADA_NO_MATERIALIZADA: {entrada} no existe; el backend debe "
            f"materializar GLOBAL/histórico/revisión desde Drive antes de ejecutar CONTROL 1."
        )
    nombre_global = consolidador_mensual.nombre_sap_global(anio, mes)
    ruta_global = os.path.join(entrada, nombre_global)
    if not os.path.isfile(ruta_global):
        raise RuntimeError(
            f"GLOBAL_OFICIAL_NO_MATERIALIZADO: falta {nombre_global} en {entrada}; "
            f"CONTROL 1 nunca usa un GLOBAL local como sustituto."
        )
    modo = control1_modos.validar_modo(modo_control1, confirmacion_cierre)
    ruta_historico = os.path.join(entrada, "HISTORICO_ASIGNACIONES.csv")
    periodo_esperado = _periodo(anio, mes)
    ruta_detalle = os.path.join(entrada, f"CONTROL_ASIGNACIONES_{periodo_esperado}.json")
    if modo == control1_modos.PRELIMINAR:
        resultado = control1_modos.ejecutar_control1_preliminar(
            ruta_global, ruta_historico, entrada, ruta_detalle_json=ruta_detalle, dry_run=dry_run)
    else:
        resultado = control1_modos.ejecutar_control1_cierre(
            ruta_global, ruta_historico, entrada, ruta_detalle_json=ruta_detalle, dry_run=dry_run,
            ruta_revision_json=ruta_revision_json)
    resultado["dir_entrada"] = os.path.abspath(entrada)
    resultado["ruta_global_materializado"] = os.path.abspath(ruta_global)
    if resultado.get("periodo") not in (None, periodo_esperado):
        raise RuntimeError(
            f"PERIODO_INCONSISTENTE: CONTROL 1 devolvió {resultado.get('periodo')!r} y se pidió {periodo_esperado!r}"
        )
    return resultado


def ejecutar_control3(anio, mes, base_dir_dev, ruta_observaciones_json=None, dry_run=False):
    """Cierre MENSUAL — paso 3 (CONTROL 3). Lee el MISMO GLOBAL del año/mes
    (ya corregido por CONTROL 1 si aplicó). Reporte (CONTROL3_CXC_CXP_
    <PERIODO>.xlsx/.json) e histórico técnico quedan en
    `base_dir_dev/global/` — antes de FASE 12D `ruta_salida_xlsx`/
    `ruta_salida_json` no se pasaban y control_cxc_cxp.ejecutar_control()
    nunca escribia el reporte (solo el histórico); esta es la única
    diferencia con el comportamiento previo, sin tocar control_cxc_cxp.py."""
    global_dir = os.path.join(base_dir_dev, "global")
    ruta_global = _ruta_global(base_dir_dev, anio, mes)
    ruta_historico = os.path.join(global_dir, "HISTORICO_CXC_CXP.csv")
    periodo = _periodo(anio, mes)
    ruta_salida_xlsx = os.path.join(global_dir, f"CONTROL3_CXC_CXP_{periodo}.xlsx")
    ruta_salida_json = os.path.join(global_dir, f"CONTROL3_CXC_CXP_{periodo}.json")
    return ejecutar_control3_mensual(
        ruta_global, ruta_historico,
        ruta_salida_xlsx=ruta_salida_xlsx, ruta_salida_json=ruta_salida_json,
        ruta_observaciones_json=ruta_observaciones_json, dry_run=dry_run,
    )


# ---------------------------------------------------------------------------
# CLI — mismo patrón Python-es-la-única-autoridad de los demás módulos.
# ---------------------------------------------------------------------------

def main(argv=None):
    import argparse

    parser = argparse.ArgumentParser(description="Backend DEV (API de lotes) de V3 — FASE 9.")
    parser.add_argument("--accion", required=True, choices=[
        "crear_lote_pendiente", "procesar_lote", "estado", "datos", "revisar", "corregir", "publicar",
        "generar_global", "preparar_global_entrada", "preparar_control1_entrada", "ejecutar_control1", "ejecutar_control3",
    ])
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)

    with open(args.input, "r", encoding="utf-8") as f:
        datos = json.load(f)

    try:
        if args.accion == "crear_lote_pendiente":
            r = crear_lote_pendiente(datos["fecha_inicio"], datos["fecha_fin"], datos.get("usuario_auditor"), datos["base_dir_dev"])
            salida = {"resultado": "OK", **r}
        elif args.accion == "procesar_lote":
            r = procesar_lote(
                datos["lote_id"], datos["base_dir_dev"], datos["origen_cierres_dir"],
                datos["ruta_maestro_origen"], datos["ruta_plantilla_origen"],
                datos.get("markers_origen_dir"), datos.get("version_codigo"),
                datos.get("ingesta_precomputada"), datos.get("requiere_ingesta_drive", False),
            )
            salida = {"resultado": "OK", "lote_id": r["lote_id"], "estado_lote": r["estado_lote"], "total_cierres": len(r["cierres"])}
        elif args.accion == "estado":
            salida = {"resultado": "OK", **obtener_estado(datos["lote_id"], datos["base_dir_dev"])}
        elif args.accion == "datos":
            salida = {"resultado": "OK", **obtener_datos(datos["lote_id"], datos["base_dir_dev"])}
        elif args.accion == "revisar":
            salida = {"resultado": "OK", **obtener_detalle_revision(datos["lote_id"], datos["fecha"], datos["base_dir_dev"])}
        elif args.accion == "corregir":
            salida = {"resultado": "OK", "cierre": aplicar_correccion(datos["lote_id"], datos["fecha"], datos["correccion"], datos["base_dir_dev"])}
        elif args.accion == "publicar":
            salida = {"resultado": "OK", **publicar_seleccionados(datos["lote_id"], datos["fechas"], datos["base_dir_dev"], datos.get("usuario_auditor"))}
        elif args.accion == "generar_global":
            salida = {"resultado": "OK", **generar_global(
                datos["anio"], datos["mes"], datos["base_dir_dev"], datos["ruta_plantilla_origen"],
                datos.get("sap_dir"),
            )}
        elif args.accion == "preparar_global_entrada":
            salida = {"resultado": "OK", **preparar_global_entrada(
                datos["anio"], datos["mes"], datos["base_dir_dev"],
            )}
        elif args.accion == "preparar_control1_entrada":
            salida = {"resultado": "OK", **preparar_control1_entrada(
                datos["anio"], datos["mes"], datos["base_dir_dev"],
            )}
        elif args.accion == "ejecutar_control1":
            salida = {"resultado": "OK", **ejecutar_control1(
                datos["anio"], datos["mes"], datos["base_dir_dev"],
                datos.get("ruta_revision_json"), datos.get("dry_run", False),
                datos.get("modo_control1"), datos.get("confirmacion_cierre", False),
            )}
        elif args.accion == "ejecutar_control3":
            salida = {"resultado": "OK", **ejecutar_control3(
                datos["anio"], datos["mes"], datos["base_dir_dev"],
                datos.get("ruta_observaciones_json"), datos.get("dry_run", False),
            )}
    except Exception as exc:
        salida = {"resultado": "ERROR", "codigo": type(exc).__name__, "mensaje": str(exc)}

    # Serializacion defensiva: si `salida` contuviera algo no serializable
    # (bug de programacion en cualquier accion de arriba), NUNCA se deja un
    # archivo de salida truncado a medio escribir — se escribe primero a un
    # buffer en memoria y solo se vuelca al archivo si el JSON completo es
    # valido; si no, se reemplaza por un ERROR limpio y ESE si es serializable.
    # default=str cubre Decimal/date que las funciones de CONTROL 1/3 (V2,
    # sin cambios) puedan devolver sin stringificar -- nunca oculta un bug
    # real, solo evita truncar la salida por un tipo no-JSON nativo.
    try:
        texto = json.dumps(salida, ensure_ascii=False, indent=2, default=str)
    except TypeError as exc:
        texto = json.dumps({"resultado": "ERROR", "codigo": "SALIDA_NO_SERIALIZABLE", "mensaje": str(exc)}, ensure_ascii=False, indent=2)

    with open(args.output, "w", encoding="utf-8") as f:
        f.write(texto)
    return 0


if __name__ == "__main__":
    sys.exit(main())
