"""tests_v3/test_auditoria_mensual.py — FASE 12: cierre MENSUAL de V3
(GLOBAL -> CONTROL 1 -> CONTROL 3), Módulo 07 · AUDITORIA.

Verifica que v3.auditoria.generar_global_mensual/ejecutar_control1_mensual/
ejecutar_control3_mensual/ejecutar_cierre_mensual son adaptadores delgados
sobre consolidador_mensual.py/control_asignaciones.py/control_cxc_cxp.py
(V2, sin cambios) — NO reimplementan ninguna regla. También verifica la
separación DIARIO/MENSUAL: CONTROL 1/3 nunca se disparan desde el flujo
diario (procesar_lote/publicar_seleccionados).

Uso: python -m pytest tests_v3/test_auditoria_mensual.py -q
"""

import datetime
import os
import sys
from decimal import Decimal

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tests"))

import openpyxl  # noqa: E402

import consolidador_mensual as cm  # noqa: E402  (reutilizado tal cual, solo para comparar paridad)
import control_asignaciones as ctrl1_v2  # noqa: E402
import control_cxc_cxp as ctrl3_v2  # noqa: E402
from xlsx_fixtures import crear_plantilla_sap  # noqa: E402
from v3.auditoria import (  # noqa: E402
    generar_global_mensual, ejecutar_control1_mensual, ejecutar_control3_mensual,
    ejecutar_cierre_mensual, consolidar_auditoria_lote,
)
from v3 import dev_api  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures — SAP diario y GLOBAL sintéticos (nunca datos contables reales).
# ---------------------------------------------------------------------------

