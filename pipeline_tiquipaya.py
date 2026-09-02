"""
pipeline_tiquipaya.py — ETAPA 7: orquestación determinística de operación
(control de procesamiento + trazabilidad + preparación de publicación).

ETAPAS 1-6 (excel_io.py, motor_tiquipaya.py, sap_writer.py) están validadas
y congeladas: este módulo NO reinterpreta contabilidad, no recalcula
cierres, cruces, cuadre ni asiento, y no cambia ninguna regla de esos
módulos. Se limita a:

  1. identificar un cierre por SHA256;
  2. detectar reprocesamiento (idempotencia por hash, no por nombre);
  3. ejecutar el pipeline ya existente (ejecutar_v2 -> construir_asiento ->
     generar_y_validar_sap) hasta SAP;
  4. producir un resumen estructurado (trazabilidad) sin datos personales;
  5. preparar (sin ejecutar) las acciones de publicación en Google Drive;
  6. permitir registrar el cierre como PROCESADO, solo tras confirmación
     externa de que la publicación/movimiento ya ocurrió;
  7. nunca autorizar publicación de un cierre inválido.

Este módulo NO implementa Google Drive API ni mueve/sube ningún archivo:
solo trabaja con rutas locales ya recibidas y devuelve un manifiesto de
acciones para que Cowork las ejecute.
"""

import csv
import hashlib
import json
import os
from datetime import datetime
from decimal import Decimal

import motor_tiquipaya as motor
import sap_writer as sap


# ---------------------------------------------------------------------------
# Estados de alto nivel devueltos por procesar_cierre_completo()
# ---------------------------------------------------------------------------

ESTADO_YA_PROCESADO = "YA_PROCESADO"
ESTADO_VALIDADO_PENDIENTE = "VALIDADO_PENDIENTE_PUBLICACION"
ESTADO_ERROR = "ERROR"
ESTADO_BLOQUEADO = "BLOQUEADO"

WARNING_MISMO_NOMBRE_HASH_DISTINTO = "CIERRE_MISMO_NOMBRE_HASH_DISTINTO"


# ---------------------------------------------------------------------------
# CONTROL_PROCESAMIENTO.csv — columnas mínimas (UTF-8)
# ---------------------------------------------------------------------------

COLUMNAS_CONTROL = [
    "FechaCierre", "ArchivoOrigen", "HashOrigen", "Estado",
    "FechaProcesamiento", "VersionCodigo", "Resultado", "Diferencia",
    "Blockers", "ArchivoSAP", "Observaciones",
]


def derivar_cabecera_fecha_cierre(fecha_cierre):
    """ETAPA 8 — FechaRegistro/BLDAT y FechaContabilizacion/BUDAT siempre
    son la fecha real del cierre (nunca fin de mes ni otro cálculo);
    Mes/MONAT se deriva de esa misma fecha. `fecha_cierre` es el ISO
    'YYYY-MM-DD' ya extraído por el motor (resultado_v2["fecha"]): esta
    función solo separa sus componentes, nunca inventa una fecha
    distinta."""
    anio, mes, dia = fecha_cierre.split("-")
    return {
        "fecha_registro": fecha_cierre,
        "fecha_contabilizacion": fecha_cierre,
        "mes": mes,
    }


def calcular_sha256(ruta_archivo):
    """SHA256 exacto del archivo en `ruta_archivo`. Llave de idempotencia
    del CIERRE: el nombre del archivo NUNCA es suficiente por sí solo."""
    hasher = hashlib.sha256()
    with open(ruta_archivo, "rb") as f:
        for bloque in iter(lambda: f.read(1 << 16), b""):
            hasher.update(bloque)
    return hasher.hexdigest()


def _leer_control(ruta_control):
    """Devuelve las filas de CONTROL_PROCESAMIENTO.csv como lista de
    dicts. Lista vacía si `ruta_control` es None o el archivo aún no
    existe (primer cierre procesado del control)."""
    if not ruta_control or not os.path.isfile(ruta_control):
        return []
    with open(ruta_control, "r", encoding="utf-8", newline="") as f:
        return [dict(fila) for fila in csv.DictReader(f)]


