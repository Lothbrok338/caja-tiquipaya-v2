"""tests_v3/test_revision.py — pruebas propias del módulo 05 ·
REVISION/CORRECCION de V3 (v3/revision.py). Este módulo es un ADAPTADOR
sobre correcciones_tiquipaya.py/pipeline_tiquipaya.py/aplicar_correccion.py
de V2 (sin modificar): estas pruebas verifican que el adaptador invoca ese
código real correctamente — NO reimplementan ni reinterpretan ninguna
regla de qué es corregible.

Uso: python -m pytest tests_v3/test_revision.py -q
"""

import hashlib
import json
import os
import sys
from datetime import datetime, timezone

import openpyxl
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tests"))

import xlsx_fixtures as fx
import correcciones_tiquipaya as correcciones
from v3.revision import ejecutar_revision, revisar_y_corregir_cierre
from v3.clasificacion import LISTO_PARA_PUBLICAR, ERROR_REVISAR


def _sha256(ruta):
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        for bloque in iter(lambda: f.read(1 << 16), b""):
            h.update(bloque)
    return h.hexdigest()


def _correccion(sha256_origen, categoria, tipo, identificadores, campo_corregido, valor_autorizado, valor_original=None):
    base = {
        "fecha_cierre": "2026-09-01", "sha256_origen": sha256_origen,
        "categoria": categoria, "tipo": tipo, "identificadores": identificadores,
        "campo_corregido": campo_corregido, "valor_original": valor_original,
        "valor_autorizado": valor_autorizado, "motivo": "test modulo 05",
        "usuario_auditor": "auditor.test", "fecha_hora": datetime.now(timezone.utc).isoformat(),
    }
    base["version_correccion"] = correcciones.calcular_version_correccion(base)
    return base


def _item_ci_bloqueante(tmp_path):
    sfc101 = {
        "total_movimiento": "100.00", "cobros_atc": "0.00", "dolares": "0.00", "depositos": [],
        "ci": [{"n": 1, "factura": "F-1", "total": "100.00", "cuenta": None,
                "asignacion": "REF1", "banco": "BNB"}],
    }
    sfc102 = {"total_movimiento": "0.00", "cobros_atc": "0.00", "dolares": "0.00", "depositos": []}
    ruta_cierre = tmp_path / "CIERRE 01-09-2026.xlsm"
    fx.crear_cierre(str(ruta_cierre), sfc101, sfc102)
    ruta_maestro = tmp_path / "MAESTRO.xlsm"
    fx.crear_maestro_unico(str(ruta_maestro), macros_filas=[], atc_filas=[])
    ruta_plantilla = tmp_path / "Plantilla.xlsx"
    fx.crear_plantilla_sap(str(ruta_plantilla))
    hash_origen = _sha256(str(ruta_cierre))
    return {
        "fecha": "2026-09-01", "estado_ingesta": "ENCONTRADO", "estado_materializacion": "MATERIALIZADO",
        "estado_motor": "PROCESADO", "resultado": "BLOQUEADO_EXCEPCION",
        "ruta_cierre_local": str(ruta_cierre), "ruta_maestro_local": str(ruta_maestro),
        "ruta_template_sap_local": str(ruta_plantilla), "ruta_markers_local": None,
        "estado_final": ERROR_REVISAR,
    }, hash_origen


# 1) CI permite solo cuenta_contable/asignacion
def test_ci_permite_solo_cuenta_contable_y_asignacion(tmp_path):
    item, hash_origen = _item_ci_bloqueante(tmp_path)
    correccion = _correccion(hash_origen, "COMUNICACION_INTERNA", "CI_CUENTA_FALTANTE",
                              {"sfc": "SFC101", "factura": "F-1"}, "cuenta_contable", "210201005")
    item["correccion"] = correccion
    r = revisar_y_corregir_cierre(item, str(tmp_path / "dev"))
    assert r["correccion_aplicada"] is True
    assert r["correccion_valida"] is True
    assert r["campos_corregidos"] == ["cuenta_contable"]
    assert r["resultado_reproceso"] == LISTO_PARA_PUBLICAR