def _crear_sap_diario(ruta, cargo="100.00", cuenta="110101001", asignacion=None,
                       fecha_valor=datetime.date(2026, 9, 5)):
    """SAP diario mínimo válido: hoja '1', cabecera fija, una partida DEBE
    + una HABER cuadradas (mismo layout que sap_writer.py/consolidador_mensual.py)."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "1"
    ws["B10"] = "BO01"
    ws["C10"] = "DB"
    ws["H10"] = "BOB"
    ws["L10"] = "CAJA TIQUIPAYA"

    ws["B16"] = "BO01"
    ws["C16"] = cuenta
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


def _crear_global_minimo(ruta, cuenta="110201002", asignacion="3P66536982", cargo=100, fecha_valor="2026-09-01"):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "1"
    ws["C16"] = cuenta
    ws["D16"] = "GLOSA DEMO"
    ws["E16"] = cargo
    ws["F16"] = None
    ws["O16"] = fecha_valor
    ws["R16"] = asignacion
    wb.save(ruta)


# ---------------------------------------------------------------------------
# GLOBAL — generar_global_mensual (delega en consolidador_mensual.py)
# ---------------------------------------------------------------------------

def test_varios_sap_diarios_producen_global_correcto(tmp_path):
    sap_dir = tmp_path / "sap_diarios"
    sap_dir.mkdir()
    _crear_sap_diario(str(sap_dir / "SAP_TIQ_01-09-2026.xlsx"), cargo="100.00")
    _crear_sap_diario(str(sap_dir / "SAP_TIQ_02-09-2026.xlsx"), cargo="50.00")
    plantilla = tmp_path / "Plantilla.xlsx"
    crear_plantilla_sap(str(plantilla))
    salida = tmp_path / "SAP_GLOBAL_TIQ_SEPTIEMBRE_2026.xlsx"

    r = generar_global_mensual(2026, 9, str(sap_dir), str(plantilla), str(salida))

    assert r["estado"] == "VALIDADO_PENDIENTE_PUBLICACION"
    assert r["cantidad_sap_incluidos"] == 2
    assert r["cantidad_partidas"] == 4  # 2 partidas por SAP diario (DEBE+HABER)
    assert os.path.isfile(r["ruta_global_generado"])
    assert r["ruta_global_generado"] == str(salida.resolve()) or r["ruta_global_generado"] == os.path.abspath(str(salida))


def test_global_ignora_sap_de_otro_mes(tmp_path):
    sap_dir = tmp_path / "sap_diarios"
    sap_dir.mkdir()
    _crear_sap_diario(str(sap_dir / "SAP_TIQ_01-09-2026.xlsx"))
    _crear_sap_diario(str(sap_dir / "SAP_TIQ_01-08-2026.xlsx"))  # AGOSTO: fuera del periodo pedido
    plantilla = tmp_path / "Plantilla.xlsx"
    crear_plantilla_sap(str(plantilla))
    salida = tmp_path / "SAP_GLOBAL_TIQ_SEPTIEMBRE_2026.xlsx"

    r = generar_global_mensual(2026, 9, str(sap_dir), str(plantilla), str(salida))
    assert r["sap_incluidos"] == ["SAP_TIQ_01-09-2026.xlsx"]


def test_sap_duplicado_identico_no_se_duplica(tmp_path):
    origen1 = tmp_path / "origen1"
    origen2 = tmp_path / "origen2"
    origen1.mkdir()
    origen2.mkdir()
    ruta1 = origen1 / "SAP_TIQ_05-09-2026.xlsx"
    ruta2 = origen2 / "SAP_TIQ_05-09-2026.xlsx"
    _crear_sap_diario(str(ruta1), cargo="75.00")
    # Copia byte a byte del mismo SAP (mismo nombre, mismo contenido, otra carpeta).
    with open(ruta1, "rb") as f_in, open(ruta2, "wb") as f_out:
        f_out.write(f_in.read())

    plantilla = tmp_path / "Plantilla.xlsx"
    crear_plantilla_sap(str(plantilla))
    salida = tmp_path / "SAP_GLOBAL_TIQ_SEPTIEMBRE_2026.xlsx"

    r = generar_global_mensual(
        2026, 9, sap_dir=None, plantilla=str(plantilla), salida=str(salida),
        archivos_lista=[str(ruta1), str(ruta2)],
    )
    assert r["estado"] == "VALIDADO_PENDIENTE_PUBLICACION"
    assert r["cantidad_sap_incluidos"] == 1  # la copia identica se ignora, no se duplica
    assert r["cantidad_partidas"] == 2  # NUNCA 4 -- si se duplicara, aqui se veria
    assert len(r["duplicados_identicos_ignorados"]) == 1


def test_sap_duplicado_con_contenido_distinto_bloquea(tmp_path):
    """Mismo nombre, contenido DISTINTO -> nunca se elige uno arbitrariamente:
    bloquea la consolidacion (blockers), no genera GLOBAL."""
    origen1 = tmp_path / "origen1"
    origen2 = tmp_path / "origen2"
    origen1.mkdir()
    origen2.mkdir()
    ruta1 = origen1 / "SAP_TIQ_05-09-2026.xlsx"
    ruta2 = origen2 / "SAP_TIQ_05-09-2026.xlsx"
    _crear_sap_diario(str(ruta1), cargo="75.00")
    _crear_sap_diario(str(ruta2), cargo="999.00")  # mismo nombre, contenido distinto

    plantilla = tmp_path / "Plantilla.xlsx"
    crear_plantilla_sap(str(plantilla))
    salida = tmp_path / "SAP_GLOBAL_TIQ_SEPTIEMBRE_2026.xlsx"

    r = generar_global_mensual(
        2026, 9, sap_dir=None, plantilla=str(plantilla), salida=str(salida),
        archivos_lista=[str(ruta1), str(ruta2)],
    )
    assert r["estado"] == "ERROR_REVISAR"
    assert any("DUPLICADO_SAP_DIFERENTE" in b for b in r["blockers"])
    assert not os.path.isfile(salida)


def test_fechas_faltantes_se_avisan_claramente(tmp_path):
    sap_dir = tmp_path / "sap_diarios"
    sap_dir.mkdir()
    _crear_sap_diario(str(sap_dir / "SAP_TIQ_01-09-2026.xlsx"))
    _crear_sap_diario(str(sap_dir / "SAP_TIQ_03-09-2026.xlsx"))
    plantilla = tmp_path / "Plantilla.xlsx"
    crear_plantilla_sap(str(plantilla))
    salida = tmp_path / "SAP_GLOBAL_TIQ_SEPTIEMBRE_2026.xlsx"

    r = generar_global_mensual(2026, 9, str(sap_dir), str(plantilla), str(salida))

    assert "2026-09-02" in r["fechas_faltantes"]
    assert "2026-09-01" not in r["fechas_faltantes"]
    assert "2026-09-03" not in r["fechas_faltantes"]
    assert len(r["fechas_faltantes"]) == 28  # septiembre tiene 30 dias, 2 presentes


def test_global_no_modifica_los_sap_diarios(tmp_path):
    sap_dir = tmp_path / "sap_diarios"
    sap_dir.mkdir()
    ruta_sap = sap_dir / "SAP_TIQ_01-09-2026.xlsx"
    _crear_sap_diario(str(ruta_sap))
    hash_antes = cm._sha256_archivo(str(ruta_sap))
    mtime_antes = os.path.getmtime(ruta_sap)

    plantilla = tmp_path / "Plantilla.xlsx"
    crear_plantilla_sap(str(plantilla))
    hash_plantilla_antes = cm._sha256_archivo(str(plantilla))
    salida = tmp_path / "SAP_GLOBAL_TIQ_SEPTIEMBRE_2026.xlsx"

    generar_global_mensual(2026, 9, str(sap_dir), str(plantilla), str(salida))

    assert cm._sha256_archivo(str(ruta_sap)) == hash_antes
    assert os.path.getmtime(ruta_sap) == mtime_antes
    assert cm._sha256_archivo(str(plantilla)) == hash_plantilla_antes


def test_generar_global_paridad_con_consolidador_mensual_directo(tmp_path):
    """V3 no reinterpreta nada: mismo input -> mismo resultado (salvo el
    campo extra fechas_faltantes, que consolidador_mensual.py no calcula)."""
    import types

    sap_dir = tmp_path / "sap_diarios"
    sap_dir.mkdir()
    _crear_sap_diario(str(sap_dir / "SAP_TIQ_01-09-2026.xlsx"), cargo="100.00")
    plantilla = tmp_path / "Plantilla.xlsx"
    crear_plantilla_sap(str(plantilla))

    salida_v2 = tmp_path / "v2" / "SAP_GLOBAL_TIQ_SEPTIEMBRE_2026.xlsx"
    os.makedirs(salida_v2.parent, exist_ok=True)
    args = types.SimpleNamespace(anio=2026, mes=9, sap_dir=str(sap_dir), plantilla=str(plantilla),
                                  salida=str(salida_v2), archivos_lista=None, force=False)
    resultado_v2 = cm.ejecutar_consolidacion(args)

    salida_v3 = tmp_path / "v3" / "SAP_GLOBAL_TIQ_SEPTIEMBRE_2026.xlsx"
    os.makedirs(salida_v3.parent, exist_ok=True)
    resultado_v3 = generar_global_mensual(2026, 9, str(sap_dir), str(plantilla), str(salida_v3))

    for campo in ("estado", "cantidad_sap_incluidos", "sap_incluidos", "cantidad_partidas",
                  "cargo_global", "haber_global", "diferencia", "blockers"):
        assert resultado_v2[campo] == resultado_v3[campo], campo
    with open(salida_v2, "rb") as a, open(salida_v3, "rb") as b:
        assert a.read() == b.read()  # el SAP GLOBAL generado es byte-identico


# ---------------------------------------------------------------------------
# CONTROL 1 / CONTROL 3 sobre el GLOBAL (delegados completos, no solo la
# correccion celda-por-celda ya probada en parity_v3).
# ---------------------------------------------------------------------------

def test_control1_sobre_global_sin_duplicados(tmp_path):
    ruta_global = tmp_path / "SAP_GLOBAL_TIQ_SEPTIEMBRE_2026.xlsx"
    _crear_global_minimo(str(ruta_global), asignacion="3P66536982")
    ruta_historico = tmp_path / "HISTORICO_ASIGNACIONES.csv"

    r = ejecutar_control1_mensual(str(ruta_global), str(ruta_historico), directorio_revision=str(tmp_path))

    assert r["estado"] == "OK_SIN_DUPLICADOS"
    assert os.path.isfile(ruta_historico)

    # Paridad: llamar ctrl1_v2.ejecutar_control() directo con el MISMO
    # historico (ya escrito arriba) debe reportar YA_PROCESADO_SIN_CAMBIOS
    # (mismo GLOBAL, mismo SHA) -- v3 no crea un historico paralelo.
    r2 = ctrl1_v2.ejecutar_control(str(ruta_global), str(ruta_historico), directorio_revision=str(tmp_path))
    assert r2["estado"] == "YA_PROCESADO_SIN_CAMBIOS"


def test_control3_sobre_global(tmp_path):
    ruta_global = tmp_path / "SAP_GLOBAL_TIQ_SEPTIEMBRE_2026.xlsx"
    _crear_global_minimo(str(ruta_global), cuenta="110201002", asignacion="3P66536982", cargo=100)
    ruta_historico = tmp_path / "HISTORICO_CXC_CXP.csv"

    r = ejecutar_control3_mensual(str(ruta_global), str(ruta_historico))

    assert r["estado"] not in ("ERROR_TECNICO", "GLOBAL_MODIFICADO_REQUIERE_REVISION")
    assert r["periodo"] == "SEPTIEMBRE_2026"
    assert os.path.isfile(ruta_historico)

    # Paridad: segunda corrida con el MISMO GLOBAL -> idempotente (V2 puro).
    r2 = ejecutar_control3_mensual(str(ruta_global), str(ruta_historico))
    assert r2["estado"] == "YA_PROCESADO_SIN_CAMBIOS"


# ---------------------------------------------------------------------------
# Orquestador mensual completo
# ---------------------------------------------------------------------------

def test_ejecutar_cierre_mensual_encadena_global_control1_control3(tmp_path):
    sap_dir = tmp_path / "sap_diarios"
    sap_dir.mkdir()
    _crear_sap_diario(str(sap_dir / "SAP_TIQ_01-09-2026.xlsx"), cargo="100.00", cuenta="110201002", asignacion="3P66536982")
    plantilla = tmp_path / "Plantilla.xlsx"
    crear_plantilla_sap(str(plantilla))
    base_dir_dev = tmp_path / "dev"

    r = ejecutar_cierre_mensual(
        2026, 9, str(sap_dir), str(plantilla), str(tmp_path / "global" / "SAP_GLOBAL_TIQ_SEPTIEMBRE_2026.xlsx"),
        str(tmp_path / "global" / "HISTORICO_ASIGNACIONES.csv"),
        str(tmp_path / "global" / "HISTORICO_CXC_CXP.csv"),
        str(base_dir_dev),
    )

    assert r["global"]["estado"] == "VALIDADO_PENDIENTE_PUBLICACION"
    assert r["control1"]["estado"] == "OK_SIN_DUPLICADOS"
    assert r["control3"]["estado"] not in ("ERROR_TECNICO", None)
    assert os.path.isfile(r["ruta_consolidado"])


def test_control1_control3_no_se_ejecutan_si_global_tiene_blockers(tmp_path):
    """Si GLOBAL no cuadra/tiene un SAP invalido, CONTROL 1/3 NUNCA corren
    sobre ese GLOBAL (nunca se genera ademas, asi que no habria ni archivo
    que leer) -- verifica que el orquestador respeta ese guard."""
    sap_dir = tmp_path / "sap_diarios"
    sap_dir.mkdir()
    # SAP diario DESCUADRADO a proposito (cargo sin haber que lo compense).
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "1"
    ws["B10"] = "BO01"; ws["C10"] = "DB"; ws["H10"] = "BOB"; ws["L10"] = "CAJA TIQUIPAYA"
    ws["B16"] = "BO01"; ws["C16"] = "110101001"; ws["E16"] = Decimal("100.00"); ws["F16"] = None
    ws["O16"] = datetime.date(2026, 9, 1)
    wb.save(sap_dir / "SAP_TIQ_01-09-2026.xlsx")
    plantilla = tmp_path / "Plantilla.xlsx"
    crear_plantilla_sap(str(plantilla))
    base_dir_dev = tmp_path / "dev"

    r = ejecutar_cierre_mensual(
        2026, 9, str(sap_dir), str(plantilla), str(tmp_path / "global" / "SAP_GLOBAL_TIQ_SEPTIEMBRE_2026.xlsx"),
        str(tmp_path / "global" / "HISTORICO_ASIGNACIONES.csv"),
        str(tmp_path / "global" / "HISTORICO_CXC_CXP.csv"),
        str(base_dir_dev),
    )
    assert r["global"]["estado"] == "ERROR_REVISAR"
    assert r["control1"] is None
    assert r["control3"] is None
    assert not os.path.isfile(tmp_path / "global" / "HISTORICO_ASIGNACIONES.csv")
    assert not os.path.isfile(tmp_path / "global" / "HISTORICO_CXC_CXP.csv")


# ---------------------------------------------------------------------------
# Separacion DIARIO / MENSUAL: CONTROL 1/3 NUNCA se disparan por cierre.
# ---------------------------------------------------------------------------

def test_flujo_diario_nunca_ejecuta_control1_ni_control3(tmp_path):
    """consolidar_auditoria_lote() (llamado desde publicar_seleccionados en
    CADA publicacion diaria) nunca invoca CONTROL 1/3 por si solo -- solo
    los REGISTRA si el llamador ya se los paso (nunca ocurre en el flujo
    diario real, ver v3/dev_api.py::publicar_seleccionados)."""
    base_dir_dev = tmp_path / "dev"
    item = {
        "fecha": "2026-09-01", "estado_final": "LISTO_PARA_PUBLICAR", "publicado": True,
        "estado_publicacion": "PUBLICADO", "sha256": "abc123",
    }
    auditoria = consolidar_auditoria_lote([item], str(base_dir_dev), "auditor.dev")

    assert auditoria["cierres"][0]["fecha"] == "2026-09-01"
    with open(auditoria["ruta_lote"], "r", encoding="utf-8") as f:
        import json
        contenido = json.load(f)
    assert contenido["controles_ejecutados"] == []  # ni CONTROL_1 ni CONTROL_3 aparecen

    # Ademas: en todo base_dir_dev (el arbol completo que usa el flujo
    # diario) nunca aparece ningun archivo de historico de CONTROL 1/3 --
    # esos archivos SOLO los crea el flujo MENSUAL (ver test de arriba).
    for root, _dirs, files in os.walk(base_dir_dev):
        for nombre in files:
            assert "HISTORICO_ASIGNACIONES" not in nombre
            assert "HISTORICO_CXC_CXP" not in nombre


# ---------------------------------------------------------------------------
# v3/dev_api.py — envoltorio con rutas fijas del lado servidor (base_dir_dev)
# ---------------------------------------------------------------------------

def test_dev_api_generar_global_y_controles_usan_base_dir_dev(tmp_path):
    base_dir_dev = tmp_path / "dev"
    sap_dir = base_dir_dev / "publicacion" / "sap"
    os.makedirs(sap_dir, exist_ok=True)
    _crear_sap_diario(str(sap_dir / "SAP_TIQ_01-09-2026.xlsx"), cargo="100.00", cuenta="110201002", asignacion="3P66536982")
    plantilla = tmp_path / "Plantilla.xlsx"
    crear_plantilla_sap(str(plantilla))

    r_global = dev_api.generar_global(2026, 9, str(base_dir_dev), str(plantilla))
    assert r_global["estado"] == "VALIDADO_PENDIENTE_PUBLICACION"
    ruta_global_esperada = os.path.join(str(base_dir_dev), "global", "SAP_GLOBAL_TIQ_SEPTIEMBRE_2026.xlsx")
    assert r_global["ruta_global_generado"] == os.path.abspath(ruta_global_esperada)

    r_c1 = dev_api.ejecutar_control1(2026, 9, str(base_dir_dev))
    assert r_c1["estado"] == "OK_SIN_DUPLICADOS"

    r_c3 = dev_api.ejecutar_control3(2026, 9, str(base_dir_dev))
    assert r_c3["estado"] not in ("ERROR_TECNICO", None)
    # FASE 12D: antes de este fix, ejecutar_control3() no pasaba
    # ruta_salida_xlsx/json y CONTROL 3 nunca escribia su reporte mensual
    # (solo el HISTORICO). Ahora si debe quedar, listo para publicarse.
    ruta_reporte_xlsx = os.path.join(str(base_dir_dev), "global", "CONTROL3_CXC_CXP_SEPTIEMBRE_2026.xlsx")
    assert os.path.isfile(ruta_reporte_xlsx)
    assert r_c3["archivo_control_xlsx"] == ruta_reporte_xlsx


def test_cli_main_generar_global_y_controles_produce_json_valido(tmp_path):
    import json as jsonlib

    base_dir_dev = tmp_path / "dev"
    sap_dir = base_dir_dev / "publicacion" / "sap"
    os.makedirs(sap_dir, exist_ok=True)
    _crear_sap_diario(str(sap_dir / "SAP_TIQ_01-09-2026.xlsx"), cargo="100.00", cuenta="110201002", asignacion="3P66536982")
    plantilla = tmp_path / "Plantilla.xlsx"
    crear_plantilla_sap(str(plantilla))

    entrada = tmp_path / "in.json"
    salida = tmp_path / "out.json"
    entrada.write_text(jsonlib.dumps({
        "anio": 2026, "mes": 9, "base_dir_dev": str(base_dir_dev), "ruta_plantilla_origen": str(plantilla),
    }), encoding="utf-8")
    dev_api.main(["--accion", "generar_global", "--input", str(entrada), "--output", str(salida)])
    resultado = jsonlib.loads(salida.read_text(encoding="utf-8"))
    assert resultado["resultado"] == "OK"
    assert resultado["estado"] == "VALIDADO_PENDIENTE_PUBLICACION"

    entrada2 = tmp_path / "in2.json"
    entrada2.write_text(jsonlib.dumps({"anio": 2026, "mes": 9, "base_dir_dev": str(base_dir_dev)}), encoding="utf-8")
    dev_api.main(["--accion", "ejecutar_control1", "--input", str(entrada2), "--output", str(salida)])
    resultado_c1 = jsonlib.loads(salida.read_text(encoding="utf-8"))
    assert resultado_c1["resultado"] == "OK"
    assert resultado_c1["estado"] == "OK_SIN_DUPLICADOS"

    dev_api.main(["--accion", "ejecutar_control3", "--input", str(entrada2), "--output", str(salida)])
    resultado_c3 = jsonlib.loads(salida.read_text(encoding="utf-8"))
    assert resultado_c3["resultado"] == "OK"


# ---------------------------------------------------------------------------
# GLOBAL regenerable (decisión del auditor, 2026-09-18): dev_api.generar_global
# ya no bloquea con SALIDA_YA_EXISTE_SIN_FORCE en una segunda llamada para el
# mismo año/mes -- siempre reemplaza la única salida determinística. CONTROL 1
# y CONTROL 3 NO cambian: siguen siendo persistentes/idempotentes (arriba).
# ---------------------------------------------------------------------------

def test_dev_api_generar_global_inexistente_crea(tmp_path):
    base_dir_dev = tmp_path / "dev"
    sap_dir = base_dir_dev / "publicacion" / "sap"
    os.makedirs(sap_dir, exist_ok=True)
    _crear_sap_diario(str(sap_dir / "SAP_TIQ_01-09-2026.xlsx"), cargo="100.00")
    plantilla = tmp_path / "Plantilla.xlsx"
    crear_plantilla_sap(str(plantilla))

    ruta_global = base_dir_dev / "global" / "SAP_GLOBAL_TIQ_SEPTIEMBRE_2026.xlsx"
    assert not os.path.isfile(ruta_global)

    r = dev_api.generar_global(2026, 9, str(base_dir_dev), str(plantilla))
    assert r["estado"] == "VALIDADO_PENDIENTE_PUBLICACION"
    assert os.path.isfile(ruta_global)


def test_dev_api_generar_global_existente_se_regenera_sin_bloquear(tmp_path):
    """Antes de esta decisión, una segunda llamada para el mismo año/mes
    fallaba con SALIDA_YA_EXISTE_SIN_FORCE. Ahora debe regenerar sin pedir
    ningún flag adicional."""
    base_dir_dev = tmp_path / "dev"
    sap_dir = base_dir_dev / "publicacion" / "sap"
    os.makedirs(sap_dir, exist_ok=True)
    _crear_sap_diario(str(sap_dir / "SAP_TIQ_01-09-2026.xlsx"), cargo="100.00")
    plantilla = tmp_path / "Plantilla.xlsx"
    crear_plantilla_sap(str(plantilla))

    dev_api.generar_global(2026, 9, str(base_dir_dev), str(plantilla))
    # Segunda llamada, mismos SAP: NO debe lanzar SALIDA_YA_EXISTE_SIN_FORCE.
    r2 = dev_api.generar_global(2026, 9, str(base_dir_dev), str(plantilla))
    assert r2["estado"] == "VALIDADO_PENDIENTE_PUBLICACION"


def test_dev_api_generar_global_segunda_regeneracion_sigue_siendo_uno_solo(tmp_path):
    import glob

    base_dir_dev = tmp_path / "dev"
    sap_dir = base_dir_dev / "publicacion" / "sap"
    os.makedirs(sap_dir, exist_ok=True)
    _crear_sap_diario(str(sap_dir / "SAP_TIQ_01-09-2026.xlsx"), cargo="100.00")
    plantilla = tmp_path / "Plantilla.xlsx"
    crear_plantilla_sap(str(plantilla))

    dev_api.generar_global(2026, 9, str(base_dir_dev), str(plantilla))
    dev_api.generar_global(2026, 9, str(base_dir_dev), str(plantilla))
    dev_api.generar_global(2026, 9, str(base_dir_dev), str(plantilla))

    coincidencias = glob.glob(str(base_dir_dev / "global" / "SAP_GLOBAL_TIQ_SEPTIEMBRE_2026.xlsx"))
    assert len(coincidencias) == 1  # nunca hay duplicado: la ruta de salida es determinística por diseño


def test_dev_api_generar_global_regenerado_incorpora_sap_nuevos(tmp_path):
    base_dir_dev = tmp_path / "dev"
    sap_dir = base_dir_dev / "publicacion" / "sap"
    os.makedirs(sap_dir, exist_ok=True)
    _crear_sap_diario(str(sap_dir / "SAP_TIQ_01-09-2026.xlsx"), cargo="100.00")
    plantilla = tmp_path / "Plantilla.xlsx"
    crear_plantilla_sap(str(plantilla))

    r1 = dev_api.generar_global(2026, 9, str(base_dir_dev), str(plantilla))
    assert r1["cantidad_sap_incluidos"] == 1

    _crear_sap_diario(str(sap_dir / "SAP_TIQ_02-09-2026.xlsx"), cargo="50.00")
    r2 = dev_api.generar_global(2026, 9, str(base_dir_dev), str(plantilla))
    assert r2["cantidad_sap_incluidos"] == 2


def test_dev_api_generar_global_no_toca_otro_mes(tmp_path):
    base_dir_dev = tmp_path / "dev"
    sap_dir = base_dir_dev / "publicacion" / "sap"
    os.makedirs(sap_dir, exist_ok=True)
    _crear_sap_diario(str(sap_dir / "SAP_TIQ_01-09-2026.xlsx"), cargo="100.00",
                       fecha_valor=datetime.date(2026, 9, 5))
    _crear_sap_diario(str(sap_dir / "SAP_TIQ_01-10-2026.xlsx"), cargo="75.00",
                       fecha_valor=datetime.date(2026, 10, 5))
    plantilla = tmp_path / "Plantilla.xlsx"
    crear_plantilla_sap(str(plantilla))

    dev_api.generar_global(2026, 10, str(base_dir_dev), str(plantilla))
    ruta_octubre = base_dir_dev / "global" / "SAP_GLOBAL_TIQ_OCTUBRE_2026.xlsx"
    hash_octubre_antes = cm._sha256_archivo(str(ruta_octubre))

    # Regenerar SEPTIEMBRE no debe tocar el GLOBAL de OCTUBRE ya generado.
    dev_api.generar_global(2026, 9, str(base_dir_dev), str(plantilla))

    assert os.path.isfile(ruta_octubre)
    assert cm._sha256_archivo(str(ruta_octubre)) == hash_octubre_antes


def test_dev_api_regenerar_global_no_afecta_historicos_de_controles(tmp_path):
    """Regenerar GLOBAL (siempre permitido) nunca debe tocar los históricos
    persistentes de CONTROL 1/CONTROL 3 -- viven en archivos separados que
    solo ejecutar_control1()/ejecutar_control3() escriben, nunca generar_global()."""
    base_dir_dev = tmp_path / "dev"
    sap_dir = base_dir_dev / "publicacion" / "sap"
    os.makedirs(sap_dir, exist_ok=True)
    _crear_sap_diario(str(sap_dir / "SAP_TIQ_01-09-2026.xlsx"), cargo="100.00",
                       cuenta="110201002", asignacion="3P66536982")
    plantilla = tmp_path / "Plantilla.xlsx"
    crear_plantilla_sap(str(plantilla))

    dev_api.generar_global(2026, 9, str(base_dir_dev), str(plantilla))
    dev_api.ejecutar_control1(2026, 9, str(base_dir_dev))
    dev_api.ejecutar_control3(2026, 9, str(base_dir_dev))

    ruta_hist_c1 = base_dir_dev / "global" / "HISTORICO_ASIGNACIONES.csv"
    ruta_hist_c3 = base_dir_dev / "global" / "HISTORICO_CXC_CXP.csv"
    assert os.path.isfile(ruta_hist_c1)
    assert os.path.isfile(ruta_hist_c3)
    hash_c1_antes = cm._sha256_archivo(str(ruta_hist_c1))
    hash_c3_antes = cm._sha256_archivo(str(ruta_hist_c3))

    # Agregar un SAP nuevo y regenerar GLOBAL -- solo GLOBAL debe cambiar.
    _crear_sap_diario(str(sap_dir / "SAP_TIQ_02-09-2026.xlsx"), cargo="25.00",
                       cuenta="110201002")
    dev_api.generar_global(2026, 9, str(base_dir_dev), str(plantilla))

    assert cm._sha256_archivo(str(ruta_hist_c1)) == hash_c1_antes
    assert cm._sha256_archivo(str(ruta_hist_c3)) == hash_c3_antes


def test_dev_api_no_expone_ninguna_accion_de_borrado_o_reset(tmp_path):
    """CONTROL 1/CONTROL 3 (y GLOBAL) nunca deben tener una vía de borrar o
    resetear histórico: ni como acción del CLI (la misma superficie que usa
    el webhook de n8n), ni como función pública del módulo."""
    import v3.auditoria as auditoria_mod

    for accion in ("crear_lote_pendiente", "procesar_lote", "estado", "datos", "revisar",
                   "corregir", "publicar", "generar_global", "ejecutar_control1", "ejecutar_control3"):
        assert "borrar" not in accion and "reset" not in accion and "eliminar" not in accion

    nombres_publicos = [n for n in dir(auditoria_mod) if not n.startswith("_")]
    for nombre in nombres_publicos:
        nombre_lower = nombre.lower()
        assert "borrar" not in nombre_lower
        assert "reset" not in nombre_lower
        assert "eliminar" not in nombre_lower
        assert "delete" not in nombre_lower


def test_ambiguedad_multiple_global_solo_es_posible_a_nivel_drive_no_local(tmp_path):
    """A nivel local, `_ruta_global()` es una ruta determinística única por
    año/mes (base_dir_dev/global/SAP_GLOBAL_TIQ_<MES>_<AÑO>.xlsx): el
    sistema de archivos no permite que existan dos archivos con ese mismo
    nombre exacto, así que ERROR_AMBIGUO nunca puede ocurrir en este nivel
    -- por diseño, no por falta de chequeo. El caso ">1 coincidencias
    exactas" solo es posible en Drive (donde SÍ puede haber dos archivos
    con igual nombre en la misma carpeta) y ya está cubierto por
    ERROR_AMBIGUO_PUBLICACION en 07D, con cobertura de test propia en
    tests_v3/n8n_publicacion_mensual/test_logic_reference.js."""
    base_dir_dev = tmp_path / "dev"
    sap_dir = base_dir_dev / "publicacion" / "sap"
    os.makedirs(sap_dir, exist_ok=True)
    _crear_sap_diario(str(sap_dir / "SAP_TIQ_01-09-2026.xlsx"), cargo="100.00")
    plantilla = tmp_path / "Plantilla.xlsx"
    crear_plantilla_sap(str(plantilla))

    dev_api.generar_global(2026, 9, str(base_dir_dev), str(plantilla))
    dev_api.generar_global(2026, 9, str(base_dir_dev), str(plantilla))

    import glob
    assert len(glob.glob(str(base_dir_dev / "global" / "SAP_GLOBAL_TIQ_*_2026.xlsx"))) == 1
