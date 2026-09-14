"""tests_v3/test_clasificacion.py — pruebas propias del módulo 04 ·
CLASIFICACION de V3 (v3/clasificacion.py). Verifica que los 5 estados
finales y sus criterios son EXACTAMENTE los de V2 (run_batch._ESTADO_MAP +
run_batch._entrada_sin_archivo/ERROR_TECNICO), no una reinterpretación.

Uso: python -m pytest tests_v3/test_clasificacion.py -q
"""

import hashlib
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from v3.clasificacion import (
    clasificar_cierre, ejecutar_clasificacion,
    LISTO_PARA_PUBLICAR, ERROR_REVISAR, SIN_ARCHIVO, YA_PROCESADO, ERROR_TECNICO,
    ACCION_PUBLICAR, ACCION_REVISAR, ACCION_NINGUNA,
)


def _sha256(ruta):
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        for bloque in iter(lambda: f.read(1 << 16), b""):
            h.update(bloque)
    return h.hexdigest()


def _base_item(**overrides):
    item = {
        "fecha": "2026-09-01", "estado_ingesta": "ENCONTRADO", "estado_materializacion": "MATERIALIZADO",
        "estado_motor": "PROCESADO", "resultado": "VALIDADO_PENDIENTE_PUBLICACION",
        "diferencia": "0.00", "bloqueadores": 0, "ruta_resultado": None, "ruta_sap": None,
        "cargo": "100.00", "haber": "100.00",
    }
    item.update(overrides)
    return item


# 1) cierre valido sin bloqueadores -> mismo estado que V2 (LISTO_PARA_PUBLICAR)
def test_cierre_valido_da_listo_para_publicar():
    r = clasificar_cierre(_base_item())
    assert r["estado_final"] == LISTO_PARA_PUBLICAR
    assert r["accion_siguiente"] == ACCION_PUBLICAR
    assert r["publicable"] is True
    assert r["requiere_revision"] is False


# 2) bloqueo/excepcion -> mismo estado de revision que V2 (ERROR_REVISAR)
@pytest.mark.parametrize("resultado_motor", ["BLOQUEADO_EXCEPCION", "ERROR"])
def test_bloqueo_o_error_pipeline_da_error_revisar(resultado_motor):
    r = clasificar_cierre(_base_item(resultado=resultado_motor, diferencia="50.00", bloqueadores=1))
    assert r["estado_final"] == ERROR_REVISAR
    assert r["accion_siguiente"] == ACCION_REVISAR
    assert r["requiere_revision"] is True
    assert r["publicable"] is False


# 3) SIN_ARCHIVO
def test_sin_archivo_ingesta_da_sin_archivo():
    r = clasificar_cierre(_base_item(
        estado_ingesta="SIN_ARCHIVO", estado_materializacion="SIN_ARCHIVO",
        estado_motor="NO_PROCESADO", resultado="SIN_ARCHIVO",
    ))
    assert r["estado_final"] == SIN_ARCHIVO
    assert r["accion_siguiente"] == ACCION_NINGUNA
    assert r["requiere_revision"] is False
    assert r["publicable"] is False


# 4) AMBIGUO -> ERROR_REVISAR (REGLA G: nunca se resuelve solo)
def test_ambiguo_ingesta_da_error_revisar_nunca_listo():
    r = clasificar_cierre(_base_item(
        estado_ingesta="AMBIGUO", estado_materializacion="AMBIGUO",
        estado_motor="NO_PROCESADO", resultado="AMBIGUO",
    ))
    assert r["estado_final"] == ERROR_REVISAR
    assert r["estado_final"] != LISTO_PARA_PUBLICAR
    assert r["requiere_revision"] is True


# 5) ERROR_INGESTA -> ERROR_TECNICO
def test_error_ingesta_da_error_tecnico():
    r = clasificar_cierre(_base_item(
        estado_ingesta="ERROR_INGESTA", estado_materializacion="ERROR_INGESTA",
        estado_motor="NO_PROCESADO", resultado="ERROR_INGESTA",
    ))
    assert r["estado_final"] == ERROR_TECNICO
    assert r["accion_siguiente"] == ACCION_NINGUNA
    assert r["requiere_revision"] is False  # V2: ERROR_TECNICO no habilita el modulo de revision/correccion


# 6) ERROR_MATERIALIZACION -> ERROR_TECNICO
def test_error_materializacion_da_error_tecnico():
    r = clasificar_cierre(_base_item(
        estado_materializacion="ERROR_MATERIALIZACION",
        estado_motor="NO_PROCESADO", resultado="ERROR_MATERIALIZACION",
    ))
    assert r["estado_final"] == ERROR_TECNICO


# 7) ERROR_MOTOR -> ERROR_TECNICO
def test_error_motor_da_error_tecnico():
    r = clasificar_cierre(_base_item(estado_motor="ERROR_MOTOR", resultado=None))
    assert r["estado_final"] == ERROR_TECNICO


# 8) YA_PROCESADO
def test_ya_procesado_da_ya_procesado():
    r = clasificar_cierre(_base_item(resultado="YA_PROCESADO"))
    assert r["estado_final"] == YA_PROCESADO
    assert r["accion_siguiente"] == ACCION_NINGUNA
    assert r["publicable"] is False
    assert r["requiere_revision"] is False