# 2) Voucher permite solo codigo_informado valido (entre candidatos)
def test_voucher_permite_solo_codigo_informado_entre_candidatos(tmp_path):
    sfc101 = {
        "total_movimiento": "500.00", "cobros_atc": "0.00", "dolares": "0.00",
        "depositos": [{"importe": "500.00", "asignacion": "VCH1O92", "banco": "BNB", "fecha": "2026-09-01"}],
    }
    sfc102 = {"total_movimiento": "0.00", "cobros_atc": "0.00", "dolares": "0.00", "depositos": []}
    ruta_cierre = tmp_path / "CIERRE 01-09-2026.xlsm"
    fx.crear_cierre(str(ruta_cierre), sfc101, sfc102)
    ruta_maestro = tmp_path / "MAESTRO.xlsm"
    # "VCH1092" (candidato POSIBLE_TYPO: O<->0 en 2 posiciones no cubre 0<->O
    # unicamente si difiere en 1-2 chars con distancia<=2) contra "VCH1O92"
    fx.crear_maestro_unico(str(ruta_maestro), macros_filas=[("2026-09-01", "VCH1P92", "500.00")], atc_filas=[])
    ruta_plantilla = tmp_path / "Plantilla.xlsx"
    fx.crear_plantilla_sap(str(ruta_plantilla))
    hash_origen = _sha256(str(ruta_cierre))

    item = {
        "fecha": "2026-09-01", "estado_ingesta": "ENCONTRADO", "estado_materializacion": "MATERIALIZADO",
        "estado_motor": "PROCESADO", "resultado": "BLOQUEADO_EXCEPCION",
        "ruta_cierre_local": str(ruta_cierre), "ruta_maestro_local": str(ruta_maestro),
        "ruta_template_sap_local": str(ruta_plantilla), "ruta_markers_local": None,
    }
    # Candidato VALIDO (esta en macros): debe aceptarse.
    correccion_valida = _correccion(hash_origen, "VOUCHER", "POSIBLE_TYPO",
                                     {"sfc": "SFC101", "codigo_informado": "VCH1O92"},
                                     "codigo_informado", "VCH1P92")
    item["correccion"] = correccion_valida
    r = revisar_y_corregir_cierre(item, str(tmp_path / "dev1"))
    assert r["correccion_aplicada"] is True
    assert r["resultado_reproceso"] == LISTO_PARA_PUBLICAR

    # Candidato INVENTADO (no propuesto por el motor): debe rechazarse.
    correccion_invalida = _correccion(hash_origen, "VOUCHER", "POSIBLE_TYPO",
                                       {"sfc": "SFC101", "codigo_informado": "VCH1O92"},
                                       "codigo_informado", "CODIGO_INVENTADO_9999")
    item2 = dict(item, correccion=correccion_invalida)
    r2 = revisar_y_corregir_cierre(item2, str(tmp_path / "dev2"))
    assert r2["correccion_aplicada"] is False
    assert "CORRECCION_CANDIDATO_INVALIDO" in r2["mensaje"]


# 3) ATC permite solo cuenta/asignacion (modo preconciliado)
def test_atc_permite_solo_cuenta_y_asignacion(tmp_path):
    sfc101 = {"total_movimiento": "1000.00", "cobros_atc": "1000.00", "dolares": "0.00", "depositos": []}
    sfc102 = {"total_movimiento": "0.00", "cobros_atc": "0.00", "dolares": "0.00", "depositos": []}
    ruta_cierre = tmp_path / "CIERRE 01-09-2026.xlsm"
    fx.crear_cierre(str(ruta_cierre), sfc101, sfc102)
    ruta_maestro = tmp_path / "MAESTRO.xlsm"
    atc_filas = [
        ("2026-09-01", "BANCO (NETO)", "999999999", "NETO ATC", "950.00", "3P00000001"),
        ("2026-09-01", "COMISION ATC", "110201008", "COMISION ATC", "50.00", "TIQUIPAYA SEP"),
    ]
    fx.crear_maestro_unico(str(ruta_maestro), macros_filas=[], atc_filas=atc_filas)
    ruta_plantilla = tmp_path / "Plantilla.xlsx"
    fx.crear_plantilla_sap(str(ruta_plantilla))
    hash_origen = _sha256(str(ruta_cierre))

    item = {
        "fecha": "2026-09-01", "estado_ingesta": "ENCONTRADO", "estado_materializacion": "MATERIALIZADO",
        "estado_motor": "PROCESADO", "resultado": "BLOQUEADO_EXCEPCION",
        "ruta_cierre_local": str(ruta_cierre), "ruta_maestro_local": str(ruta_maestro),
        "ruta_template_sap_local": str(ruta_plantilla), "ruta_markers_local": None,
        "correccion": _correccion(hash_origen, "ATC", "ATC_NETO_CUENTA_INVALIDA", {},
                                   "neto_cuenta_contable", "110103012", valor_original="999999999"),
    }
    r = revisar_y_corregir_cierre(item, str(tmp_path / "dev"))
    assert r["correccion_aplicada"] is True
    assert r["resultado_reproceso"] == LISTO_PARA_PUBLICAR


