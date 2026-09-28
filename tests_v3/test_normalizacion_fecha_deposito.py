"""tests_v3/test_normalizacion_fecha_deposito.py — normalización operativa
de FECHA DE DEPOSITO antes del precheck (hallazgo real CAJA AMÉRICA,
2026-09-28: '28/09/26' con año de 2 dígitos rompía
v3/precheck_maestro.py, reportado engañosamente como "Maestro sin
cobertura"). Ver v3/normalizacion_fecha_deposito.py: reutiliza LITERAL el
regex y la regla de expansión del año de 2 dígitos del skill
`claude/auditor-cierres-skill` (control5_fecha_deposito.py /
control5_regla.md, paso 3 "TEXTO válido"), y el mecanismo de escritura
XML seguro vendorizado en v3/_xlsm_xml.py (nunca openpyxl.save() sobre un
cierre real).

Uso: python -m pytest tests_v3/test_normalizacion_fecha_deposito.py -q
"""
import datetime
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tests"))

import openpyxl  # noqa: E402

import xlsx_fixtures as fx  # noqa: E402
from v3 import normalizacion_fecha_deposito as nfd  # noqa: E402
from v3 import precheck_maestro as pm  # noqa: E402
import excel_io  # noqa: E402


# ---------------------------------------------------------------------------
# interpretar_fecha_texto: la regla pura, extraída literal del auditor
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("texto,anio_cierre,esperado", [
    ("28/09/26", 2026, datetime.date(2026, 9, 28)),   # caso real CIERRE 26-09-2026 SFC108!F3
    ("25/09/26", 2026, datetime.date(2026, 9, 25)),   # caso real CIERRE 25-09-2026 SFC108!F3
    ("5/9/26", 2026, datetime.date(2026, 9, 5)),       # D/M/YY (un solo dígito)
    ("05/9/2026", 2026, datetime.date(2026, 9, 5)),    # DD/M/YYYY
    ("28/09/2026", 2020, datetime.date(2026, 9, 28)),  # año de 4 dígitos: nunca depende del año del cierre
    ("28/09/2026", None, datetime.date(2026, 9, 28)),  # idem, aunque no se conozca el año del cierre
])
def test_formatos_admitidos_se_interpretan_correctamente(texto, anio_cierre, esperado):
    fecha, motivo = nfd.interpretar_fecha_texto(texto, anio_cierre)
    assert fecha == esperado
    assert motivo is None


@pytest.mark.parametrize("texto,anio_cierre,motivo_esperado", [
    ("28/09/26", 2025, "TEXTO_ANIO_2_DIGITOS_NO_COINCIDE_CON_ANIO_DEL_CIERRE"),  # NO se autocorrige: año no coincide
    ("28/09/26", None, "TEXTO_ANIO_2_DIGITOS_NO_COINCIDE_CON_ANIO_DEL_CIERRE"),  # año del cierre desconocido: tampoco
    ("31/02/26", 2026, "TEXTO_FECHA_INEXISTENTE_EN_CALENDARIO"),                # 31 de febrero no existe
    ("2026-09-28", 2026, "TEXTO_FORMATO_NO_ADMITIDO"),                          # ISO: no es el formato que esta regla admite
    (" 28/09/26", 2026, "TEXTO_FORMATO_NO_ADMITIDO"),                           # espacio: ambiguo, no se admite
    ("28/09/26 ", 2026, "TEXTO_FORMATO_NO_ADMITIDO"),
    ("28-09-2026", 2026, "TEXTO_FORMATO_NO_ADMITIDO"),                          # separador '-': no admitido aquí
    ("28/9", 2026, "TEXTO_FORMATO_NO_ADMITIDO"),
    ("hola", 2026, "TEXTO_FORMATO_NO_ADMITIDO"),
])
def test_formatos_ambiguos_o_no_admitidos_nunca_se_autocorrigen(texto, anio_cierre, motivo_esperado):
    fecha, motivo = nfd.interpretar_fecha_texto(texto, anio_cierre)
    assert fecha is None
    assert motivo == motivo_esperado


# ---------------------------------------------------------------------------
# clasificar_fechas_deposito / aplicar / normalizar_cierre_para_precheck
# ---------------------------------------------------------------------------

