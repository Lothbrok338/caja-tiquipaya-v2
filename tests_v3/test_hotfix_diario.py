"""tests_v3/test_hotfix_diario.py — HOTFIX operación diaria (2026-09-19).

A) "PUBLICADO" solo con confirmación real de 06B/Drive (PUBLICADO_OFICIAL).
B) /procesar usa el MACROS oficial vigente descargado de Drive por corrida
   (`procesar_entrada/<lote>/`) y el precheck exige cobertura de las fechas de
   los depósitos del cierre.

Uso: python -m pytest tests_v3/test_hotfix_diario.py -q
"""

import json
import os
import shutil
import sys

import pytest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
sys.path.insert(0, os.path.join(RAIZ, "tests"))

import run_batch  # noqa: E402
import xlsx_fixtures as fx  # noqa: E402
from v3 import dev_api  # noqa: E402
from v3.publicacion import (  # noqa: E402
    publicar_cierre_dev, PUBLICACION_LOCAL_PREPARADA, PUBLICADO, YA_PUBLICADO,
)
from v3.precheck_maestro import (  # noqa: E402
    evaluar_cobertura_maestro, MAESTRO_APTO, BLOQUEADO_MAESTRO_COBERTURA_NO_CONFIRMADA,
    MACROS_NO_CUBRE_FECHA_DEPOSITO,
)
from v3.shadow_guard import PublicacionOficialBloqueadaError  # noqa: E402
from test_publicacion import _cierre_procesado  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _sfc(importe, fecha, asignacion):
    return {"total_movimiento": importe, "cobros_atc": "0.00", "dolares": "0.00",
            "depositos": [{"deposito": "DEPOSITO 1", "importe": importe, "fecha": fecha, "asignacion": asignacion, "banco": "BNB"}]}


_SFC_VACIO = {"total_movimiento": "0.00", "cobros_atc": "0.00", "dolares": "0.00", "depositos": []}


def _cierre_12(carpeta, fecha_dep_101="2026-09-15", fecha_dep_102="2026-09-15"):
    os.makedirs(carpeta, exist_ok=True)
    ruta = os.path.join(carpeta, run_batch.nombre_cierre_esperado("2026-09-12"))
    fx.crear_cierre(ruta, _sfc("11096.00", fecha_dep_101, "3P9E113705"), _sfc("9123.00", fecha_dep_102, "3P9E116189"))
    return ruta


def _maestro(ruta, macros_filas):
    fx.crear_maestro_unico(str(ruta), macros_filas=macros_filas, atc_filas=[])
    return str(ruta)


MACROS_VIEJO = [("2026-09-14", "3P94000001", "5.00")]                         # copia vieja: llega al 14/09
MACROS_NUEVO = MACROS_VIEJO + [("2026-09-15", "3P9E113705", "11096.00"), ("2026-09-15", "3P9E116189", "9123.00"),
                               ("2026-09-17", "3P97000009", "7.00")]           # Drive actual: llega al 17/09 y trae ambos vouchers


def _procesar(tmp_path, ruta_cierre_dir, ruta_maestro, nombre_base="dev"):
    plantilla = tmp_path / "Plantilla.xlsx"
    if not plantilla.exists():
        fx.crear_plantilla_sap(str(plantilla))
    base = str(tmp_path / nombre_base)
    r = dev_api.crear_lote_pendiente("2026-09-12", "2026-09-12", "auditor.dev", base)
    return dev_api.procesar_lote(r["lote_id"], base, ruta_cierre_dir, ruta_maestro, str(plantilla)), base, r["lote_id"]


# ---------------------------------------------------------------------------
# B — precheck de cobertura de depósitos
# ---------------------------------------------------------------------------

def test_B3_deposito_posterior_a_la_cobertura_de_macros_bloquea_con_mensaje_claro(tmp_path):
    ruta_cierre = _cierre_12(str(tmp_path / "c"))
    r = evaluar_cobertura_maestro(_maestro(tmp_path / "m.xlsm", MACROS_VIEJO), "2026-09-12", ruta_cierre)
    assert r["estado"] == BLOQUEADO_MAESTRO_COBERTURA_NO_CONFIRMADA
    assert r["codigo_bloqueo"] == MACROS_NO_CUBRE_FECHA_DEPOSITO
    assert r["fecha_requerida_deposito"] == "2026-09-15" and r["fecha_maxima_macros"] == "2026-09-14"
    assert MACROS_NO_CUBRE_FECHA_DEPOSITO in r["mensaje"] and "2026-09-15" in r["mensaje"] and "2026-09-14" in r["mensaje"]


