"""aplicar_correccion.py — CLI mínimo, FASE 3 Parte B (HANDOFF_CODE_V2.md
sección 16): valida una corrección autorizada por el auditor, la aplica EN
MEMORIA sobre el cierre original y reprocesa, escribiendo SIEMPRE a rutas
nuevas dentro de REPROCESOS/ (nunca sobre el SAP/RESULTADO_TIQ originales,
nunca sobre el .xlsm original).

Mismo patrón que publicar_cierre.py: reutiliza exclusivamente
pipeline_tiquipaya.procesar_cierre_con_correccion() y
correcciones_tiquipaya.py — este script no reinterpreta ninguna regla de
negocio, solo la expone por línea de comandos. Nunca se conecta a Google
Drive, no publica SAP, no crea marcadores PROCESADO y no ejecuta ningún
cierre real más allá del reproceso local pedido explícitamente.

Idempotencia por (SHA256 original, version_correccion): el nombre de los
archivos de REPROCESOS ya codifica ambos (fecha del cierre + version_correccion,
ligada 1:1 a categoria/tipo/identificadores/campo_corregido/valor_autorizado).
Si el RESULTADO_TIQ del reproceso ya existe en disco Y su sha256_origen +
version_correccion coinciden con los de esta corrida, no se vuelve a invocar
el motor ni a regenerar el SAP: se reporta YA_APLICADA con el contenido ya
existente.

Rechaza cualquier corrección si el cierre ya tiene un marcador
PROCESADO_<hash>.json (--controles-dir/--marcadores-dir, mismo mecanismo de
lectura que run_batch.cargar_marcadores_procesados): un cierre ya publicado
nunca se corrige.

Uso:
    python aplicar_correccion.py \\
        --resultado /ruta/RESULTADO_TIQ_02-09-2026.json \\
        --correccion /ruta/CORRECCION_....json \\
        --cierre /ruta/CIERRE 02-09-2026.xlsm \\
        --maestro /ruta/MACROS_SEPTIEMBRE.xlsm \\
        --plantilla-sap /ruta/Plantilla_SAP_maestra.xlsx \\
        --resultados-dir /ruta/resultados \\
        --salidas-dir /ruta/salidas \\
        --controles-dir /ruta/controles
"""

import argparse
import csv
import json
import os
import sys

import correcciones_tiquipaya as correcciones
import pipeline_tiquipaya as pipeline
import run_batch


_COLUMNAS_HISTORICO_CORRECCIONES = [
    "FechaCierre", "HashOrigen", "VersionCorreccion", "Categoria", "Tipo",
    "CampoCorregido", "ValorAutorizado", "UsuarioAuditor", "FechaHora",
    "EstadoReproceso", "ArchivoResultado", "ArchivoSAP",
]


def construir_parser():
    parser = argparse.ArgumentParser(
        description="Aplica una corrección autorizada por el auditor sobre un cierre "
                     "ERROR_REVISAR y reprocesa, vía "
                     "pipeline_tiquipaya.procesar_cierre_con_correccion(). Nunca modifica "
                     "el .xlsm original, nunca sobrescribe SAP/RESULTADO_TIQ originales, "
                     "nunca se conecta a Google Drive."
    )
    parser.add_argument("--resultado", required=True,
                         help="RESULTADO_TIQ_DD-MM-YYYY.json original del cierre en ERROR_REVISAR")
    grupo_correccion = parser.add_mutually_exclusive_group(required=True)
    grupo_correccion.add_argument("--correccion",
                         help="Ruta al JSON de la corrección, YA con version_correccion calculado "
                              "(schema HANDOFF §16.3)")
    grupo_correccion.add_argument("--correccion-sin-version",
                         help="Ruta al JSON de la corrección SIN version_correccion (o con cualquier "
                              "valor en ese campo: se ignora y se recalcula). Pensado para "
                              "orquestadores (p. ej. n8n) que arman los campos de la corrección pero "
                              "no deben reimplementar el hash determinístico de version_correccion: "
                              "aquí se calcula con correcciones_tiquipaya.calcular_version_correccion(), "
                              "la MISMA función que valida --correccion, nunca una lógica distinta.")
    parser.add_argument("--cierre", required=True, help="Ruta local al CIERRE DD-MM-YYYY.xlsm original")
    parser.add_argument("--maestro", required=True, help="Ruta local al maestro mensual (MACROS + ATC TIQUIPAYA)")
    parser.add_argument("--plantilla-sap", required=True, help="Ruta local a la plantilla SAP maestra")
    parser.add_argument("--resultados-dir", required=True,
                         help="Directorio base; el RESULTADO del reproceso se escribe en <resultados-dir>/REPROCESOS/")
    parser.add_argument("--salidas-dir", required=True,
                         help="Directorio base; el SAP del reproceso se escribe en <salidas-dir>/REPROCESOS/")
    parser.add_argument("--controles-dir", default=None,
                         help="Directorio local con PROCESADO_<SHA256>.json existentes (opcional; si se "
                              "omite, no se puede verificar 'cierre ya publicado' ni registrar trazabilidad)")
    parser.add_argument("--marcadores-dir", default=None,
                         help="Igual semántica que run_batch.py --marcadores-dir")
    parser.add_argument("--version-codigo", default=None,
                         help="Opcional; por defecto se resuelve como run_batch.py (git rev-parse corto)")
    return parser