# 4) intento de cambiar importe -> rechazado
def test_importe_nunca_corregible(tmp_path):
    item, hash_origen = _item_ci_bloqueante(tmp_path)
    correccion = _correccion(hash_origen, "COMUNICACION_INTERNA", "CI_CUENTA_FALTANTE",
                              {"sfc": "SFC101", "factura": "F-1"}, "importe", "999999.00")
    item["correccion"] = correccion
    r = revisar_y_corregir_cierre(item, str(tmp_path / "dev"))
    assert r["correccion_aplicada"] is False
    assert r["correccion_valida"] is False
    assert "CORRECCION_CAMPO_NO_CORREGIBLE" in r["mensaje"]


# 5) campo no autorizado -> rechazado
def test_campo_no_autorizado_rechazado(tmp_path):
    item, hash_origen = _item_ci_bloqueante(tmp_path)
    correccion = _correccion(hash_origen, "COMUNICACION_INTERNA", "CI_CUENTA_FALTANTE",
                              {"sfc": "SFC101", "factura": "F-1"}, "glosa", "TEXTO NUEVO")
    item["correccion"] = correccion
    r = revisar_y_corregir_cierre(item, str(tmp_path / "dev"))
    assert r["correccion_aplicada"] is False
    assert "CORRECCION_CAMPO_NO_CORREGIBLE" in r["mensaje"]


# 6) original permanece identico
def test_original_permanece_identico(tmp_path):
    item, hash_origen = _item_ci_bloqueante(tmp_path)
    hash_antes = _sha256(item["ruta_cierre_local"])
    correccion = _correccion(hash_origen, "COMUNICACION_INTERNA", "CI_CUENTA_FALTANTE",
                              {"sfc": "SFC101", "factura": "F-1"}, "cuenta_contable", "210201005")
    item["correccion"] = correccion
    revisar_y_corregir_cierre(item, str(tmp_path / "dev"))
    assert _sha256(item["ruta_cierre_local"]) == hash_antes


# 7) correccion queda registrada aparte (trazabilidad)
def test_correccion_queda_registrada_aparte(tmp_path):
    item, hash_origen = _item_ci_bloqueante(tmp_path)
    correccion = _correccion(hash_origen, "COMUNICACION_INTERNA", "CI_CUENTA_FALTANTE",
                              {"sfc": "SFC101", "factura": "F-1"}, "cuenta_contable", "210201005")
    item["correccion"] = correccion
    controles_dir = tmp_path / "dev" / "controles"
    controles_dir.mkdir(parents=True)
    r = revisar_y_corregir_cierre(item, str(tmp_path / "dev"), controles_dir_dev=str(controles_dir))
    assert r["ruta_correccion_guardada"] is not None
    assert os.path.isfile(r["ruta_correccion_guardada"])
    ruta_historico = controles_dir / "CORRECCIONES_AUDITOR" / "HISTORICO_CORRECCIONES.csv"
    assert ruta_historico.is_file()
    # la correccion registrada es un archivo APARTE del resultado/SAP del reproceso
    assert os.path.abspath(r["ruta_correccion_guardada"]) != os.path.abspath(r["ruta_resultado"])


