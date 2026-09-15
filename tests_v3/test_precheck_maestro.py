"""tests_v3/test_precheck_maestro.py — pruebas del precheck de cobertura
del maestro (v3/precheck_maestro.py, FASE 10C), la precondición V3 que
corre entre el Módulo 02 MATERIALIZACION y el Módulo 03 MOTOR PYTHON.

Uso: python -m pytest tests_v3/test_precheck_maestro.py -q
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tests"))

import xlsx_fixtures as fx  # noqa: E402
from v3.precheck_maestro import (  # noqa: E402
    evaluar_cobertura_maestro, aplicar_precheck_maestro, filtrar_aptos_para_motor,
    MAESTRO_APTO, BLOQUEADO_MAESTRO_COBERTURA_NO_CONFIRMADA,
)
from v3.materializacion import MATERIALIZADO, SIN_ARCHIVO
from v3.motor import NO_PROCESADO


def _maestro(tmp_path, macros_filas, atc_filas, nombre="MAESTRO.xlsm"):
    ruta = tmp_path / nombre
    fx.crear_maestro_unico(str(ruta), macros_filas=macros_filas, atc_filas=atc_filas)
    return str(ruta)


def _fila_atc(fecha, monto="0.00"):
    return (fecha, "BANCO (NETO)", "110103012", f"ATC {fecha}", monto, "ASIG")


def _fila_macros(fecha, credito="0.01"):
    return (fecha, "COD-TEST", credito)


# 1) cierre <= ambas fechas maximas -> MAESTRO_APTO
def test_cierre_dentro_de_cobertura_da_maestro_apto(tmp_path):
    macros_filas = [_fila_macros(f) for f in ("2026-09-01", "2026-09-05", "2026-09-10")]
    atc_filas = [_fila_atc(f) for f in ("2026-09-01", "2026-09-05", "2026-09-10")]
    ruta = _maestro(tmp_path, macros_filas, atc_filas)

    r = evaluar_cobertura_maestro(ruta, "2026-09-10")
    assert r["estado"] == MAESTRO_APTO
    assert r["fecha_maxima_macros"] == "2026-09-10"
    assert r["fecha_maxima_atc"] == "2026-09-10"

    # una fecha ANTERIOR a la maxima tambien es apta
    r2 = evaluar_cobertura_maestro(ruta, "2026-09-01")
    assert r2["estado"] == MAESTRO_APTO


# 2) cierre > fecha maxima de MACROS -> bloqueado
def test_cierre_posterior_a_macros_bloquea(tmp_path):
    macros_filas = [_fila_macros("2026-09-05")]
    atc_filas = [_fila_atc(f) for f in ("2026-09-01", "2026-09-10")]  # ATC SI llega hasta 09-10
    ruta = _maestro(tmp_path, macros_filas, atc_filas)

    r = evaluar_cobertura_maestro(ruta, "2026-09-10")
    assert r["estado"] == BLOQUEADO_MAESTRO_COBERTURA_NO_CONFIRMADA
    assert r["fecha_maxima_macros"] == "2026-09-05"
    assert r["fecha_maxima_atc"] == "2026-09-10"


# 3) cierre > fecha maxima de ATC -> bloqueado
def test_cierre_posterior_a_atc_bloquea(tmp_path):
    macros_filas = [_fila_macros(f) for f in ("2026-09-01", "2026-09-10")]  # MACROS SI llega hasta 09-10
    atc_filas = [_fila_atc("2026-09-05")]
    ruta = _maestro(tmp_path, macros_filas, atc_filas)

    r = evaluar_cobertura_maestro(ruta, "2026-09-10")
    assert r["estado"] == BLOQUEADO_MAESTRO_COBERTURA_NO_CONFIRMADA
    assert r["fecha_maxima_macros"] == "2026-09-10"
    assert r["fecha_maxima_atc"] == "2026-09-05"


# 4) ambas fuentes insuficientes -> bloqueado
def test_ambas_fuentes_insuficientes_bloquea(tmp_path):
    macros_filas = [_fila_macros("2026-09-03")]
    atc_filas = [_fila_atc("2026-09-04")]
    ruta = _maestro(tmp_path, macros_filas, atc_filas)

    r = evaluar_cobertura_maestro(ruta, "2026-09-10")
    assert r["estado"] == BLOQUEADO_MAESTRO_COBERTURA_NO_CONFIRMADA
    assert r["fecha_maxima_macros"] == "2026-09-03"
    assert r["fecha_maxima_atc"] == "2026-09-04"


# 5) maestro ilegible (archivo inexistente / sin datos) -> bloqueo de precondicion
def test_maestro_inexistente_bloquea():
    r = evaluar_cobertura_maestro("/no/existe/MAESTRO.xlsm", "2026-09-10")
    assert r["estado"] == BLOQUEADO_MAESTRO_COBERTURA_NO_CONFIRMADA
    assert "MAESTRO_ILEGIBLE" in r["mensaje"]
    assert r["fecha_maxima_macros"] is None
    assert r["fecha_maxima_atc"] is None


def test_maestro_sin_ninguna_fecha_registrada_bloquea(tmp_path):
    # Maestro sintacticamente valido (hojas correctas) pero sin ninguna
    # fila de datos -- "no adivinar": sin evidencia, no hay MAESTRO_APTO.
    ruta = _maestro(tmp_path, macros_filas=[], atc_filas=[])
    r = evaluar_cobertura_maestro(ruta, "2026-09-10")
    assert r["estado"] == BLOQUEADO_MAESTRO_COBERTURA_NO_CONFIRMADA
    assert "MAESTRO_SIN_FECHAS_REGISTRADAS" in r["mensaje"]


# 6) un hueco INTERMEDIO (una fecha sin fila propia, anterior a la fecha
#    maxima real) nunca se interpreta automaticamente como desactualizacion
#    -- reproduce el hallazgo real de FASE 10B (ATC TIQUIPAYA sin fila para
#    2026-09-06, con datos hasta 2026-09-10).
def test_hueco_intermedio_no_bloquea_si_hay_cobertura_posterior(tmp_path):
    fechas_macros = ["2026-09-01", "2026-09-02", "2026-09-03", "2026-09-04",
                      "2026-09-05", "2026-09-06", "2026-09-07", "2026-09-08",
                      "2026-09-09", "2026-09-10"]
    # ATC SIN fila para 2026-09-06 (hueco real, p. ej. dia sin ATC aplicable)
    fechas_atc = ["2026-09-01", "2026-09-02", "2026-09-03", "2026-09-04",
                  "2026-09-05", "2026-09-07", "2026-09-08", "2026-09-09", "2026-09-10"]
    macros_filas = [_fila_macros(f) for f in fechas_macros]
    atc_filas = [_fila_atc(f) for f in fechas_atc]
    ruta = _maestro(tmp_path, macros_filas, atc_filas)

    # la fecha DENTRO del hueco (09-06) sigue APTA: lo que importa es hasta
    # donde llegan los datos, no si cada dia individual tiene fila propia.
    r_hueco = evaluar_cobertura_maestro(ruta, "2026-09-06")
    assert r_hueco["estado"] == MAESTRO_APTO
    assert r_hueco["fecha_maxima_atc"] == "2026-09-10"

    # y la ULTIMA fecha real cubierta tambien es apta
    r_max = evaluar_cobertura_maestro(ruta, "2026-09-10")
    assert r_max["estado"] == MAESTRO_APTO

    # pero una fecha REALMENTE posterior a la cobertura sigue bloqueada
    r_fuera = evaluar_cobertura_maestro(ruta, "2026-09-11")
    assert r_fuera["estado"] == BLOQUEADO_MAESTRO_COBERTURA_NO_CONFIRMADA


# ---------------------------------------------------------------------------
# aplicar_precheck_maestro() / filtrar_aptos_para_motor() — orquestacion
# por lote, tal como se inserta entre v3.materializacion y v3.motor.
# ---------------------------------------------------------------------------

def test_aplicar_precheck_solo_anota_items_materializados(tmp_path):
    ruta_apta = _maestro(tmp_path, [_fila_macros("2026-09-10")], [_fila_atc("2026-09-10")], "APTO.xlsm")
    items = [
        {"fecha": "2026-09-01", "estado_materializacion": SIN_ARCHIVO},
        {"fecha": "2026-09-10", "estado_materializacion": MATERIALIZADO, "ruta_maestro_local": ruta_apta},
    ]
    anotados = aplicar_precheck_maestro(items)
    assert "estado_precheck_maestro" not in anotados[0]  # nunca se evalua lo que no hace falta
    assert anotados[1]["estado_precheck_maestro"] == MAESTRO_APTO


# 7) un cierre BLOQUEADO por el precheck nunca llega al Modulo 03 (motor):
#    filtrar_aptos_para_motor() lo excluye explicitamente de la lista que
#    v3.motor.ejecutar_motor() recibe -- no es "no procesado dentro del
#    motor", es "el motor jamas lo ve".
def test_cierre_bloqueado_nunca_pasa_a_filtrar_aptos_para_motor(tmp_path):
    ruta_vieja = _maestro(tmp_path, [_fila_macros("2026-09-05")], [_fila_atc("2026-09-05")], "VIEJO.xlsm")
    ruta_apta = _maestro(tmp_path, [_fila_macros("2026-09-11")], [_fila_atc("2026-09-11")], "APTO.xlsm")
    items = [
        {"fecha": "2026-09-11", "estado_materializacion": MATERIALIZADO, "ruta_maestro_local": ruta_vieja},
        {"fecha": "2026-09-05", "estado_materializacion": MATERIALIZADO, "ruta_maestro_local": ruta_apta},
    ]
    anotados = aplicar_precheck_maestro(items)
    bloqueado, apto = anotados
    assert bloqueado["estado_precheck_maestro"] == BLOQUEADO_MAESTRO_COBERTURA_NO_CONFIRMADA
    assert bloqueado["estado_motor"] == NO_PROCESADO
    assert bloqueado["resultado"] is None
    assert apto["estado_precheck_maestro"] == MAESTRO_APTO

    aptos_para_motor = filtrar_aptos_para_motor(anotados)
    fechas_aptas = {c["fecha"] for c in aptos_para_motor}
    assert fechas_aptas == {"2026-09-05"}  # el bloqueado (09-11) nunca aparece aqui
    assert len(aptos_para_motor) == 1


def test_cierre_bloqueado_en_procesar_lote_no_invoca_motor_real(tmp_path, monkeypatch):
    # Integracion con v3.dev_api.procesar_lote(): el cierre bloqueado
    # termina con estado_final BLOQUEADO_MAESTRO_COBERTURA_NO_CONFIRMADA y
    # pipeline_tiquipaya.procesar_cierre_completo() NUNCA se llama para esa
    # fecha (se intercepta la funcion real para probarlo, no se confia
    # solo en el resultado final).
    import pipeline_tiquipaya as pipeline
    from v3 import dev_api

    llamadas = []
    original = pipeline.procesar_cierre_completo

    def _espia(*args, **kwargs):
        llamadas.append(kwargs.get("ruta_cierre") or (args[0] if args else None))
        return original(*args, **kwargs)

    monkeypatch.setattr(pipeline, "procesar_cierre_completo", _espia)

    origen_dir = tmp_path / "origen"
    origen_dir.mkdir()
    import run_batch
    nombre = run_batch.nombre_cierre_esperado("2026-09-11")
    fx.crear_cierre(
        str(origen_dir / nombre),
        {"total_movimiento": "0.00", "cobros_atc": "0.00", "dolares": "0.00", "depositos": []},
        {"total_movimiento": "0.00", "cobros_atc": "0.00", "dolares": "0.00", "depositos": []},
    )
    # maestro con cobertura SOLO hasta 09-10 (como el maestro real de FASE 10B)
    ruta_maestro = _maestro(tmp_path, [_fila_macros("2026-09-10")], [_fila_atc("2026-09-10")])
    ruta_plantilla = tmp_path / "Plantilla.xlsx"
    fx.crear_plantilla_sap(str(ruta_plantilla))

    base_dir_dev = str(tmp_path / "dev")
    r = dev_api.crear_lote_pendiente("2026-09-11", "2026-09-11", "auditor.dev", base_dir_dev)
    lote = dev_api.procesar_lote(
        r["lote_id"], base_dir_dev, str(origen_dir), ruta_maestro, str(ruta_plantilla),
    )
    assert lote["cierres"][0]["estado_final"] == BLOQUEADO_MAESTRO_COBERTURA_NO_CONFIRMADA
    assert lote["cierres"][0]["fecha_maxima_macros"] == "2026-09-10"
    assert lote["cierres"][0]["fecha_maxima_atc"] == "2026-09-10"
    assert llamadas == []  # el motor real JAMAS se invoco para este cierre
    # ni corregible ni publicable: no es un problema del cierre que el
    # auditor deba resolver desde el formulario de correccion.
    assert lote["cierres"][0]["requiere_revision"] is False
    assert lote["cierres"][0]["publicable"] is False


def test_cierre_apto_en_procesar_lote_si_llega_al_motor(tmp_path):
    from v3 import dev_api
    import run_batch

    origen_dir = tmp_path / "origen"
    origen_dir.mkdir()
    nombre = run_batch.nombre_cierre_esperado("2026-09-10")
    fx.crear_cierre(
        str(origen_dir / nombre),
        {"total_movimiento": "0.00", "cobros_atc": "0.00", "dolares": "0.00", "depositos": []},
        {"total_movimiento": "0.00", "cobros_atc": "0.00", "dolares": "0.00", "depositos": []},
    )
    ruta_maestro = _maestro(tmp_path, [_fila_macros("2026-09-10")], [_fila_atc("2026-09-10")])
    ruta_plantilla = tmp_path / "Plantilla.xlsx"
    fx.crear_plantilla_sap(str(ruta_plantilla))

    base_dir_dev = str(tmp_path / "dev")
    r = dev_api.crear_lote_pendiente("2026-09-10", "2026-09-10", "auditor.dev", base_dir_dev)
    lote = dev_api.procesar_lote(
        r["lote_id"], base_dir_dev, str(origen_dir), ruta_maestro, str(ruta_plantilla),
    )
    assert lote["cierres"][0]["estado_precheck_maestro"] == MAESTRO_APTO
    assert lote["cierres"][0]["estado_final"] != BLOQUEADO_MAESTRO_COBERTURA_NO_CONFIRMADA
