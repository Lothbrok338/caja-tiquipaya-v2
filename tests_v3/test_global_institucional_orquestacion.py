"""tests_v3/test_global_institucional_orquestacion.py — GENERAR GLOBAL
institucional (v3.dev_api.generar_global_institucional).

Verifica ÚNICAMENTE la NUEVA orquestación de un solo botón que produce los
TRES SAP GLOBAL del periodo (TIQ, AME, INSTITUCIONAL), reutilizando SIN
cambios `dev_api.generar_global()` (por caja, ya probado en
tests_v3/test_auditoria_mensual.py) y
`v3.global_institucional.fusionar_global_institucional()` (ya probado en
tests_v3/test_global_institucional.py). No repite ninguna regla contable.

Uso: python -m pytest tests_v3/test_global_institucional_orquestacion.py -q
"""

import datetime
import json
import os
import sys
from decimal import Decimal

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tests"))

import openpyxl  # noqa: E402

import config_cajas as cfg  # noqa: E402
from xlsx_fixtures import crear_plantilla_sap  # noqa: E402
from v3 import dev_api  # noqa: E402


def _crear_sap_diario(ruta, caja, cargo="100.00", asignacion=None,
                       fecha_valor=datetime.date(2026, 9, 5)):
    """SAP diario mínimo válido de `caja`: hoja '1', cabecera fija, una
    partida DEBE + una HABER cuadradas (mismo layout que
    tests_v3/test_auditoria_mensual.py::_crear_sap_diario, parametrizado
    por caja en vez de fijo a TIQUIPAYA)."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "1"
    ws["B10"] = "BO01"
    ws["C10"] = "DB"
    ws["H10"] = "BOB"
    ws["L10"] = caja.nombre_sap

    ws["B16"] = "BO01"
    ws["C16"] = "110101001"
    ws["D16"] = "RECAUDACION"
    ws["E16"] = Decimal(cargo)
    ws["F16"] = None
    ws["L16"] = "10010101"
    ws["O16"] = fecha_valor
    ws["R16"] = asignacion

    ws["B17"] = "BO01"
    ws["C17"] = "210101001"
    ws["D17"] = "CONTRAPARTIDA"
    ws["E17"] = None
    ws["F17"] = Decimal(cargo)
    ws["L17"] = "10010101"
    ws["O17"] = fecha_valor
    ws["R17"] = None
    wb.save(ruta)


def _preparar_entrada(base_dir_dev, caja, cargo="100.00"):
    dir_entrada = dev_api.global_entrada_dir(str(base_dir_dev), 2026, 9, caja)
    os.makedirs(dir_entrada, exist_ok=True)
    nombre = f"SAP_{caja.prefijo_archivo}_01-09-2026.xlsx"
    _crear_sap_diario(os.path.join(dir_entrada, nombre), caja, cargo=cargo)
    return dir_entrada


@pytest.fixture
def plantilla(tmp_path):
    ruta = tmp_path / "Plantilla.xlsx"
    crear_plantilla_sap(str(ruta))
    return ruta


def _generar(base_dir_dev, plantilla):
    return dev_api.generar_global_institucional(2026, 9, str(base_dir_dev), str(plantilla))


# ---------------------------------------------------------------------------
# Un solo botón / una petición mensual -- genera TIQ y AME por separado,
# fusiona el INSTITUCIONAL, orden TIQ -> AME, naming de los 3 correcto.
# ---------------------------------------------------------------------------

def test_una_sola_llamada_produce_los_tres_global(tmp_path, plantilla):
    base_dir_dev = tmp_path / "dev"
    _preparar_entrada(base_dir_dev, cfg.TIQUIPAYA, cargo="100.00")
    _preparar_entrada(base_dir_dev, cfg.AMERICA, cargo="50.00")

    r = _generar(base_dir_dev, plantilla)

    assert os.path.isfile(r["ruta_global_tiq"])
    assert os.path.isfile(r["ruta_global_ame"])
    assert os.path.isfile(r["ruta_global_institucional"])
    assert os.path.isfile(r["ruta_mapa_origen_institucional"])

    # naming de los tres, exactamente el contrato pedido.
    assert os.path.basename(r["ruta_global_tiq"]) == "SAP_GLOBAL_TIQ_SEPTIEMBRE_2026.xlsx"
    assert os.path.basename(r["ruta_global_ame"]) == "SAP_GLOBAL_AME_SEPTIEMBRE_2026.xlsx"
    assert os.path.basename(r["ruta_global_institucional"]) == "SAP_GLOBAL_INSTITUCIONAL_SEPTIEMBRE_2026.xlsx"


def test_genera_tiq_y_ame_por_separado_con_su_propio_resultado(tmp_path, plantilla):
    base_dir_dev = tmp_path / "dev"
    _preparar_entrada(base_dir_dev, cfg.TIQUIPAYA)
    _preparar_entrada(base_dir_dev, cfg.AMERICA)

    r = _generar(base_dir_dev, plantilla)

    assert r["resultado_tiq"]["estado"] == "VALIDADO_PENDIENTE_PUBLICACION"
    assert r["resultado_ame"]["estado"] == "VALIDADO_PENDIENTE_PUBLICACION"
    assert r["resultado_tiq"]["cantidad_sap_incluidos"] == 1
    assert r["resultado_ame"]["cantidad_sap_incluidos"] == 1
    # rutas locales aisladas: TIQ nunca en la misma carpeta que AME.
    assert os.path.dirname(r["ruta_global_tiq"]).endswith(os.path.join("global"))
    assert os.path.dirname(r["ruta_global_ame"]).endswith(os.path.join("global", "america"))


def test_institucional_contiene_ambas_partidas_en_orden_tiq_ame(tmp_path, plantilla):
    base_dir_dev = tmp_path / "dev"
    _preparar_entrada(base_dir_dev, cfg.TIQUIPAYA, cargo="100.00")
    _preparar_entrada(base_dir_dev, cfg.AMERICA, cargo="50.00")

    r = _generar(base_dir_dev, plantilla)

    assert r["cantidad_partidas_tiq"] == 2  # DEBE+HABER de 1 SAP diario TIQ
    assert r["cantidad_partidas_ame"] == 2  # DEBE+HABER de 1 SAP diario AME
    assert r["cantidad_partidas_total"] == 4

    with open(r["ruta_mapa_origen_institucional"], "r", encoding="utf-8") as f:
        mapa = json.load(f)
    filas = sorted(mapa.items(), key=lambda kv: int(kv[0]))
    cajas_en_orden = [v["caja"] for _, v in filas]
    assert cajas_en_orden == ["tiquipaya", "tiquipaya", "america", "america"]


# ---------------------------------------------------------------------------
# Fail closed en cascada -- nunca institucional parcial.
# ---------------------------------------------------------------------------

def test_falta_sap_tiq_falla_cerrado_y_no_genera_nada_institucional(tmp_path, plantilla):
    base_dir_dev = tmp_path / "dev"
    _preparar_entrada(base_dir_dev, cfg.AMERICA)  # TIQ nunca se materializa

    with pytest.raises(RuntimeError, match="GLOBAL_ENTRADA_NO_MATERIALIZADA"):
        _generar(base_dir_dev, plantilla)

    assert not os.path.isdir(base_dir_dev / "global" / "institucional")
    # tampoco debe quedar un GLOBAL AME huerfano publicado como si el
    # institucional hubiera tenido éxito.
    ruta_institucional = base_dir_dev / "global" / "institucional" / "SAP_GLOBAL_INSTITUCIONAL_SEPTIEMBRE_2026.xlsx"
    assert not ruta_institucional.exists()


def test_falta_sap_ame_falla_cerrado_y_no_genera_nada_institucional(tmp_path, plantilla):
    base_dir_dev = tmp_path / "dev"
    _preparar_entrada(base_dir_dev, cfg.TIQUIPAYA)  # AME nunca se materializa

    with pytest.raises(RuntimeError, match="GLOBAL_ENTRADA_NO_MATERIALIZADA"):
        _generar(base_dir_dev, plantilla)

    ruta_institucional = base_dir_dev / "global" / "institucional" / "SAP_GLOBAL_INSTITUCIONAL_SEPTIEMBRE_2026.xlsx"
    assert not ruta_institucional.exists()
    # el GLOBAL TIQ sí se llegó a generar (orden TIQ -> AME), pero eso no
    # implica institucional parcial: se queda tal cual, sin fusionar.
    assert os.path.isfile(base_dir_dev / "global" / "SAP_GLOBAL_TIQ_SEPTIEMBRE_2026.xlsx")


# ---------------------------------------------------------------------------
# CLI (mismo patrón Python-es-la-unica-autoridad del resto de acciones).
# ---------------------------------------------------------------------------

def test_cli_generar_global_institucional_produce_json_valido(tmp_path, plantilla):
    base_dir_dev = tmp_path / "dev"
    _preparar_entrada(base_dir_dev, cfg.TIQUIPAYA)
    _preparar_entrada(base_dir_dev, cfg.AMERICA)

    entrada = tmp_path / "in.json"
    salida = tmp_path / "out.json"
    entrada.write_text(json.dumps({
        "anio": 2026, "mes": 9,
        "base_dir_dev": str(base_dir_dev),
        "ruta_plantilla_origen": str(plantilla),
    }), encoding="utf-8")

    dev_api.main(["--accion", "generar_global_institucional", "--input", str(entrada), "--output", str(salida)])
    resultado = json.loads(salida.read_text(encoding="utf-8"))
    assert resultado["resultado"] == "OK"
    assert os.path.basename(resultado["ruta_global_institucional"]) == "SAP_GLOBAL_INSTITUCIONAL_SEPTIEMBRE_2026.xlsx"


def test_cli_generar_global_institucional_falla_cerrado_reporta_error(tmp_path, plantilla):
    base_dir_dev = tmp_path / "dev"
    _preparar_entrada(base_dir_dev, cfg.TIQUIPAYA)  # AME falta

    entrada = tmp_path / "in.json"
    salida = tmp_path / "out.json"
    entrada.write_text(json.dumps({
        "anio": 2026, "mes": 9,
        "base_dir_dev": str(base_dir_dev),
        "ruta_plantilla_origen": str(plantilla),
    }), encoding="utf-8")

    dev_api.main(["--accion", "generar_global_institucional", "--input", str(entrada), "--output", str(salida)])
    resultado = json.loads(salida.read_text(encoding="utf-8"))
    assert resultado["resultado"] == "ERROR"
    assert "GLOBAL_ENTRADA_NO_MATERIALIZADA" in resultado["mensaje"]


# ---------------------------------------------------------------------------
# Compatibilidad: generar_global() por caja sigue intacta (flujo diario).
# ---------------------------------------------------------------------------

def test_generar_global_por_caja_sigue_funcionando_sin_cambios(tmp_path, plantilla):
    base_dir_dev = tmp_path / "dev"
    _preparar_entrada(base_dir_dev, cfg.TIQUIPAYA)

    r = dev_api.generar_global(2026, 9, str(base_dir_dev), str(plantilla))
    assert r["estado"] == "VALIDADO_PENDIENTE_PUBLICACION"
    assert os.path.basename(r["ruta_global_generado"]) == "SAP_GLOBAL_TIQ_SEPTIEMBRE_2026.xlsx"
