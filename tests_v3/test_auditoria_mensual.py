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


def _materializar_control1(base_dir_dev, anio=2026, mes=9, historico_drive=None, revision_drive=None):
    """Simula lo que el backend hace desde Drive antes de CONTROL 1: deja el
    GLOBAL 'oficial' (aqui: copia del GLOBAL recien generado, que en
    produccion es la descarga de 05_CONTROLES/GLOBAL/) en
    control1_entrada/<periodo>/, junto con el historico/revision 'de Drive'
    si se indican (rutas de archivos fuente)."""
    import shutil as _sh
    base = str(base_dir_dev)
    dir_c1 = dev_api.preparar_control1_entrada(anio, mes, base)["dir_entrada"]
    nombre = cm.nombre_sap_global(anio, mes)
    _sh.copyfile(os.path.join(base, "global", nombre), os.path.join(dir_c1, nombre))
    if historico_drive:
        _sh.copyfile(str(historico_drive), os.path.join(dir_c1, "HISTORICO_ASIGNACIONES.csv"))
    if revision_drive:
        _sh.copyfile(str(revision_drive), os.path.join(dir_c1, os.path.basename(str(revision_drive))))
    return dir_c1


# ---------------------------------------------------------------------------
# v3/dev_api.py — envoltorio con rutas fijas del lado servidor (base_dir_dev)
# ---------------------------------------------------------------------------