# 8) reproceso usa original + correccion (nunca sobrescribe el resultado original)
def test_reproceso_usa_original_mas_correccion_sin_sobrescribir(tmp_path):
    item, hash_origen = _item_ci_bloqueante(tmp_path)
    correccion = _correccion(hash_origen, "COMUNICACION_INTERNA", "CI_CUENTA_FALTANTE",
                              {"sfc": "SFC101", "factura": "F-1"}, "cuenta_contable", "210201005")
    item["correccion"] = correccion
    r = revisar_y_corregir_cierre(item, str(tmp_path / "dev"))
    assert "REPROCESOS" in r["ruta_resultado"].split(os.sep)
    assert "REPROCESOS" in r["ruta_sap"].split(os.sep)
    assert os.path.isfile(r["ruta_resultado"])
    assert os.path.isfile(r["ruta_sap"])


# 9) correccion valida puede producir resultado listo
def test_correccion_valida_produce_listo(tmp_path):
    item, hash_origen = _item_ci_bloqueante(tmp_path)
    correccion = _correccion(hash_origen, "COMUNICACION_INTERNA", "CI_CUENTA_FALTANTE",
                              {"sfc": "SFC101", "factura": "F-1"}, "cuenta_contable", "210201005")
    item["correccion"] = correccion
    r = revisar_y_corregir_cierre(item, str(tmp_path / "dev"))
    assert r["resultado_reproceso"] == LISTO_PARA_PUBLICAR


# 10) correccion invalida permanece bloqueada
def test_correccion_invalida_permanece_bloqueada(tmp_path):
    item, hash_origen = _item_ci_bloqueante(tmp_path)
    # sha256_origen incorrecto -> CORRECCION_HUERFANA
    correccion = _correccion("f" * 64, "COMUNICACION_INTERNA", "CI_CUENTA_FALTANTE",
                              {"sfc": "SFC101", "factura": "F-1"}, "cuenta_contable", "210201005")
    item["correccion"] = correccion
    r = revisar_y_corregir_cierre(item, str(tmp_path / "dev"))
    assert r["correccion_aplicada"] is False
    assert r["resultado_reproceso"] is None
    assert "CORRECCION_HUERFANA" in r["mensaje"]


def test_sin_correccion_aportada_permanece_pendiente(tmp_path):
    item, _hash = _item_ci_bloqueante(tmp_path)
    item["correccion"] = None
    r = revisar_y_corregir_cierre(item, str(tmp_path / "dev"))
    assert r["correccion_aplicada"] is False
    assert r["correccion_valida"] is None
    assert r["resultado_reproceso"] is None


# CONTRACT-014: un cierre con marcador PROCESADO_<hash>.json ya
# materializado (Modulo 02) nunca admite una correccion nueva.
def test_cierre_ya_publicado_no_admite_correccion(tmp_path):
    item, hash_origen = _item_ci_bloqueante(tmp_path)
    markers_dir = tmp_path / "markers"
    markers_dir.mkdir()
    contenido_marcador = {"HashOrigen": hash_origen, "Estado": "PROCESADO", "ArchivoOrigen": "CIERRE 01-09-2026.xlsm"}
    (markers_dir / f"PROCESADO_{hash_origen}.json").write_text(json.dumps(contenido_marcador))
    item["ruta_markers_local"] = str(markers_dir)

    correccion = _correccion(hash_origen, "COMUNICACION_INTERNA", "CI_CUENTA_FALTANTE",
                              {"sfc": "SFC101", "factura": "F-1"}, "cuenta_contable", "210201005")
    item["correccion"] = correccion
    r = revisar_y_corregir_cierre(item, str(tmp_path / "dev"))
    assert r["correccion_aplicada"] is False
    assert r["correccion_valida"] is False
    assert "CIERRE_YA_PUBLICADO_NO_CORREGIBLE" in r["mensaje"]


