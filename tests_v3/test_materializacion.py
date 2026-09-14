"""tests_v3/test_materializacion.py — pruebas propias del módulo 02 ·
MATERIALIZACION/PREPARACION de V3 (v3/materializacion.py). Independiente de
tests/ (V2, sin cambios) y de parity_v3/ (contratos V2 vs V3).

Uso: python -m pytest tests_v3/test_materializacion.py -q
"""

import hashlib
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tests"))

import xlsx_fixtures as fx
from v3.materializacion import (
    ejecutar_materializacion, preparar_directorio_dev, materializar_cierre,
    preparar_maestro, preparar_plantilla_sap, DirectorioForaDeBaseError,
    MATERIALIZADO, ERROR_MATERIALIZACION,
)
from v3.ingesta import ENCONTRADO, SIN_ARCHIVO, AMBIGUO, ERROR_INGESTA


def _sha256(ruta):
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        for bloque in iter(lambda: f.read(1 << 16), b""):
            h.update(bloque)
    return h.hexdigest()


@pytest.fixture()
def entorno(tmp_path):
    origen_cierres = tmp_path / "origen_cierres"
    origen_cierres.mkdir()
    ruta_cierre_origen = origen_cierres / "CIERRE 01-09-2026.xlsm"
    fx.crear_cierre(
        str(ruta_cierre_origen),
        {"total_movimiento": "0.00", "cobros_atc": "0.00", "dolares": "0.00", "depositos": []},
        {"total_movimiento": "0.00", "cobros_atc": "0.00", "dolares": "0.00", "depositos": []},
    )

    ruta_maestro_origen = tmp_path / "MAESTRO_SEPTIEMBRE.xlsm"
    fx.crear_maestro_unico(str(ruta_maestro_origen), macros_filas=[], atc_filas=[])

    ruta_plantilla_origen = tmp_path / "Plantilla_SAP_maestra.xlsx"
    fx.crear_plantilla_sap(str(ruta_plantilla_origen))

    base_dir_dev = tmp_path / "dev_workdir"

    return {
        "tmp": tmp_path,
        "origen_cierres_dir": str(origen_cierres),
        "ruta_cierre_origen": str(ruta_cierre_origen),
        "ruta_maestro_origen": str(ruta_maestro_origen),
        "ruta_plantilla_origen": str(ruta_plantilla_origen),
        "base_dir_dev": str(base_dir_dev),
    }


def _params(entorno, **overrides):
    p = {
        "base_dir_dev": entorno["base_dir_dev"],
        "origen_cierres_dir": entorno["origen_cierres_dir"],
        "ruta_maestro_origen": entorno["ruta_maestro_origen"],
        "ruta_plantilla_origen": entorno["ruta_plantilla_origen"],
        "markers_origen_dir": None,
        "mes_rango": 9,
    }
    p.update(overrides)
    return p


# 1) ENCONTRADO -> materializado correctamente
def test_encontrado_se_materializa_correctamente(entorno):
    item = {"fecha": "2026-09-01", "archivo_esperado": "CIERRE 01-09-2026.xlsm", "estado_ingesta": ENCONTRADO}
    resultados = ejecutar_materializacion([item], _params(entorno))
    r = resultados[0]
    assert r["estado_materializacion"] == MATERIALIZADO
    assert r["ruta_cierre_local"] is not None
    assert os.path.isfile(r["ruta_cierre_local"])
    assert _sha256(r["ruta_cierre_local"]) == _sha256(entorno["ruta_cierre_origen"])  # copia fiel


# 2) SIN_ARCHIVO -> no intenta materializar
def test_sin_archivo_no_intenta_materializar(entorno):
    item = {"fecha": "2026-09-02", "archivo_esperado": "CIERRE 02-09-2026.xlsm", "estado_ingesta": SIN_ARCHIVO}
    resultados = ejecutar_materializacion([item], _params(entorno))
    r = resultados[0]
    assert r["estado_materializacion"] == SIN_ARCHIVO
    assert r["ruta_cierre_local"] is None
    assert not os.path.isfile(os.path.join(entorno["base_dir_dev"], "cierres", "CIERRE 02-09-2026.xlsm"))


