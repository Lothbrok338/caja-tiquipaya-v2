"""tests_v3/test_dev_api_caja_america.py — Caja América sobre el backend
DEV de lotes (v3/dev_api.py): persistencia de la identidad de caja al
crear el lote, inmutabilidad de esa identidad frente a acciones/requests
posteriores, propagación a los módulos v3.* subyacentes y aislamiento de
directorios/nombres entre TIQUIPAYA y AMERICA.

No repite las pruebas contables de tests/test_caja_america.py (columna
CAJA del ATC, regla POSGRADO RESERVA, etc.) ni las de naming de
tests/test_naming_caja_america.py (nombre_sap_global, descubrimiento):
esas ya cubren el núcleo del motor/consolidador. Aquí se prueba
ÚNICAMENTE lo que vive en v3/dev_api.py.

Uso: python -m pytest tests_v3/test_dev_api_caja_america.py -q
"""

import os
import sys

import openpyxl
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tests"))

import xlsx_fixtures as fx  # noqa: E402
import run_batch  # noqa: E402
from v3.clasificacion import LISTO_PARA_PUBLICAR  # noqa: E402
from v3 import dev_api  # noqa: E402
import config_cajas as cfg  # noqa: E402
from tests.test_caja_america import crear_cierre_america  # noqa: E402


_SFC_VACIO = {"total_movimiento": "0.00", "cobros_atc": "0.00", "dolares": "0.00", "depositos": []}
_SFC_VACIO_AME = dict(_SFC_VACIO, posgrado_reserva="0.00")  # AMERICA exige este campo


def _preparar_origen(tmp_path, fechas, caja=None):
    """Mismo patrón que tests_v3/test_dev_api.py::_preparar_origen: el
    contenido del cierre/maestro no importa aquí más allá de lo que exige
    el PRECHECK (v3/precheck_maestro.py, FASE 10C) según la caja: hojas
    SFC de esa caja (para poder leer cobros_atc) y, si `caja` no es
    TIQUIPAYA, columna CAJA en el ATC del maestro (un maestro histórico
    sin esa columna falla cerrado para cualquier otra caja -- ver
    excel_io._resolver_columna_caja). Solo se necesita que la cadena
    01->03 llegue hasta ejecutar_motor, que en estas pruebas se reemplaza
    por un doble."""
    caja_resuelta = cfg.resolver_caja(caja)
    origen_dir = tmp_path / "origen_drive"
    origen_dir.mkdir()
    for fecha in fechas:
        nombre = run_batch.nombre_cierre_esperado(fecha)
        if caja_resuelta.codigo == cfg.TIQUIPAYA.codigo:
            fx.crear_cierre(str(origen_dir / nombre), _SFC_VACIO, _SFC_VACIO)
        else:
            crear_cierre_america(str(origen_dir / nombre), _SFC_VACIO_AME, _SFC_VACIO_AME)
    ruta_maestro = tmp_path / "MAESTRO.xlsm"
    macros_filas = [(fecha, "DUMMY-PRECHECK", "0.01") for fecha in fechas]
    if caja_resuelta.codigo == cfg.TIQUIPAYA.codigo:
        atc_filas = [(fecha, "BANCO (NETO)", "999999999", "DUMMY PRECHECK", "0.00", "DUMMY") for fecha in fechas]
        fx.crear_maestro_unico(str(ruta_maestro), macros_filas=macros_filas, atc_filas=atc_filas)
    else:
        # sin filas ATC: cobros_atc="0.00" en ambos SFC -> el cierre no
        # tuvo movimiento ATC, así que el precheck no exige ninguna fila
        # (solo exige que la columna CAJA exista en el maestro).
        wb = openpyxl.Workbook()
        ws_macros = wb.active
        ws_macros.title = "Tablas Dinamicas Profesional"
        ws_macros.append(["Fecha", "Código de Asignación", "Créditos"])
        for fila in macros_filas:
            ws_macros.append(list(fila))
        ws_atc = wb.create_sheet("ATC TIQUIPAYA")
        ws_atc.append(["FECHA", "TIPO", "CUENTA CONTABLE", "DETALLE", "MONTO", "ASIGNACION", "CAJA"])
        wb.save(str(ruta_maestro))
    ruta_plantilla = tmp_path / "Plantilla.xlsx"
    fx.crear_plantilla_sap(str(ruta_plantilla))
    return str(origen_dir), str(ruta_maestro), str(ruta_plantilla)


