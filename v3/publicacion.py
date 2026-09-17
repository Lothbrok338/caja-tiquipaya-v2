"""v3/publicacion.py — Módulo 06 · PUBLICACION de Caja Tiquipaya V3 (FASE 5,
sexta etapa).

Adaptador delgado sobre la lógica de publicación YA VALIDADA de V2 —
ninguno de estos archivos se modifica ni se reinterpreta desde aquí:

  - pipeline_tiquipaya.py  (calcular_sha256(), nombre_marcador_procesado(),
                             construir_marcador_procesado(): las 4
                             confirmaciones, nunca un marcador a medias)
  - publicar_cierre.py     (mismo patrón de invocación: construir el
                             marcador SOLO después de que las acciones de
                             publicación ya ocurrieron, nunca antes)
  - run_batch.py           (cargar_marcadores_procesados(), reutilizado
                             para poder leer/combinar el estado de
                             publicación ya materializado)

CONTRACT-011 (procesar y publicar separados): que el Módulo 03 haya
calculado un cierre y el Módulo 04/05 lo hayan clasificado
LISTO_PARA_PUBLICAR NO significa que esté publicado — este módulo es el
ÚNICO que "publica" (en DEV: copia a `publicacion/` y genera el marcador).

CONTRACT-008/009 (idempotencia SHA256 / marcador con 4 confirmaciones):
antes de publicar, SIEMPRE se verifica si ya existe
`publicacion/markers/PROCESADO_<SHA256>.json`; si existe, no se duplica
nada (ni SAP, ni resultado, ni cierre procesado, ni marcador). El marcador
solo se construye con `pipeline.construir_marcador_procesado()` — la
MISMA función de V2 — que lanza si falta cualquiera de las 4
confirmaciones.

UNIFICACIÓN SINGLE/MÚLTIPLE (a diferencia de V2, donde la duplicación
single/múltiple era puramente de WIRING en n8n — ambas ramas terminaban
invocando el mismo `publicar_cierre.py`): aquí hay UNA sola función,
`publicar_cierre_dev()`, y `publicar_lote()` simplemente la aplica a cada
elemento de una lista. No existen dos caminos de lógica distintos.
"""

import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pipeline_tiquipaya as pipeline  # noqa: E402  (reutilizado tal cual)
from v3.materializacion import _verificar_contenido_en_base_dir  # noqa: E402
from v3.clasificacion import LISTO_PARA_PUBLICAR, YA_PROCESADO  # noqa: E402


PUBLICADO = "PUBLICADO"
YA_PUBLICADO = "YA_PUBLICADO"
NO_PUBLICABLE = "NO_PUBLICABLE"
ERROR_PUBLICACION = "ERROR_PUBLICACION"

_ESTADOS_HABILITADOS = (LISTO_PARA_PUBLICAR,)  # CONTRACT-011: unicamente este estado autoriza publicar


def _nombre_sap_oficial(fecha_iso):
    """Nombre del SAP diario tal como lo espera consolidador_mensual.py
    para la futura consolidación GLOBAL: `SAP_TIQ_DD-MM-YYYY.xlsx`
    (`_RE_SAP_DIARIO` en consolidador_mensual.py). run_batch._nombre_sap_esperado()
    (V2, reutilizado tal cual por v3.motor para generar el SAP) produce
    `SAP_DD-MM-YYYY.xlsx` — sin 'TIQ' — un mismatch histórico de V2 que
    consolidador_mensual.py nunca reconcilia (V2 no se toca desde aquí).
    Esta función SOLO renombra la COPIA que este módulo ya hace al publicar
    (nunca el archivo original que produjo el motor): el SAP oficial que
    queda publicado (en DEV y, después, en Drive) ya nace con el nombre
    que GLOBAL podrá consumir."""
    anio, mes, dia = fecha_iso.split("-")
    return f"SAP_TIQ_{dia}-{mes}-{anio}.xlsx"


def _directorios_publicacion(base_dir_dev):
    base = os.path.join(base_dir_dev, "publicacion")
    dirs = {
        "sap": os.path.join(base, "sap"),
        "resultados": os.path.join(base, "resultados"),
        "procesados": os.path.join(base, "procesados"),
        "markers": os.path.join(base, "markers"),
    }
    for ruta in dirs.values():
        _verificar_contenido_en_base_dir(ruta, base_dir_dev)
        os.makedirs(ruta, exist_ok=True)
    return dirs