# 11) no publica nada
def test_no_publica_ni_crea_marcadores(tmp_path):
    item, hash_origen = _item_ci_bloqueante(tmp_path)
    correccion = _correccion(hash_origen, "COMUNICACION_INTERNA", "CI_CUENTA_FALTANTE",
                              {"sfc": "SFC101", "factura": "F-1"}, "cuenta_contable", "210201005")
    item["correccion"] = correccion
    revisar_y_corregir_cierre(item, str(tmp_path / "dev"))
    import glob
    assert glob.glob(str(tmp_path / "**" / "PROCESADO_*.json"), recursive=True) == []


# 12) no mueve archivos (el original sigue en su ruta original, nada se movio)
def test_no_mueve_archivos(tmp_path):
    item, hash_origen = _item_ci_bloqueante(tmp_path)
    ruta_original = item["ruta_cierre_local"]
    correccion = _correccion(hash_origen, "COMUNICACION_INTERNA", "CI_CUENTA_FALTANTE",
                              {"sfc": "SFC101", "factura": "F-1"}, "cuenta_contable", "210201005")
    item["correccion"] = correccion
    revisar_y_corregir_cierre(item, str(tmp_path / "dev"))
    assert os.path.isfile(ruta_original)  # sigue exactamente donde estaba


# 13) error en una correccion no rompe el lote
def test_error_en_una_correccion_no_rompe_el_lote(tmp_path):
    (tmp_path / "ok").mkdir()
    item_ok, hash_ok = _item_ci_bloqueante(tmp_path / "ok")
    item_ok["correccion"] = _correccion(hash_ok, "COMUNICACION_INTERNA", "CI_CUENTA_FALTANTE",
                                         {"sfc": "SFC101", "factura": "F-1"}, "cuenta_contable", "210201005")

    item_roto = {
        "fecha": "2026-09-02",
        "ruta_cierre_local": str(tmp_path / "no_existe.xlsm"),
        "ruta_maestro_local": item_ok["ruta_maestro_local"],
        "ruta_template_sap_local": item_ok["ruta_template_sap_local"],
        "ruta_markers_local": None,
        "correccion": _correccion("0" * 64, "COMUNICACION_INTERNA", "CI_CUENTA_FALTANTE",
                                   {"sfc": "SFC101", "factura": "F-1"}, "cuenta_contable", "210201005"),
    }
    resultados = ejecutar_revision([item_ok, item_roto], str(tmp_path / "dev"))
    por_fecha = {r["fecha"]: r for r in resultados}
    assert por_fecha["2026-09-01"]["correccion_aplicada"] is True
    assert por_fecha["2026-09-02"]["correccion_aplicada"] is False


def test_todas_las_filas_tienen_al_menos_las_claves_pedidas(tmp_path):
    # FASE 8: revisar_y_corregir_cierre() ahora preserva TODO lo que el
    # item ya traía de los Módulos 01-04 (carry-forward: ruta_cierre_local,
    # ruta_maestro_local, etc.) — necesario para que el Módulo 06
    # (PUBLICACION) tenga ruta_cierre_local disponible tras un reproceso
    # (ver FASE 8, hallazgo de incompatibilidad corregido en v3/revision.py).
    # Por eso la aserción es "al menos estas claves", no un conjunto exacto.
    item, hash_origen = _item_ci_bloqueante(tmp_path)
    correccion = _correccion(hash_origen, "COMUNICACION_INTERNA", "CI_CUENTA_FALTANTE",
                              {"sfc": "SFC101", "factura": "F-1"}, "cuenta_contable", "210201005")
    item["correccion"] = correccion
    r = revisar_y_corregir_cierre(item, str(tmp_path / "dev"))
    esperado_minimo = {
        "fecha", "correccion_aplicada", "correccion_valida", "campos_corregidos",
        "resultado_reproceso", "diferencia", "bloqueadores", "ruta_resultado", "ruta_sap",
        "cargo", "haber", "version_correccion", "ruta_correccion_guardada", "usuario_auditor",
        "mensaje", "mensajes",
    }
    assert esperado_minimo.issubset(set(r.keys()))
    assert "correccion" not in r  # ya se consumio, no tiene sentido reenviarla
    # y las rutas locales del Modulo 02 sobreviven intactas para el Modulo 06
    assert r["ruta_cierre_local"] == item["ruta_cierre_local"]
