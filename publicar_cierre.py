"""publicar_cierre.py — CLI mínimo para construir, en LOCAL, el marcador
PROCESADO_<SHA256>.json de un cierre ya publicado.

Reutiliza exclusivamente pipeline_tiquipaya.construir_marcador_procesado():
este script no reinterpreta ni duplica ninguna regla de negocio, solo la
expone por línea de comandos para que n8n pueda invocarla después de que
las 4 confirmaciones de publicación (SAP publicado por el usuario, SAP
verificado en Drive, resultado publicado, cierre movido a PROCESADOS)
ya hayan ocurrido realmente.

Este script NUNCA se conecta a Google Drive, no sube archivos, no mueve
cierres, no publica SAP y no crea ningún marcador productivo: solo lee un
RESULTADO_TIQ_DD-MM-YYYY.json local y escribe el marcador resultante en la
ruta LOCAL indicada por --salida-marcador. Subir ese archivo a Drive es
responsabilidad exclusiva de n8n (Execute Command -> este script -> Google
Drive: createFromText), nunca de este script.

Si falta o es falsa cualquiera de las 4 confirmaciones,
construir_marcador_procesado() lanza ValueError y aquí NO se escribe
ningún archivo: se reporta el error estructurado y se sale con código != 0.

Uso:
    python publicar_cierre.py \\
        --resultado /ruta/RESULTADO_TIQ_01-09-2026.json \\
        --sap-publicado-por-usuario true \\
        --sap-verificado-en-drive true \\
        --resultado-publicado true \\
        --cierre-movido-a-procesados true \\
        --observaciones "..." \\
        --salida-marcador /ruta/PROCESADO_<hash>.json
"""

import argparse
import json
import os
import sys

import pipeline_tiquipaya as pipeline


def _str2bool(valor):
    normalizado = valor.strip().lower()
    if normalizado == "true":
        return True
    if normalizado == "false":
        return False
    raise argparse.ArgumentTypeError(
        f"Valor booleano inválido: {valor!r} (usar 'true' o 'false')"
    )


def construir_parser():
    parser = argparse.ArgumentParser(
        description="Construye en LOCAL el marcador PROCESADO_<SHA256>.json de un "
                     "cierre ya publicado, vía pipeline_tiquipaya.construir_marcador_procesado(). "
                     "Nunca se conecta a Google Drive ni sube/mueve/publica nada."
    )
    parser.add_argument("--resultado", required=True,
                         help="Ruta local al RESULTADO_TIQ_DD-MM-YYYY.json del cierre ya procesado")
    parser.add_argument("--sap-publicado-por-usuario", required=True, type=_str2bool,
                         help="'true'/'false' — el usuario ya publicó el SAP manualmente")
    parser.add_argument("--sap-verificado-en-drive", required=True, type=_str2bool,
                         help="'true'/'false' — el SAP publicado ya fue verificado en Drive")
    parser.add_argument("--resultado-publicado", required=True, type=_str2bool,
                         help="'true'/'false' — el RESULTADO_TIQ ya fue subido a Drive")
    parser.add_argument("--cierre-movido-a-procesados", required=True, type=_str2bool,
                         help="'true'/'false' — el cierre origen ya fue movido a 03_PROCESADOS")
    parser.add_argument("--archivo-sap", default=None,
                         help="Nombre del archivo SAP publicado (opcional; por defecto usa "
                              "resultado_json['sap_archivo'])")
    parser.add_argument("--observaciones", default="")
    parser.add_argument("--fecha-procesamiento", default=None,
                         help="Fecha de procesamiento explícita 'YYYY-MM-DD HH:MM:SS' "
                              "(opcional; por defecto la hora actual)")
    parser.add_argument("--salida-marcador", required=True,
                         help="Ruta LOCAL donde escribir el marcador generado (nunca se sube "
                              "a Drive desde este script)")
    return parser


def _reportar(payload, codigo_salida):
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return codigo_salida


def main(argv=None):
    parser = construir_parser()
    args = parser.parse_args(argv)

    try:
        with open(args.resultado, "r", encoding="utf-8") as f:
            resultado_json = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        return _reportar({
            "resultado": "ERROR",
            "codigo": "RESULTADO_NO_LEGIBLE",
            "detalle": f"{type(exc).__name__}: {exc}",
        }, 2)

    try:
        nombre_archivo, contenido = pipeline.construir_marcador_procesado(
            resultado_json,
            sap_publicado_por_usuario=args.sap_publicado_por_usuario,
            sap_verificado_en_drive=args.sap_verificado_en_drive,
            resultado_publicado=args.resultado_publicado,
            cierre_movido_a_procesados=args.cierre_movido_a_procesados,
            archivo_sap=args.archivo_sap,
            observaciones=args.observaciones,
            fecha_procesamiento=args.fecha_procesamiento,
        )
    except ValueError as exc:
        mensaje = str(exc)
        faltantes = []
        if mensaje.startswith("MARCADOR_NO_AUTORIZADO:"):
            faltantes = mensaje.split(":", 1)[1].split(",")
        return _reportar({
            "resultado": "ERROR",
            "codigo": "MARCADOR_NO_AUTORIZADO",
            "faltantes": faltantes,
            "detalle": mensaje,
        }, 2)
    except KeyError as exc:
        return _reportar({
            "resultado": "ERROR",
            "codigo": "RESULTADO_INCOMPLETO",
            "detalle": f"Campo requerido ausente en --resultado: {exc}",
        }, 2)

    directorio = os.path.dirname(os.path.abspath(args.salida_marcador))
    if directorio:
        os.makedirs(directorio, exist_ok=True)
    with open(args.salida_marcador, "w", encoding="utf-8") as f:
        json.dump(contenido, f, ensure_ascii=False, indent=2)

    return _reportar({
        "resultado": "OK",
        "marcador_nombre": nombre_archivo,
        "marcador_ruta_local": os.path.abspath(args.salida_marcador),
        "hash_origen": contenido.get("HashOrigen"),
        "contenido": contenido,
    }, 0)


if __name__ == "__main__":
    sys.exit(main())