def test_B3_deposito_dentro_de_la_cobertura_es_apto(tmp_path):
    ruta_cierre = _cierre_12(str(tmp_path / "c"))
    r = evaluar_cobertura_maestro(_maestro(tmp_path / "m.xlsm", MACROS_NUEVO), "2026-09-12", ruta_cierre)
    assert r["estado"] == MAESTRO_APTO and r["codigo_bloqueo"] is None and r["observaciones"] == []


def test_B4_fecha_de_deposito_de_otro_anio_no_exige_cobertura_y_se_reporta_aparte(tmp_path):
    """SFC101 con '2016-09-15' (tipeo): NO obliga a MACROS a cubrir 2016 ni bloquea; queda como observación."""
    ruta_cierre = _cierre_12(str(tmp_path / "c"), fecha_dep_101="2016-09-15", fecha_dep_102="2026-09-13")
    r = evaluar_cobertura_maestro(_maestro(tmp_path / "m.xlsm", MACROS_VIEJO), "2026-09-12", ruta_cierre)
    assert r["estado"] == MAESTRO_APTO                                   # 13/09 <= 14/09 y 2016 se ignora para la cobertura
    assert [o["codigo"] for o in r["observaciones"]] == ["FECHA_DEPOSITO_ANOMALA"]
    assert r["observaciones"][0]["fecha_deposito"] == "2016-09-15" and "2016-09-15" in r["mensaje"]
    # y la anomalía no enmascara un bloqueo real de cobertura
    ruta2 = _cierre_12(str(tmp_path / "c2"), fecha_dep_101="2016-09-15", fecha_dep_102="2026-09-15")
    r2 = evaluar_cobertura_maestro(_maestro(tmp_path / "m2.xlsm", MACROS_VIEJO), "2026-09-12", ruta2)
    assert r2["codigo_bloqueo"] == MACROS_NO_CUBRE_FECHA_DEPOSITO and r2["fecha_requerida_deposito"] == "2026-09-15"


# ---------------------------------------------------------------------------
# B — /procesar con MACROS de Drive (procesar_entrada/<lote>)
# ---------------------------------------------------------------------------

def test_B_preparar_procesar_entrada_limpia_solo_el_directorio_del_lote(tmp_path):
    base = str(tmp_path / "dev")
    a = dev_api.preparar_procesar_entrada("aaaa1111", base)
    b = dev_api.preparar_procesar_entrada("bbbb2222", base)
    open(os.path.join(a["dir_entrada"], "MACROS SEPTIEMBRE.xlsm"), "w").write("viejo")
    open(os.path.join(b["dir_entrada"], "MACROS SEPTIEMBRE.xlsm"), "w").write("otra corrida")
    assert a["dir_cierres"].endswith("procesar_entrada/aaaa1111/cierres") and os.path.isdir(a["dir_cierres"])
    dev_api.preparar_procesar_entrada("aaaa1111", base)                            # nueva materialización del mismo lote
    assert os.listdir(a["dir_entrada"]) == ["cierres"]                              # residuo eliminado
    assert open(os.path.join(b["dir_entrada"], "MACROS SEPTIEMBRE.xlsm")).read() == "otra corrida"   # otro lote intacto
    for malo in ("../x", "a/b", "", None):
        with pytest.raises(ValueError, match="LOTE_ID_INVALIDO"):
            dev_api.preparar_procesar_entrada(malo, base)


def test_B_marcar_lote_error_deja_el_lote_en_error_con_mensaje(tmp_path):
    base = str(tmp_path / "dev")
    l = dev_api.crear_lote_pendiente("2026-09-12", "2026-09-12", "a", base)
    r = dev_api.marcar_lote_error(l["lote_id"], "ERROR_AMBIGUO_MACROS: hay 2 archivos", base)
    assert r["estado_lote"] == "ERROR"
    est = dev_api.obtener_estado(l["lote_id"], base)
    assert est["estado_lote"] == "ERROR" and "ERROR_AMBIGUO_MACROS" in est["mensaje_error"]


