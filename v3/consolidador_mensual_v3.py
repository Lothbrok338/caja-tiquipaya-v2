"""v3/consolidador_mensual_v3.py — capa V3 del cierre MENSUAL (GLOBAL),
FASE 12E.2 (2026-09-18).

POR QUÉ EXISTE ESTE ARCHIVO EN VEZ DE SEGUIR USANDO SOLO
consolidador_mensual.py (V2, congelado desde `7dbcf93`, ver `v2.0-final`):

consolidador_mensual.py exige C10/BLART="DB" en cada SAP diario de
ENTRADA (`_CABECERA_ESPERADA["C"]`), pero todo SAP diario real trae
C10="SA" (`run_batch.py::_TIPO_ASIENTO`, confirmado leyendo el SAP
oficial real). Ese chequeo vive hardcodeado dentro de
`leer_y_validar_sap_diario()`, sin ningún parámetro ni punto de
extensión — no hay forma de pedirle "acepta también SA" sin:

  (a) modificar consolidador_mensual.py directamente, o
  (b) hacer monkeypatch de `_CABECERA_ESPERADA` en tiempo de ejecución, o
  (c) escribir copias adulteradas de los SAP diarios con C10 cambiado.

Las tres están explícitamente prohibidas por decisión del auditor
(2026-09-18): V2 no se toca, ni siquiera en memoria ni con datos
temporales. Este módulo es la alternativa: una capa V3 delgada que
REUTILIZA sin cambios todas las funciones públicas de
consolidador_mensual.py que no tienen nada que ver con el valor de C10
de la entrada (validación de partidas/cuadre, deduplicación por SHA256,
guardarraíles de --salida, escritura del SAP GLOBAL con su cabecera
"DB"), y reimplementa ÚNICAMENTE dos piezas pequeñas:

  1. el descubrimiento de qué SAP diarios entran al universo del mes
     (`descubrir_sap_oficiales_del_mes`, ya existía desde FASE 12E.1);
  2. la reinterpretación de los `problemas` que
     `leer_y_validar_sap_diario()` YA calculó, para que un C10="SA" deje
     de contar como problema en el contexto V3 (`_reinterpretar_
     problemas_entrada_v3`) — sin tocar `leer_y_validar_sap_diario`
     ni ninguna otra función de V2, sin monkeypatch, sin mutar constantes,
     sin escribir ninguna copia de ningún SAP diario.

El resto de la orquestación (`ejecutar_consolidacion_v3`) es
deliberadamente un espejo pequeño de
`consolidador_mensual.ejecutar_consolidacion()`, porque esa función no
expone un punto de extensión para inyectar el paso 2 de arriba sin
reimplementar el bucle que la contiene — pero cada llamada dentro de ese
espejo es a una función PÚBLICA y SIN CAMBIOS de consolidador_mensual.py
(`validar_guardarrieles_salida`, `detectar_duplicados`,
`leer_y_validar_sap_diario`, `construir_metadata_cabecera_global`,
`escribir_sap_global`, `nombre_sap_global`, `nombre_resultado_json`,
`ultimo_dia_mes`). La SALIDA (`SAP_GLOBAL_TIQ_<MES>_<AÑO>.xlsx`) se sigue
escribiendo con `construir_metadata_cabecera_global()` sin cambios, que
sigue usando `_TIPO_ASIENTO_GLOBAL = "DB"` — la regla de salida NO
cambia, solo la de entrada.
"""

import datetime
import json
import os
import re
import sys
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import consolidador_mensual as cm  # noqa: E402  (reutilizado tal cual — funciones públicas, sin cambios)
from excel_io import money_str  # noqa: E402  (reutilizado tal cual, igual que consolidador_mensual.py)


# ---------------------------------------------------------------------------
# 1. Descubrimiento de SAP diarios oficiales del mes (legacy + V3).
# ---------------------------------------------------------------------------

# consolidador_mensual.py (V2) solo reconoce SAP_TIQ_DD-MM-YYYY.xlsx en su
# propio escaneo de directorio (`_RE_SAP_DIARIO`/`seleccionar_sap_directorio`).
# GLOBAL debe consolidar TODO SAP diario válido de la carpeta oficial del
# mes, sin importar si viene de V2 (nombre legacy) o V3 -- por eso este
# descubrimiento vive aquí y el resultado se pasa a `resolver_archivos`-
# equivalente de este módulo como una lista explícita ya resuelta.
_RE_SAP_DIARIO_V3 = re.compile(r"^SAP_TIQ_(\d{2})-(\d{2})-(\d{4})\.xlsx$", re.IGNORECASE)
_RE_SAP_DIARIO_LEGACY = re.compile(r"^SAP_(\d{2})-(\d{2})-(\d{4})\.xlsx$", re.IGNORECASE)