def _reportar(payload, codigo_salida):
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return codigo_salida


def _leer_json(ruta):
    with open(ruta, "r", encoding="utf-8") as f:
        return json.load(f)


def _rutas_reproceso(resultados_dir, salidas_dir, fecha_cierre, version_correccion):
    anio, mes, dia = fecha_cierre.split("-")
    sufijo = f"{dia}-{mes}-{anio}_REPROCESO_{version_correccion}"
    ruta_resultado = os.path.join(resultados_dir, "REPROCESOS", f"RESULTADO_TIQ_{sufijo}.json")
    ruta_sap = os.path.join(salidas_dir, "REPROCESOS", f"SAP_{sufijo}.xlsx")
    return ruta_resultado, ruta_sap


def _registrar_trazabilidad(controles_dir, correccion, hash_origen, version_correccion,
                             estado_legible, ruta_resultado, ruta_sap):
    """Escribe (si no existen ya) el registro inmutable de la corrección
    (CORRECCION_<hash>_<version>.json) y una fila en el índice append-only
    HISTORICO_CORRECCIONES.csv. Nunca duplica una fila para la misma clave
    (HashOrigen, VersionCorreccion). No es requisito para reprocesar: si
    `controles_dir` es None, simplemente no se registra nada (igual que
    run_batch.py sin --controles-dir)."""
    if not controles_dir:
        return None, False

    directorio = os.path.join(controles_dir, "CORRECCIONES_AUDITOR")
    os.makedirs(directorio, exist_ok=True)

    ruta_correccion = os.path.join(directorio, f"CORRECCION_{hash_origen}_{version_correccion}.json")
    if not os.path.isfile(ruta_correccion):
        with open(ruta_correccion, "w", encoding="utf-8") as f:
            json.dump(correccion, f, ensure_ascii=False, indent=2)

    ruta_historico = os.path.join(directorio, "HISTORICO_CORRECCIONES.csv")
    filas = []
    if os.path.isfile(ruta_historico):
        with open(ruta_historico, "r", encoding="utf-8", newline="") as f:
            filas = list(csv.DictReader(f))

    ya_indexada = any(
        fila.get("HashOrigen") == hash_origen and fila.get("VersionCorreccion") == version_correccion
        for fila in filas
    )
    if not ya_indexada:
        filas.append({
            "FechaCierre": correccion.get("fecha_cierre", ""),
            "HashOrigen": hash_origen,
            "VersionCorreccion": version_correccion,
            "Categoria": correccion.get("categoria", ""),
            "Tipo": correccion.get("tipo", ""),
            "CampoCorregido": correccion.get("campo_corregido", ""),
            "ValorAutorizado": correccion.get("valor_autorizado", ""),
            "UsuarioAuditor": correccion.get("usuario_auditor", ""),
            "FechaHora": correccion.get("fecha_hora", ""),
            "EstadoReproceso": estado_legible,
            "ArchivoResultado": ruta_resultado or "",
            "ArchivoSAP": ruta_sap or "",
        })
        ruta_tmp = f"{ruta_historico}.tmp"
        with open(ruta_tmp, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=_COLUMNAS_HISTORICO_CORRECCIONES)
            writer.writeheader()
            for fila in filas:
                writer.writerow({col: fila.get(col, "") for col in _COLUMNAS_HISTORICO_CORRECCIONES})
        os.replace(ruta_tmp, ruta_historico)

    return ruta_correccion, not ya_indexada