def _escribir_control(ruta_control, filas):
    """Reescribe CONTROL_PROCESAMIENTO.csv completo, en UTF-8, de forma
    segura (archivo temporal + reemplazo atómico)."""
    directorio = os.path.dirname(os.path.abspath(ruta_control))
    if directorio:
        os.makedirs(directorio, exist_ok=True)

    ruta_tmp = f"{ruta_control}.tmp"
    with open(ruta_tmp, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNAS_CONTROL)
        writer.writeheader()
        for fila in filas:
            writer.writerow({col: fila.get(col, "") for col in COLUMNAS_CONTROL})
    os.replace(ruta_tmp, ruta_control)


# ---------------------------------------------------------------------------
# Resultado estructurado (RESULTADO_TIQ_DD-MM-YYYY.json)
# ---------------------------------------------------------------------------

def nombre_resultado_json(fecha_cierre):
    """'RESULTADO_TIQ_DD-MM-YYYY.json' a partir de fecha_cierre YYYY-MM-DD."""
    anio, mes, dia = fecha_cierre.split("-")
    return f"RESULTADO_TIQ_{dia}-{mes}-{anio}.json"


def _construir_resultado_json(fecha_cierre, archivo_origen, hash_origen,
                               version_codigo, resultado_v2, asiento,
                               sap_resumen, ruta_sap_salida, warnings_extra):
    """Resumen operativo estable, sin datos personales de estudiantes ni
    detalle completo de CI (solo cantidad_ci/total_ci agregados). Todos
    los importes ya vienen serializados como string con 2 decimales
    (money_str) desde motor_tiquipaya/sap_writer: aquí no se recalcula
    ningún Decimal, solo se reexponen."""
    detalle = resultado_v2.get("detalle") or {}
    componentes = resultado_v2.get("componentes") or {}

    advertencias = list(warnings_extra)
    for w in (asiento.get("advertencias") or []):
        if w not in advertencias:
            advertencias.append(w)

    atc_neto = detalle.get("atc_neto")
    atc_comision = detalle.get("atc_comision")

    sap_estado = sap_resumen.get("estado_sap") if sap_resumen else "NO_GENERADO"
    sap_validacion = None
    if sap_resumen and sap_resumen.get("validacion"):
        sap_validacion = sap_resumen["validacion"].get("estado")

    return {
        "fecha_cierre": fecha_cierre,
        "archivo_origen": archivo_origen,
        "sha256_origen": hash_origen,
        "version_codigo": version_codigo,
        "estado_v2": resultado_v2.get("estado"),
        "diferencia": resultado_v2.get("diferencia", "0.00"),
        "blockers": resultado_v2.get("excepciones_bloqueantes", 0) or 0,
        "advertencias": advertencias,
        "universo_original": resultado_v2.get("universo_original"),
        "alquileres": resultado_v2.get("alquileres"),
        "universo_ajustado": resultado_v2.get("universo_ajustado"),
        "total_vouchers": componentes.get("vouchers"),
        "cantidad_vouchers": len(detalle.get("vouchers_confirmados") or []),
        "total_ci": componentes.get("ci_operativas"),
        "cantidad_ci": len(detalle.get("ci_validas") or []),
        "atc_bruto": componentes.get("atc_bruto"),
        "atc_neto": atc_neto.get("importe") if atc_neto else None,
        "atc_comision": atc_comision.get("importe") if atc_comision else None,
        "atc_estado": detalle.get("atc_estado"),
        "usd": componentes.get("dolares"),
        "asiento_estado": asiento.get("estado"),
        "cantidad_partidas": asiento.get("cantidad_partidas", 0),
        "cargo": asiento.get("total_cargo"),
        "haber": asiento.get("total_haber"),
        "diferencia_asiento": asiento.get("diferencia"),
        "sap_estado": sap_estado,
        "sap_archivo": ruta_sap_salida,
        "sap_validacion": sap_validacion,
    }