def _fecha_y_origen_desde_nombre_sap(nombre):
    """Reconoce los dos formatos válidos de SAP diario oficial. Nunca
    matchea SAP_GLOBAL_*.xlsx (no tiene dígitos justo después de "SAP_"),
    RESULTADO_*.json, ni ningún otro archivo -- ambigüedad de nombre
    imposible entre los dos patrones porque uno exige literalmente "TIQ_"
    y el otro un dígito en esa misma posición. Devuelve (fecha, origen) o
    (None, None) si `nombre` no es ninguno de los dos."""
    m = _RE_SAP_DIARIO_V3.match(nombre)
    if m:
        dia, mes, anio = m.groups()
        return datetime.date(int(anio), int(mes), int(dia)), "v3"
    m = _RE_SAP_DIARIO_LEGACY.match(nombre)
    if m:
        dia, mes, anio = m.groups()
        return datetime.date(int(anio), int(mes), int(dia)), "legacy"
    return None, None


def descubrir_sap_oficiales_del_mes(sap_dir, anio, mes):
    """Escanea `sap_dir` (la carpeta SAP oficial del mes, materializada
    localmente) y decide qué SAP diarios entran al universo de GLOBAL,
    aceptando ambos formatos válidos (ver _fecha_y_origen_desde_nombre_sap)
    y filtrando por año/mes -- SAP_GLOBAL_*.xlsx, archivos de otro
    mes/año, temporales (`consolidador_mensual._es_temporal`) y cualquier
    nombre no reconocido quedan fuera. GLOBAL nunca depende de marker,
    publicación o resultado V3: solo de que el archivo esté válidamente en
    la carpeta oficial del mes pedido.

    Protección por fecha: como máximo un SAP efectivo por fecha. Si dos
    (o más) nombres distintos representan la MISMA fecha:
      - mismo SHA256 (`consolidador_mensual._sha256_archivo`, solo
        lectura) -> mismo contenido con dos nombres: se conserva el de
        nombre V3 (o, si ninguno lo es, el primero en orden alfabético —
        caso degenerado que no se espera en la práctica) y el otro queda
        registrado como duplicado idéntico omitido, informativo, nunca
        sumado dos veces;
      - SHA256 distinto -> ambigüedad real: no se elige ninguno, se
        agrega un blocker DUPLICADO_FECHA_AMBIGUA (mismo criterio que
        `duplicados_diferentes` de consolidador_mensual.py) y esa fecha
        queda fuera del universo consolidado.

    Nunca abre ningún SAP en modo escritura, nunca reinterpreta su
    validación estructural/contable (eso lo sigue haciendo
    consolidador_mensual.py, sin cambios, sobre la lista final, vía
    ejecutar_consolidacion_v3 de este mismo módulo).

    Devuelve {"archivos": [ruta_absoluta, ...] en orden cronológico,
    "sap_incluidos": [{"nombre","fecha","origen"}, ...],
    "duplicados_identicos_omitidos": [...], "blockers": [...]}."""
    if not os.path.isdir(sap_dir):
        raise RuntimeError(f"SAP_DIR_NO_ENCONTRADO: {sap_dir}")

    por_fecha = {}
    for nombre in sorted(os.listdir(sap_dir)):
        if cm._es_temporal(nombre):
            continue
        fecha, origen = _fecha_y_origen_desde_nombre_sap(nombre)
        if fecha is None:
            continue
        if fecha.year != anio or fecha.month != mes:
            continue
        ruta = os.path.abspath(os.path.join(sap_dir, nombre))
        por_fecha.setdefault(fecha, []).append((nombre, ruta, origen))

    archivos = []
    sap_incluidos = []
    duplicados_identicos_omitidos = []
    blockers = []

    for fecha in sorted(por_fecha.keys()):
        candidatos = por_fecha[fecha]
        if len(candidatos) == 1:
            nombre, ruta, origen = candidatos[0]
            archivos.append(ruta)
            sap_incluidos.append({"nombre": nombre, "fecha": fecha.isoformat(), "origen": origen})
            continue

        hashes = {ruta: cm._sha256_archivo(ruta) for _, ruta, _ in candidatos}
        if len(set(hashes.values())) > 1:
            nombres = ", ".join(n for n, _, _ in candidatos)
            blockers.append(f"DUPLICADO_FECHA_AMBIGUA:{fecha.isoformat()}:{nombres}")
            continue

        elegido = next((c for c in candidatos if c[2] == "v3"), candidatos[0])
        for candidato in candidatos:
            if candidato == elegido:
                continue
            duplicados_identicos_omitidos.append({
                "fecha": fecha.isoformat(), "nombre_omitido": candidato[0], "nombre_usado": elegido[0],
            })
        archivos.append(elegido[1])
        sap_incluidos.append({"nombre": elegido[0], "fecha": fecha.isoformat(), "origen": elegido[2]})

    return {
        "archivos": archivos,
        "sap_incluidos": sap_incluidos,
        "duplicados_identicos_omitidos": duplicados_identicos_omitidos,
        "blockers": blockers,
    }