def _salida(item, estado_publicacion, publicado, mensaje, usuario_auditor=None, **extra):
    # Preserva TODO lo que el item ya traía de los Módulos 01-05
    # (archivo_esperado, estado_ingesta, estado_materializacion,
    # estado_final/resultado_reproceso, etc.) — necesario para que el
    # Módulo 07 (AUDITORIA) pueda leer estado_ingesta/estado_materializacion/
    # estado_motor/estado_final directamente del item final, sin que este
    # módulo los descarte (incompatibilidad real encontrada en FASE 8).
    # HALLAZGO 2 (prueba manual FASE 9): una llamada idempotente repetida
    # (mismo marker ya existente) produce el MISMO mensaje cada vez; sin
    # esta guarda, cada clic de "Publicar" sobre un cierre ya publicado
    # volvía a anexarlo, inflando el historial con copias identicas del
    # mismo evento. El historial debe reflejar EVENTOS reales del cierre,
    # no cuantas veces el usuario volvio a intentar una accion que el
    # backend ya sabe que no tiene efecto — nunca se descarta un evento
    # genuinamente nuevo, solo se evita repetir el ULTIMO si es identico.
    mensajes = list(item.get("mensajes") or [])
    if not mensajes or mensajes[-1] != mensaje:
        mensajes.append(mensaje)
    base = dict(item)
    base.update({
        "fecha": item.get("fecha"), "estado_publicacion": estado_publicacion, "publicado": publicado,
        "sha256": None, "ruta_sap_publicado": None, "ruta_resultado_publicado": None,
        "ruta_cierre_procesado": None, "ruta_marker": None,
        "usuario_auditor": usuario_auditor or item.get("usuario_auditor"),
        "mensaje": mensaje, "mensajes": mensajes,
    })
    base.update(extra)
    return base


def publicar_cierre_dev(item, base_dir_dev, usuario_auditor=None):
    """`item`: registro combinado (01-05) para UN cierre. Debe traer
    `estado_final` (del Módulo 04) o, si vino de una corrección aplicada
    en el Módulo 05, `resultado_reproceso` — ambos usan los MISMOS 5
    nombres de v3.clasificacion. También debe traer `ruta_cierre_local`,
    `ruta_sap` y `ruta_resultado` (rutas ya producidas por el Módulo 03/05).

    Publica ÚNICAMENTE si el estado es LISTO_PARA_PUBLICAR; para
    YA_PROCESADO respeta la idempotencia de V2 sin intentar nada nuevo;
    para cualquier otro estado (ERROR_REVISAR/SIN_ARCHIVO/ERROR_TECNICO/
    AMBIGUO/bloqueado) rechaza sin tocar nada — CONTRACT-011.

    Nunca lanza: cualquier problema se refleja en el resultado de ESTE
    cierre (ver publicar_lote() para el aislamiento de lote)."""
    estado = item.get("resultado_reproceso") or item.get("estado_final")

    if estado == YA_PROCESADO:
        return _salida(item, YA_PUBLICADO, False,
                        "Cierre YA_PROCESADO según el motor (idempotencia SHA256 de V2): nada que publicar.",
                        usuario_auditor)

    if estado not in _ESTADOS_HABILITADOS:
        return _salida(item, NO_PUBLICABLE, False,
                        f"Estado '{estado}' no habilita publicación (CONTRACT-011: solo {_ESTADOS_HABILITADOS}).",
                        usuario_auditor)

    ruta_cierre = item.get("ruta_cierre_local")
    ruta_sap = item.get("ruta_sap")
    ruta_resultado = item.get("ruta_resultado")
    if not ruta_cierre or not ruta_sap or not ruta_resultado:
        return _salida(item, ERROR_PUBLICACION, False,
                        "PUBLICACION_INCOMPLETA: faltan rutas (cierre/sap/resultado) para publicar.",
                        usuario_auditor)

    try:
        sha256 = pipeline.calcular_sha256(ruta_cierre)  # REUTILIZADO tal cual (solo lectura)
        dirs = _directorios_publicacion(base_dir_dev)

        nombre_marker = pipeline.nombre_marcador_procesado(sha256)  # REUTILIZADO tal cual
        ruta_marker = os.path.join(dirs["markers"], nombre_marker)

        nombre_sap_oficial = _nombre_sap_oficial(item.get("fecha"))

        if os.path.isfile(ruta_marker):
            # CONTRACT-008/009: idempotencia — el marcador ya existe, NUNCA
            # se duplica SAP/resultado/cierre procesado/marker.
            ruta_sap_existente = os.path.join(dirs["sap"], nombre_sap_oficial)
            ruta_resultado_existente = os.path.join(dirs["resultados"], os.path.basename(ruta_resultado))
            ruta_procesado_existente = os.path.join(dirs["procesados"], os.path.basename(ruta_cierre))
            return _salida(
                item, YA_PUBLICADO, False,
                "Marcador ya existente en publicacion/markers/: no se republica (idempotencia SHA256).",
                usuario_auditor,
                sha256=sha256,
                ruta_sap_publicado=ruta_sap_existente if os.path.isfile(ruta_sap_existente) else None,
                ruta_resultado_publicado=ruta_resultado_existente if os.path.isfile(ruta_resultado_existente) else None,
                ruta_cierre_procesado=ruta_procesado_existente if os.path.isfile(ruta_procesado_existente) else None,
                ruta_marker=ruta_marker,
            )

        # Publicación DEV: SIEMPRE copyfile (solo lectura del origen, nunca
        # mover/renombrar/borrar). "procesados/" recibe una COPIA del
        # cierre DEV — el original (fuera de base_dir_dev) nunca se toca.
        # El SAP SÍ cambia de NOMBRE en esta copia (nunca de contenido):
        # ver _nombre_sap_oficial().
        ruta_sap_dest = os.path.join(dirs["sap"], nombre_sap_oficial)
        shutil.copyfile(ruta_sap, ruta_sap_dest)

        ruta_resultado_dest = os.path.join(dirs["resultados"], os.path.basename(ruta_resultado))
        shutil.copyfile(ruta_resultado, ruta_resultado_dest)

        ruta_cierre_dest = os.path.join(dirs["procesados"], os.path.basename(ruta_cierre))
        shutil.copyfile(ruta_cierre, ruta_cierre_dest)

        with open(ruta_resultado, "r", encoding="utf-8") as f:
            resultado_json = json.load(f)

        # Las 4 confirmaciones se pasan True porque, en este punto, las 3
        # copias DEV de arriba YA ocurrieron con éxito (si cualquiera
        # hubiera fallado, la excepción se habría propagado antes de
        # llegar aquí) — mismo criterio que V2 aplica en su wiring n8n
        # real (ver auditoria_v2/V2_RISKS.csv RISK-003).
        nombre_marker_real, contenido_marker = pipeline.construir_marcador_procesado(  # REUTILIZADO tal cual
            resultado_json,
            sap_publicado_por_usuario=True, sap_verificado_en_drive=True,
            resultado_publicado=True, cierre_movido_a_procesados=True,
            archivo_sap=os.path.basename(ruta_sap_dest),
            observaciones=f"Publicado en DEV (V3) por {usuario_auditor or 'auditor.dev'}",
        )
        with open(ruta_marker, "w", encoding="utf-8") as f:
            json.dump(contenido_marker, f, ensure_ascii=False, indent=2)

        return _salida(
            item, PUBLICADO, True,
            "Cierre publicado en DEV: SAP + resultado + procesado + marcador.",
            usuario_auditor,
            sha256=sha256, ruta_sap_publicado=ruta_sap_dest, ruta_resultado_publicado=ruta_resultado_dest,
            ruta_cierre_procesado=ruta_cierre_dest, ruta_marker=ruta_marker,
        )
    except ValueError as exc:  # MARCADOR_NO_AUTORIZADO u otro rechazo explicito de V2
        codigo, _, detalle = str(exc).partition(":")
        return _salida(item, ERROR_PUBLICACION, False, f"{codigo}: {detalle or exc}", usuario_auditor)
    except Exception as exc:  # aislamiento tecnico: nunca se propaga fuera de este cierre
        return _salida(item, ERROR_PUBLICACION, False, f"{type(exc).__name__}: {exc}", usuario_auditor)


