"""v3/ingesta.py — Módulo 01 · INGESTA de Caja Tiquipaya V3 (FASE 5).

Responsabilidad ÚNICA: dado un rango de fechas, decidir por cada fecha si
el CIERRE correspondiente está ENCONTRADO, SIN_ARCHIVO o AMBIGUO en la
carpeta de entrada de Drive — aplicando REGLA G (búsqueda EXACTA, nunca
"primer resultado"). No materializa nada, no toca Python del motor, no
genera SAP, no publica, no mueve ni borra archivos.

Réplica exacta de responsabilidad del bloque "FASE 0 · ENTRADA" de V2
(GENERAR - Fechas del rango + BUSCAR/IF - Cierre del dia en Drive), pero
simplificada: en V2 esa decisión vive implícita dentro de nodos n8n
(Google Drive + IF) sin ningún test propio (ver auditoria_v2/
V2_BUSINESS_RULES.csv BR-008 y V2_TEST_AUDIT.csv T-021). Aquí es una
función Python pura, explícita y testeada — el nodo Code JS del
subworkflow n8n `TIQ V3 · 01 INGESTA · DEV` (CanZtkmnm0ukAC8c) es un
puerto directo de esta misma lógica a JavaScript (documentado nodo por
nodo en el propio workflow); mantenerlos sincronizados es responsabilidad
de quien edite cualquiera de los dos lados.

REUTILIZACIÓN DELIBERADA DE V2 (ningún archivo de V2 se modifica):
  - generar_rango_fechas() y nombre_cierre_esperado() se REUTILIZAN tal
    cual de run_batch.py (misma regla: rango dentro de un único mes,
    mismo patrón de nombre "CIERRE DD-MM-YYYY.xlsm"). No se duplica ni se
    reinterpreta esa lógica.

Este módulo NUNCA se conecta a Google Drive: recibe como parámetro
explícito los nombres de archivo ya listados por fecha
(`candidatos_por_fecha`), exactamente igual que run_batch.py recibe un
directorio YA MATERIALIZADO por Cowork/n8n. Quién obtiene esa lista (una
llamada real de solo lectura a Drive, o un fixture sintético en modo DEV)
es responsabilidad exclusiva del llamador — nunca de este módulo.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import run_batch  # noqa: E402  (reutilizado tal cual, ver docstring)


# ---------------------------------------------------------------------------
# REGLA G — búsqueda EXACTA. Ver auditoria_v2/V2_CONTRACTS.md CONTRACT-010.
# ---------------------------------------------------------------------------

ENCONTRADO = "ENCONTRADO"
SIN_ARCHIVO = "SIN_ARCHIVO"
AMBIGUO = "AMBIGUO"
ERROR_INGESTA = "ERROR_INGESTA"

_ESTADOS_VALIDOS = (ENCONTRADO, SIN_ARCHIVO, AMBIGUO, ERROR_INGESTA)

_MENSAJES = {
    ENCONTRADO: "Archivo localizado por coincidencia exacta de nombre.",
    SIN_ARCHIVO: "Ninguna coincidencia exacta de nombre en la carpeta de entrada.",
    AMBIGUO: "Más de una coincidencia exacta de nombre: requiere decisión humana, nunca se toma la primera.",
}


def buscar_cierre_exacto(nombre_buscado, candidatos):
    """REGLA G: coincidencia EXACTA de nombre de archivo, nunca "primer
    resultado". `candidatos`: lista de dicts {"nombre": str, "file_id":
    str|None} (o de strings simples, para llamadas más simples/sintéticas).

    Devuelve (estado, drive_file_id, coincidencias) donde:
      - estado in (ENCONTRADO, SIN_ARCHIVO, AMBIGUO)
      - drive_file_id es el id del ÚNICO archivo si estado==ENCONTRADO,
        None en cualquier otro caso (nunca se inventa ni se adivina)
      - coincidencias es la cantidad de coincidencias EXACTAS encontradas
    """
    normalizados = [
        c if isinstance(c, dict) else {"nombre": c, "file_id": None}
        for c in candidatos
    ]
    exactos = [c for c in normalizados if c.get("nombre") == nombre_buscado]

    if len(exactos) == 1:
        return ENCONTRADO, exactos[0].get("file_id"), 1
    if len(exactos) == 0:
        return SIN_ARCHIVO, None, 0
    return AMBIGUO, None, len(exactos)


# ---------------------------------------------------------------------------
# Orquestación del módulo 01 · INGESTA
# ---------------------------------------------------------------------------

def ejecutar_ingesta(fecha_inicio, fecha_fin, candidatos_por_fecha):
    """Aplica REGLA G sobre cada fecha del rango [fecha_inicio, fecha_fin].

    - fecha_inicio / fecha_fin: 'YYYY-MM-DD', deben pertenecer al MISMO
      MES (reutiliza run_batch.generar_rango_fechas tal cual: lanza
      ValueError RANGO_INVALIDO / RANGO_CRUZA_MES en caso contrario, sin
      reinterpretar esa regla aquí).
    - candidatos_por_fecha: {"YYYY-MM-DD": [nombres_o_dicts, ...]}. Una
      fecha ausente de este dict se trata como carpeta vacía para esa
      fecha (0 candidatos), NUNCA como error técnico.

    Devuelve una lista de dicts, uno por fecha del rango, con EXACTAMENTE
    estas claves: fecha, archivo_esperado, estado_ingesta, drive_file_id,
    coincidencias, mensaje. Nunca lanza una excepción por una fecha
    individual: un problema técnico puntual (p. ej. candidatos_por_fecha
    con una forma inesperada para esa fecha) se refleja como
    ERROR_INGESTA en ESA fila, sin detener el resto del rango — mismo
    criterio de aislamiento de errores que run_batch.py usa entre cierres.
    """
    fechas = run_batch.generar_rango_fechas(fecha_inicio, fecha_fin)  # puede lanzar RANGO_INVALIDO/RANGO_CRUZA_MES

    resultados = []
    for fecha in fechas:
        archivo_esperado = run_batch.nombre_cierre_esperado(fecha)
        try:
            candidatos = candidatos_por_fecha.get(fecha, [])
            estado, drive_file_id, coincidencias = buscar_cierre_exacto(archivo_esperado, candidatos)
            mensaje = _MENSAJES[estado]
        except Exception as exc:  # aislamiento: nunca detiene el resto del rango
            estado, drive_file_id, coincidencias = ERROR_INGESTA, None, None
            mensaje = f"{type(exc).__name__}: {exc}"

        resultados.append({
            "fecha": fecha,
            "archivo_esperado": archivo_esperado,
            "estado_ingesta": estado,
            "drive_file_id": drive_file_id,
            "coincidencias": coincidencias,
            "mensaje": mensaje,
        })

    return resultados


# ---------------------------------------------------------------------------
# FASE 10A — conexión de solo lectura a Google Drive real. `source_mode`
# distingue explícitamente de dónde vino `candidatos_por_fecha`:
#   "fixture"        -> candidatos_por_fecha ya viene armado (DEV, tests).
#   "drive_readonly" -> n8n hizo UN listado de solo lectura de la carpeta
#                        real (sin filtrar por fecha; ver incidente 09/10/11
#                        documentado en CONTRACT-010 — nunca confiar en un
#                        query de Drive por nombre, siempre traer TODO el
#                        listado y dejar que REGLA G decida en Python) y ese
#                        MISMO listado se evalúa contra cada fecha del rango.
# Este módulo NUNCA se conecta a Drive (ver docstring del archivo): solo
# reestructura un listado ya obtenido por el llamador.
# ---------------------------------------------------------------------------

def normalizar_listado_drive(archivos_drive):
    """Convierte el listado crudo de la API de Google Drive (objetos con
    al menos `name`/`id`) al formato {"nombre":, "file_id":} que
    buscar_cierre_exacto()/ejecutar_ingesta() ya esperaban desde FASE 5.
    Pura reestructuración de datos -- NUNCA decide nada de REGLA G aquí
    (eso sigue siendo exclusivo de buscar_cierre_exacto)."""
    return [
        {"nombre": a.get("name"), "file_id": a.get("id")}
        for a in (archivos_drive or [])
    ]


def expandir_candidatos_a_rango(fecha_inicio, fecha_fin, candidatos_planos):
    """Modo drive_readonly: Drive devuelve UN listado completo de la
    carpeta de entrada (nunca una búsqueda por fecha específica -- ver
    normalizar_listado_drive). Cada fecha del rango se evalúa contra ESE
    MISMO listado completo; REGLA G (buscar_cierre_exacto) filtra por
    nombre EXACTO dentro de él para cada fecha, exactamente igual que si
    se hubiera pedido un listado ya acotado por fecha. Reutiliza
    run_batch.generar_rango_fechas tal cual (puede lanzar
    RANGO_INVALIDO/RANGO_CRUZA_MES, sin reinterpretar esa regla aquí)."""
    fechas = run_batch.generar_rango_fechas(fecha_inicio, fecha_fin)
    candidatos_normalizados = normalizar_listado_drive(candidatos_planos)
    return {fecha: candidatos_normalizados for fecha in fechas}


# ---------------------------------------------------------------------------
# CLI — cierra DEBT-001 (ver v3/TECHNICAL_DEBT.md): mismo patrón
# Execute-Command-invoca-Python que v3/materializacion.py/dev_api.py desde
# FASE 5/9. Python es la única autoridad; el subworkflow n8n
# `TIQ V3 · 01 INGESTA · DEV` (CanZtkmnm0ukAC8c) ya NO reimplementa REGLA G
# en JavaScript -- solo arma el payload (candidatos_por_fecha en modo
# fixture, o el listado crudo de Drive en modo drive_readonly) y lee este
# resultado.
# ---------------------------------------------------------------------------

def main(argv=None):
    parser = argparse.ArgumentParser(description="Modulo 01 INGESTA de V3 (DEV).")
    parser.add_argument("--input", required=True, help="Ruta a un JSON {'fecha_inicio','fecha_fin','source_mode','candidatos_por_fecha'|'candidatos_drive_crudo'}")
    parser.add_argument("--output", required=True, help="Ruta donde escribir el JSON de resultado")
    args = parser.parse_args(argv)

    with open(args.input, "r", encoding="utf-8") as f:
        datos = json.load(f)

    source_mode = datos.get("source_mode") or "fixture"
    try:
        fecha_inicio = datos["fecha_inicio"]
        fecha_fin = datos["fecha_fin"]
        if source_mode == "drive_readonly":
            candidatos_drive_crudo = datos.get("candidatos_drive_crudo") or []
            candidatos_por_fecha = expandir_candidatos_a_rango(fecha_inicio, fecha_fin, candidatos_drive_crudo)
        else:
            candidatos_por_fecha = datos.get("candidatos_por_fecha") or {}

        cierres = ejecutar_ingesta(fecha_inicio, fecha_fin, candidatos_por_fecha)
        salida = {"resultado": "OK", "source_mode": source_mode, "cierres": cierres}
        if source_mode == "drive_readonly":
            # Inventario crudo tal cual lo devolvió Drive (solo lectura),
            # reexpuesto sin reinterpretar -- para reportar qué archivos
            # existen realmente, más allá de si calzan con alguna fecha
            # pedida en este rango.
            salida["inventario_drive"] = candidatos_drive_crudo
    except Exception as exc:
        salida = {"resultado": "ERROR", "codigo": type(exc).__name__, "mensaje": str(exc), "source_mode": source_mode}

    try:
        texto = json.dumps(salida, ensure_ascii=False, indent=2)
    except TypeError as exc:
        texto = json.dumps({"resultado": "ERROR", "codigo": "SALIDA_NO_SERIALIZABLE", "mensaje": str(exc)}, ensure_ascii=False, indent=2)

    with open(args.output, "w", encoding="utf-8") as f:
        f.write(texto)
    return 0


if __name__ == "__main__":
    sys.exit(main())