# ---------------------------------------------------------------------------
# 2. Reinterpretación V3 de C10/BLART en la ENTRADA (sin tocar V2).
# ---------------------------------------------------------------------------

# Formato EXACTO que genera consolidador_mensual.leer_y_validar_sap_diario()
# para un mismatch de cabecera (columna C, fila 10): ver
# tests_v3/test_auditoria_mensual.py::test_v2_mensaje_cabecera_c10_no_cambio_de_formato,
# que falla en rojo si V2 alguna vez cambia este formato -- señal explícita
# de que este regex necesita revisión, en vez de dejar de filtrar en
# silencio.
_RE_PROBLEMA_CABECERA_C10 = re.compile(r"^CABECERA_C10_ESPERADO_'DB'_OBTENIDO_'([^']*)'$")

_C10_ENTRADA_VALIDO_V3 = "SA"


def _reinterpretar_problemas_entrada_v3(problemas):
    """Recibe la lista `problemas` que
    `consolidador_mensual.leer_y_validar_sap_diario()` YA calculó (llamada
    sin cambios, sin monkeypatch, sin mutar `_CABECERA_ESPERADA`, sin
    escribir ninguna copia del SAP) y reinterpreta ÚNICAMENTE el problema
    de C10 según el contrato real de ENTRADA de V3
    (C10/BLART="SA", run_batch.py::_TIPO_ASIENTO):

      - C10 == "SA": el único caso real hoy, y el correcto -- deja de ser
        un problema;
      - C10 con cualquier OTRO valor: sigue siendo un blocker claro (nunca
        se consolida en silencio), pero con un mensaje que refleja el
        contrato real de V3 (`ESPERADO_'SA'`) en vez del de V2
        (`ESPERADO_'DB'`), para no confundir al auditor;
      - cualquier otro problema (hoja, partidas, cuadre, otras columnas de
        cabecera) se conserva exactamente igual -- V3 no relaja ninguna
        otra validación estructural."""
    resultado = []
    for problema in problemas:
        m = _RE_PROBLEMA_CABECERA_C10.match(problema)
        if m is None:
            resultado.append(problema)
            continue
        valor_obtenido = m.group(1)
        if valor_obtenido == _C10_ENTRADA_VALIDO_V3:
            continue
        resultado.append(f"CABECERA_C10_ESPERADO_{_C10_ENTRADA_VALIDO_V3!r}_OBTENIDO_{valor_obtenido!r}")
    return resultado


# ---------------------------------------------------------------------------
# 3. Orquestador V3 — espejo delgado de
#    consolidador_mensual.ejecutar_consolidacion(), reutilizando sus
#    funciones públicas sin cambios salvo el paso 2 de arriba.
# ---------------------------------------------------------------------------