# ---------------------------------------------------------------------------
# 1) crear_lote_pendiente persiste la caja
# ---------------------------------------------------------------------------

def test_crear_lote_america_persiste_caja(tmp_path):
    base_dir_dev = str(tmp_path / "dev")
    r = dev_api.crear_lote_pendiente("2026-09-01", "2026-09-01", "auditor.test", base_dir_dev, caja="america")
    assert r["caja"] == "america"

    lote = dev_api._leer_lote(r["lote_id"], base_dir_dev)
    assert lote["caja"] == "america"


def test_crear_lote_sin_caja_persiste_tiquipaya(tmp_path):
    base_dir_dev = str(tmp_path / "dev")
    r = dev_api.crear_lote_pendiente("2026-09-01", "2026-09-01", "auditor.test", base_dir_dev)
    assert r["caja"] == "tiquipaya"
    lote = dev_api._leer_lote(r["lote_id"], base_dir_dev)
    assert lote["caja"] == "tiquipaya"


def test_crear_lote_caja_invalida_falla_cerrado(tmp_path):
    base_dir_dev = str(tmp_path / "dev")
    with pytest.raises(ValueError):
        dev_api.crear_lote_pendiente("2026-09-01", "2026-09-01", "auditor.test", base_dir_dev, caja="bolivia")
    # Fail-closed: no debe quedar ningún LOTE_*.json huérfano en disco.
    lotes_dir = os.path.join(base_dir_dev, "lotes")
    assert not os.path.isdir(lotes_dir) or os.listdir(lotes_dir) == []


# ---------------------------------------------------------------------------
# 2) compatibilidad: lote histórico sin "caja" -> TIQUIPAYA
# ---------------------------------------------------------------------------

def test_lote_historico_sin_campo_caja_se_interpreta_tiquipaya(tmp_path):
    base_dir_dev = str(tmp_path / "dev")
    lote_viejo = {
        "lote_id": "abc123", "fecha_inicio": "2026-09-01", "fecha_fin": "2026-09-01",
        "usuario_auditor": "auditor.viejo", "estado_lote": dev_api.PROCESANDO,
        "creado_en": "2026-01-01T00:00:00+00:00", "cierres": [],
        # sin "caja": simula un lote creado antes de esta funcionalidad.
    }
    dev_api._escribir_lote(lote_viejo, base_dir_dev)

    lote = dev_api._leer_lote("abc123", base_dir_dev)
    assert "caja" not in lote
    assert dev_api._caja_lote(lote) is cfg.TIQUIPAYA


# ---------------------------------------------------------------------------
# 3) procesar_lote pasa la caja persistida al motor
# ---------------------------------------------------------------------------

def test_procesar_lote_pasa_caja_america_al_motor(tmp_path, monkeypatch):
    fecha = "2026-09-01"
    origen_dir, ruta_maestro, ruta_plantilla = _preparar_origen(tmp_path, [fecha], caja="america")
    base_dir_dev = str(tmp_path / "dev")

    llamadas = []

    def _motor_falso(aptos, base_dir, version_codigo, caja=None):
        llamadas.append(caja)
        return [dict(item, estado_motor="OK", caja=cfg.resolver_caja(caja).codigo) for item in aptos]

    monkeypatch.setattr(dev_api, "ejecutar_motor", _motor_falso)

    r = dev_api.crear_lote_pendiente(fecha, fecha, "auditor.test", base_dir_dev, caja="america")
    lote = dev_api.procesar_lote(r["lote_id"], base_dir_dev, origen_dir, ruta_maestro, ruta_plantilla)

    assert llamadas == ["america"]
    assert lote["estado_lote"] == dev_api.LISTO_LOTE
    assert lote["cierres"][0]["caja"] == "america"


