"""v3/clasificacion.py — Módulo 04 · CLASIFICACION de Caja Tiquipaya V3
(FASE 5, cuarta etapa).

Este módulo NO calcula contabilidad, NO vuelve a ejecutar Python contable,
NO modifica nada, NO publica y NO corrige: solo decide, para cada cierre
que ya pasó por los módulos 01-03, a cuál de los 5 estados finales que
YA EXISTEN en V2 pertenece. Esos 5 estados y sus nombres exactos NO se
inventan aquí — se PORTAN literalmente de:

  - `run_batch._ESTADO_MAP` (pipeline_tiquipaya.py -> nombre de estado por
    cierre en `resultado_batch.json`):
        ESTADO_YA_PROCESADO       -> "YA_PROCESADO"
        ESTADO_VALIDADO_PENDIENTE -> "LISTO_PARA_PUBLICAR"
        ESTADO_BLOQUEADO          -> "ERROR_REVISAR"
        ESTADO_ERROR              -> "ERROR_REVISAR"
  - `run_batch._entrada_sin_archivo()` -> "SIN_ARCHIVO" (cuando el .xlsm
    no aparece en el directorio de cierres).
  - `run_batch.procesar_cierre()` (bloque except) -> "ERROR_TECNICO"
    (excepción técnica inesperada, nunca una regla de negocio).
  - El propio frontend de V2 (`n8n_frontend/revision_correccion.html`,
    diccionario `ESTADOS`/`MENSAJE_SIN_EXCEPCIONES`) confirma que estos son
    EXACTAMENTE los 5 estados por cierre que existen en producción, y que
    **solo** `ERROR_REVISAR` habilita el módulo de revisión/corrección —
    los otros 4 son terminales de solo lectura. Esa misma distinción es la
    que produce aquí el campo `requiere_revision`.

V3 divide en 3 módulos (01/02/03) lo que en V2 es una sola llamada a
`pipeline_tiquipaya.procesar_cierre_completo()`; este módulo 04 es el punto
donde se reconstruye la MISMA decisión final que V2 tomaría con una sola
llamada, a partir de los 3 resultados parciales — sin reinterpretar ningún
criterio.

CONTRACT-011 (procesar y publicar son responsabilidades separadas):
clasificar como LISTO_PARA_PUBLICAR nunca publica nada — este módulo no
escribe archivos, no sube SAP, no mueve originales, no genera marcadores.
Es una función pura: mismo input, mismo output, sin efectos secundarios.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import run_batch  # noqa: E402  (reutilizado tal cual: _ESTADO_MAP)
from v3.ingesta import SIN_ARCHIVO as ING_SIN_ARCHIVO, AMBIGUO as ING_AMBIGUO, ERROR_INGESTA  # noqa: E402
from v3.materializacion import ERROR_MATERIALIZACION  # noqa: E402
from v3.motor import PROCESADO, NO_PROCESADO, ERROR_MOTOR, _ESTADO_MOTOR_MAP_RESULTADO  # noqa: E402
import pipeline_tiquipaya as pipeline  # noqa: E402


# ---------------------------------------------------------------------------
# Los 5 estados finales de V2 — nombres EXACTOS, no inventados aquí.
# ---------------------------------------------------------------------------

LISTO_PARA_PUBLICAR = "LISTO_PARA_PUBLICAR"
ERROR_REVISAR = "ERROR_REVISAR"
SIN_ARCHIVO = "SIN_ARCHIVO"
YA_PROCESADO = "YA_PROCESADO"
ERROR_TECNICO = "ERROR_TECNICO"

_ESTADOS_FINALES_V2 = (LISTO_PARA_PUBLICAR, ERROR_REVISAR, SIN_ARCHIVO, YA_PROCESADO, ERROR_TECNICO)

ACCION_PUBLICAR = "PUBLICAR"
ACCION_REVISAR = "REVISAR"
ACCION_NINGUNA = "NINGUNA"

# run_batch._ESTADO_MAP (V2, sin cambios) mapea el estado INTERNO de
# pipeline_tiquipaya a estos mismos 4 nombres (YA_PROCESADO/
# LISTO_PARA_PUBLICAR/ERROR_REVISAR/ERROR_REVISAR); se compone aquí con el
# renombrado que ya hace v3.motor (_ESTADO_MOTOR_MAP_RESULTADO) para que el
# campo `resultado` que produce el Módulo 03 mapee a la MISMA decisión
# final que run_batch.py ya toma hoy — sin retipear esa lógica a mano.
_RESULTADO_MOTOR_A_ESTADO_FINAL = {
    _ESTADO_MOTOR_MAP_RESULTADO[estado_interno]: nombre_v2
    for estado_interno, nombre_v2 in run_batch._ESTADO_MAP.items()
}

_ACCION_POR_ESTADO = {
    LISTO_PARA_PUBLICAR: ACCION_PUBLICAR,
    ERROR_REVISAR: ACCION_REVISAR,
    SIN_ARCHIVO: ACCION_NINGUNA,
    YA_PROCESADO: ACCION_NINGUNA,
    ERROR_TECNICO: ACCION_NINGUNA,
}

_MENSAJES = {
    LISTO_PARA_PUBLICAR: "Cierre cuadrado y validado: listo para publicar (aún no publicado).",
    ERROR_REVISAR: "Cierre requiere revisión/corrección del auditor antes de poder publicarse.",
    SIN_ARCHIVO: "No se encontró el archivo de cierre para esta fecha.",
    YA_PROCESADO: "Este cierre ya fue procesado y publicado previamente (idempotencia por SHA256).",
    ERROR_TECNICO: "Error técnico durante ingesta, materialización o ejecución del motor.",
}


def clasificar_cierre(item):
    """`item`: dict que combina los campos ya producidos por los módulos
    01+02+03 para UN cierre (fecha, estado_ingesta, estado_materializacion,
    estado_motor, resultado, diferencia, bloqueadores, ruta_resultado,
    ruta_sap, cargo, haber). Nunca lanza: cualquier combinación no
    reconocida cae, de forma explícita y FAIL-CLOSED, en ERROR_TECNICO —
    NUNCA se clasifica como LISTO_PARA_PUBLICAR algo que no se entiende.

    Función pura: no lee ni escribe ningún archivo, no publica nada."""
    fecha = item.get("fecha")
    estado_ingesta = item.get("estado_ingesta")
    estado_materializacion = item.get("estado_materializacion")
    estado_motor = item.get("estado_motor")
    resultado_motor = item.get("resultado")

    # Prioridad conservadora (misma idea que la aggregacion de V2 en
    # "DECIDIR - Estado del cierre": lo mas temprano/tecnico primero,
    # nunca se reinterpreta un problema de una etapa anterior como si la
    # etapa siguiente lo hubiera resuelto).
    if estado_ingesta == ERROR_INGESTA:
        estado_final = ERROR_TECNICO
    elif estado_ingesta == ING_SIN_ARCHIVO:
        estado_final = SIN_ARCHIVO
    elif estado_ingesta == ING_AMBIGUO:
        # REGLA G: mas de una coincidencia exacta NUNCA se resuelve sola.
        # Requiere decision humana -> mismo destino que una excepcion de
        # negocio (ERROR_REVISAR), nunca SIN_ARCHIVO ni, mucho menos,
        # LISTO_PARA_PUBLICAR.
        estado_final = ERROR_REVISAR
    elif estado_materializacion == ERROR_MATERIALIZACION:
        estado_final = ERROR_TECNICO
    elif estado_motor == ERROR_MOTOR:
        estado_final = ERROR_TECNICO
    elif estado_motor == PROCESADO:
        estado_final = _RESULTADO_MOTOR_A_ESTADO_FINAL.get(resultado_motor, ERROR_TECNICO)
    elif estado_motor == NO_PROCESADO:
        # No debería llegar aquí sin haber calzado ya en uno de los casos
        # de arriba (ingesta/materializacion); si ocurre, es una
        # combinación no contemplada -> fail-closed, nunca "listo".
        estado_final = ERROR_TECNICO
    else:
        estado_final = ERROR_TECNICO  # combinación desconocida: fail-closed

    accion = _ACCION_POR_ESTADO[estado_final]
    mensaje = _MENSAJES[estado_final]
    mensajes = list(item.get("mensajes") or [])
    mensajes.append(mensaje)

    # Se preserva TODO lo que el item ya traía de los Módulos 01-03
    # (archivo_esperado, estado_ingesta, estado_materializacion,
    # estado_motor, ruta_cierre_local/ruta_maestro_local/
    # ruta_template_sap_local/ruta_markers_local) — sin este
    # "carry-forward", el Módulo 05 (REVISION) no tendría las rutas
    # locales que necesita para reprocesar, y el Módulo 06 (PUBLICACION)
    # no tendría ruta_cierre_local para calcular el SHA256 (incompatibilidad
    # real encontrada en FASE 8, corregida aquí y no en el llamador).
    salida = dict(item)
    salida.update({
        "estado_final": estado_final,
        "accion_siguiente": accion,
        "requiere_revision": estado_final == ERROR_REVISAR,  # igual que revision_correccion.html (V2)
        "publicable": estado_final == LISTO_PARA_PUBLICAR,
        "mensaje": mensaje,
        "mensajes": mensajes,
    })
    return salida


def ejecutar_clasificacion(cierres):
    """Aplica clasificar_cierre() a cada cierre del lote. Nunca lanza ni
    detiene el resto del lote por un item individual mal formado."""
    resultados = []
    for item in cierres:
        try:
            resultados.append(clasificar_cierre(item))
        except Exception as exc:  # defensivo: nunca debería ocurrir (clasificar_cierre no lanza)
            resultados.append({
                "fecha": item.get("fecha"), "estado_final": ERROR_TECNICO,
                "accion_siguiente": ACCION_NINGUNA, "requiere_revision": False, "publicable": False,
                "mensaje": f"{type(exc).__name__}: {exc}",
                "diferencia": None, "bloqueadores": None, "ruta_resultado": None,
                "ruta_sap": None, "cargo": None, "haber": None,
            })
    return resultados


# ---------------------------------------------------------------------------
# CLI — mismo patrón Python-es-la-unica-autoridad de los módulos anteriores.
# ---------------------------------------------------------------------------

def main(argv=None):
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Modulo 04 CLASIFICACION de V3 (DEV, funcion pura).")
    parser.add_argument("--input", required=True, help="JSON {'cierres': [...]}")
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)

    with open(args.input, "r", encoding="utf-8") as f:
        datos = json.load(f)

    resultado = ejecutar_clasificacion(datos["cierres"])
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump({"resultado": "OK", "cierres": resultado}, f, ensure_ascii=False, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