def _cierre_composicion_depositos(ruta, hojas):
    """Fixture MÍNIMO (solo el bloque COMPOSICION DE DEPOSITOS que este
    módulo lee) -- deliberadamente distinto de xlsx_fixtures.crear_cierre
    (que arma un cierre COMPLETO para excel_io.leer_cierre): alcanza para
    probar clasificar_fechas_deposito()/aplicar() en aislamiento.
    `hojas`: {"SFC107": [(etiqueta, importe, fecha_valor, asignacion), ...]}."""
    wb = openpyxl.Workbook()
    primero = True
    for nombre_hoja, filas in hojas.items():
        ws = wb.active if primero else wb.create_sheet(nombre_hoja)
        if primero:
            ws.title = nombre_hoja
            primero = False
        ws.append(["COMPOSICION DE DEPOSITOS", "IMPORTE Bs", "FECHA DE DEPOSITO", "ASIGNACION", "BANCO"])
        for etiqueta, importe, fecha_valor, asignacion in filas:
            ws.append([etiqueta, importe, fecha_valor, asignacion, "BNB 123"])
    wb.save(ruta)


def test_clasifica_solo_las_celdas_de_texto_ambiguo_pero_resoluble(tmp_path):
    ruta = str(tmp_path / "CIERRE 26-09-2026.xlsm")
    _cierre_composicion_depositos(ruta, {
        "SFC107": [("DEPOSITO", "100.00", "28/09/26", "AB1")],   # america, año coincide -> normaliza
        "SFC108": [("DEPOSITO", "50.00", "28/09/25", "AB2")],    # america, año NO coincide -> NO se toca
    })
    resultado = nfd.clasificar_fechas_deposito(ruta, "america", "2026-09-26")
    assert len(resultado["plan"]) == 1
    assert resultado["plan"][0]["hoja"] == "SFC107"
    assert resultado["plan"][0]["fecha_nueva"] == datetime.date(2026, 9, 28)
    assert len(resultado["trazabilidad"]) == 1
    traza = resultado["trazabilidad"][0]
    assert traza["valor_original"] == "28/09/26"
    assert traza["valor_normalizado"] == "2026-09-28"
    assert traza["motivo"] == nfd.MOTIVO_ANIO_2_DIGITOS
    assert traza["hoja"] == "SFC107" and traza["celda"]


def test_tiquipaya_usa_sfc101_102_no_sfc107_108(tmp_path):
    ruta = str(tmp_path / "CIERRE 26-09-2026.xlsm")
    _cierre_composicion_depositos(ruta, {
        "SFC101": [("DEPOSITO", "100.00", "26/09/26", "AB1")],
        "SFC107": [("DEPOSITO", "100.00", "26/09/26", "AB1")],  # misma fecha, pero NO es hoja de tiquipaya
    })
    resultado = nfd.clasificar_fechas_deposito(ruta, "tiquipaya", "2026-09-26")
    assert len(resultado["plan"]) == 1
    assert resultado["plan"][0]["hoja"] == "SFC101"


def test_normalizar_cierre_para_precheck_escribe_copia_nueva_y_no_toca_el_original(tmp_path):
    ruta = str(tmp_path / "CIERRE 26-09-2026.xlsm")
    _cierre_composicion_depositos(ruta, {"SFC108": [("DEPOSITO", "100.00", "28/09/26", "AB1")]})
    bytes_originales = open(ruta, "rb").read()

    resultado = nfd.normalizar_cierre_para_precheck(ruta, "2026-09-26", "america")

    assert resultado["normalizado"] is True
    assert resultado["ruta_cierre_local"] != ruta
    assert resultado["ruta_cierre_local"].endswith(".normalizado.xlsm")
    assert os.path.isfile(resultado["ruta_cierre_local"])
    # el original queda BYTE A BYTE intacto -- nunca se modifica ni se sobrescribe
    assert open(ruta, "rb").read() == bytes_originales

    # la copia nueva SI tiene la fecha real (no texto) al releerla --
    # openpyxl puede devolver datetime.datetime para una celda de fecha
    # corta (igual que ya asume excel_io._fecha_iso), nunca un str.
    wb = openpyxl.load_workbook(resultado["ruta_cierre_local"], data_only=True)
    valor = wb["SFC108"]["C2"].value
    assert isinstance(valor, (datetime.date, datetime.datetime)), f"deberia ser una fecha real, no texto: {valor!r}"
    fecha_leida = valor.date() if isinstance(valor, datetime.datetime) else valor
    assert fecha_leida == datetime.date(2026, 9, 28)