def main(argv=None):
    parser = construir_parser()
    args = parser.parse_args(argv)

    try:
        resultado_original = _leer_json(args.resultado)
    except (OSError, json.JSONDecodeError) as exc:
        return _reportar({
            "resultado": "ERROR", "codigo": "RESULTADO_NO_LEGIBLE",
            "detalle": f"{type(exc).__name__}: {exc}",
        }, 2)

    ruta_correccion_entrada = args.correccion or args.correccion_sin_version
    try:
        correccion = _leer_json(ruta_correccion_entrada)
    except (OSError, json.JSONDecodeError) as exc:
        return _reportar({
            "resultado": "ERROR", "codigo": "CORRECCION_NO_LEGIBLE",
            "detalle": f"{type(exc).__name__}: {exc}",
        }, 2)

    if args.correccion_sin_version:
        # El llamador (p. ej. n8n) nunca calcula este hash: se recalcula
        # aquí con la MISMA función que --correccion valida, para que
        # Python siga siendo la única autoridad sobre version_correccion.
        correccion["version_correccion"] = correcciones.calcular_version_correccion(correccion)

    if resultado_original.get("sha256_origen") != correccion.get("sha256_origen"):
        return _reportar({
            "resultado": "ERROR", "codigo": "CORRECCION_RESULTADO_INCONSISTENTE",
            "detalle": "sha256_origen de --resultado y de --correccion no coinciden",
        }, 2)
    if resultado_original.get("fecha_cierre") != correccion.get("fecha_cierre"):
        return _reportar({
            "resultado": "ERROR", "codigo": "CORRECCION_RESULTADO_INCONSISTENTE",
            "detalle": "fecha_cierre de --resultado y de --correccion no coinciden",
        }, 2)

    try:
        version_correccion = correcciones.validar_schema_correccion(correccion)
    except ValueError as exc:
        codigo, _, detalle = str(exc).partition(":")
        return _reportar({"resultado": "ERROR", "codigo": codigo, "detalle": detalle or str(exc)}, 2)

    try:
        hash_origen = correcciones.calcular_sha256_archivo(args.cierre)
    except OSError as exc:
        return _reportar({
            "resultado": "ERROR", "codigo": "CIERRE_NO_LEGIBLE",
            "detalle": f"{type(exc).__name__}: {exc}",
        }, 2)

    ya_publicado = False
    if args.controles_dir:
        hashes_procesados, _, _, _ = run_batch.cargar_marcadores_procesados(
            args.controles_dir, args.marcadores_dir
        )
        ya_publicado = hash_origen in hashes_procesados

    # Se rechaza ANTES de mirar si ya existe un reproceso previo con esta
    # misma corrección: un cierre publicado nunca se corrige de nuevo,
    # incluso si esta corrección exacta ya se había calculado antes de la
    # publicación.
    if ya_publicado:
        return _reportar({
            "resultado": "ERROR", "codigo": "CIERRE_YA_PUBLICADO_NO_CORREGIBLE",
            "detalle": (
                f"el cierre con HashOrigen={hash_origen} ya tiene un marcador "
                "PROCESADO_<hash>.json; un cierre ya publicado no admite correcciones nuevas"
            ),
        }, 2)

    ruta_resultado_reproceso, ruta_sap_reproceso = _rutas_reproceso(
        args.resultados_dir, args.salidas_dir, correccion["fecha_cierre"], version_correccion
    )

    if os.path.isfile(ruta_resultado_reproceso):
        with open(ruta_resultado_reproceso, "r", encoding="utf-8") as f:
            existente = json.load(f)
        if existente.get("sha256_origen") == hash_origen and existente.get("version_correccion") == version_correccion:
            return _reportar({
                "resultado": "OK",
                "estado": "YA_APLICADA",
                "hash_origen": hash_origen,
                "version_correccion": version_correccion,
                "ruta_resultado_reproceso": ruta_resultado_reproceso,
                "ruta_sap_reproceso": ruta_sap_reproceso if os.path.isfile(ruta_sap_reproceso) else None,
                "resultado_json": existente,
            }, 0)
        return _reportar({
            "resultado": "ERROR", "codigo": "REPROCESO_CONFLICTO",
            "detalle": (
                f"{ruta_resultado_reproceso} ya existe con sha256_origen/version_correccion "
                "distintos a esta corrida"
            ),
        }, 2)

    os.makedirs(os.path.dirname(ruta_resultado_reproceso), exist_ok=True)
    os.makedirs(os.path.dirname(ruta_sap_reproceso), exist_ok=True)

    metadata_cabecera = run_batch.construir_metadata_cabecera(correccion["fecha_cierre"])
    version_codigo = run_batch._resolver_version_codigo(args.version_codigo)

    try:
        resultado = pipeline.procesar_cierre_con_correccion(
            ruta_cierre=args.cierre,
            ruta_maestro=args.maestro,
            ruta_plantilla_sap=args.plantilla_sap,
            ruta_sap_salida=ruta_sap_reproceso,
            metadata_cabecera=metadata_cabecera,
            version_codigo=version_codigo,
            correccion=correccion,
            ruta_resultado=ruta_resultado_reproceso,
            ya_publicado=ya_publicado,
        )
    except ValueError as exc:
        codigo, _, detalle = str(exc).partition(":")
        return _reportar({"resultado": "ERROR", "codigo": codigo, "detalle": detalle or str(exc)}, 2)

    estado_legible = run_batch._ESTADO_MAP.get(resultado["estado"], "ERROR_REVISAR")
    sap_generado = bool(resultado.get("sap")) and resultado["sap"].get("estado_sap") == "OK"

    ruta_correccion_guardada, _ = _registrar_trazabilidad(
        args.controles_dir, correccion, hash_origen, version_correccion,
        estado_legible, resultado.get("ruta_resultado_json"),
        ruta_sap_reproceso if sap_generado else None,
    )

    return _reportar({
        "resultado": "OK",
        "estado": estado_legible,
        "hash_origen": hash_origen,
        "version_correccion": version_correccion,
        "publicacion_autorizada": resultado["publicacion_autorizada"],
        "ruta_resultado_reproceso": resultado.get("ruta_resultado_json"),
        "ruta_sap_reproceso": ruta_sap_reproceso if sap_generado else None,
        "ruta_correccion_guardada": ruta_correccion_guardada,
        "resultado_json": resultado["resultado_json"],
    }, 0)


if __name__ == "__main__":
    sys.exit(main())