def test_D1_D2_maestro_local_viejo_vs_macros_de_drive_nuevo(tmp_path):
    """El MACROS local estático (viejo) deja el cierre bloqueado por cobertura; el de Drive (materializado en
    procesar_entrada) lo procesa y ambos vouchers dan MATCH_EXACTO (0 excepciones de voucher)."""
    ruta_cierre = _cierre_12(str(tmp_path / "cierres_origen"))
    viejo = _maestro(tmp_path / "maestro_origen_viejo.xlsm", MACROS_VIEJO)
    lote_viejo, _b, _l = _procesar(tmp_path, os.path.dirname(ruta_cierre), viejo, "dev_viejo")
    c = lote_viejo["cierres"][0]
    assert c["estado_final"] == BLOQUEADO_MAESTRO_COBERTURA_NO_CONFIRMADA and c["codigo_bloqueo_precheck"] == MACROS_NO_CUBRE_FECHA_DEPOSITO

    base = str(tmp_path / "dev")
    ent = dev_api.preparar_procesar_entrada("lote0001", base)                       # lo que materializa n8n desde Drive
    shutil.copyfile(_maestro(tmp_path / "drive_macros.xlsm", MACROS_NUEVO), os.path.join(ent["dir_entrada"], "MACROS SEPTIEMBRE.xlsm"))
    shutil.copyfile(ruta_cierre, os.path.join(ent["dir_cierres"], os.path.basename(ruta_cierre)))
    plantilla = tmp_path / "Plantilla.xlsx"
    fx.crear_plantilla_sap(str(plantilla))
    lote = dev_api.crear_lote_pendiente("2026-09-12", "2026-09-12", "a", base)
    r = dev_api.procesar_lote(lote["lote_id"], base, ent["dir_cierres"], os.path.join(ent["dir_entrada"], "MACROS SEPTIEMBRE.xlsm"), str(plantilla))
    c = r["cierres"][0]
    assert c["estado_precheck_maestro"] == MAESTRO_APTO
    resultado = json.load(open(c["ruta_resultado"]))
    tipos = [e["tipo"] for e in resultado["excepciones"] if e["categoria"] == "VOUCHER"]
    assert tipos == [] and resultado["blockers"] == 0 and c["estado_final"] == "LISTO_PARA_PUBLICAR"


def test_D3_segunda_corrida_con_macros_actualizado_usa_la_nueva_version(tmp_path):
    """Sin caché: la segunda corrida (MACROS de Drive ya actualizado, nueva materialización) deja de estar bloqueada."""
    ruta_cierre = _cierre_12(str(tmp_path / "cierres_origen"))
    base = str(tmp_path / "dev")
    plantilla = tmp_path / "Plantilla.xlsx"
    fx.crear_plantilla_sap(str(plantilla))

    def corrida(lote_id, macros_filas):
        ent = dev_api.preparar_procesar_entrada(lote_id, base)
        ruta_m = os.path.join(ent["dir_entrada"], "MACROS SEPTIEMBRE.xlsm")
        shutil.copyfile(_maestro(tmp_path / f"m_{lote_id}.xlsm", macros_filas), ruta_m)
        shutil.copyfile(ruta_cierre, os.path.join(ent["dir_cierres"], os.path.basename(ruta_cierre)))
        l = dev_api.crear_lote_pendiente("2026-09-12", "2026-09-12", "a", base)
        return dev_api.procesar_lote(l["lote_id"], base, ent["dir_cierres"], ruta_m, str(plantilla))["cierres"][0]

    assert corrida("lote0001", MACROS_VIEJO)["estado_final"] == BLOQUEADO_MAESTRO_COBERTURA_NO_CONFIRMADA
    assert corrida("lote0002", MACROS_NUEVO)["estado_final"] == "LISTO_PARA_PUBLICAR"
    # y el maestro materializado en el workdir es exactamente el de la última corrida
    with open(os.path.join(base, "maestro", "MACROS SEPTIEMBRE.xlsm"), "rb") as f1, open(str(tmp_path / "m_lote0002.xlsm"), "rb") as f2:
        assert f1.read() == f2.read()