def test_dev_api_generar_global_y_controles_usan_base_dir_dev(tmp_path):
    base_dir_dev = tmp_path / "dev"
    sap_dir = base_dir_dev / "global_entrada" / "2026-09"
    os.makedirs(sap_dir, exist_ok=True)
    _crear_sap_diario(str(sap_dir / "SAP_TIQ_01-09-2026.xlsx"), cargo="100.00", cuenta="110201002", asignacion="3P66536982")
    plantilla = tmp_path / "Plantilla.xlsx"
    crear_plantilla_sap(str(plantilla))

    r_global = dev_api.generar_global(2026, 9, str(base_dir_dev), str(plantilla))
    assert r_global["estado"] == "VALIDADO_PENDIENTE_PUBLICACION"
    ruta_global_esperada = os.path.join(str(base_dir_dev), "global", "SAP_GLOBAL_TIQ_SEPTIEMBRE_2026.xlsx")
    assert r_global["ruta_global_generado"] == os.path.abspath(ruta_global_esperada)

    _materializar_control1(base_dir_dev)
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
    sap_dir = base_dir_dev / "global_entrada" / "2026-09"
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
    _materializar_control1(base_dir_dev)
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
    sap_dir = base_dir_dev / "global_entrada" / "2026-09"
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
    sap_dir = base_dir_dev / "global_entrada" / "2026-09"
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
    sap_dir = base_dir_dev / "global_entrada" / "2026-09"
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
    sap_dir = base_dir_dev / "global_entrada" / "2026-09"
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
    sap_dir = base_dir_dev / "global_entrada" / "2026-09"
    sap_dir_oct = base_dir_dev / "global_entrada" / "2026-10"
    os.makedirs(sap_dir, exist_ok=True)
    os.makedirs(sap_dir_oct, exist_ok=True)
    _crear_sap_diario(str(sap_dir / "SAP_TIQ_01-09-2026.xlsx"), cargo="100.00",
                       fecha_valor=datetime.date(2026, 9, 5))
    _crear_sap_diario(str(sap_dir_oct / "SAP_TIQ_01-10-2026.xlsx"), cargo="75.00",
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
    sap_dir = base_dir_dev / "global_entrada" / "2026-09"
    os.makedirs(sap_dir, exist_ok=True)
    _crear_sap_diario(str(sap_dir / "SAP_TIQ_01-09-2026.xlsx"), cargo="100.00",
                       cuenta="110201002", asignacion="3P66536982")
    plantilla = tmp_path / "Plantilla.xlsx"
    crear_plantilla_sap(str(plantilla))

    dev_api.generar_global(2026, 9, str(base_dir_dev), str(plantilla))
    _materializar_control1(base_dir_dev)
    dev_api.ejecutar_control1(2026, 9, str(base_dir_dev))
    dev_api.ejecutar_control3(2026, 9, str(base_dir_dev))

    ruta_hist_c1 = base_dir_dev / "control1_entrada" / "2026-09" / "HISTORICO_ASIGNACIONES.csv"
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
    sap_dir = base_dir_dev / "global_entrada" / "2026-09"
    os.makedirs(sap_dir, exist_ok=True)
    _crear_sap_diario(str(sap_dir / "SAP_TIQ_01-09-2026.xlsx"), cargo="100.00")
    plantilla = tmp_path / "Plantilla.xlsx"
    crear_plantilla_sap(str(plantilla))

    dev_api.generar_global(2026, 9, str(base_dir_dev), str(plantilla))
    dev_api.generar_global(2026, 9, str(base_dir_dev), str(plantilla))

    import glob
    assert len(glob.glob(str(base_dir_dev / "global" / "SAP_GLOBAL_TIQ_*_2026.xlsx"))) == 1


# ---------------------------------------------------------------------------
# FASE 12E (2026-09-18) — GLOBAL debe consolidar TODO SAP diario válido de
# la carpeta SAP oficial del mes (legacy SAP_DD-MM-YYYY.xlsx y V3
# SAP_TIQ_DD-MM-YYYY.xlsx), no solo los que V3 generó/publicó. Fixtures con
# C10="SA" -- el valor REAL que escribe run_batch.py en todo SAP diario
# real (_TIPO_ASIENTO="SA") -- a propósito, para no repetir el mismo
# supuesto equivocado (C10="DB") que ya tenían los fixtures de arriba y que
# ocultó, hasta el primer GLOBAL real, que consolidador_mensual.py exige
# "DB" en la entrada.
# ---------------------------------------------------------------------------

from v3.auditoria import descubrir_sap_oficiales_del_mes  # noqa: E402


def _crear_sap_diario_real(ruta, cargo="100.00", cuenta="110101001", asignacion=None,
                            fecha_valor=datetime.date(2026, 9, 5)):
    """Igual que _crear_sap_diario, pero con C10="SA" (el valor real,
    confirmado leyendo SAP_TIQ_10-09-2026.xlsx en Drive), no "DB"."""
    _crear_sap_diario(ruta, cargo=cargo, cuenta=cuenta, asignacion=asignacion, fecha_valor=fecha_valor)
    wb = openpyxl.load_workbook(ruta)
    wb["1"]["C10"] = "SA"
    wb.save(ruta)


def test_descubrimiento_reconoce_legacy_sap_dd_mm_yyyy(tmp_path):
    sap_dir = tmp_path / "sap_oficial"
    sap_dir.mkdir()
    _crear_sap_diario_real(str(sap_dir / "SAP_01-09-2026.xlsx"))

    r = descubrir_sap_oficiales_del_mes(str(sap_dir), 2026, 9)
    assert [i["nombre"] for i in r["sap_incluidos"]] == ["SAP_01-09-2026.xlsx"]
    assert r["sap_incluidos"][0]["origen"] == "legacy"
    assert r["blockers"] == []


def test_descubrimiento_reconoce_sap_tiq_dd_mm_yyyy(tmp_path):
    sap_dir = tmp_path / "sap_oficial"
    sap_dir.mkdir()
    _crear_sap_diario_real(str(sap_dir / "SAP_TIQ_10-09-2026.xlsx"))

    r = descubrir_sap_oficiales_del_mes(str(sap_dir), 2026, 9)
    assert [i["nombre"] for i in r["sap_incluidos"]] == ["SAP_TIQ_10-09-2026.xlsx"]
    assert r["sap_incluidos"][0]["origen"] == "v3"


def test_descubrimiento_legacy_y_v3_en_fechas_distintas_ambos_incluidos(tmp_path):
    sap_dir = tmp_path / "sap_oficial"
    sap_dir.mkdir()
    _crear_sap_diario_real(str(sap_dir / "SAP_01-09-2026.xlsx"), fecha_valor=datetime.date(2026, 9, 1))
    _crear_sap_diario_real(str(sap_dir / "SAP_TIQ_10-09-2026.xlsx"), fecha_valor=datetime.date(2026, 9, 10))

    r = descubrir_sap_oficiales_del_mes(str(sap_dir), 2026, 9)
    nombres = sorted(i["nombre"] for i in r["sap_incluidos"])
    assert nombres == ["SAP_01-09-2026.xlsx", "SAP_TIQ_10-09-2026.xlsx"]
    assert len(r["archivos"]) == 2
    assert r["blockers"] == []


def test_sap_diario_real_c10_sa_es_aceptado_por_global(tmp_path):
    """Resuelto en FASE 12E.2: v3.consolidador_mensual_v3 acepta C10='SA'
    (el valor real de run_batch.py::_TIPO_ASIENTO) en la ENTRADA, sin
    tocar consolidador_mensual.py V2."""
    base_dir_dev = tmp_path / "dev"
    sap_dir = base_dir_dev / "global_entrada" / "2026-09"
    os.makedirs(sap_dir, exist_ok=True)
    _crear_sap_diario_real(str(sap_dir / "SAP_TIQ_10-09-2026.xlsx"), cuenta="110201002")
    plantilla = tmp_path / "Plantilla.xlsx"
    crear_plantilla_sap(str(plantilla))

    r = dev_api.generar_global(2026, 9, str(base_dir_dev), str(plantilla))
    assert r["estado"] == "VALIDADO_PENDIENTE_PUBLICACION", r.get("blockers")


def test_sap_diario_con_c10_inesperado_sigue_siendo_blocker(tmp_path):
    """C10/BLART con un valor que NO es 'SA' (ni el 'DB' que V2 exigía)
    debe seguir bloqueando con claridad -- V3 amplía la entrada válida,
    nunca la relaja a "cualquier cosa"."""
    base_dir_dev = tmp_path / "dev"
    sap_dir = base_dir_dev / "global_entrada" / "2026-09"
    os.makedirs(sap_dir, exist_ok=True)
    ruta = str(sap_dir / "SAP_TIQ_10-09-2026.xlsx")
    _crear_sap_diario_real(ruta, cuenta="110201002")
    wb = openpyxl.load_workbook(ruta)
    wb["1"]["C10"] = "XX"
    wb.save(ruta)
    plantilla = tmp_path / "Plantilla.xlsx"
    crear_plantilla_sap(str(plantilla))

    r = dev_api.generar_global(2026, 9, str(base_dir_dev), str(plantilla))
    assert r["estado"] == "ERROR_REVISAR"
    assert any("CABECERA_C10_ESPERADO_'SA'_OBTENIDO_'XX'" in b for b in r["blockers"])
    assert r["ruta_global_generado"] is None


def test_global_generado_usa_c10_db_en_la_salida(tmp_path):
    """La SALIDA de GLOBAL siempre debe llevar C10='DB'
    (_TIPO_ASIENTO_GLOBAL, sin cambios) -- esto es independiente de qué
    acepte como ENTRADA."""
    base_dir_dev = tmp_path / "dev"
    sap_dir = base_dir_dev / "global_entrada" / "2026-09"
    os.makedirs(sap_dir, exist_ok=True)
    _crear_sap_diario_real(str(sap_dir / "SAP_TIQ_10-09-2026.xlsx"), cuenta="110201002")
    plantilla = tmp_path / "Plantilla.xlsx"
    crear_plantilla_sap(str(plantilla))

    r = dev_api.generar_global(2026, 9, str(base_dir_dev), str(plantilla))
    assert r["estado"] == "VALIDADO_PENDIENTE_PUBLICACION"
    wb = openpyxl.load_workbook(r["ruta_global_generado"], data_only=True)
    assert wb["1"]["C10"].value == "DB"


def test_descubrimiento_ignora_sap_global_existente(tmp_path):
    sap_dir = tmp_path / "sap_oficial"
    sap_dir.mkdir()
    _crear_sap_diario_real(str(sap_dir / "SAP_TIQ_01-09-2026.xlsx"))
    # Un SAP_GLOBAL_* en la misma carpeta (p.ej. de una corrida anterior)
    # nunca debe tratarse como si fuera un SAP diario más.
    (sap_dir / "SAP_GLOBAL_TIQ_SEPTIEMBRE_2026.xlsx").write_bytes(b"contenido cualquiera")

    r = descubrir_sap_oficiales_del_mes(str(sap_dir), 2026, 9)
    assert [i["nombre"] for i in r["sap_incluidos"]] == ["SAP_TIQ_01-09-2026.xlsx"]


def test_descubrimiento_excluye_otro_mes(tmp_path):
    sap_dir = tmp_path / "sap_oficial"
    sap_dir.mkdir()
    _crear_sap_diario_real(str(sap_dir / "SAP_TIQ_01-09-2026.xlsx"), fecha_valor=datetime.date(2026, 9, 1))
    _crear_sap_diario_real(str(sap_dir / "SAP_TIQ_01-10-2026.xlsx"), fecha_valor=datetime.date(2026, 10, 1))

    r = descubrir_sap_oficiales_del_mes(str(sap_dir), 2026, 9)
    assert [i["nombre"] for i in r["sap_incluidos"]] == ["SAP_TIQ_01-09-2026.xlsx"]


def test_descubrimiento_excluye_otro_anio(tmp_path):
    sap_dir = tmp_path / "sap_oficial"
    sap_dir.mkdir()
    _crear_sap_diario_real(str(sap_dir / "SAP_TIQ_01-09-2026.xlsx"), fecha_valor=datetime.date(2026, 9, 1))
    _crear_sap_diario_real(str(sap_dir / "SAP_TIQ_01-09-2027.xlsx"), fecha_valor=datetime.date(2027, 9, 1))

    r = descubrir_sap_oficiales_del_mes(str(sap_dir), 2026, 9)
    assert [i["nombre"] for i in r["sap_incluidos"]] == ["SAP_TIQ_01-09-2026.xlsx"]


def test_descubrimiento_excluye_nombre_invalido(tmp_path):
    sap_dir = tmp_path / "sap_oficial"
    sap_dir.mkdir()
    _crear_sap_diario_real(str(sap_dir / "SAP_TIQ_01-09-2026.xlsx"))
    (sap_dir / "notas.txt").write_text("no es un SAP")
    (sap_dir / "RESULTADO_TIQ_01-09-2026.json").write_text("{}")
    (sap_dir / "SAP_TIQ_01-09-2026.xlsx.tmp").write_bytes(b"temporal")
    (sap_dir / "~$SAP_TIQ_01-09-2026.xlsx").write_bytes(b"lock de excel")

    r = descubrir_sap_oficiales_del_mes(str(sap_dir), 2026, 9)
    assert [i["nombre"] for i in r["sap_incluidos"]] == ["SAP_TIQ_01-09-2026.xlsx"]


def test_descubrimiento_misma_fecha_dos_nombres_contenido_identico_no_duplica(tmp_path):
    sap_dir = tmp_path / "sap_oficial"
    sap_dir.mkdir()
    _crear_sap_diario_real(str(sap_dir / "SAP_10-09-2026.xlsx"), fecha_valor=datetime.date(2026, 9, 10))
    # Copia byte-identica con el nombre V3 (mismo escenario que el retry
    # local visto en 06B: mismo contenido, dos nombres para el mismo dia).
    import shutil as _shutil
    _shutil.copyfile(str(sap_dir / "SAP_10-09-2026.xlsx"), str(sap_dir / "SAP_TIQ_10-09-2026.xlsx"))

    r = descubrir_sap_oficiales_del_mes(str(sap_dir), 2026, 9)
    assert len(r["archivos"]) == 1  # nunca doble conteo
    assert r["sap_incluidos"][0]["nombre"] == "SAP_TIQ_10-09-2026.xlsx"  # se prefiere el nombre V3
    assert r["sap_incluidos"][0]["origen"] == "v3"
    assert len(r["duplicados_identicos_omitidos"]) == 1
    assert r["duplicados_identicos_omitidos"][0]["nombre_omitido"] == "SAP_10-09-2026.xlsx"
    assert r["blockers"] == []


def test_descubrimiento_misma_fecha_contenido_distinto_es_blocker_ambiguo(tmp_path):
    sap_dir = tmp_path / "sap_oficial"
    sap_dir.mkdir()
    _crear_sap_diario_real(str(sap_dir / "SAP_10-09-2026.xlsx"), cargo="100.00", fecha_valor=datetime.date(2026, 9, 10))
    _crear_sap_diario_real(str(sap_dir / "SAP_TIQ_10-09-2026.xlsx"), cargo="999.00", fecha_valor=datetime.date(2026, 9, 10))

    r = descubrir_sap_oficiales_del_mes(str(sap_dir), 2026, 9)
    assert r["archivos"] == []  # ninguno se elige arbitrariamente
    assert len(r["blockers"]) == 1
    assert r["blockers"][0].startswith("DUPLICADO_FECHA_AMBIGUA:2026-09-10:")
    assert "SAP_10-09-2026.xlsx" in r["blockers"][0]
    assert "SAP_TIQ_10-09-2026.xlsx" in r["blockers"][0]


def test_global_mensual_propaga_blocker_de_ambiguedad_de_fecha(tmp_path):
    """El blocker de ambigüedad de fecha debe llegar hasta el resultado
    final de generar_global_mensual y forzar ERROR_REVISAR -- nunca se
    resuelve la ambigüedad eligiendo un archivo por su cuenta."""
    base_dir_dev = tmp_path / "dev"
    sap_dir = base_dir_dev / "global_entrada" / "2026-09"
    os.makedirs(sap_dir, exist_ok=True)
    _crear_sap_diario_real(str(sap_dir / "SAP_10-09-2026.xlsx"), cargo="100.00", fecha_valor=datetime.date(2026, 9, 10))
    _crear_sap_diario_real(str(sap_dir / "SAP_TIQ_10-09-2026.xlsx"), cargo="999.00", fecha_valor=datetime.date(2026, 9, 10))
    plantilla = tmp_path / "Plantilla.xlsx"
    crear_plantilla_sap(str(plantilla))

    r = dev_api.generar_global(2026, 9, str(base_dir_dev), str(plantilla))
    assert r["estado"] == "ERROR_REVISAR"
    assert any(b.startswith("DUPLICADO_FECHA_AMBIGUA:2026-09-10:") for b in r["blockers"])
    assert r["ruta_global_generado"] is None


def test_fechas_faltantes_son_informativas_no_bloquean_global(tmp_path):
    """Con un único SAP real del mes (C10='SA'), GLOBAL sigue bloqueado
    hoy por el mismo blocker C10 (ver test_sap_diario_real_c10_sa_es_...);
    lo que este test aísla y prueba es que, aunque eso NO estuviera
    bloqueado, `fechas_faltantes` nunca aparece en `blockers` ni afecta
    `estado` -- se prueba directamente sobre `descubrir_sap_oficiales_del_mes`
    + el cálculo de fechas_faltantes que hace generar_global_mensual,
    usando un SAP con C10='DB' (fixture antiguo, aceptado hoy por V2) para
    no mezclar los dos problemas en un mismo test."""
    sap_dir = tmp_path / "sap_diarios"
    sap_dir.mkdir()
    _crear_sap_diario(str(sap_dir / "SAP_TIQ_01-09-2026.xlsx"), cargo="100.00")
    plantilla = tmp_path / "Plantilla.xlsx"
    crear_plantilla_sap(str(plantilla))
    salida = tmp_path / "SAP_GLOBAL_TIQ_SEPTIEMBRE_2026.xlsx"

    r = generar_global_mensual(2026, 9, str(sap_dir), str(plantilla), str(salida))

    assert r["estado"] == "VALIDADO_PENDIENTE_PUBLICACION"
    assert "fechas_faltantes" in r
    assert len(r["fechas_faltantes"]) == 29  # septiembre tiene 30 dias, 1 presente
    assert not any("fecha" in b.lower() for b in r["blockers"])


def test_v2_consolidador_mensual_no_fue_modificado_por_fase_12e():
    """Guardarraíl de regresión: FASE 12E deliberadamente NO toca
    consolidador_mensual.py (V2, congelado) -- toda la lógica nueva de
    descubrimiento/dedup vive en v3.auditoria/v3.consolidador_mensual_v3.
    Verifica que las constantes y funciones de V2 relevantes a este cambio
    siguen exactamente igual, incluido después de FASE 12E.2 (C10)."""
    assert cm._CABECERA_ESPERADA == {"B": "BO01", "C": "DB", "H": "BOB", "L": "CAJA TIQUIPAYA"}
    assert cm._TIPO_ASIENTO_GLOBAL == "DB"
    assert cm._RE_SAP_DIARIO.pattern == r"^SAP_TIQ_(\d{2})-(\d{2})-(\d{4})\.xlsx$"


# ---------------------------------------------------------------------------
# FASE 12E.2 (2026-09-18) — resolución del bloqueador C10/BLART EXCLUSIVAMENTE
# en V3 (v3/consolidador_mensual_v3.py), sin tocar consolidador_mensual.py,
# sin monkeypatch, sin mutar constantes en runtime, sin adulterar SAP
# diarios. Decisión del auditor: entrada acepta C10="SA" (run_batch.py,
# real); salida de GLOBAL sigue en C10="DB" (sin cambios).
# ---------------------------------------------------------------------------

def test_v2_mensaje_cabecera_c10_no_cambio_de_formato(tmp_path):
    """Guardarraíl explícito del que depende
    v3.consolidador_mensual_v3._reinterpretar_problemas_entrada_v3(): si
    V2 alguna vez cambia el formato exacto de este mensaje, este test
    falla en rojo -- señal de que el regex de reinterpretación necesita
    revisión, en vez de dejar de filtrar en silencio."""
    ruta = str(tmp_path / "SAP_TIQ_10-09-2026.xlsx")
    _crear_sap_diario_real(ruta)
    resultado = cm.leer_y_validar_sap_diario(ruta)
    assert resultado["problemas"] == ["CABECERA_C10_ESPERADO_'DB'_OBTENIDO_'SA'"]


def test_nueve_sap_reales_legacy_y_v3_consolidan_global_valido(tmp_path):
    """Reproduce exactamente el universo real de septiembre 2026 detectado
    en Drive (8 legacy + 1 V3, fechas 01-05,07-09,10, sin el 06): con el
    fix de C10, GLOBAL debe consolidar los 9 sin bloquear."""
    base_dir_dev = tmp_path / "dev"
    sap_dir = base_dir_dev / "global_entrada" / "2026-09"
    os.makedirs(sap_dir, exist_ok=True)

    dias_legacy = [1, 2, 3, 4, 5, 7, 8, 9]
    for dia in dias_legacy:
        _crear_sap_diario_real(
            str(sap_dir / f"SAP_{dia:02d}-09-2026.xlsx"),
            cargo="100.00", cuenta="110201002",
            fecha_valor=datetime.date(2026, 9, dia),
        )
    _crear_sap_diario_real(
        str(sap_dir / "SAP_TIQ_10-09-2026.xlsx"),
        cargo="100.00", cuenta="110201002", fecha_valor=datetime.date(2026, 9, 10),
    )
    plantilla = tmp_path / "Plantilla.xlsx"
    crear_plantilla_sap(str(plantilla))

    r = dev_api.generar_global(2026, 9, str(base_dir_dev), str(plantilla))

    assert r["estado"] == "VALIDADO_PENDIENTE_PUBLICACION", r.get("blockers")
    assert r["cantidad_sap_incluidos"] == 9
    assert sorted(r["sap_incluidos"]) == sorted(
        [f"SAP_{dia:02d}-09-2026.xlsx" for dia in dias_legacy] + ["SAP_TIQ_10-09-2026.xlsx"]
    )
    assert r["ruta_global_generado"] is not None
    # 06/09 es la única fecha del mes con SAP real ausente entre las
    # detectadas -- las demas (11..30) tambien faltan pero son informativas.
    assert "2026-09-06" in r["fechas_faltantes"]
    assert len(r["fechas_faltantes"]) == 21  # 30 dias - 9 con SAP

    wb = openpyxl.load_workbook(r["ruta_global_generado"], data_only=True)
    assert wb["1"]["C10"].value == "DB"


# ---------------------------------------------------------------------------
# FASE 12E.3 (2026-09-18) — la fuente de GLOBAL es EXCLUSIVAMENTE un snapshot
# de la carpeta SAP oficial de Drive materializado en
# dev_workdir/global_entrada/<YYYY-MM>/. publicacion/sap/ (artefactos locales
# del flujo diario, con residuos DEV) NUNCA se usa como entrada. Caso real que
# lo motivó: GLOBAL de septiembre tomó solo 2 SAP (10/09 oficial + un
# SAP_11-09-2026.xlsx residual de pruebas DEV) y omitió 8 SAP legacy oficiales.
# ---------------------------------------------------------------------------

_DIAS_LEGACY_SEP_2026 = [1, 2, 3, 4, 5, 7, 8, 9]


def _sandbox_septiembre_drive(tmp_path, extra_11_oficial=False):
    """Simula lo que el backend materializa desde Drive: 8 SAP legacy + el
    SAP_TIQ del 10/09 en global_entrada/2026-09/ (C10='SA', como los reales),
    y, APARTE, un residuo local DEV SAP_11-09-2026.xlsx en publicacion/sap/."""
    base_dir_dev = tmp_path / "dev"
    entrada = base_dir_dev / "global_entrada" / "2026-09"
    pub_local = base_dir_dev / "publicacion" / "sap"
    os.makedirs(entrada, exist_ok=True)
    os.makedirs(pub_local, exist_ok=True)
    for dia in _DIAS_LEGACY_SEP_2026:
        _crear_sap_diario_real(str(entrada / f"SAP_{dia:02d}-09-2026.xlsx"), cargo="100.00",
                                cuenta="110201002", fecha_valor=datetime.date(2026, 9, dia))
    _crear_sap_diario_real(str(entrada / "SAP_TIQ_10-09-2026.xlsx"), cargo="100.00",
                            cuenta="110201002", fecha_valor=datetime.date(2026, 9, 10))
    _crear_sap_diario_real(str(pub_local / "SAP_11-09-2026.xlsx"), cargo="555.00",
                            cuenta="110201002", fecha_valor=datetime.date(2026, 9, 11))
    _crear_sap_diario_real(str(pub_local / "SAP_TIQ_10-09-2026.xlsx"), cargo="100.00",
                            cuenta="110201002", fecha_valor=datetime.date(2026, 9, 10))
    if extra_11_oficial:
        _crear_sap_diario_real(str(entrada / "SAP_TIQ_11-09-2026.xlsx"), cargo="100.00",
                                cuenta="110201002", fecha_valor=datetime.date(2026, 9, 11))
    plantilla = tmp_path / "Plantilla.xlsx"
    crear_plantilla_sap(str(plantilla))
    return base_dir_dev, entrada, pub_local, plantilla


def test_caso_a_drive_9_sap_mas_residuo_local_11_incluye_solo_los_9(tmp_path):
    base_dir_dev, _entrada, _pub, plantilla = _sandbox_septiembre_drive(tmp_path)
    r = dev_api.generar_global(2026, 9, str(base_dir_dev), str(plantilla))
    assert r["estado"] == "VALIDADO_PENDIENTE_PUBLICACION", r.get("blockers")
    assert r["cantidad_sap_incluidos"] == 9
    assert "SAP_11-09-2026.xlsx" not in r["sap_incluidos"]
    fechas = sorted(i["fecha"] for i in r["sap_incluidos_detalle"])
    assert fechas == ["2026-09-01", "2026-09-02", "2026-09-03", "2026-09-04", "2026-09-05",
                      "2026-09-07", "2026-09-08", "2026-09-09", "2026-09-10"]
    assert r["cargo_global"] == "900.00"  # 9 x 100.00; el residuo (555.00) NO suma
    wb = openpyxl.load_workbook(r["ruta_global_generado"], data_only=True)
    assert wb["1"]["C10"].value == "DB"


def test_caso_b_nuevo_sap_oficial_11_en_drive_regenera_con_10(tmp_path):
    base_dir_dev, entrada, _pub, plantilla = _sandbox_septiembre_drive(tmp_path)
    r1 = dev_api.generar_global(2026, 9, str(base_dir_dev), str(plantilla))
    assert r1["cantidad_sap_incluidos"] == 9

    _crear_sap_diario_real(str(entrada / "SAP_TIQ_11-09-2026.xlsx"), cargo="100.00",
                            cuenta="110201002", fecha_valor=datetime.date(2026, 9, 11))
    r2 = dev_api.generar_global(2026, 9, str(base_dir_dev), str(plantilla))
    assert r2["cantidad_sap_incluidos"] == 10
    assert "SAP_TIQ_11-09-2026.xlsx" in r2["sap_incluidos"]


def test_caso_c_archivos_locales_no_oficiales_se_ignoran(tmp_path):
    base_dir_dev, entrada, pub_local, plantilla = _sandbox_septiembre_drive(tmp_path)
    (entrada / "notas_locales.txt").write_text("no oficial")
    (entrada / "SAP_GLOBAL_TIQ_SEPTIEMBRE_2026.xlsx").write_bytes(b"global viejo")
    (entrada / "SAP_TIQ_01-08-2026.xlsx").write_bytes(b"otro mes")
    _crear_sap_diario_real(str(pub_local / "SAP_12-09-2026.xlsx"), fecha_valor=datetime.date(2026, 9, 12))

    r = dev_api.generar_global(2026, 9, str(base_dir_dev), str(plantilla))
    assert r["estado"] == "VALIDADO_PENDIENTE_PUBLICACION", r.get("blockers")
    assert r["cantidad_sap_incluidos"] == 9


def test_caso_d_dos_sap_distintos_misma_fecha_en_drive_es_ambiguo(tmp_path):
    base_dir_dev, entrada, _pub, plantilla = _sandbox_septiembre_drive(tmp_path)
    _crear_sap_diario_real(str(entrada / "SAP_10-09-2026.xlsx"), cargo="999.00",
                            cuenta="110201002", fecha_valor=datetime.date(2026, 9, 10))
    r = dev_api.generar_global(2026, 9, str(base_dir_dev), str(plantilla))
    assert r["estado"] == "ERROR_REVISAR"
    assert any(b.startswith("DUPLICADO_FECHA_AMBIGUA:2026-09-10:") for b in r["blockers"])
    assert r["ruta_global_generado"] is None


def test_caso_e_global_previo_existente_se_actualiza_sin_duplicar(tmp_path):
    import glob
    base_dir_dev, entrada, _pub, plantilla = _sandbox_septiembre_drive(tmp_path)
    dev_api.generar_global(2026, 9, str(base_dir_dev), str(plantilla))
    _crear_sap_diario_real(str(entrada / "SAP_TIQ_11-09-2026.xlsx"), cargo="100.00",
                            cuenta="110201002", fecha_valor=datetime.date(2026, 9, 11))
    r = dev_api.generar_global(2026, 9, str(base_dir_dev), str(plantilla))
    assert r["cantidad_sap_incluidos"] == 10
    assert len(glob.glob(str(base_dir_dev / "global" / "SAP_GLOBAL_TIQ_SEPTIEMBRE_2026.xlsx"))) == 1
    assert len(glob.glob(str(base_dir_dev / "global" / "RESULTADO_GLOBAL_TIQ_SEPTIEMBRE_2026.json"))) == 1


def test_caso_f_legacy_y_v3_en_fechas_distintas_ambos_validos(tmp_path):
    base_dir_dev, _entrada, _pub, plantilla = _sandbox_septiembre_drive(tmp_path)
    r = dev_api.generar_global(2026, 9, str(base_dir_dev), str(plantilla))
    origenes = {i["nombre"]: i["origen"] for i in r["sap_incluidos_detalle"]}
    assert origenes["SAP_01-09-2026.xlsx"] == "legacy"
    assert origenes["SAP_TIQ_10-09-2026.xlsx"] == "v3"


def test_fechas_faltantes_de_septiembre_con_9_sap_son_informativas(tmp_path):
    base_dir_dev, _entrada, _pub, plantilla = _sandbox_septiembre_drive(tmp_path)
    r = dev_api.generar_global(2026, 9, str(base_dir_dev), str(plantilla))
    assert r["estado"] == "VALIDADO_PENDIENTE_PUBLICACION"
    assert len(r["fechas_faltantes"]) == 21 and "2026-09-06" in r["fechas_faltantes"]
    assert not any("fecha" in b.lower() for b in r["blockers"])


def test_global_nunca_usa_publicacion_sap_como_entrada(tmp_path):
    """Con global_entrada vacía y SAP válidos SOLO en publicacion/sap, GLOBAL
    no los toma: bloquea con SIN_SAP_PARA_CONSOLIDAR."""
    base_dir_dev, entrada, pub_local, plantilla = _sandbox_septiembre_drive(tmp_path)
    for f in entrada.iterdir():
        f.unlink()
    r = dev_api.generar_global(2026, 9, str(base_dir_dev), str(plantilla))
    assert r["estado"] == "ERROR_REVISAR"
    assert "SIN_SAP_PARA_CONSOLIDAR" in r["blockers"]
    assert r["cantidad_sap_incluidos"] == 0


def test_generar_global_sin_materializacion_falla_claro(tmp_path):
    base_dir_dev = tmp_path / "dev"
    os.makedirs(base_dir_dev / "publicacion" / "sap", exist_ok=True)
    _crear_sap_diario_real(str(base_dir_dev / "publicacion" / "sap" / "SAP_TIQ_10-09-2026.xlsx"))
    plantilla = tmp_path / "Plantilla.xlsx"
    crear_plantilla_sap(str(plantilla))
    with pytest.raises(RuntimeError, match="GLOBAL_ENTRADA_NO_MATERIALIZADA"):
        dev_api.generar_global(2026, 9, str(base_dir_dev), str(plantilla))


def test_preparar_global_entrada_limpia_solo_el_periodo(tmp_path):
    base_dir_dev, entrada, pub_local, _plantilla = _sandbox_septiembre_drive(tmp_path)
    otro_periodo = base_dir_dev / "global_entrada" / "2026-10"
    os.makedirs(otro_periodo)
    (otro_periodo / "SAP_TIQ_01-10-2026.xlsx").write_bytes(b"octubre")
    otro_tmp = base_dir_dev / "otro_temporal.txt"
    otro_tmp.write_text("no tocar")
    residuos_pub = sorted(os.listdir(pub_local))

    r = dev_api.preparar_global_entrada(2026, 9, str(base_dir_dev))

    assert r["periodo"] == "2026-09"
    assert os.path.isdir(entrada) and os.listdir(entrada) == []
    assert sorted(os.listdir(pub_local)) == residuos_pub              # publicacion/sap intacto
    assert os.listdir(otro_periodo) == ["SAP_TIQ_01-10-2026.xlsx"]    # otro periodo intacto
    assert otro_tmp.read_text() == "no tocar"


def test_preparar_global_entrada_crea_si_no_existe_y_valida_periodo(tmp_path):
    base_dir_dev = tmp_path / "dev"
    os.makedirs(base_dir_dev)
    r = dev_api.preparar_global_entrada(2026, 9, str(base_dir_dev))
    assert os.path.isdir(r["dir_entrada"])
    for anio, mes in ((2026, 13), (2026, 0), ("2026", 9), (1999, 9), (True, 9)):
        with pytest.raises(ValueError, match="PERIODO_INVALIDO"):
            dev_api.preparar_global_entrada(anio, mes, str(base_dir_dev))


def test_cli_preparar_global_entrada_y_generar_global(tmp_path):
    import json as jsonlib
    base_dir_dev, entrada, _pub, plantilla = _sandbox_septiembre_drive(tmp_path)
    salida = tmp_path / "out.json"
    entrada_json = tmp_path / "in.json"
    entrada_json.write_text(jsonlib.dumps({"anio": 2026, "mes": 9, "base_dir_dev": str(base_dir_dev)}))
    dev_api.main(["--accion", "preparar_global_entrada", "--input", str(entrada_json), "--output", str(salida)])
    r = jsonlib.loads(salida.read_text(encoding="utf-8"))
    assert r["resultado"] == "OK" and os.listdir(entrada) == []
    assert '"resultado": "OK"' in salida.read_text(encoding="utf-8")  # el nodo n8n lo verifica con grep -q


# ---------------------------------------------------------------------------
# FASE 12E.4 (2026-09-18) — AUDITORIA DE ASIGNACIONES (CONTROL 1): Drive oficial
# = fuente de verdad; local = materializacion temporal de la corrida en
# dev_workdir/control1_entrada/<YYYY-MM>/. Estos tests simulan con archivos
# locales lo que el backend descarga de Drive (nunca escriben en Drive).
# ---------------------------------------------------------------------------

import csv as _csv
import shutil as _shutil

_NOMBRE_GLOBAL_SEP = "SAP_GLOBAL_TIQ_SEPTIEMBRE_2026.xlsx"
_NOMBRE_REVISION_SEP = "REVISION_ASIGNACIONES_SEPTIEMBRE_2026.xlsx"


def _crear_global_con_filas(ruta, asignaciones, cuenta="110201002", cargo=100):
    """GLOBAL minimo con una partida por asignacion (fila 16 en adelante)."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "1"
    for i, asig in enumerate(asignaciones):
        fila = 16 + i
        ws[f"B{fila}"] = "BO01"
        ws[f"C{fila}"] = cuenta
        ws[f"D{fila}"] = f"GLOSA {i}"
        ws[f"E{fila}"] = cargo
        ws[f"O{fila}"] = "2026-09-01"
        ws[f"R{fila}"] = asig
    wb.save(ruta)


def _base_control1(tmp_path):
    base = tmp_path / "dev"
    os.makedirs(base / "global", exist_ok=True)
    return base


def _materializar_desde_drive(base, global_src, historico_src=None, revision_src=None):
    """Lo que hace el backend: limpiar control1_entrada/<periodo> y dejar ahi lo
    descargado de 'Drive' (los *_src son los archivos que estarian en Drive)."""
    dir_c1 = dev_api.preparar_control1_entrada(2026, 9, str(base))["dir_entrada"]
    _shutil.copyfile(str(global_src), os.path.join(dir_c1, _NOMBRE_GLOBAL_SEP))
    if historico_src:
        _shutil.copyfile(str(historico_src), os.path.join(dir_c1, "HISTORICO_ASIGNACIONES.csv"))
    if revision_src:
        _shutil.copyfile(str(revision_src), os.path.join(dir_c1, _NOMBRE_REVISION_SEP))
    return dir_c1


def _filas_csv(ruta):
    with open(ruta, encoding="utf-8", newline="") as f:
        return list(_csv.DictReader(f))


def _decidir_revision(ruta_xlsx, decisiones):
    """Simula al auditor editando el Excel de revision: {FILA_GLOBAL: (validacion, asignacion_correcta)}."""
    wb = openpyxl.load_workbook(ruta_xlsx)
    ws = wb["REVISION"]
    cab = {c.value: c.column for c in ws[1]}
    for fila in range(2, ws.max_row + 1):
        fg = ws.cell(row=fila, column=cab["FILA_GLOBAL"]).value
        if fg in decisiones:
            val, corr = decisiones[fg]
            ws.cell(row=fila, column=cab["VALIDACION_AUDITOR"]).value = val
            if corr:
                ws.cell(row=fila, column=cab["ASIGNACION_CORRECTA"]).value = corr
    wb.save(ruta_xlsx)


def test_control1_sin_materializacion_falla_claro_no_usa_global_local(tmp_path):
    base = _base_control1(tmp_path)
    _crear_global_con_filas(str(base / "global" / _NOMBRE_GLOBAL_SEP), ["A1"])  # GLOBAL local residual
    with pytest.raises(RuntimeError, match="CONTROL1_ENTRADA_NO_MATERIALIZADA"):
        dev_api.ejecutar_control1(2026, 9, str(base))
    dev_api.preparar_control1_entrada(2026, 9, str(base))  # dir existe pero sin GLOBAL oficial
    with pytest.raises(RuntimeError, match="GLOBAL_OFICIAL_NO_MATERIALIZADO"):
        dev_api.ejecutar_control1(2026, 9, str(base))


def test_control1_ignora_global_historico_y_revision_locales_residuales(tmp_path):
    """B/F/J: solo cuenta lo materializado en control1_entrada; los residuos de
    dev_workdir/global/ (GLOBAL distinto, historico viejo, revision vieja) no influyen."""
    base = _base_control1(tmp_path)
    # Residuos locales: GLOBAL con duplicado, historico viejo con la asignacion, revision vieja.
    _crear_global_con_filas(str(base / "global" / _NOMBRE_GLOBAL_SEP), ["DUP", "DUP"])
    with open(base / "global" / "HISTORICO_ASIGNACIONES.csv", "w", encoding="utf-8") as f:
        f.write("asignacion,fecha_valor,cuenta_mayor,glosa,monto,archivo_global,fila_sap,sha256_archivo,fecha_incorporacion\nUNICA,2026-08-01,110201002,x,1,SAP_GLOBAL_TIQ_AGOSTO_2026.xlsx,16,zz,2026-08-31\n")
    (base / "global" / _NOMBRE_REVISION_SEP).write_bytes(b"revision local vieja")
    # "Drive": GLOBAL distinto y limpio (una asignacion unica).
    drive_global = tmp_path / "drive_global.xlsx"
    _crear_global_con_filas(str(drive_global), ["UNICA"])
    _materializar_desde_drive(base, drive_global)

    r = dev_api.ejecutar_control1(2026, 9, str(base))
    # Si hubiera usado los residuos: GLOBAL local (DUP x2) y/o historico viejo (UNICA) => alertas.
    assert r["estado"] == "OK_SIN_DUPLICADOS", r
    assert r["ruta_global_materializado"].endswith("control1_entrada/2026-09/" + _NOMBRE_GLOBAL_SEP)
    assert r["filas_historico_totales"] if "filas_historico_totales" in r else True
    filas = _filas_csv(base / "control1_entrada" / "2026-09" / "HISTORICO_ASIGNACIONES.csv")
    assert [f["asignacion"] for f in filas] == ["UNICA"]  # historico local viejo NO se mezcló
    # Los residuos locales quedan intactos (no se leen ni se escriben).
    assert (base / "global" / _NOMBRE_REVISION_SEP).read_bytes() == b"revision local vieja"


def test_control1_primera_ejecucion_sin_historico_en_drive_empieza_vacio(tmp_path):
    """G: solo cuando el historico NO existe en Drive (no se materializa) arranca vacio."""
    base = _base_control1(tmp_path)
    drive_global = tmp_path / "drive_global.xlsx"
    _crear_global_con_filas(str(drive_global), ["A1", "B2"])
    dir_c1 = _materializar_desde_drive(base, drive_global)
    assert not os.path.exists(os.path.join(dir_c1, "HISTORICO_ASIGNACIONES.csv"))
    r = dev_api.ejecutar_control1(2026, 9, str(base))
    assert r["estado"] == "OK_SIN_DUPLICADOS" and r["historico_actualizado"] is True
    assert len(_filas_csv(os.path.join(dir_c1, "HISTORICO_ASIGNACIONES.csv"))) == 2


def test_control1_historico_de_drive_se_usa_y_no_se_pierde(tmp_path):
    """E/N: el historico materializado desde Drive detecta alertas contra periodos previos
    y sus filas previas se conservan al agregar el periodo nuevo."""
    base = _base_control1(tmp_path)
    hist = tmp_path / "hist_drive.csv"
    with open(hist, "w", encoding="utf-8") as f:
        f.write("asignacion,fecha_valor,cuenta_mayor,glosa,monto,archivo_global,fila_sap,sha256_archivo,fecha_incorporacion\nPREVIA,2026-08-01,110201002,x,1,SAP_GLOBAL_TIQ_AGOSTO_2026.xlsx,16,zz,2026-08-31\n")
    drive_global = tmp_path / "drive_global.xlsx"
    _crear_global_con_filas(str(drive_global), ["PREVIA", "NUEVA"])
    dir_c1 = _materializar_desde_drive(base, drive_global, historico_src=hist)

    r = dev_api.ejecutar_control1(2026, 9, str(base))
    assert r["estado"] == "REVISAR_DUPLICADOS_ENCONTRADOS"      # PREVIA choca con el historico de Drive
    assert r["alertas_contra_historico"] == 1
    assert r["historico_actualizado"] is False                  # pendiente: el historico NO se toca todavia
    assert [f["asignacion"] for f in _filas_csv(os.path.join(dir_c1, "HISTORICO_ASIGNACIONES.csv"))] == ["PREVIA"]


def test_control1_revision_de_drive_preserva_decisiones_y_publica_global_corregido(tmp_path):
    """I + correccion autorizada: (1) 1a corrida: alertas pendientes, se genera la revision.
    (2) el auditor decide en el Excel (que 'esta en Drive'). (3) 2a corrida con historico y
    revision materializados desde Drive: preserva las decisiones, cierra, corrige la columna
    R del GLOBAL materializado y actualiza el historico sin perder lo previo."""
    base = _base_control1(tmp_path)
    drive_global = tmp_path / "drive_global.xlsx"
    _crear_global_con_filas(str(drive_global), ["DUP", "DUP", "OK"])
    dir1 = _materializar_desde_drive(base, drive_global)
    r1 = dev_api.ejecutar_control1(2026, 9, str(base))
    assert r1["estado_validacion"] == "PENDIENTE_VALIDACION_AUDITOR" and r1["global_modificado"] is False
    assert r1["revision_actualizada"] is True and r1["historico_actualizado"] is False
    ruta_rev = os.path.join(dir1, _NOMBRE_REVISION_SEP)
    assert os.path.isfile(ruta_rev)

    # El auditor valida en el Excel de Drive: fila 16 CORRECTA, fila 17 INCORRECTA -> "CORREGIDA".
    rev_drive = tmp_path / "rev_drive.xlsx"
    _shutil.copyfile(ruta_rev, rev_drive)
    _decidir_revision(str(rev_drive), {16: ("CORRECTA", None), 17: ("INCORRECTA", "CORREGIDA")})

    # 2a corrida: se limpia la entrada (los residuos de la corrida 1 desaparecen) y se materializa de 'Drive'.
    dir2 = _materializar_desde_drive(base, drive_global, revision_src=rev_drive)
    assert sorted(os.listdir(dir2)) == sorted([_NOMBRE_GLOBAL_SEP, _NOMBRE_REVISION_SEP])
    r2 = dev_api.ejecutar_control1(2026, 9, str(base))

    assert r2["estado_validacion"] == "CERRADO_CON_VALIDACION_AUDITOR"
    assert r2["global_modificado"] is True and r2["correcciones_aplicadas"] == 1
    assert r2["sha256_global_original"] != r2["sha256_global_final"]
    assert r2["archivo_global"] == _NOMBRE_GLOBAL_SEP and r2["periodo"] == "SEPTIEMBRE_2026"
    assert r2["historico_actualizado"] is True and r2["revision_actualizada"] is True
    # GLOBAL corregido: solo la celda R de la fila 17, en el archivo MATERIALIZADO (no en el 'oficial' de origen).
    ws = openpyxl.load_workbook(os.path.join(dir2, _NOMBRE_GLOBAL_SEP))["1"]
    assert [ws[f"R{f}"].value for f in (16, 17, 18)] == ["DUP", "CORREGIDA", "OK"]
    assert openpyxl.load_workbook(str(drive_global))["1"]["R17"].value == "DUP"  # el origen no se toco
    # Historico: asignacion FINAL; decisiones del auditor preservadas.
    filas = _filas_csv(os.path.join(dir2, "HISTORICO_ASIGNACIONES.csv"))
    assert sorted(f["asignacion"] for f in filas) == ["CORREGIDA", "DUP", "OK"]


def test_control1_reejecutar_mismo_global_no_duplica_periodo(tmp_path):
    """M: con el historico ya publicado (materializado de Drive), el mismo GLOBAL es
    YA_PROCESADO_SIN_CAMBIOS: no agrega el periodo dos veces."""
    base = _base_control1(tmp_path)
    drive_global = tmp_path / "drive_global.xlsx"
    _crear_global_con_filas(str(drive_global), ["A1", "B2"])
    dir1 = _materializar_desde_drive(base, drive_global)
    dev_api.ejecutar_control1(2026, 9, str(base))
    hist_drive = tmp_path / "hist_drive.csv"
    _shutil.copyfile(os.path.join(dir1, "HISTORICO_ASIGNACIONES.csv"), hist_drive)

    dir2 = _materializar_desde_drive(base, drive_global, historico_src=hist_drive)
    r2 = dev_api.ejecutar_control1(2026, 9, str(base))
    assert r2["estado"] == "YA_PROCESADO_SIN_CAMBIOS"
    assert len(_filas_csv(os.path.join(dir2, "HISTORICO_ASIGNACIONES.csv"))) == 2


def test_preparar_control1_entrada_limpia_solo_ese_periodo_y_valida(tmp_path):
    """L: cada corrida empieza limpiando SOLO control1_entrada/<periodo>/."""
    base = _base_control1(tmp_path)
    dir_sep = dev_api.preparar_control1_entrada(2026, 9, str(base))["dir_entrada"]
    (open(os.path.join(dir_sep, "HISTORICO_ASIGNACIONES.csv"), "w")).write("residuo")
    otro = dev_api.preparar_control1_entrada(2026, 10, str(base))["dir_entrada"]
    (open(os.path.join(otro, "x.txt"), "w")).write("octubre")
    (base / "global" / "HISTORICO_ASIGNACIONES.csv").write_text("residuo global/")
    dev_api.preparar_control1_entrada(2026, 9, str(base))
    assert os.listdir(dir_sep) == []
    assert os.listdir(otro) == ["x.txt"]
    assert (base / "global" / "HISTORICO_ASIGNACIONES.csv").read_text() == "residuo global/"
    for anio, mes in ((2026, 13), ("2026", 9), (1999, 9)):
        with pytest.raises(ValueError, match="PERIODO_INVALIDO"):
            dev_api.preparar_control1_entrada(anio, mes, str(base))


def test_cli_preparar_control1_entrada_y_meses_del_backend_coinciden_con_consolidador(tmp_path):
    import json as jsonlib
    import re as _re
    base = _base_control1(tmp_path)
    ent = tmp_path / "in.json"
    out = tmp_path / "out.json"
    ent.write_text(jsonlib.dumps({"anio": 2026, "mes": 9, "base_dir_dev": str(base)}))
    dev_api.main(["--accion", "preparar_control1_entrada", "--input", str(ent), "--output", str(out)])
    assert '"resultado": "OK"' in out.read_text(encoding="utf-8")
    # Los nombres de mes que arma el nodo n8n RESOLVER deben ser los de consolidador_mensual.
    js = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "tests_v3", "n8n_control1_fuente_drive", "nodos", "resolver.js"), encoding="utf-8").read()
    meses_js = _re.search(r"const MESES = \[(.*?)\];", js).group(1)
    meses_js = [m.strip().strip("'") for m in meses_js.split(",")]
    meses_py = [cm.nombre_sap_global(2026, m)[len("SAP_GLOBAL_TIQ_"):-len("_2026.xlsx")] for m in range(1, 13)]
    assert meses_js == meses_py


# ---------------------------------------------------------------------------
# FASE 12E.5 — historico CANONICO en la raiz de 05_CONTROLES + artefactos por
# periodo en CONTROL_1_ASIGNACIONES/<YYYY-MM>/. Python solo ve control1_entrada/.
# ---------------------------------------------------------------------------

_ESQUEMA_HISTORICO = ("asignacion,fecha_valor,cuenta_mayor,glosa,monto,archivo_global,fila_sap,sha256_archivo,"
                      "fecha_incorporacion,alerta_duplicado,validacion_auditor,observacion_auditor,fecha_validacion,"
                      "asignacion_original,asignacion_final,fila_global,sha256_global_original,sha256_global_final")


def _crear_historico_agosto(ruta, n=5):
    """Historico 'canonico' con n filas del periodo anterior (esquema completo, decisiones del auditor)."""
    lineas = [_ESQUEMA_HISTORICO]
    for i in range(n):
        val = "CORRECTA" if i == 0 else ("INCORRECTA" if i == 1 else "")
        lineas.append(f"AGO{i:03d},2026-08-0{(i % 9) + 1},110201002,glosa {i},10.00,SAP_GLOBAL_TIQ_AGOSTO_2026.xlsx,{16 + i},"
                      f"aaaa,2026-09-09T22:11:15,,{val},obs {i},2026-09-09,AGO{i:03d},AGO{i:03d},{16 + i},aaaa,aaaa")
    with open(ruta, "w", encoding="utf-8", newline="") as f:
        f.write("\n".join(lineas) + "\n")


def test_control1_historico_raiz_es_acumulativo_agosto_preservado_y_septiembre_agregado(tmp_path):
    base = _base_control1(tmp_path)
    hist_raiz = tmp_path / "hist_raiz_drive.csv"
    _crear_historico_agosto(str(hist_raiz), n=5)
    antes = _filas_csv(hist_raiz)
    drive_global = tmp_path / "drive_global.xlsx"
    _crear_global_con_filas(str(drive_global), ["SEP001", "SEP002", "SEP003"])
    dir_c1 = _materializar_desde_drive(base, drive_global, historico_src=hist_raiz)

    r = dev_api.ejecutar_control1(2026, 9, str(base))
    assert r["estado"] == "OK_SIN_DUPLICADOS" and r["historico_actualizado"] is True
    despues = _filas_csv(os.path.join(dir_c1, "HISTORICO_ASIGNACIONES.csv"))
    assert len(despues) == 5 + 3
    assert despues[:5] == antes                                   # agosto intacto, fila por fila, con sus decisiones
    assert {f["archivo_global"] for f in despues[5:]} == {"SAP_GLOBAL_TIQ_SEPTIEMBRE_2026.xlsx"}
    assert [f["validacion_auditor"] for f in despues[:2]] == ["CORRECTA", "INCORRECTA"]
    # los antecedentes de agosto se usan: reejecutar con una asignacion repetida de agosto genera alerta historica.
    drive_global2 = tmp_path / "drive_global2.xlsx"
    _crear_global_con_filas(str(drive_global2), ["AGO002", "SEP009"])
    _materializar_desde_drive(base, drive_global2, historico_src=hist_raiz)
    r2 = dev_api.ejecutar_control1(2026, 9, str(base))
    assert r2["alertas_contra_historico"] == 1


def test_control1_escribe_detalle_del_periodo_con_nombre_canonico(tmp_path):
    base = _base_control1(tmp_path)
    drive_global = tmp_path / "drive_global.xlsx"
    _crear_global_con_filas(str(drive_global), ["A1", "B2"])
    dir_c1 = _materializar_desde_drive(base, drive_global)
    r = dev_api.ejecutar_control1(2026, 9, str(base))
    assert r["detalle_json"] == os.path.join(dir_c1, "CONTROL_ASIGNACIONES_SEPTIEMBRE_2026.json")
    assert os.path.isfile(r["detalle_json"])


def test_control1_ignora_snapshot_mensual_como_fuente_maestra(tmp_path):
    """El snapshot del periodo anterior (otra carpeta / otro contenido) jamas se lee: solo cuenta el
    historico materializado desde la RAIZ. Aqui el 'snapshot' esta en una subcarpeta 2026-08 local
    con una asignacion que, de leerse, produciria una alerta."""
    base = _base_control1(tmp_path)
    snap_dir = base / "control1_entrada" / "2026-08"
    os.makedirs(snap_dir, exist_ok=True)
    _crear_historico_agosto(str(snap_dir / "HISTORICO_ASIGNACIONES.csv"), n=3)
    drive_global = tmp_path / "drive_global.xlsx"
    _crear_global_con_filas(str(drive_global), ["AGO001", "NUEVA1"])       # AGO001 esta SOLO en el snapshot
    _materializar_desde_drive(base, drive_global)                             # historico raiz: no existe (vacio)
    r = dev_api.ejecutar_control1(2026, 9, str(base))
    assert r["estado"] == "OK_SIN_DUPLICADOS" and r["alertas_contra_historico"] == 0
    assert (snap_dir / "HISTORICO_ASIGNACIONES.csv").exists()                 # y el snapshot queda intacto
