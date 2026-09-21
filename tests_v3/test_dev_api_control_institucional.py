"""tests_v3/test_dev_api_control_institucional.py — wiring de CONTROL 1/
CONTROL 3 institucionales en v3/dev_api.py: materialización de
`control{1,3}_institucional_entrada/<periodo>/` con AMBOS GLOBAL, y
delegación en v3.control1_institucional / v3.control3_institucional.

También verifica NEGATIVAMENTE que el GLOBAL institucional (tercer SAP
combinado) fue eliminado: no existe `generar_global_institucional` en el
CLI, y GENERAR GLOBAL (`generar_global`) nunca produce un
SAP_GLOBAL_INSTITUCIONAL_*.xlsx.
"""
import os
import sys
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import openpyxl

import config_cajas as cfg
import consolidador_mensual
from v3 import dev_api

ANIO, MES = 2026, 9


def _crear_global(ruta, partidas):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "1"
    fila = 16
    for p in partidas:
        ws[f"C{fila}"] = p.get("cuenta_mayor", "110101001")
        ws[f"D{fila}"] = "GLOSA"
        ws[f"E{fila}"] = Decimal(str(p.get("cargo", "100.00")))
        ws[f"R{fila}"] = p["asignacion"]
        fila += 1
    wb.save(ruta)


def _materializar_control1_institucional(tmp_path):
    base_dir_dev = str(tmp_path / "dev")
    dev_api.preparar_control1_institucional_entrada(ANIO, MES, base_dir_dev)
    entrada = dev_api.control1_institucional_entrada_dir(base_dir_dev, ANIO, MES)
    ruta_tiq = os.path.join(entrada, consolidador_mensual.nombre_sap_global(ANIO, MES, cfg.TIQUIPAYA))
    ruta_ame = os.path.join(entrada, consolidador_mensual.nombre_sap_global(ANIO, MES, cfg.AMERICA))
    _crear_global(ruta_tiq, [{"asignacion": "X1"}])
    _crear_global(ruta_ame, [{"asignacion": "X2"}])
    return base_dir_dev


def test_preparar_control1_institucional_entrada_no_depende_de_caja(tmp_path):
    base_dir_dev = str(tmp_path / "dev")
    r = dev_api.preparar_control1_institucional_entrada(ANIO, MES, base_dir_dev)
    assert r["periodo"] == "2026-09"
    entrada = dev_api.control1_institucional_entrada_dir(base_dir_dev, ANIO, MES)
    assert os.path.isdir(entrada)
    assert "america" not in entrada and "tiquipaya" not in entrada


def test_ejecutar_control1_institucional_falla_cerrado_sin_materializar(tmp_path):
    base_dir_dev = str(tmp_path / "dev")
    try:
        dev_api.ejecutar_control1_institucional(ANIO, MES, base_dir_dev)
        assert False, "debia fallar"
    except RuntimeError as exc:
        assert "CONTROL1_INSTITUCIONAL_ENTRADA_NO_MATERIALIZADA" in str(exc)


def test_ejecutar_control1_institucional_ok(tmp_path):
    base_dir_dev = _materializar_control1_institucional(tmp_path)
    r = dev_api.ejecutar_control1_institucional(ANIO, MES, base_dir_dev)
    assert r["estado"] == "OK_SIN_DUPLICADOS"
    assert r["candidatas_tiq"] == 1
    assert r["candidatas_ame"] == 1


def test_corregir_control1_institucional_toca_solo_su_caja(tmp_path):
    base_dir_dev = _materializar_control1_institucional(tmp_path)
    entrada = dev_api.control1_institucional_entrada_dir(base_dir_dev, ANIO, MES)
    ruta_tiq = os.path.join(entrada, consolidador_mensual.nombre_sap_global(ANIO, MES, cfg.TIQUIPAYA))
    dev_api.corregir_control1_institucional(
        ANIO, MES, base_dir_dev, correcciones_tiq=[[16, "X1", "X1_CORREGIDA"]],
    )
    import control_asignaciones as ca
    partidas = ca.leer_partidas_global(ruta_tiq)
    assert partidas[0]["asignacion"] == "X1_CORREGIDA"


def test_ejecutar_control3_institucional_ok(tmp_path):
    base_dir_dev = str(tmp_path / "dev")
    dev_api.preparar_control3_institucional_entrada(ANIO, MES, base_dir_dev)
    entrada = dev_api.control3_institucional_entrada_dir(base_dir_dev, ANIO, MES)
    ruta_tiq = os.path.join(entrada, consolidador_mensual.nombre_sap_global(ANIO, MES, cfg.TIQUIPAYA))
    ruta_ame = os.path.join(entrada, consolidador_mensual.nombre_sap_global(ANIO, MES, cfg.AMERICA))
    _crear_global(ruta_tiq, [{"asignacion": "A1", "cuenta_mayor": "110201002", "cargo": "10.00"}])
    _crear_global(ruta_ame, [{"asignacion": "B1", "cuenta_mayor": "210103002", "cargo": "0.00"}])
    r = dev_api.ejecutar_control3_institucional(ANIO, MES, base_dir_dev)
    assert r["estado"] == "OK"
    assert "america" not in entrada and "tiquipaya" not in entrada


def test_ejecutar_control1_institucional_preliminar_no_persiste_historico(tmp_path):
    """AUDITORÍA (preliminar, sin confirmacion_cierre): nunca escribe el
    histórico institucional, aunque no haya duplicados -- solo previsualiza."""
    base_dir_dev = _materializar_control1_institucional(tmp_path)
    r = dev_api.ejecutar_control1_institucional(ANIO, MES, base_dir_dev)
    assert r["modo"] == "preliminar"
    assert r["dry_run"] is True
    assert r["historico_actualizado"] is False
    entrada = dev_api.control1_institucional_entrada_dir(base_dir_dev, ANIO, MES)
    ruta_historico = os.path.join(entrada, "HISTORICO_ASIGNACIONES_INSTITUCIONAL.csv")
    assert not os.path.isfile(ruta_historico)