def test_B5_vouchers_presentes_solo_en_drive_nuevo_hacen_match_exacto(tmp_path):
    import excel_io
    import motor_tiquipaya as mt
    ruta_cierre = _cierre_12(str(tmp_path / "c"))
    cierre = excel_io.leer_cierre(ruta_cierre)
    for macros, esperado in ((MACROS_VIEJO, "NO_ENCONTRADO"), (MACROS_NUEVO, "MATCH_EXACTO")):
        idx = excel_io.leer_macros_bnb(_maestro(tmp_path / f"{esperado}.xlsm", macros))
        r = mt.cruzar_vouchers(cierre, idx)
        assert [d["estado"] for d in r["detalle"]] == [esperado, esperado]


# ---------------------------------------------------------------------------
# A — estado PUBLICADO solo con 06B/Drive
# ---------------------------------------------------------------------------

def test_A_modo_oficial_marcador_local_residual_no_corta_ni_cuenta_como_publicacion(tmp_path):
    """Caso 11/09: un marcador/SAP locales de una publicación DEV vieja NO equivalen a una publicación oficial:
    en modo oficial se prepara de nuevo el SAP_TIQ_* para 06B y el resultado nunca es PUBLICADO/YA_PUBLICADO."""
    item = _cierre_procesado(tmp_path)
    base = str(tmp_path / "dev")
    dev = publicar_cierre_dev(item, base)                                           # residuo DEV (como el del 15/09)
    assert dev["estado_publicacion"] == PUBLICADO
    os.remove(dev["ruta_sap_publicado"])                                            # solo queda el marcador local + un SAP con nombre viejo
    open(os.path.join(base, "publicacion", "sap", "SAP_01-09-2026.xlsx"), "wb").write(b"residuo DEV")
    assert publicar_cierre_dev(item, base)["estado_publicacion"] == YA_PUBLICADO    # en DEV sigue siendo idempotente local

    oficial = publicar_cierre_dev(item, base, modo_oficial=True)
    assert oficial["estado_publicacion"] == PUBLICACION_LOCAL_PREPARADA and oficial["publicado"] is False
    assert oficial["ruta_sap_publicado"].endswith("SAP_TIQ_01-09-2026.xlsx") and os.path.isfile(oficial["ruta_sap_publicado"])
    assert oficial["ruta_marker"] and oficial["sha256"]                              # elegible para 06B (n8n exige estos campos)


def _lote_con_cierre(tmp_path, estado_local, sha="a" * 64):
    base = str(tmp_path / "dev")
    r = dev_api.crear_lote_pendiente("2026-09-11", "2026-09-11", "a", base)
    lote = dev_api._leer_lote(r["lote_id"], base)
    p = {"fecha": "2026-09-11", "estado_final": "LISTO_PARA_PUBLICAR", "estado_publicacion": estado_local, "publicado": estado_local == PUBLICADO,
         "sha256": sha, "ruta_sap_publicado": "/x/SAP_TIQ_11-09-2026.xlsx", "mensajes": []}
    lote["cierres"] = [dict(p)]
    dev_api._escribir_lote(lote, base)
    return base, r["lote_id"], p


def test_A_D6_D7_solo_06b_publicado_oficial_cuenta_como_publicado(tmp_path, monkeypatch):
    # Prueba la lógica de fusión de consolidar_publicacion_oficial() independientemente
    # del entorno: TIQ_BLOCK_OFFICIAL_PUBLISH es una guarda de entorno (Railway shadow),
    # no una regla de negocio — este test valida el contrato base sin ella.
    monkeypatch.delenv("TIQ_BLOCK_OFFICIAL_PUBLISH", raising=False)
    base, lote_id, p = _lote_con_cierre(tmp_path, PUBLICACION_LOCAL_PREPARADA)
    drive = {"fecha": "2026-09-11", "sha256": "a" * 64, "estado_publicacion": "PUBLICADO_OFICIAL", "publicado": True,
             "drive_sap_file_id": "S", "drive_resultado_file_id": "R", "drive_marker_file_id": "M", "drive_entrada_file_id": "E", "mensaje": "ok"}
    r = dev_api.consolidar_publicacion_oficial({"resultado": "OK", "publicados": [dict(p)], "publicados_drive_oficial": [drive]}, lote_id, base)
    x = r["publicados"][0]
    assert (x["estado_publicacion"], x["publicado"], x["drive_sap_file_id"]) == ("PUBLICADO_OFICIAL", True, "S")
    assert r["publicacion_oficial_confirmada"] == ["2026-09-11"]
    assert dev_api._leer_lote(lote_id, base)["cierres"][0]["estado_publicacion"] == "PUBLICADO_OFICIAL"   # persistido