# 9) diferencia distinta de cero -> nunca LISTO (V2: pipeline solo marca
# VALIDADO_PENDIENTE_PUBLICACION si diferencia==0; cualquier otro caso con
# blockers==0 pero diferencia!=0 termina en estado interno ERROR).
def test_diferencia_no_cero_nunca_es_listo():
    r = clasificar_cierre(_base_item(resultado="ERROR", diferencia="25.00", bloqueadores=0))
    assert r["estado_final"] != LISTO_PARA_PUBLICAR
    assert r["estado_final"] == ERROR_REVISAR


# 10) Cargo/Haber invalido (asiento.estado=ERROR en V2) -> mismo criterio: ERROR_REVISAR
def test_cargo_haber_invalido_dispara_mismo_criterio_v2():
    r = clasificar_cierre(_base_item(resultado="ERROR", cargo="100.00", haber="90.00"))
    assert r["estado_final"] == ERROR_REVISAR
    assert r["cargo"] == "100.00" and r["haber"] == "90.00"  # se conserva la metadata, no se "arregla"


# 11) clasificacion no publica nada (funcion pura, sin I/O)
def test_clasificacion_no_crea_archivos(tmp_path):
    antes = set(os.listdir(tmp_path))
    clasificar_cierre(_base_item(ruta_resultado=str(tmp_path / "no_deberia_crearse.json")))
    despues = set(os.listdir(tmp_path))
    assert antes == despues
    assert not (tmp_path / "no_deberia_crearse.json").exists()


# 12) clasificacion no modifica archivos ni resultados existentes
def test_clasificacion_no_modifica_archivos_existentes(tmp_path):
    ruta_resultado = tmp_path / "RESULTADO_TIQ_01-09-2026.json"
    ruta_resultado.write_text(json.dumps({"algo": "ya calculado por el Modulo 03"}))
    ruta_sap = tmp_path / "SAP_01-09-2026.xlsx"
    ruta_sap.write_bytes(b"contenido-sap-ficticio")

    hash_resultado_antes = _sha256(str(ruta_resultado))
    hash_sap_antes = _sha256(str(ruta_sap))

    clasificar_cierre(_base_item(ruta_resultado=str(ruta_resultado), ruta_sap=str(ruta_sap)))

    assert _sha256(str(ruta_resultado)) == hash_resultado_antes
    assert _sha256(str(ruta_sap)) == hash_sap_antes


# ---------------------------------------------------------------------------
# Defensivos adicionales
# ---------------------------------------------------------------------------

def test_combinacion_desconocida_es_fail_closed_error_tecnico():
    r = clasificar_cierre(_base_item(estado_motor="ALGO_NUNCA_VISTO", resultado="ALGO_NUNCA_VISTO"))
    assert r["estado_final"] == ERROR_TECNICO
    assert r["estado_final"] != LISTO_PARA_PUBLICAR


def test_ejecutar_clasificacion_aisla_items_individuales():
    items = [_base_item(fecha="2026-09-01"), {"fecha": "2026-09-02"}]  # 2do item minimo/incompleto
    resultados = ejecutar_clasificacion(items)
    assert len(resultados) == 2
    assert resultados[0]["estado_final"] == LISTO_PARA_PUBLICAR
    assert resultados[1]["estado_final"] == ERROR_TECNICO  # fail-closed, nunca crashea


def test_todas_las_filas_tienen_al_menos_las_claves_pedidas():
    # FASE 8: clasificar_cierre() ahora preserva TODO lo que el item ya
    # traía de los Módulos 01-03 (carry-forward, ver docstring) además de
    # agregar sus propias claves — por eso la aserción es "al menos estas
    # claves", no un conjunto exacto (el conjunto exacto depende de lo que
    # el llamador ya haya puesto en el item de entrada).
    r = clasificar_cierre(_base_item())
    esperado_minimo = {
        "fecha", "estado_final", "accion_siguiente", "requiere_revision", "publicable",
        "mensaje", "mensajes", "diferencia", "bloqueadores", "ruta_resultado", "ruta_sap", "cargo", "haber",
    }
    assert esperado_minimo.issubset(set(r.keys()))


def test_preserva_campos_de_modulos_anteriores_no_contemplados_en_su_propio_schema():
    # Campos que 01-03 ya calcularon y que 04 NO necesita para clasificar,
    # pero que 05/06/07 SÍ necesitan más adelante (rutas locales) deben
    # sobrevivir intactos a través de clasificar_cierre().
    r = clasificar_cierre(_base_item(
        archivo_esperado="CIERRE 01-09-2026.xlsm",
        ruta_cierre_local="/dev/cierres/CIERRE 01-09-2026.xlsm",
        ruta_maestro_local="/dev/maestro/MAESTRO.xlsm",
        ruta_template_sap_local="/dev/plantilla/Plantilla.xlsx",
        ruta_markers_local="/dev/markers",
    ))
    assert r["archivo_esperado"] == "CIERRE 01-09-2026.xlsm"
    assert r["ruta_cierre_local"] == "/dev/cierres/CIERRE 01-09-2026.xlsm"
    assert r["ruta_maestro_local"] == "/dev/maestro/MAESTRO.xlsm"
    assert r["ruta_template_sap_local"] == "/dev/plantilla/Plantilla.xlsx"
    assert r["ruta_markers_local"] == "/dev/markers"


def test_solo_5_estados_finales_posibles():
    from v3.clasificacion import _ESTADOS_FINALES_V2
    assert set(_ESTADOS_FINALES_V2) == {
        LISTO_PARA_PUBLICAR, ERROR_REVISAR, SIN_ARCHIVO, YA_PROCESADO, ERROR_TECNICO,
    }
    assert len(_ESTADOS_FINALES_V2) == 5