def publicar_lote(cierres, base_dir_dev, usuario_auditor=None):
    """Aplica publicar_cierre_dev() a cada cierre de la lista — LA MISMA
    función que se usa para publicar un único cierre (ver docstring del
    módulo: no existen dos caminos de lógica). Un error en UNO nunca
    detiene la publicación de los demás."""
    resultados = []
    for item in cierres:
        try:
            resultados.append(publicar_cierre_dev(item, base_dir_dev, usuario_auditor))
        except Exception as exc:  # red de seguridad adicional a nivel de lote
            resultados.append(_salida(item, ERROR_PUBLICACION, False, f"{type(exc).__name__}: {exc}", usuario_auditor))
    return resultados


# ---------------------------------------------------------------------------
# CLI — mismo patrón Python-es-la-unica-autoridad de los módulos anteriores.
# ---------------------------------------------------------------------------

def main(argv=None):
    import argparse

    parser = argparse.ArgumentParser(description="Modulo 06 PUBLICACION de V3 (DEV, adaptador sobre V2).")
    parser.add_argument("--input", required=True, help="JSON {'cierres':[...], 'base_dir_dev':str, 'usuario_auditor':str|null}")
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)

    with open(args.input, "r", encoding="utf-8") as f:
        datos = json.load(f)

    resultado = publicar_lote(datos["cierres"], datos["base_dir_dev"], datos.get("usuario_auditor"))
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump({"resultado": "OK", "cierres": resultado}, f, ensure_ascii=False, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