@pytest.mark.parametrize("local", [PUBLICADO, YA_PUBLICADO, PUBLICACION_LOCAL_PREPARADA, None])
def test_A_D5_D7_D8_artefactos_locales_o_06b_ausente_nunca_son_publicado(tmp_path, local):
    base, lote_id, p = _lote_con_cierre(tmp_path, local)
    r = dev_api.consolidar_publicacion_oficial({"resultado": "OK", "publicados": [dict(p)], "publicados_drive_oficial": []}, lote_id, base)
    x = r["publicados"][0]
    assert x["estado_publicacion"] == "ERROR_PUBLICACION_OFICIAL" and x["publicado"] is False
    assert x["estado_publicacion_local"] == local and "no se completó" in x["mensaje"]
    assert r["publicacion_oficial_confirmada"] == []
    assert dev_api._leer_lote(lote_id, base)["cierres"][0]["estado_publicacion"] == "ERROR_PUBLICACION_OFICIAL"


def test_A_D7_06b_con_sha_distinto_o_otra_fecha_no_confirma(tmp_path):
    base, lote_id, p = _lote_con_cierre(tmp_path, PUBLICACION_LOCAL_PREPARADA)
    otro_sha = {"fecha": "2026-09-11", "sha256": "b" * 64, "estado_publicacion": "PUBLICADO_OFICIAL", "publicado": True}
    otra_fecha = {"fecha": "2026-09-10", "sha256": "a" * 64, "estado_publicacion": "PUBLICADO_OFICIAL", "publicado": True}
    r = dev_api.consolidar_publicacion_oficial({"publicados": [dict(p)], "publicados_drive_oficial": [otro_sha, otra_fecha]}, lote_id, base)
    assert r["publicados"][0]["estado_publicacion"] == "ERROR_PUBLICACION_OFICIAL"


def test_A_D9_reintento_oficial_es_idempotente_marcador_de_drive_ya_existe(tmp_path, monkeypatch):
    # Ver nota en test_A_D6_D7_...: contrato base, independiente de la guarda de entorno.
    monkeypatch.delenv("TIQ_BLOCK_OFFICIAL_PUBLISH", raising=False)
    base, lote_id, p = _lote_con_cierre(tmp_path, PUBLICACION_LOCAL_PREPARADA)
    drive = {"fecha": "2026-09-11", "sha256": "a" * 64, "estado_publicacion": "YA_PUBLICADO", "publicado": False,
             "mensaje": "Marcador ya existe en Drive (oficial): no se republica (idempotencia SHA256)."}
    r = dev_api.consolidar_publicacion_oficial({"publicados": [dict(p)], "publicados_drive_oficial": [drive]}, lote_id, base)
    x = r["publicados"][0]
    assert x["estado_publicacion"] == "YA_PUBLICADO_OFICIAL" and x["publicado"] is False and r["publicacion_oficial_confirmada"] == ["2026-09-11"]


def test_A_estado_de_error_real_de_publicacion_no_se_disfraza(tmp_path):
    base, lote_id, p = _lote_con_cierre(tmp_path, "ERROR_PUBLICACION")
    r = dev_api.consolidar_publicacion_oficial({"publicados": [dict(p)], "publicados_drive_oficial": []}, lote_id, base)
    assert r["publicados"][0]["estado_publicacion"] == "ERROR_PUBLICACION"


