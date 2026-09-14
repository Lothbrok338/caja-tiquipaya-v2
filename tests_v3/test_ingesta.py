"""tests_v3/test_ingesta.py — pruebas propias del módulo 01 · INGESTA de V3
(v3/ingesta.py). Independiente de tests/ (suite V2, sin cambios) y de
parity_v3/ (comparación de contratos V2 vs V3): esto verifica que el
CÓDIGO DE V3 en sí mismo se comporta como se diseñó.

Uso: python -m pytest tests_v3/ -q
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from v3.ingesta import (
    buscar_cierre_exacto, ejecutar_ingesta,
    ENCONTRADO, SIN_ARCHIVO, AMBIGUO, ERROR_INGESTA,
)


# ---------------------------------------------------------------------------
# buscar_cierre_exacto() — REGLA G
# ---------------------------------------------------------------------------

def test_una_coincidencia_exacta_da_encontrado():
    estado, file_id, n = buscar_cierre_exacto(
        "CIERRE 09-09-2026.xlsm",
        [{"nombre": "CIERRE 09-09-2026.xlsm", "file_id": "abc123"}],
    )
    assert (estado, file_id, n) == (ENCONTRADO, "abc123", 1)


def test_cero_coincidencias_da_sin_archivo():
    estado, file_id, n = buscar_cierre_exacto(
        "CIERRE 09-09-2026.xlsm",
        [{"nombre": "CIERRE 10-09-2026.xlsm", "file_id": "xyz"}],
    )
    assert (estado, file_id, n) == (SIN_ARCHIVO, None, 0)


def test_carpeta_vacia_da_sin_archivo():
    estado, file_id, n = buscar_cierre_exacto("CIERRE 09-09-2026.xlsm", [])
    assert (estado, file_id, n) == (SIN_ARCHIVO, None, 0)


def test_multiples_coincidencias_exactas_da_ambiguo_nunca_primero():
    estado, file_id, n = buscar_cierre_exacto(
        "CIERRE 09-09-2026.xlsm",
        [
            {"nombre": "CIERRE 09-09-2026.xlsm", "file_id": "primero"},
            {"nombre": "CIERRE 09-09-2026.xlsm", "file_id": "segundo"},
        ],
    )
    assert estado == AMBIGUO
    assert file_id is None  # NUNCA se elige "primero" ni ningún otro
    assert n == 2


def test_incidente_real_09_10_11_nunca_toma_primer_resultado():
    # Reproduce el incidente documentado: al buscar el cierre 09, una
    # carpeta que también contiene 10 y 11 NO debe hacer que se tome
    # ninguno de esos por error (aquí no hay coincidencia EXACTA para
    # "09" salvo el propio archivo 09 -> ENCONTRADO, nunca 10 ni 11).
    candidatos = [
        {"nombre": "CIERRE 09-09-2026.xlsm", "file_id": "id-09"},
        {"nombre": "CIERRE 10-09-2026.xlsm", "file_id": "id-10"},
        {"nombre": "CIERRE 11-09-2026.xlsm", "file_id": "id-11"},
    ]
    estado, file_id, n = buscar_cierre_exacto("CIERRE 09-09-2026.xlsm", candidatos)
    assert (estado, file_id, n) == (ENCONTRADO, "id-09", 1)


def test_acepta_strings_simples_sin_file_id():
    estado, file_id, n = buscar_cierre_exacto("CIERRE 09-09-2026.xlsm", ["CIERRE 09-09-2026.xlsm"])
    assert (estado, file_id, n) == (ENCONTRADO, None, 1)


def test_coincidencia_no_es_substring_ni_prefijo():
    # "CIERRE 09-09-2026.xlsm" NUNCA hace match con un nombre que solo lo
    # contiene como substring/variante (ej. una copia "(1)").
    estado, _, n = buscar_cierre_exacto(
        "CIERRE 09-09-2026.xlsm",
        [{"nombre": "CIERRE 09-09-2026 (1).xlsm", "file_id": "copia"}],
    )
    assert (estado, n) == (SIN_ARCHIVO, 0)


# ---------------------------------------------------------------------------
# ejecutar_ingesta() — orquestación por rango
# ---------------------------------------------------------------------------

def test_ejecutar_ingesta_un_dia_encontrado():
    resultados = ejecutar_ingesta(
        "2026-09-09", "2026-09-09",
        {"2026-09-09": [{"nombre": "CIERRE 09-09-2026.xlsm", "file_id": "id-09"}]},
    )
    assert len(resultados) == 1
    r = resultados[0]
    assert r["fecha"] == "2026-09-09"
    assert r["archivo_esperado"] == "CIERRE 09-09-2026.xlsm"
    assert r["estado_ingesta"] == ENCONTRADO
    assert r["drive_file_id"] == "id-09"
    assert r["coincidencias"] == 1
    assert isinstance(r["mensaje"], str) and r["mensaje"]


def test_ejecutar_ingesta_rango_multiple_estados_mezclados():
    resultados = ejecutar_ingesta(
        "2026-09-01", "2026-09-03",
        {
            "2026-09-01": [{"nombre": "CIERRE 01-09-2026.xlsm", "file_id": "id-01"}],
            # 2026-09-02 ausente del dict -> tratado como carpeta vacia (SIN_ARCHIVO)
            "2026-09-03": [
                {"nombre": "CIERRE 03-09-2026.xlsm", "file_id": "a"},
                {"nombre": "CIERRE 03-09-2026.xlsm", "file_id": "b"},
            ],
        },
    )
    estados = {r["fecha"]: r["estado_ingesta"] for r in resultados}
    assert estados == {
        "2026-09-01": ENCONTRADO,
        "2026-09-02": SIN_ARCHIVO,
        "2026-09-03": AMBIGUO,
    }


def test_ejecutar_ingesta_fecha_ausente_del_dict_es_sin_archivo_no_error():
    resultados = ejecutar_ingesta("2026-09-05", "2026-09-05", {})
    assert resultados[0]["estado_ingesta"] == SIN_ARCHIVO
    assert resultados[0]["estado_ingesta"] != ERROR_INGESTA


def test_ejecutar_ingesta_reutiliza_regla_mismo_mes_de_run_batch():
    with pytest.raises(ValueError) as exc:
        ejecutar_ingesta("2026-09-28", "2026-10-02", {})
    assert "RANGO_CRUZA_MES" in str(exc.value)


def test_ejecutar_ingesta_forma_candidato_invalida_da_error_ingesta_aislado():
    # Un valor no iterable para una fecha especifica no debe tumbar el
    # resto del rango: se refleja como ERROR_INGESTA solo en esa fila.
    resultados = ejecutar_ingesta(
        "2026-09-01", "2026-09-02",
        {"2026-09-01": [{"nombre": "CIERRE 01-09-2026.xlsm", "file_id": "ok"}], "2026-09-02": 12345},
    )
    por_fecha = {r["fecha"]: r for r in resultados}
    assert por_fecha["2026-09-01"]["estado_ingesta"] == ENCONTRADO
    assert por_fecha["2026-09-02"]["estado_ingesta"] == ERROR_INGESTA
    assert por_fecha["2026-09-02"]["drive_file_id"] is None
    assert por_fecha["2026-09-02"]["coincidencias"] is None


def test_todas_las_filas_tienen_exactamente_las_6_claves_pedidas():
    resultados = ejecutar_ingesta("2026-09-01", "2026-09-01", {})
    esperado = {"fecha", "archivo_esperado", "estado_ingesta", "drive_file_id", "coincidencias", "mensaje"}
    assert set(resultados[0].keys()) == esperado