def test_sin_nada_que_normalizar_no_crea_ningun_archivo_nuevo(tmp_path):
    """Caso normal (incluida toda Caja Tiquipaya hoy): cero fechas de
    texto ambiguas -> ruta_cierre_local queda EXACTAMENTE igual, sin
    ningun archivo nuevo -- cero costo, cero cambio de comportamiento."""
    ruta = str(tmp_path / "CIERRE 26-09-2026.xlsm")
    _cierre_composicion_depositos(ruta, {"SFC101": [("DEPOSITO", "100.00", datetime.date(2026, 9, 26), "AB1")]})
    resultado = nfd.normalizar_cierre_para_precheck(ruta, "2026-09-26", "tiquipaya")
    assert resultado["normalizado"] is False
    assert resultado["ruta_cierre_local"] == ruta
    assert resultado["cambios"] == []
    assert not os.path.isfile(ruta.replace(".xlsm", ".normalizado.xlsm"))


def test_anio_que_no_coincide_no_se_autocorrige_ni_crea_copia(tmp_path):
    ruta = str(tmp_path / "CIERRE 26-09-2026.xlsm")
    _cierre_composicion_depositos(ruta, {"SFC108": [("DEPOSITO", "100.00", "28/09/25", "AB1")]})  # año 25, cierre 2026
    resultado = nfd.normalizar_cierre_para_precheck(ruta, "2026-09-26", "america")
    assert resultado["normalizado"] is False
    assert resultado["ruta_cierre_local"] == ruta


def test_normalizar_cierres_materializados_solo_toca_items_materializados():
    items = [
        {"fecha": "2026-09-26", "estado_materializacion": "MATERIALIZADO", "ruta_cierre_local": "/no/existe/CIERRE.xlsm"},
        {"fecha": "2026-09-27", "estado_materializacion": "SIN_ARCHIVO", "ruta_cierre_local": None},
    ]
    # ruta_cierre_local inexistente -> clasificar_fechas_deposito lanza,
    # normalizar_cierre_para_precheck lo aisla (no normaliza, no lanza).
    resultado = nfd.normalizar_cierres_materializados(items, caja="america")
    assert resultado[0]["ruta_cierre_local"] == "/no/existe/CIERRE.xlsm"
    assert resultado[0]["normalizacion_fecha_deposito"] == []
    assert resultado[1]["estado_materializacion"] == "SIN_ARCHIVO"
    assert "normalizacion_fecha_deposito" not in resultado[1]


# ---------------------------------------------------------------------------
# End-to-end REAL: precheck_maestro sobre el cierre SIN normalizar (falla
# con CIERRE_FECHA_INVALIDA) vs. sobre la copia normalizada (decide con
# datos reales) -- el mismo escenario que rompía en producción (CAJA
# AMÉRICA, 2026-09-28), reproducido aquí con TIQUIPAYA (misma lógica,
# mismos módulos, sin datos reales de ninguna caja).
# ---------------------------------------------------------------------------

