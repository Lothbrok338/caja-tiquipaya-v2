"""tests_v3/test_avance_caja.py — "Procesado continuo hasta" (v3/avance_caja.py).

Cubre lo que esa función decide: qué nombres cuentan como SAP oficial por
caja (config-driven), dónde se corta la continuidad ante un hueco, y que la
acción `avance_caja` de v3/dev_api.py (la que invoca n8n) devuelve el mismo
resultado por el CLI real (--input/--output).

Uso: python -m pytest tests_v3/test_avance_caja.py -q
"""
import json
import os
import subprocess
import sys

import pytest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

import config_cajas as cfg  # noqa: E402
from v3.avance_caja import calcular_avance, fechas_procesadas  # noqa: E402


def _sap(prefijo, *dias, mes=9, anio=2026):
    return [f"SAP_{prefijo}_{d:02d}-{mes:02d}-{anio}.xlsx" for d in dias]


def test_hueco_corta_la_continuidad_no_es_la_fecha_maxima():
    # 01..10 procesados, 11 pendiente, 12 procesado -> continuo hasta 10, NO 12.
    r = calcular_avance("tiquipaya", _sap("TIQ", *range(1, 11), 12))
    assert r["procesado_continuo_hasta"] == "2026-09-10"
    assert r["ultimo_cierre_existente"] == "2026-09-12"
    assert r["pendientes"] == 1
    assert r["primer_pendiente"] == "2026-09-11"
    assert r["desde"] == "2026-09-01"
    assert r["disponible"] is True and r["caja"] == "tiquipaya"


def test_sin_huecos_continuo_es_el_ultimo():
    r = calcular_avance("tiquipaya", _sap("TIQ", *range(1, 13)))
    assert r["procesado_continuo_hasta"] == r["ultimo_cierre_existente"] == "2026-09-12"
    assert r["pendientes"] == 0 and r["primer_pendiente"] is None


def test_dia_uno_pendiente_no_hay_racha_continua():
    r = calcular_avance("tiquipaya", _sap("TIQ", 2, 3, 4))
    assert r["procesado_continuo_hasta"] is None
    assert r["ultimo_cierre_existente"] == "2026-09-04"
    assert r["pendientes"] == 1 and r["primer_pendiente"] == "2026-09-01"


def test_varios_huecos_cuentan_todos_pero_el_continuo_solo_llega_al_primero():
    r = calcular_avance("tiquipaya", _sap("TIQ", 1, 2, 3, 6, 9))
    assert r["procesado_continuo_hasta"] == "2026-09-03"
    assert r["pendientes"] == 4  # 4, 5, 7, 8
    assert r["primer_pendiente"] == "2026-09-04"


def test_sin_cierres():
    r = calcular_avance("tiquipaya", [])
    assert r["procesado_continuo_hasta"] is None and r["ultimo_cierre_existente"] is None
    assert r["pendientes"] == 0 and r["dias_procesados"] == 0
    assert calcular_avance("america", None)["ultimo_cierre_existente"] is None


def test_ventana_es_el_mes_del_ultimo_cierre():
    # Un cierre de agosto no cuenta como hueco del avance de septiembre.
    nombres = _sap("TIQ", 30, 31, mes=8) + _sap("TIQ", 1, 2)
    r = calcular_avance("tiquipaya", nombres)
    assert r["desde"] == "2026-09-01"
    assert r["procesado_continuo_hasta"] == "2026-09-02" and r["pendientes"] == 0


def test_cada_caja_solo_ve_sus_propios_sap_por_configuracion():
    nombres = _sap("TIQ", 1, 2, 3) + _sap("AME", 1, 2, 3, 4, 5)
    assert calcular_avance("tiquipaya", nombres)["procesado_continuo_hasta"] == "2026-09-03"
    assert calcular_avance("america", nombres)["procesado_continuo_hasta"] == "2026-09-05"


def test_todas_las_cajas_configuradas_funcionan_sin_codigo_especifico():
    for codigo, caja in cfg.CAJAS.items():
        r = calcular_avance(codigo, _sap(caja.prefijo_archivo, 1, 2))
        assert r["caja"] == codigo and r["procesado_continuo_hasta"] == "2026-09-02"


def test_no_cuentan_global_resultado_temporales_ni_fechas_imposibles():
    nombres = [
        "SAP_GLOBAL_TIQ_SEPTIEMBRE_2026.xlsx", "RESULTADO_TIQ_01-09-2026.json",
        "~$SAP_TIQ_01-09-2026.xlsx", "SAP_TIQ_31-02-2026.xlsx", "SAP_TIQ_01-09-2026.xlsx.tmp",
        "notas.txt", None, 123,
    ]
    assert fechas_procesadas("tiquipaya", nombres) == set()


def test_legacy_solo_para_tiquipaya():
    assert calcular_avance("tiquipaya", ["SAP_01-09-2026.xlsx", "SAP_02-09-2026.xlsx"])["procesado_continuo_hasta"] == "2026-09-02"
    assert calcular_avance("america", ["SAP_01-09-2026.xlsx"])["ultimo_cierre_existente"] is None


def test_caja_desconocida_falla_cerrado():
    with pytest.raises(ValueError):
        calcular_avance("inexistente", _sap("TIQ", 1))


def test_accion_avance_caja_del_cli_dev_api(tmp_path):
    entrada, salida = tmp_path / "in.json", tmp_path / "out.json"
    entrada.write_text(json.dumps({"caja": "america", "nombres_archivos": _sap("AME", 1, 2, 4)}), encoding="utf-8")
    r = subprocess.run(
        [sys.executable, "-m", "v3.dev_api", "--accion", "avance_caja", "--input", str(entrada), "--output", str(salida)],
        cwd=RAIZ, capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr
    out = json.loads(salida.read_text(encoding="utf-8"))
    assert out["resultado"] == "OK" and out["caja"] == "america"
    assert out["procesado_continuo_hasta"] == "2026-09-02"
    assert out["pendientes"] == 1 and out["primer_pendiente"] == "2026-09-03"


def test_accion_avance_caja_caja_desconocida_devuelve_error_limpio(tmp_path):
    entrada, salida = tmp_path / "in.json", tmp_path / "out.json"
    entrada.write_text(json.dumps({"caja": "inexistente", "nombres_archivos": []}), encoding="utf-8")
    r = subprocess.run(
        [sys.executable, "-m", "v3.dev_api", "--accion", "avance_caja", "--input", str(entrada), "--output", str(salida)],
        cwd=RAIZ, capture_output=True, text=True,
    )
    assert r.returncode == 0
    assert json.loads(salida.read_text(encoding="utf-8"))["resultado"] == "ERROR"