# 3) AMBIGUO -> no intenta materializar
def test_ambiguo_no_intenta_materializar(entorno):
    item = {"fecha": "2026-09-03", "archivo_esperado": "CIERRE 03-09-2026.xlsm", "estado_ingesta": AMBIGUO}
    resultados = ejecutar_materializacion([item], _params(entorno))
    r = resultados[0]
    assert r["estado_materializacion"] == AMBIGUO
    assert r["ruta_cierre_local"] is None


def test_error_ingesta_pasa_tal_cual_sin_intentar_materializar(entorno):
    item = {"fecha": "2026-09-04", "archivo_esperado": "CIERRE 04-09-2026.xlsm", "estado_ingesta": ERROR_INGESTA}
    resultados = ejecutar_materializacion([item], _params(entorno))
    assert resultados[0]["estado_materializacion"] == ERROR_INGESTA


# 4) original no modificado
def test_original_no_modificado(entorno):
    hash_antes = _sha256(entorno["ruta_cierre_origen"])
    hash_maestro_antes = _sha256(entorno["ruta_maestro_origen"])
    hash_plantilla_antes = _sha256(entorno["ruta_plantilla_origen"])

    item = {"fecha": "2026-09-01", "archivo_esperado": "CIERRE 01-09-2026.xlsm", "estado_ingesta": ENCONTRADO}
    ejecutar_materializacion([item], _params(entorno))

    assert _sha256(entorno["ruta_cierre_origen"]) == hash_antes
    assert _sha256(entorno["ruta_maestro_origen"]) == hash_maestro_antes
    assert _sha256(entorno["ruta_plantilla_origen"]) == hash_plantilla_antes


# 5) rutas DEV correctas
def test_rutas_dev_correctas(entorno):
    item = {"fecha": "2026-09-01", "archivo_esperado": "CIERRE 01-09-2026.xlsm", "estado_ingesta": ENCONTRADO}
    r = ejecutar_materializacion([item], _params(entorno))[0]
    base = os.path.abspath(entorno["base_dir_dev"])
    for clave in ("ruta_cierre_local", "ruta_maestro_local", "ruta_template_sap_local", "ruta_markers_local"):
        assert r[clave] is not None
        assert os.path.commonpath([os.path.abspath(r[clave]), base]) == base


# 6) maestro preparado (reutiliza run_batch.validar_maestro)
def test_maestro_preparado_y_validado(entorno):
    dirs = preparar_directorio_dev(entorno["base_dir_dev"])
    resultado = preparar_maestro(entorno["ruta_maestro_origen"], dirs["maestro"], mes_rango=9)
    assert resultado["estado_maestro"] == MATERIALIZADO
    assert os.path.isfile(resultado["ruta_maestro_local"])


def test_maestro_mes_no_coincide_es_error(entorno):
    # run_batch.validar_maestro() solo detecta el mes por el NOMBRE del
    # archivo; "MAESTRO_SEPTIEMBRE.xlsm" pedido para mes_rango=10 (octubre)
    # debe fallar exactamente como en V2 (MAESTRO_MES_NO_COINCIDE).
    dirs = preparar_directorio_dev(entorno["base_dir_dev"])
    resultado = preparar_maestro(entorno["ruta_maestro_origen"], dirs["maestro"], mes_rango=10)
    assert resultado["estado_maestro"] == ERROR_MATERIALIZACION
    assert "MAESTRO_MES_NO_COINCIDE" in resultado["mensaje"]


# 7) template SAP preparado
def test_plantilla_sap_preparada(entorno):
    dirs = preparar_directorio_dev(entorno["base_dir_dev"])
    resultado = preparar_plantilla_sap(entorno["ruta_plantilla_origen"], dirs["plantilla"])
    assert resultado["estado_plantilla"] == MATERIALIZADO
    assert os.path.isfile(resultado["ruta_template_sap_local"])


def test_plantilla_sap_inexistente_es_error(entorno):
    dirs = preparar_directorio_dev(entorno["base_dir_dev"])
    resultado = preparar_plantilla_sap(str(entorno["tmp"] / "no_existe.xlsx"), dirs["plantilla"])
    assert resultado["estado_plantilla"] == ERROR_MATERIALIZACION