def test_end_to_end_precheck_antes_y_despues_de_normalizar(tmp_path):
    macros_filas = [("2026-09-26", "COD-TEST", "0.01"), ("2026-09-27", "COD-TEST", "0.01")]
    atc_filas = [("2026-09-26", "BANCO (NETO)", "110103012", "ATC 2026-09-26", "0.00", "ASIG")]
    ruta_maestro = str(tmp_path / "MAESTRO.xlsm")
    fx.crear_maestro_unico(str(ruta_maestro), macros_filas=macros_filas, atc_filas=atc_filas)

    ruta_cierre = str(tmp_path / "CIERRE 26-09-2026.xlsm")
    sfc_con_deposito_ambiguo = {
        "total_movimiento": "0.00", "cobros_atc": "0.00", "dolares": "0.00",
        "depositos": [{"importe": "100.00", "fecha": "26/09/26", "asignacion": "AB1"}],
    }
    sfc_vacio = {"total_movimiento": "0.00", "cobros_atc": "0.00", "dolares": "0.00", "depositos": []}
    fx.crear_cierre(ruta_cierre, sfc_con_deposito_ambiguo, sfc_vacio)

    # ANTES de normalizar: el cierre no se puede leer para el chequeo ATC
    # (año de 2 dígitos que excel_io._fecha_iso rechaza) -> CIERRE_FECHA_INVALIDA,
    # NUNCA "Maestro sin cobertura".
    r_antes = pm.evaluar_cobertura_maestro(ruta_maestro, "2026-09-26", ruta_cierre, caja="tiquipaya")
    assert r_antes["estado"] == pm.CIERRE_FECHA_INVALIDA
    assert r_antes["estado"] != pm.BLOQUEADO_MAESTRO_COBERTURA_NO_CONFIRMADA
    assert "Fecha de depósito inválida en el cierre" in r_antes["mensaje"]

    # DESPUES de normalizar (mismo año que el cierre: 26/09/26 -> 2026-09-26,
    # inequívoco): decide con datos reales -> MAESTRO_APTO.
    norm = nfd.normalizar_cierre_para_precheck(ruta_cierre, "2026-09-26", "tiquipaya")
    assert norm["normalizado"] is True
    r_despues = pm.evaluar_cobertura_maestro(ruta_maestro, "2026-09-26", norm["ruta_cierre_local"], caja="tiquipaya")
    assert r_despues["estado"] == pm.MAESTRO_APTO


def test_ano_no_coincide_sigue_bloqueado_como_cierre_fecha_invalida_tras_intentar_normalizar(tmp_path):
    """Un año de 2 dígitos que NO coincide con el año del cierre nunca se
    autocorrige (regla explícita): sigue siendo CIERRE_FECHA_INVALIDA
    incluso después de pasar por la normalización (que, correctamente, no
    tocó nada)."""
    macros_filas = [("2026-09-26", "COD-TEST", "0.01")]
    atc_filas = [("2026-09-26", "BANCO (NETO)", "110103012", "ATC", "0.00", "ASIG")]
    ruta_maestro = str(tmp_path / "MAESTRO.xlsm")
    fx.crear_maestro_unico(str(ruta_maestro), macros_filas=macros_filas, atc_filas=atc_filas)

    ruta_cierre = str(tmp_path / "CIERRE 26-09-2026.xlsm")
    sfc = {
        "total_movimiento": "0.00", "cobros_atc": "0.00", "dolares": "0.00",
        "depositos": [{"importe": "100.00", "fecha": "26/09/25", "asignacion": "AB1"}],  # año 25, cierre 2026
    }
    sfc_vacio = {"total_movimiento": "0.00", "cobros_atc": "0.00", "dolares": "0.00", "depositos": []}
    fx.crear_cierre(ruta_cierre, sfc, sfc_vacio)

    norm = nfd.normalizar_cierre_para_precheck(ruta_cierre, "2026-09-26", "tiquipaya")
    assert norm["normalizado"] is False

    r = pm.evaluar_cobertura_maestro(ruta_maestro, "2026-09-26", norm["ruta_cierre_local"], caja="tiquipaya")
    assert r["estado"] == pm.CIERRE_FECHA_INVALIDA


def test_excel_io_no_se_toca_para_nada(tmp_path):
    """excel_io.py es código compartido con V2/Tiquipaya con pruebas
    propias que exigen diff CERO contra HEAD (ver
    tests_v3/test_auditoria_mensual.py::test_P_Q_v2_y_control3_permanecen_sin_cambios) --
    _fecha_iso() sigue lanzando exactamente el mismo ValueError genérico
    de siempre, con el mismo mensaje; v3.precheck_maestro distingue el
    caso por ese mensaje, nunca por un tipo de excepción nuevo."""
    with pytest.raises(ValueError) as exc_info:
        excel_io._fecha_iso("28/09/26")  # 2 dígitos: excel_io por sí solo nunca expande el año
    assert type(exc_info.value) is ValueError  # exactamente ValueError, ninguna subclase nueva
    assert "Fecha en formato no reconocido" in str(exc_info.value)