def _escribir_resultado_json(ruta_resultado, resultado_json):
    directorio = os.path.dirname(os.path.abspath(ruta_resultado))
    if directorio:
        os.makedirs(directorio, exist_ok=True)
    with open(ruta_resultado, "w", encoding="utf-8") as f:
        json.dump(resultado_json, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Manifiesto de publicación — Python NUNCA mueve/sube nada de Drive; solo
# devuelve las acciones que Cowork debe ejecutar.
# ---------------------------------------------------------------------------

def _construir_manifiesto(fecha_cierre, archivo_origen, ruta_sap_salida, ruta_resultado):
    anio, mes, _ = fecha_cierre.split("-")
    anio_mes = f"{anio}-{mes}"
    origen_resultado = ruta_resultado or nombre_resultado_json(fecha_cierre)
    return [
        {
            "accion": "SUBIR_SAP",
            "origen": ruta_sap_salida,
            "destino": f"04_SALIDAS/{anio}/{anio_mes}/SAP/",
        },
        {
            "accion": "SUBIR_RESULTADO",
            "origen": origen_resultado,
            "destino": f"04_SALIDAS/{anio}/{anio_mes}/RESULTADOS/",
        },
        {
            "accion": "ACTUALIZAR_CONTROL",
            "origen": "CONTROL_PROCESAMIENTO.csv",
            "destino": "05_CONTROLES/",
        },
        {
            "accion": "MOVER_CIERRE",
            "origen": f"00_ENTRADA_CIERRES/{archivo_origen}",
            "destino": f"03_PROCESADOS/{anio}/{anio_mes}/",
        },
    ]


# ---------------------------------------------------------------------------
# API principal
# ---------------------------------------------------------------------------

def procesar_cierre_completo(
    ruta_cierre,
    ruta_maestro,
    ruta_plantilla_sap,
    ruta_sap_salida,
    metadata_cabecera,
    version_codigo,
    ruta_control=None,
    ruta_resultado=None,
    hashes_procesados=None,
    registros_control=None,
):
    """Orquesta ETAPAS 1-6 sobre un único cierre, con control de
    procesamiento por SHA256 e idempotencia.

    - `ruta_maestro` se usa como MACROS y como ATC (maestro mensual único,
      ver HANDOFF_CODE_V2.md): motor_tiquipaya.ejecutar_v2(ruta_cierre,
      ruta_maestro, ruta_maestro).
    - `version_codigo` se recibe explícito del llamador; nunca se
      inventa/adivina un commit aquí.
    - `ruta_control`: ruta a CONTROL_PROCESAMIENTO.csv (opcional, se
      conserva como compatibilidad/auditoría). Si el HashOrigen del
      cierre ya figura con Estado=PROCESADO —en el CSV, o en
      `hashes_procesados`/`registros_control`—, se devuelve YA_PROCESADO
      sin ejecutar el motor, sin generar SAP y sin tocar ningún control.
    - `hashes_procesados`: colección (set o dict) de HashOrigen ya
      PROCESADO, para cuando el control operativo real vive fuera del
      CSV (p. ej. los HashOrigen de los marcadores
      PROCESADO_<SHA256>.json ya existentes en Drive, recolectados por
      Cowork antes de llamar aquí). No obliga a que exista un CSV local.
    - `registros_control`: lista de dicts con la misma forma que las
      filas de CONTROL_PROCESAMIENTO.csv (HashOrigen/ArchivoOrigen/
      Estado/...) — típicamente el contenido ya parseado de esos mismos
      marcadores PROCESADO_<SHA256>.json. Se combinan con las del CSV
      para la idempotencia y la advertencia de mismo-nombre-hash-distinto.
    - `ruta_resultado`: si se pasa, se escribe ahí el JSON de resultado
      estructurado (RESULTADO_TIQ_DD-MM-YYYY.json).

    Las fechas de cabecera (FechaRegistro/FechaContabilizacion/Mes) que
    se envían a `sap_writer` siempre se derivan de la fecha real del
    cierre ya extraída por el motor (`derivar_cabecera_fecha_cierre`),
    nunca del valor que traiga `metadata_cabecera`: el resto de los
    campos de cabecera (tipo_asiento, texto_cabecera, referencia) sí
    vienen tal cual del llamador.

    Nunca marca PROCESADO: como mucho devuelve
    VALIDADO_PENDIENTE_PUBLICACION cuando el cierre es válido de punta a
    punta (V2 OK + asiento OK + SAP generado y validado). Marcar
    PROCESADO es responsabilidad exclusiva de registrar_procesado(),
    llamada solo después de que Cowork confirme la publicación.
    """
    archivo_origen = os.path.basename(str(ruta_cierre))
    hash_origen = calcular_sha256(ruta_cierre)

    filas_control = _leer_control(ruta_control)
    registros_externos = list(registros_control or [])
    todas_las_filas = filas_control + registros_externos

    fila_mismo_hash = next(
        (f for f in todas_las_filas if f.get("HashOrigen") == hash_origen), None
    )
    ya_procesado_externo = bool(hashes_procesados) and hash_origen in hashes_procesados
    ya_procesado = ya_procesado_externo or (
        fila_mismo_hash is not None and fila_mismo_hash.get("Estado") == "PROCESADO"
    )
    if ya_procesado:
        return {
            "estado": ESTADO_YA_PROCESADO,
            "hash_origen": hash_origen,
            "archivo_origen": archivo_origen,
            "warnings": [],
            "resultado_v2": None,
            "asiento": None,
            "sap": None,
            "resultado_json": None,
            "ruta_resultado_json": None,
            "publicacion_autorizada": False,
            "acciones_requeridas": [],
            "version_codigo": version_codigo,
            "fila_control_existente": fila_mismo_hash,
        }

    warnings_list = []
    mismo_nombre_otro_hash = any(
        f.get("ArchivoOrigen") == archivo_origen and f.get("HashOrigen") != hash_origen
        for f in todas_las_filas
    )
    if mismo_nombre_otro_hash:
        warnings_list.append(WARNING_MISMO_NOMBRE_HASH_DISTINTO)

    resultado_v2 = motor.ejecutar_v2(ruta_cierre, ruta_maestro, ruta_maestro)
    asiento = motor.construir_asiento(resultado_v2)

    blockers = resultado_v2.get("excepciones_bloqueantes", 0) or 0
    diferencia = resultado_v2.get("diferencia", "0.00") or "0.00"

    v2_ok = (
        resultado_v2.get("estado") == "OK"
        and blockers == 0
        and Decimal(diferencia) == 0
    )
    asiento_ok = asiento.get("estado") == "OK"

    sap_resumen = None
    if v2_ok and asiento_ok:
        metadata_sap = dict(metadata_cabecera or {})
        metadata_sap.update(derivar_cabecera_fecha_cierre(resultado_v2["fecha"]))
        sap_resumen = sap.generar_y_validar_sap(
            asiento, ruta_plantilla_sap, ruta_sap_salida, metadata_sap
        )
    sap_ok = bool(sap_resumen) and sap_resumen.get("estado_sap") == "OK"

    resultado_json = _construir_resultado_json(
        fecha_cierre=resultado_v2.get("fecha"),
        archivo_origen=archivo_origen,
        hash_origen=hash_origen,
        version_codigo=version_codigo,
        resultado_v2=resultado_v2,
        asiento=asiento,
        sap_resumen=sap_resumen,
        ruta_sap_salida=ruta_sap_salida if sap_ok else None,
        warnings_extra=warnings_list,
    )

    if v2_ok and asiento_ok and sap_ok:
        estado_final = ESTADO_VALIDADO_PENDIENTE
        publicacion_autorizada = True
        acciones_requeridas = _construir_manifiesto(
            resultado_v2["fecha"], archivo_origen, ruta_sap_salida, ruta_resultado
        )
    else:
        publicacion_autorizada = False
        acciones_requeridas = []
        if resultado_v2.get("estado") == "BLOQUEADO_EXCEPCION":
            estado_final = ESTADO_BLOQUEADO
        else:
            estado_final = ESTADO_ERROR

    if ruta_resultado:
        _escribir_resultado_json(ruta_resultado, resultado_json)

    return {
        "estado": estado_final,
        "hash_origen": hash_origen,
        "archivo_origen": archivo_origen,
        "warnings": warnings_list,
        "resultado_v2": resultado_v2,
        "asiento": asiento,
        "sap": sap_resumen,
        "resultado_json": resultado_json,
        "ruta_resultado_json": ruta_resultado,
        "publicacion_autorizada": publicacion_autorizada,
        "acciones_requeridas": acciones_requeridas,
        "version_codigo": version_codigo,
    }


# ---------------------------------------------------------------------------
# Registro final — SOLO tras confirmación explícita de Cowork de que SAP,
# resultado y cierre ya fueron publicados/movidos en Drive.
# ---------------------------------------------------------------------------

def construir_registro_control(resultado_json, estado="PROCESADO", archivo_sap=None,
                                observaciones="", fecha_procesamiento=None):
    """Construye el registro de control (misma forma que una fila de
    CONTROL_PROCESAMIENTO.csv y que el contenido de un marcador
    PROCESADO_<SHA256>.json — ver HANDOFF, corrección post-ETAPA 8) a
    partir de `resultado_json` (el dict devuelto en
    procesar_cierre_completo(...)["resultado_json"], o uno con la misma
    forma).

    Este dict es la única fuente de verdad del registro de control:
    tanto `registrar_procesado` (destino CSV, legacy/fallback) como
    `construir_marcador_procesado` (destino marcador inmutable por
    SHA256, que Cowork materializa en Drive con `textContent` — Python
    nunca escribe en Drive ni implementa su API aquí) lo usan tal cual,
    sin reinterpretar ningún campo. Sin datos personales de CI ni detalle
    sensible del cierre. Claves: FechaCierre, ArchivoOrigen, HashOrigen,
    Estado, FechaProcesamiento, VersionCodigo, Resultado, Diferencia,
    Blockers, ArchivoSAP, Observaciones.
    """
    fecha_proc = fecha_procesamiento or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return {
        "FechaCierre": resultado_json.get("fecha_cierre", ""),
        "ArchivoOrigen": resultado_json.get("archivo_origen", ""),
        "HashOrigen": resultado_json.get("sha256_origen", ""),
        "Estado": estado,
        "FechaProcesamiento": fecha_proc,
        "VersionCodigo": resultado_json.get("version_codigo", ""),
        "Resultado": resultado_json.get("estado_v2", ""),
        "Diferencia": resultado_json.get("diferencia_asiento") or resultado_json.get("diferencia", "0.00"),
        "Blockers": str(resultado_json.get("blockers", 0)),
        "ArchivoSAP": archivo_sap or resultado_json.get("sap_archivo") or "",
        "Observaciones": observaciones,
    }


def registrar_procesado(ruta_control, resultado_json, archivo_sap=None,
                         observaciones="", fecha_procesamiento=None):
    """Añade o actualiza, de forma segura, CONTROL_PROCESAMIENTO.csv con
    Estado=PROCESADO para el HashOrigen de `resultado_json`.

    `resultado_json` es el dict devuelto en
    procesar_cierre_completo(...)["resultado_json"] (o uno con la misma
    forma: fecha_cierre, archivo_origen, sha256_origen, version_codigo,
    estado_v2, diferencia_asiento/diferencia, blockers, sap_archivo).

    Si ya existe una fila con ese mismo HashOrigen en Estado=PROCESADO,
    no duplica el control: devuelve YA_PROCESADO sin escribir nada. Nunca
    se debe llamar antes de que Cowork confirme que SAP, RESULTADO y el
    CIERRE original ya fueron publicados/movidos correctamente.

    Ruta CSV: LEGACY/FALLBACK (se conserva intacta, ver corrección
    post-ETAPA 8). El control operativo real en producción es el
    marcador inmutable PROCESADO_<SHA256>.json (`nombre_marcador_procesado`
    / `construir_marcador_procesado`); Google Sheets queda descartado
    como dependencia productiva (Cowork no puede editar/append celdas de
    forma confiable con las herramientas disponibles).
    """
    hash_origen = resultado_json["sha256_origen"]
    filas = _leer_control(ruta_control)

    existente = next((f for f in filas if f.get("HashOrigen") == hash_origen), None)
    if existente and existente.get("Estado") == "PROCESADO":
        return {"estado": ESTADO_YA_PROCESADO, "duplicado": True, "fila": existente}

    nueva_fila = construir_registro_control(
        resultado_json, estado="PROCESADO", archivo_sap=archivo_sap,
        observaciones=observaciones, fecha_procesamiento=fecha_procesamiento,
    )

    if existente is not None:
        filas[filas.index(existente)] = nueva_fila
    else:
        filas.append(nueva_fila)

    _escribir_control(ruta_control, filas)
    return {"estado": "PROCESADO", "duplicado": False, "fila": nueva_fila}


# ---------------------------------------------------------------------------
# CORRECCIÓN POST-ETAPA 8 — CONTROL INMUTABLE POR SHA256.
#
# Hallazgo real de Cowork: Google Sheets no permite append/edición de
# celdas con las herramientas disponibles, y CONTROL_PROCESAMIENTO.csv
# tampoco puede actualizarse en sitio sin crear un archivo nuevo. Se
# descarta Google Sheets como control operativo de producción.
#
# Nueva arquitectura autorizada: cada cierre oficialmente publicado
# tendrá un marcador inmutable PROCESADO_<SHA256>.json en Drive. Python
# nunca escribe en Drive ni implementa ninguna API de Google: solo
# construye el nombre de archivo y el dict de contenido; Cowork
# materializa ese JSON con `textContent` una vez confirmada la
# publicación. El CSV (`registrar_procesado` arriba) se conserva intacto
# como legacy/fallback.
# ---------------------------------------------------------------------------

def nombre_marcador_procesado(hash_origen):
    """Nombre estable y determinístico del marcador inmutable:
    'PROCESADO_<SHA256>.json'. Mismo HashOrigen -> siempre el mismo
    nombre (esa es la clave de idempotencia: Cowork solo necesita
    comprobar si el archivo ya existe en Drive)."""
    return f"PROCESADO_{hash_origen}.json"


def construir_marcador_procesado(
    resultado_json,
    sap_publicado_por_usuario,
    sap_verificado_en_drive,
    resultado_publicado,
    cierre_movido_a_procesados,
    archivo_sap=None,
    observaciones="",
    fecha_procesamiento=None,
):
    """Devuelve `(nombre_archivo, contenido)` del marcador
    PROCESADO_<SHA256>.json para `resultado_json`, listo para que Cowork
    lo cree en Drive con `textContent`. Python nunca crea/escribe este
    archivo: solo lo construye.

    Solo se autoriza el marcador cuando las 4 confirmaciones de
    publicación ya ocurrieron (nunca al terminar el motor):
    SAP publicado manualmente por el usuario, SAP verificado por Cowork
    en Drive, RESULTADO publicado y el CIERRE movido a PROCESADOS. Si
    falta alguna, lanza ValueError con el detalle de qué falta — nunca
    construye un marcador a medias.

    `contenido` es exactamente `construir_registro_control(...)`: mismas
    claves que una fila de CONTROL_PROCESAMIENTO.csv, sin datos
    personales de CI ni ningún detalle sensible del cierre.
    """
    faltantes = []
    if not sap_publicado_por_usuario:
        faltantes.append("SAP_NO_PUBLICADO_POR_USUARIO")
    if not sap_verificado_en_drive:
        faltantes.append("SAP_NO_VERIFICADO_EN_DRIVE")
    if not resultado_publicado:
        faltantes.append("RESULTADO_NO_PUBLICADO")
    if not cierre_movido_a_procesados:
        faltantes.append("CIERRE_NO_MOVIDO_A_PROCESADOS")
    if faltantes:
        raise ValueError("MARCADOR_NO_AUTORIZADO:" + ",".join(faltantes))

    hash_origen = resultado_json["sha256_origen"]
    contenido = construir_registro_control(
        resultado_json, estado="PROCESADO", archivo_sap=archivo_sap,
        observaciones=observaciones, fecha_procesamiento=fecha_procesamiento,
    )
    return nombre_marcador_procesado(hash_origen), contenido