def test_A_CLI_publicar_en_modo_oficial_prepara_pero_no_publica(tmp_path, monkeypatch):
    """publicar_seleccionados(modo_oficial=True) persiste PUBLICACION_LOCAL_PREPARADA en el lote (nunca PUBLICADO)."""
    # Ver nota en test_A_D6_D7_...: contrato base, independiente de la guarda de entorno.
    monkeypatch.delenv("TIQ_BLOCK_OFFICIAL_PUBLISH", raising=False)
    item = _cierre_procesado(tmp_path)
    base = str(tmp_path / "dev")
    r = dev_api.crear_lote_pendiente(item["fecha"], item["fecha"], "a", base)
    lote = dev_api._leer_lote(r["lote_id"], base)
    lote["cierres"] = [item]
    dev_api._escribir_lote(lote, base)
    res = dev_api.publicar_seleccionados(r["lote_id"], [item["fecha"]], base, "a", modo_oficial=True)
    assert res["publicados"][0]["estado_publicacion"] == PUBLICACION_LOCAL_PREPARADA
    assert dev_api._leer_lote(r["lote_id"], base)["cierres"][0]["estado_publicacion"] == PUBLICACION_LOCAL_PREPARADA
    res2 = dev_api.publicar_seleccionados(r["lote_id"], [item["fecha"]], base, "a")           # DEV sin cambios
    assert res2["publicados"][0]["estado_publicacion"] in (PUBLICADO, YA_PUBLICADO)


# ---------------------------------------------------------------------------
# SHADOW — guarda de entorno TIQ_BLOCK_OFFICIAL_PUBLISH (migración Railway).
# Deterministas: solo tmp_path/diccionarios en memoria, nada de Drive ni n8n.
# ---------------------------------------------------------------------------

def test_shadow_publicar_seleccionados_modo_oficial_lanza_bloqueada(tmp_path, monkeypatch):
    """Con TIQ_BLOCK_OFFICIAL_PUBLISH=true, modo_oficial=True se rechaza siempre,
    sin importar el estado del lote — ver v3/shadow_guard.py."""
    monkeypatch.setenv("TIQ_BLOCK_OFFICIAL_PUBLISH", "true")
    item = _cierre_procesado(tmp_path)
    base = str(tmp_path / "dev")
    r = dev_api.crear_lote_pendiente(item["fecha"], item["fecha"], "a", base)
    lote = dev_api._leer_lote(r["lote_id"], base)
    lote["cierres"] = [item]
    dev_api._escribir_lote(lote, base)
    with pytest.raises(PublicacionOficialBloqueadaError):
        dev_api.publicar_seleccionados(r["lote_id"], [item["fecha"]], base, "a", modo_oficial=True)


def test_shadow_consolidar_publicacion_oficial_ignora_evidencia_drive_simulada(tmp_path, monkeypatch):
    """Con TIQ_BLOCK_OFFICIAL_PUBLISH=true, ninguna evidencia de 06B/Drive —ni siquiera
    PUBLICADO_OFICIAL/publicado=true simulada— puede resultar en PUBLICADO_OFICIAL."""
    monkeypatch.setenv("TIQ_BLOCK_OFFICIAL_PUBLISH", "true")
    base, lote_id, p = _lote_con_cierre(tmp_path, PUBLICACION_LOCAL_PREPARADA)
    drive = {"fecha": "2026-09-11", "sha256": "a" * 64, "estado_publicacion": "PUBLICADO_OFICIAL", "publicado": True,
             "drive_sap_file_id": "S", "drive_resultado_file_id": "R", "drive_marker_file_id": "M", "drive_entrada_file_id": "E", "mensaje": "ok"}
    r = dev_api.consolidar_publicacion_oficial({"resultado": "OK", "publicados": [dict(p)], "publicados_drive_oficial": [drive]}, lote_id, base)
    x = r["publicados"][0]
    assert x["estado_publicacion"] == "ERROR_PUBLICACION_OFICIAL" and x["publicado"] is False
    assert r["publicacion_oficial_confirmada"] == []


def test_D10_v2_y_modulos_mensuales_sin_cambios():
    import shutil
    import subprocess
    if shutil.which("git") is None or not os.path.isdir(os.path.join(RAIZ, ".git")):
        pytest.skip("repo-integrity check requires a Git checkout; runtime container has no .git")
    intactos = ["consolidador_mensual.py", "control_asignaciones.py", "control_cxc_cxp.py", "run_batch.py", "excel_io.py",
                "correcciones_tiquipaya.py", "motor_tiquipaya.py", "pipeline_tiquipaya.py", "v3/control1_modos.py", "v3/control3_modos.py"]
    r = subprocess.run(["git", "diff", "HEAD", "--stat", "--"] + [os.path.join(RAIZ, p) for p in intactos],
                       capture_output=True, text=True, cwd=RAIZ)
    assert r.returncode == 0 and r.stdout.strip() == ""