def ejecutar_consolidacion_v3(anio, mes, plantilla, salida, archivos_lista, force, blockers_previos=None):
    """Igual que consolidador_mensual.ejecutar_consolidacion(), mismo
    formato de resultado JSON, mismas garantías (nunca abre un SAP diario
    ni la plantilla en modo escritura, nunca duplica partidas, nunca
    escribe la SALIDA si hay blockers) -- la única diferencia real es que
    la validación de cabecera de cada SAP diario pasa por
    `_reinterpretar_problemas_entrada_v3()` antes de convertirse en
    blocker. `archivos_lista` viene siempre resuelto por
    `descubrir_sap_oficiales_del_mes()` (o pasado explícito por el
    llamador); este orquestador no vuelve a escanear `sap_dir`.

    `blockers_previos`: blockers ya detectados aguas arriba (p.ej.
    DUPLICADO_FECHA_AMBIGUA del descubrimiento). Cuentan como cualquier
    otro blocker: NO se escribe el SAP GLOBAL — un mes con una fecha
    ambigua nunca produce un GLOBAL parcial que parezca completo."""
    if not os.path.isfile(plantilla):
        raise RuntimeError(f"PLANTILLA_NO_ENCONTRADA: {plantilla}")

    rutas_candidatas = [os.path.abspath(r) for r in archivos_lista]
    for ruta in rutas_candidatas:
        if not os.path.isfile(ruta):
            raise RuntimeError(f"ARCHIVO_LISTA_NO_ENCONTRADO: {ruta}")

    cm.validar_guardarrieles_salida(salida, plantilla, rutas_candidatas, force)

    rutas_unicas, sha256_por_archivo, duplicados_identicos, duplicados_diferentes = \
        cm.detectar_duplicados(rutas_candidatas)

    blockers = list(blockers_previos or [])
    for dup in duplicados_diferentes:
        blockers.append(f"DUPLICADO_SAP_DIFERENTE:{dup['nombre']}")

    partidas_por_archivo = {}
    if not duplicados_diferentes:
        for ruta in rutas_unicas:
            resultado_archivo = cm.leer_y_validar_sap_diario(ruta)
            partidas_por_archivo[ruta] = resultado_archivo["partidas"]
            for problema in _reinterpretar_problemas_entrada_v3(resultado_archivo["problemas"]):
                blockers.append(f"SAP_INVALIDO:{os.path.basename(ruta)}:{problema}")

    if not rutas_unicas and not duplicados_diferentes:
        blockers.append("SIN_SAP_PARA_CONSOLIDAR")

    todas_partidas = []
    cargo_global = haber_global = diferencia = None
    cantidad_partidas = None

    if not blockers:
        for ruta in rutas_unicas:
            todas_partidas.extend(partidas_por_archivo[ruta])

        cargo_global = sum((p["cargo"] for p in todas_partidas), Decimal("0.00"))
        haber_global = sum((p["haber"] for p in todas_partidas), Decimal("0.00"))
        diferencia = cargo_global - haber_global
        cantidad_partidas = len(todas_partidas)

        if diferencia != 0:
            blockers.append(
                f"CUADRE_GLOBAL_DESCUADRADO:cargo_{money_str(cargo_global)}"
                f"_haber_{money_str(haber_global)}_diferencia_{money_str(diferencia)}"
            )

    ruta_global_generado = None
    if not blockers:
        # construir_metadata_cabecera_global() sigue usando
        # _TIPO_ASIENTO_GLOBAL="DB" sin cambios: la SALIDA de GLOBAL sigue
        # llevando C10="DB" -- eso nunca cambió, solo la ENTRADA.
        metadata = cm.construir_metadata_cabecera_global(anio, mes)
        cm.escribir_sap_global(todas_partidas, plantilla, salida, metadata)
        ruta_global_generado = os.path.abspath(salida)

    estado = "VALIDADO_PENDIENTE_PUBLICACION" if not blockers else "ERROR_REVISAR"

    nombre_periodo = cm.nombre_sap_global(anio, mes)[len("SAP_GLOBAL_TIQ_"):-len(".xlsx")]
    mes_nombre = nombre_periodo.rsplit("_", 1)[0]

    resultado_json = {
        "anio": anio,
        "mes": mes,
        "mes_nombre": mes_nombre,
        "fecha_generacion": datetime.datetime.now().isoformat(timespec="seconds"),
        "cantidad_sap_incluidos": len(rutas_unicas),
        "sap_incluidos": [os.path.basename(r) for r in rutas_unicas],
        "sha256_sap_origen": {
            os.path.basename(r): sha256_por_archivo[r] for r in rutas_unicas
        },
        "duplicados_identicos_ignorados": duplicados_identicos,
        "duplicados_diferentes_encontrados": duplicados_diferentes,
        "cantidad_partidas": cantidad_partidas,
        "cargo_global": money_str(cargo_global) if cargo_global is not None else None,
        "haber_global": money_str(haber_global) if haber_global is not None else None,
        "diferencia": money_str(diferencia) if diferencia is not None else None,
        "ruta_global_generado": ruta_global_generado,
        "blockers": blockers,
        "estado": estado,
    }

    ruta_json = os.path.join(
        os.path.dirname(os.path.abspath(salida)) or ".",
        cm.nombre_resultado_json(anio, mes),
    )
    with open(ruta_json, "w", encoding="utf-8") as f:
        json.dump(resultado_json, f, ensure_ascii=False, indent=2)

    resultado_json["ruta_resultado_json"] = ruta_json
    return resultado_json