def test_procesar_lote_default_pasa_tiquipaya_al_motor(tmp_path, monkeypatch):
    fecha = "2026-09-01"
    origen_dir, ruta_maestro, ruta_plantilla = _preparar_origen(tmp_path, [fecha])
    base_dir_dev = str(tmp_path / "dev")

    llamadas = []

    def _motor_falso(aptos, base_dir, version_codigo, caja=None):
        llamadas.append(caja)
        return [dict(item, estado_motor="OK", caja=cfg.resolver_caja(caja).codigo) for item in aptos]

    monkeypatch.setattr(dev_api, "ejecutar_motor", _motor_falso)

    r = dev_api.crear_lote_pendiente(fecha, fecha, "auditor.test", base_dir_dev)
    dev_api.procesar_lote(r["lote_id"], base_dir_dev, origen_dir, ruta_maestro, ruta_plantilla)

    assert llamadas == ["tiquipaya"]


# ---------------------------------------------------------------------------
# 4) corregir/publicar usan SIEMPRE la caja persistida del lote — un
#    request/item que intente decir otra cosa nunca gana.
# ---------------------------------------------------------------------------

def _lote_con_un_cierre(tmp_path, base_dir_dev, caja_lote, caja_en_item, fecha="2026-09-01"):
    r = dev_api.crear_lote_pendiente(fecha, fecha, "auditor.test", base_dir_dev, caja=caja_lote)
    ruta_cierre = tmp_path / "cierre_local.xlsx"
    fx.crear_cierre(str(ruta_cierre), _SFC_VACIO, _SFC_VACIO)
    lote = dev_api._leer_lote(r["lote_id"], base_dir_dev)
    cierre = {
        "fecha": fecha, "estado_final": LISTO_PARA_PUBLICAR,
        "ruta_cierre_local": str(ruta_cierre), "ruta_resultado": None,
    }
    if caja_en_item is not None:
        cierre["caja"] = caja_en_item
    lote["cierres"] = [cierre]
    dev_api._escribir_lote(lote, base_dir_dev)
    return r["lote_id"]


def test_aplicar_correccion_usa_caja_del_lote_no_la_del_item_tampereado(tmp_path, monkeypatch):
    base_dir_dev = str(tmp_path / "dev")
    # El lote es AMERICA, pero el item (por lo que sea: un bug, un archivo
    # editado a mano) trae "caja": "tiquipaya" -- nunca debe ganar.
    lote_id = _lote_con_un_cierre(tmp_path, base_dir_dev, "america", "tiquipaya")

    llamadas = []

    def _revision_falsa(item, base_dir, controles_dir_dev=None, caja=None):
        llamadas.append((item.get("caja"), caja))
        return dict(item, resultado_reproceso=LISTO_PARA_PUBLICAR)

    monkeypatch.setattr(dev_api, "revisar_y_corregir_cierre", _revision_falsa)

    correccion = {
        "categoria": "VOUCHER", "tipo": "X", "identificadores": {},
        "campo_corregido": "cuenta_contable", "valor_original": None,
        "valor_autorizado": "999", "motivo": "test", "usuario_auditor": "auditor.test",
        "caja": "tiquipaya",  # intento (irrelevante) de cambiar la identidad desde el request
    }
    dev_api.aplicar_correccion(lote_id, "2026-09-01", correccion, base_dir_dev)

    assert llamadas == [("america", "america")]


def test_publicar_seleccionados_usa_caja_del_lote_no_la_del_item_tampereado(tmp_path, monkeypatch):
    base_dir_dev = str(tmp_path / "dev")
    lote_id = _lote_con_un_cierre(tmp_path, base_dir_dev, "america", "tiquipaya")

    llamadas = []

    def _publicar_lote_falso(elegibles, base_dir, usuario_auditor=None, modo_oficial=False, caja=None):
        llamadas.append((elegibles[0].get("caja"), caja))
        return [dict(e, publicado=True) for e in elegibles]

    monkeypatch.setattr(dev_api, "publicar_lote", _publicar_lote_falso)
    monkeypatch.setattr(dev_api, "consolidar_auditoria_lote",
                        lambda cierres, base_dir, usuario_auditor: {"ruta_lote": "x"})

    dev_api.publicar_seleccionados(lote_id, ["2026-09-01"], base_dir_dev, "auditor.test")

    assert llamadas == [("america", "america")]