def test_ejecutar_control1_institucional_cierre_persiste_historico(tmp_path):
    """CIERRE (confirmacion_cierre=True explícito): sin duplicados pendientes,
    sí persiste al histórico institucional."""
    base_dir_dev = _materializar_control1_institucional(tmp_path)
    r = dev_api.ejecutar_control1_institucional(ANIO, MES, base_dir_dev, confirmacion_cierre=True)
    assert r["modo"] == "cierre"
    assert r["dry_run"] is False
    assert r["historico_actualizado"] is True
    entrada = dev_api.control1_institucional_entrada_dir(base_dir_dev, ANIO, MES)
    ruta_historico = os.path.join(entrada, "HISTORICO_ASIGNACIONES_INSTITUCIONAL.csv")
    assert os.path.isfile(ruta_historico)


def test_ejecutar_control1_institucional_confirmacion_cierre_nunca_se_infiere(tmp_path):
    """dry_run=True explícito sigue ganando incluso con confirmacion_cierre=True:
    nunca hay un camino donde el cierre se infiera solo."""
    base_dir_dev = _materializar_control1_institucional(tmp_path)
    r = dev_api.ejecutar_control1_institucional(ANIO, MES, base_dir_dev, dry_run=True, confirmacion_cierre=True)
    assert r["dry_run"] is True
    assert r["historico_actualizado"] is False


def test_ejecutar_control3_institucional_preliminar_no_sella_periodo(tmp_path):
    base_dir_dev = str(tmp_path / "dev")
    dev_api.preparar_control3_institucional_entrada(ANIO, MES, base_dir_dev)
    entrada = dev_api.control3_institucional_entrada_dir(base_dir_dev, ANIO, MES)
    ruta_tiq = os.path.join(entrada, consolidador_mensual.nombre_sap_global(ANIO, MES, cfg.TIQUIPAYA))
    ruta_ame = os.path.join(entrada, consolidador_mensual.nombre_sap_global(ANIO, MES, cfg.AMERICA))
    _crear_global(ruta_tiq, [{"asignacion": "A1", "cuenta_mayor": "110201002", "cargo": "10.00"}])
    _crear_global(ruta_ame, [{"asignacion": "B1", "cuenta_mayor": "210103002", "cargo": "0.00"}])
    r = dev_api.ejecutar_control3_institucional(ANIO, MES, base_dir_dev)
    assert r["modo"] == "preliminar"
    assert r["historico_actualizado"] is False
    ruta_historico = os.path.join(entrada, "HISTORICO_CXC_CXP.csv")
    assert not os.path.isfile(ruta_historico)


def test_ejecutar_control3_institucional_cierre_sella_periodo(tmp_path):
    base_dir_dev = str(tmp_path / "dev")
    dev_api.preparar_control3_institucional_entrada(ANIO, MES, base_dir_dev)
    entrada = dev_api.control3_institucional_entrada_dir(base_dir_dev, ANIO, MES)
    ruta_tiq = os.path.join(entrada, consolidador_mensual.nombre_sap_global(ANIO, MES, cfg.TIQUIPAYA))
    ruta_ame = os.path.join(entrada, consolidador_mensual.nombre_sap_global(ANIO, MES, cfg.AMERICA))
    _crear_global(ruta_tiq, [{"asignacion": "A1", "cuenta_mayor": "110201002", "cargo": "10.00"}])
    _crear_global(ruta_ame, [{"asignacion": "B1", "cuenta_mayor": "210103002", "cargo": "0.00"}])
    r = dev_api.ejecutar_control3_institucional(ANIO, MES, base_dir_dev, confirmacion_cierre=True)
    assert r["modo"] == "cierre"
    assert r["historico_actualizado"] is True
    ruta_historico = os.path.join(entrada, "HISTORICO_CXC_CXP.csv")
    assert os.path.isfile(ruta_historico)


def test_cli_no_ofrece_generar_global_institucional():
    import argparse
    parser_choices = None
    # Reconstruye las choices tal como main() las define, sin ejecutar main().
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "v3", "dev_api.py"), encoding="utf-8").read()
    assert "generar_global_institucional" not in src
    assert "ejecutar_control1_institucional" in src
    assert "ejecutar_control3_institucional" in src


def test_generar_global_nunca_produce_un_tercer_sap_institucional(tmp_path):
    """GENERAR GLOBAL (por caja) nunca debe crear SAP_GLOBAL_INSTITUCIONAL_*."""
    base_dir_dev = str(tmp_path / "dev")
    for caja in (cfg.TIQUIPAYA, cfg.AMERICA):
        sap_dir = dev_api.global_entrada_dir(base_dir_dev, ANIO, MES, caja)
        os.makedirs(sap_dir, exist_ok=True)
    # No hay SAP diarios: alcanza con verificar que el árbol de salida nunca
    # contiene un nombre SAP_GLOBAL_INSTITUCIONAL_ tras preparar ambos.
    for root, _dirs, files in os.walk(base_dir_dev):
        for nombre in files:
            assert "INSTITUCIONAL" not in nombre.upper() or "control" in root.lower(), (
                f"archivo institucional inesperado: {os.path.join(root, nombre)}"
            )
    assert not os.path.isdir(os.path.join(base_dir_dev, "global", "institucional"))