# 8) error de archivo -> ERROR_MATERIALIZACION
def test_encontrado_sin_archivo_real_da_error_materializacion(entorno):
    # ingesta dijo ENCONTRADO pero el archivo no esta realmente en origen_dir
    # (caso "fantasma": inconsistencia entre lo reportado y la realidad).
    item = {"fecha": "2026-09-09", "archivo_esperado": "CIERRE 09-09-2026.xlsm", "estado_ingesta": ENCONTRADO}
    resultados = ejecutar_materializacion([item], _params(entorno))
    r = resultados[0]
    assert r["estado_materializacion"] == ERROR_MATERIALIZACION
    assert r["ruta_cierre_local"] is None


def test_error_de_un_cierre_no_detiene_el_resto_del_lote(entorno):
    items = [
        {"fecha": "2026-09-01", "archivo_esperado": "CIERRE 01-09-2026.xlsm", "estado_ingesta": ENCONTRADO},
        {"fecha": "2026-09-09", "archivo_esperado": "CIERRE 09-09-2026.xlsm", "estado_ingesta": ENCONTRADO},
    ]
    resultados = ejecutar_materializacion(items, _params(entorno))
    por_fecha = {r["fecha"]: r["estado_materializacion"] for r in resultados}
    assert por_fecha["2026-09-01"] == MATERIALIZADO
    assert por_fecha["2026-09-09"] == ERROR_MATERIALIZACION


# 9) limpieza temporal no elimina nada fuera del directorio DEV
def test_limpieza_no_toca_nada_fuera_de_base_dir(entorno):
    centinela = entorno["tmp"] / "NO_TOCAR_centinela.txt"
    centinela.write_text("no me borres")

    preparar_directorio_dev(entorno["base_dir_dev"])
    # segunda llamada: ejercita la rama de "ya existe -> limpiar y recrear"
    preparar_directorio_dev(entorno["base_dir_dev"])

    assert centinela.is_file()
    assert centinela.read_text() == "no me borres"
    # tambien el propio origen de cierres/maestro/plantilla debe sobrevivir
    assert os.path.isfile(entorno["ruta_cierre_origen"])
    assert os.path.isfile(entorno["ruta_maestro_origen"])
    assert os.path.isfile(entorno["ruta_plantilla_origen"])


def test_preparar_directorio_dev_rechaza_ruta_fuera_de_base_por_diseno():
    # Defensa explicita: _verificar_contenido_en_base_dir es la unica
    # funcion que decide que se puede limpiar; se prueba directamente que
    # una ruta fuera de base_dir es rechazada, no solo que "no paso nada".
    from v3.materializacion import _verificar_contenido_en_base_dir
    with pytest.raises(DirectorioForaDeBaseError):
        _verificar_contenido_en_base_dir("/tmp/otro/lugar", "/tmp/dev_workdir")


def test_todas_las_filas_tienen_exactamente_las_9_claves_pedidas(entorno):
    item = {"fecha": "2026-09-01", "archivo_esperado": "CIERRE 01-09-2026.xlsm", "estado_ingesta": ENCONTRADO}
    r = ejecutar_materializacion([item], _params(entorno))[0]
    esperado = {
        "fecha", "archivo_esperado", "estado_ingesta", "estado_materializacion",
        "ruta_cierre_local", "ruta_maestro_local", "ruta_template_sap_local",
        "ruta_markers_local", "mensaje",
    }
    assert set(r.keys()) == esperado


def test_markers_existentes_se_copian_y_se_cuentan(entorno):
    import json
    markers_origen = entorno["tmp"] / "markers_origen"
    markers_origen.mkdir()
    contenido = {"HashOrigen": "a" * 64, "Estado": "PROCESADO", "ArchivoOrigen": "CIERRE 01-08-2026.xlsm"}
    (markers_origen / f"PROCESADO_{contenido['HashOrigen']}.json").write_text(json.dumps(contenido))

    item = {"fecha": "2026-09-01", "archivo_esperado": "CIERRE 01-09-2026.xlsm", "estado_ingesta": ENCONTRADO}
    resultados = ejecutar_materializacion([item], _params(entorno, markers_origen_dir=str(markers_origen)))
    ruta_markers_local = resultados[0]["ruta_markers_local"]
    assert os.path.isfile(os.path.join(ruta_markers_local, f"PROCESADO_{contenido['HashOrigen']}.json"))