# ---------------------------------------------------------------------------
# 5) aislamiento de directorios (cierre mensual)
# ---------------------------------------------------------------------------

def test_rutas_tiquipaya_permanecen_historicas(tmp_path):
    base = str(tmp_path)
    assert dev_api.global_entrada_dir(base, 2026, 9) == os.path.join(base, "global_entrada", "2026-09")
    assert dev_api.control1_entrada_dir(base, 2026, 9) == os.path.join(base, "control1_entrada", "2026-09")
    assert dev_api.control3_entrada_dir(base, 2026, 9) == os.path.join(base, "control3_entrada", "2026-09")
    assert dev_api._ruta_global(base, 2026, 9) == os.path.join(base, "global", "SAP_GLOBAL_TIQ_SEPTIEMBRE_2026.xlsx")
    # Explícito "tiquipaya" debe dar exactamente lo mismo que el default.
    assert dev_api.global_entrada_dir(base, 2026, 9, "tiquipaya") == dev_api.global_entrada_dir(base, 2026, 9)
    assert dev_api._ruta_global(base, 2026, 9, "tiquipaya") == dev_api._ruta_global(base, 2026, 9)


def test_rutas_america_quedan_bajo_america(tmp_path):
    base = str(tmp_path)
    assert dev_api.global_entrada_dir(base, 2026, 9, "america") == os.path.join(base, "global_entrada", "america", "2026-09")
    assert dev_api.control1_entrada_dir(base, 2026, 9, "america") == os.path.join(base, "control1_entrada", "america", "2026-09")
    assert dev_api.control3_entrada_dir(base, 2026, 9, "america") == os.path.join(base, "control3_entrada", "america", "2026-09")
    assert dev_api._ruta_global(base, 2026, 9, "america") == os.path.join(base, "global", "america", "SAP_GLOBAL_AME_SEPTIEMBRE_2026.xlsx")


def test_global_tiq_y_ame_no_se_cruzan(tmp_path):
    base = str(tmp_path)
    ruta_tiq = dev_api._ruta_global(base, 2026, 9, "tiquipaya")
    ruta_ame = dev_api._ruta_global(base, 2026, 9, "america")
    assert ruta_tiq != ruta_ame
    assert os.path.dirname(ruta_tiq) != os.path.dirname(ruta_ame)
    assert "TIQ" in os.path.basename(ruta_tiq) and "AME" not in os.path.basename(ruta_tiq)
    assert "AME" in os.path.basename(ruta_ame) and "TIQ" not in os.path.basename(ruta_ame)


def test_preparar_entradas_mensuales_respetan_caja(tmp_path):
    base = str(tmp_path)
    r_tiq = dev_api.preparar_global_entrada(2026, 9, base)
    r_ame = dev_api.preparar_global_entrada(2026, 9, base, "america")
    assert r_tiq["dir_entrada"] != r_ame["dir_entrada"]
    assert os.path.isdir(r_tiq["dir_entrada"]) and os.path.isdir(r_ame["dir_entrada"])
    assert os.path.join("global_entrada", "america") in r_ame["dir_entrada"]
    assert os.path.join("global_entrada", "america") not in r_tiq["dir_entrada"]


def test_caja_invalida_en_rutas_mensuales_falla_cerrado(tmp_path):
    base = str(tmp_path)
    with pytest.raises(ValueError):
        dev_api.global_entrada_dir(base, 2026, 9, "bolivia")
    with pytest.raises(ValueError):
        dev_api.control1_entrada_dir(base, 2026, 9, "bolivia")
    with pytest.raises(ValueError):
        dev_api.control3_entrada_dir(base, 2026, 9, "bolivia")
    with pytest.raises(ValueError):
        dev_api._ruta_global(base, 2026, 9, "bolivia")
