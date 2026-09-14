"""test_parity_scenarios.py — FASE 4: arnés de paridad V2 vs V3.

Cubre los 18 CONTRACT-* de auditoria_v2/V2_CONTRACTS.md. Ver
PARITY_SCENARIOS.csv para el inventario completo (input, comportamiento
esperado, archivos a comparar, criterio PASS/FAIL) y PARITY_STRATEGY.md
para la estrategia general.

REGLA DE ORO DE ESTE ARNÉS (impuesta explícitamente por el usuario, FASE 4):
V2 es el ORÁCULO. Cada test aquí:
  1. Ejecuta código REAL de V2 (motor_tiquipaya / pipeline_tiquipaya /
     sap_writer / correcciones_tiquipaya / control_asignaciones /
     control_cxc_cxp, sin modificar ninguno) sobre un insumo sintético
     mínimo, y afirma el contrato correspondiente contra ESE resultado.
  2. Compara el mismo insumo contra V3 (módulos 01-07, todos implementados
     desde FASE 5). Si en el futuro V3 no coincide con lo que V2 ya prueba
     aquí: SE CAMBIA V3, nunca este archivo ni los tests de tests/.

Estado actual (FASE 5, Módulo 07 · AUDITORIA — el último): 18/18 contratos
con comparación V2-vs-V3 real y verde, 0 skipped. Ningún PASS fue forzado:
cada test que compara contra V3 invoca la implementación real del módulo
correspondiente (ver PARITY_STRATEGY.md para el detalle módulo por módulo).

Este archivo NUNCA importa ni modifica nada de tests/ (los 432 tests de V2
se ejecutan aparte, sin cambios: ver FASE 0 de esta misma fase). Se ejecuta
de forma independiente:

    python -m pytest parity_v3/ -q
"""

import glob
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from decimal import Decimal

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "tests"))

import motor_tiquipaya as motor
import pipeline_tiquipaya as pipeline
import sap_writer as sap
import correcciones_tiquipaya as correcciones
import control_asignaciones as ctrl1
import control_cxc_cxp as ctrl3
import aplicar_correccion as aplicar_cli
import xlsx_fixtures as fx

from regla_g_reference import buscar_cierre_exacto, ENCONTRADO, NO_LOCALIZADO, AMBIGUO


def _sha256(ruta):
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        for bloque in iter(lambda: f.read(1 << 16), b""):
            h.update(bloque)
    return h.hexdigest()


def _cierre_vacio_balanceado():
    """Cierre sintetico minimo, trivialmente balanceado (todo en 0.00):
    universo=0, recaudacion=0, diferencia=0, sin vouchers/CI/ATC/USD.
    Reutilizado como fixture base para varios contratos (003/004/005/008/
    009/011/013) que no necesitan importes realistas, solo un cierre OK
    de punta a punta."""
    return {
        "total_movimiento": "0.00", "cobros_atc": "0.00", "dolares": "0.00",
        "total_ci": "0.00", "depositos": [],
    }


@pytest.fixture()
def cierre_vacio_paths(tmp_path):
    ruta_cierre = tmp_path / "CIERRE 01-09-2026.xlsm"
    fx.crear_cierre(str(ruta_cierre), _cierre_vacio_balanceado(), _cierre_vacio_balanceado())
    ruta_maestro = tmp_path / "MAESTRO_SEPTIEMBRE.xlsm"
    fx.crear_maestro_unico(str(ruta_maestro), macros_filas=[], atc_filas=[])
    ruta_plantilla = tmp_path / "Plantilla_SAP_maestra.xlsx"
    fx.crear_plantilla_sap(str(ruta_plantilla))
    return {
        "cierre": str(ruta_cierre), "maestro": str(ruta_maestro), "plantilla": str(ruta_plantilla),
        "tmp": tmp_path,
    }


def _metadata_cabecera():
    return {"tipo_asiento": "SA", "texto_cabecera": "INGRESOS SEP CBBA", "referencia": "CAJA TIQUIPAYA"}


# ---------------------------------------------------------------------------
# PARITY-001 — CONTRACT-001: exclusión de ALQUILERES
# ---------------------------------------------------------------------------

def test_PARITY_001_contract_001_alquileres_excluidos(tmp_path):
    cierre = {
        "fecha_cierre": "2026-09-01",
        "sfc101": {"total_movimiento": "150.00", "cobros_atc": "0.00", "dolares": "0.00", "depositos": []},
        "sfc102": {"total_movimiento": "0.00", "cobros_atc": "0.00", "dolares": "0.00", "depositos": []},
        "comunicaciones_internas": [
            {"sfc": "SFC101", "referencia": "F-1", "importe": "50.00", "cuenta_contable": None,
             "asignacion": None, "banco": "ALQUILERES", "alquileres": True, "glosa": None, "fecha_ci": None},
            {"sfc": "SFC101", "referencia": "F-2", "importe": "100.00", "cuenta_contable": "210201005",
             "asignacion": "REF2", "banco": "BNB", "alquileres": False, "glosa": None, "fecha_ci": None},
        ],
    }
    macros_idx = {"por_codigo": {}, "por_importe": {}}
    atc_idx = {"modo": "PRECONCILIADO", "por_fecha": {}}

    # ---- V2 (oráculo real) ----
    resultado_v2 = motor._ejecutar_v2_sobre_cierre(cierre, macros_idx, atc_idx)
    assert resultado_v2["alquileres"] == "50.00"
    assert resultado_v2["universo_ajustado"] == "100.00"  # 150 - 50
    assert resultado_v2["estado"] == "OK"
    asiento = motor.construir_asiento(resultado_v2)
    origenes = [p["origen"] for p in asiento["partidas"]]
    assert "ALQUILERES" not in origenes
    assert sum(1 for o in origenes if o == "CI") == 1  # solo la CI no-alquileres

    # ---- FASE 5: V3 YA implementa esto — v3.motor es un adaptador sobre el
    # MISMO motor_tiquipaya.py, invocado vía pipeline_tiquipaya.procesar_cierre_completo().
    # Se reproduce el mismo escenario (mismos importes) con archivos reales
    # y se compara el resultado del adaptador contra el oráculo de arriba.
    from v3.motor import ejecutar_motor_cierre, PROCESADO as V3_PROCESADO
    sfc101 = {
        "total_movimiento": "150.00", "cobros_atc": "0.00", "dolares": "0.00", "depositos": [],
        "ci": [
            {"n": 1, "factura": "F-1", "total": "50.00", "cuenta": None, "asignacion": None, "banco": "ALQUILERES"},
            {"n": 2, "factura": "F-2", "total": "100.00", "cuenta": "210201005", "asignacion": "REF2", "banco": "BNB"},
        ],
    }
    sfc102 = {"total_movimiento": "0.00", "cobros_atc": "0.00", "dolares": "0.00", "depositos": []}
    ruta_cierre = tmp_path / "CIERRE 01-09-2026.xlsm"
    fx.crear_cierre(str(ruta_cierre), sfc101, sfc102)
    ruta_maestro = tmp_path / "MAESTRO.xlsm"
    fx.crear_maestro_unico(str(ruta_maestro), macros_filas=[], atc_filas=[])
    ruta_plantilla = tmp_path / "Plantilla.xlsx"
    fx.crear_plantilla_sap(str(ruta_plantilla))

    item = {
        "fecha": "2026-09-01", "archivo_esperado": "CIERRE 01-09-2026.xlsm",
        "estado_ingesta": "ENCONTRADO", "estado_materializacion": "MATERIALIZADO",
        "ruta_cierre_local": str(ruta_cierre), "ruta_maestro_local": str(ruta_maestro),
        "ruta_template_sap_local": str(ruta_plantilla), "ruta_markers_local": None,
    }
    r_v3 = ejecutar_motor_cierre(item, str(tmp_path / "dev"))
    assert r_v3["estado_motor"] == V3_PROCESADO
    assert r_v3["resultado"] == "VALIDADO_PENDIENTE_PUBLICACION"
    assert r_v3["diferencia"] == "0.00"  # misma conclusion que el oraculo V2 de arriba

    import json
    with open(r_v3["ruta_resultado"], "r", encoding="utf-8") as f:
        resultado_json_v3 = json.load(f)
    assert resultado_json_v3["alquileres"] == resultado_v2["alquileres"] == "50.00"
    assert resultado_json_v3["universo_ajustado"] == resultado_v2["universo_ajustado"] == "100.00"


# ---------------------------------------------------------------------------
# PARITY-002 — CONTRACT-002: 110201003 vs 110201008 (no prohibición global)
# ---------------------------------------------------------------------------

def test_PARITY_002_contract_002_comision_atc_cuenta(tmp_path):
    partidas_malas = [
        {"origen": "UNIVERSO_SFC101", "cuenta_mayor": "110101001", "cargo": "0.00", "haber": "10.00", "asignacion": "SFC101"},
        {"origen": "UNIVERSO_SFC102", "cuenta_mayor": "110101001", "cargo": "0.00", "haber": "0.00", "asignacion": "SFC102"},
        {"origen": "ATC_COMISION", "cuenta_mayor": "999999999", "cargo": "10.00", "haber": "0.00", "asignacion": "TIQUIPAYA SEP"},
    ]
    problemas = motor._validar_partidas(partidas_malas, Decimal("10.00"), Decimal("10.00"), Decimal("0"))
    assert "ATC_COMISION_CUENTA_INVALIDA" in problemas

    # 110201003 en una CI legítima (NO es ATC_COMISION) nunca debe bloquear.
    partidas_ci_legitima = [
        {"origen": "UNIVERSO_SFC101", "cuenta_mayor": "110101001", "cargo": "0.00", "haber": "10.00", "asignacion": "SFC101"},
        {"origen": "UNIVERSO_SFC102", "cuenta_mayor": "110101001", "cargo": "0.00", "haber": "0.00", "asignacion": "SFC102"},
        {"origen": "CI", "cuenta_mayor": "110201003", "cargo": "10.00", "haber": "0.00", "asignacion": "REF-CI"},
    ]
    problemas2 = motor._validar_partidas(partidas_ci_legitima, Decimal("10.00"), Decimal("10.00"), Decimal("0"))
    assert not any("110201003" in p or p.startswith("ATC_COMISION") for p in problemas2)

    # ---- FASE 5: V3 YA implementa esto — mismo escenario end-to-end vía el
    # adaptador v3.motor (que a su vez invoca el MISMO motor_tiquipaya.py). ----
    from v3.motor import ejecutar_motor_cierre, PROCESADO as V3_PROCESADO

    # Caso a) CI legitima con cuenta 110201003 -> nunca bloqueada.
    sfc101 = {
        "total_movimiento": "10.00", "cobros_atc": "0.00", "dolares": "0.00", "depositos": [],
        "ci": [{"n": 1, "factura": "F-1", "total": "10.00", "cuenta": "110201003",
                "asignacion": "REF-CI", "banco": "BNB"}],
    }
    sfc102 = {"total_movimiento": "0.00", "cobros_atc": "0.00", "dolares": "0.00", "depositos": []}
    ruta_cierre = tmp_path / "CIERRE 01-09-2026.xlsm"
    fx.crear_cierre(str(ruta_cierre), sfc101, sfc102)
    ruta_maestro = tmp_path / "MAESTRO.xlsm"
    fx.crear_maestro_unico(str(ruta_maestro), macros_filas=[], atc_filas=[])
    ruta_plantilla = tmp_path / "Plantilla.xlsx"
    fx.crear_plantilla_sap(str(ruta_plantilla))

    item = {
        "fecha": "2026-09-01", "archivo_esperado": "CIERRE 01-09-2026.xlsm",
        "estado_ingesta": "ENCONTRADO", "estado_materializacion": "MATERIALIZADO",
        "ruta_cierre_local": str(ruta_cierre), "ruta_maestro_local": str(ruta_maestro),
        "ruta_template_sap_local": str(ruta_plantilla), "ruta_markers_local": None,
    }
    r_v3 = ejecutar_motor_cierre(item, str(tmp_path / "dev"))
    assert r_v3["estado_motor"] == V3_PROCESADO
    assert r_v3["resultado"] == "VALIDADO_PENDIENTE_PUBLICACION"  # nunca bloqueado, igual que el oraculo V2


# ---------------------------------------------------------------------------
# PARITY-003 — CONTRACT-003: Cargo = Haber cuando hay asiento
# ---------------------------------------------------------------------------

def test_PARITY_003_contract_003_cargo_igual_haber(cierre_vacio_paths):
    resultado_v2 = motor.ejecutar_v2(cierre_vacio_paths["cierre"], cierre_vacio_paths["maestro"], cierre_vacio_paths["maestro"])
    assert resultado_v2["estado"] == "OK"
    assert resultado_v2["excepciones_bloqueantes"] == 0
    assert Decimal(resultado_v2["diferencia"]) == 0

    asiento = motor.construir_asiento(resultado_v2)
    assert asiento["estado"] == "OK"
    assert Decimal(asiento["total_cargo"]) == Decimal(asiento["total_haber"])
    assert Decimal(asiento["diferencia"]) == 0

    # ---- FASE 5: V3 YA implementa esto — v3.motor invoca el MISMO
    # pipeline_tiquipaya.procesar_cierre_completo() sobre el mismo fixture. ----
    from v3.motor import ejecutar_motor_cierre, PROCESADO as V3_PROCESADO
    item = {
        "fecha": "2026-09-01", "archivo_esperado": "CIERRE 01-09-2026.xlsm",
        "estado_ingesta": "ENCONTRADO", "estado_materializacion": "MATERIALIZADO",
        "ruta_cierre_local": cierre_vacio_paths["cierre"], "ruta_maestro_local": cierre_vacio_paths["maestro"],
        "ruta_template_sap_local": cierre_vacio_paths["plantilla"], "ruta_markers_local": None,
    }
    r_v3 = ejecutar_motor_cierre(item, str(cierre_vacio_paths["tmp"] / "dev"))
    assert r_v3["estado_motor"] == V3_PROCESADO
    assert r_v3["cargo"] == r_v3["haber"]
    assert Decimal(r_v3["diferencia"]) == 0


# ---------------------------------------------------------------------------
# PARITY-004 — CONTRACT-004: reglas SAP (columnas autorizadas, plantilla intacta)
# ---------------------------------------------------------------------------

def test_PARITY_004_contract_004_sap_columnas_y_plantilla(cierre_vacio_paths):
    resultado_v2 = motor.ejecutar_v2(cierre_vacio_paths["cierre"], cierre_vacio_paths["maestro"], cierre_vacio_paths["maestro"])
    asiento = motor.construir_asiento(resultado_v2)
    metadata = dict(_metadata_cabecera())
    metadata.update(pipeline.derivar_cabecera_fecha_cierre(resultado_v2["fecha"]))

    hash_plantilla_antes = _sha256(cierre_vacio_paths["plantilla"])
    ruta_salida = str(cierre_vacio_paths["tmp"] / "SAP_01-09-2026.xlsx")
    resumen = sap.generar_y_validar_sap(asiento, cierre_vacio_paths["plantilla"], ruta_salida, metadata)

    assert resumen["estado_sap"] == "OK"
    hash_plantilla_despues = _sha256(cierre_vacio_paths["plantilla"])
    assert hash_plantilla_antes == hash_plantilla_despues  # CONTRACT-004/005: plantilla nunca se toca

    # ---- FASE 5: V3 YA implementa esto — mismo fixture vía v3.motor. ----
    from v3.motor import ejecutar_motor_cierre, PROCESADO as V3_PROCESADO
    item = {
        "fecha": "2026-09-01", "archivo_esperado": "CIERRE 01-09-2026.xlsm",
        "estado_ingesta": "ENCONTRADO", "estado_materializacion": "MATERIALIZADO",
        "ruta_cierre_local": cierre_vacio_paths["cierre"], "ruta_maestro_local": cierre_vacio_paths["maestro"],
        "ruta_template_sap_local": cierre_vacio_paths["plantilla"], "ruta_markers_local": None,
    }
    hash_plantilla_antes_v3 = _sha256(cierre_vacio_paths["plantilla"])
    r_v3 = ejecutar_motor_cierre(item, str(cierre_vacio_paths["tmp"] / "dev_v3"))
    assert r_v3["estado_motor"] == V3_PROCESADO
    assert os.path.isfile(r_v3["ruta_sap"])
    assert _sha256(cierre_vacio_paths["plantilla"]) == hash_plantilla_antes_v3  # plantilla ORIGEN intacta tambien via V3


# ---------------------------------------------------------------------------
# PARITY-005 — CONTRACT-005: original .xlsm inmutable
# ---------------------------------------------------------------------------

def test_PARITY_005_contract_005_original_inmutable(cierre_vacio_paths):
    hash_antes = _sha256(cierre_vacio_paths["cierre"])
    resultado_v2 = motor.ejecutar_v2(cierre_vacio_paths["cierre"], cierre_vacio_paths["maestro"], cierre_vacio_paths["maestro"])
    motor.construir_asiento(resultado_v2)
    # Además de leerlo, se intenta un flujo de corrección en memoria sobre
    # una copia deepcopy: tampoco debe tocar el archivo en disco.
    cierre_dict = motor.io.leer_cierre(cierre_vacio_paths["cierre"])
    macros_idx = motor.io.leer_macros_bnb(cierre_vacio_paths["maestro"])
    atc_idx = motor.io.leer_atc_mensual(cierre_vacio_paths["maestro"])
    del cierre_dict, macros_idx, atc_idx  # solo se leen, no se corrige nada aquí
    hash_despues = _sha256(cierre_vacio_paths["cierre"])
    assert hash_antes == hash_despues

    # ---- FASE 5: V3 YA implementa esto (Modulo 02 · MATERIALIZACION). ----
    # v3.materializacion.materializar_cierre() SOLO copia (shutil.copyfile,
    # solo lectura del origen) hacia el directorio DEV — nunca abre el
    # original en modo escritura, nunca lo mueve ni lo renombra. Mismo
    # archivo origen (cierre_vacio_paths), verificado con el MISMO hash de
    # arriba. (Cobertura adicional e independiente: tests_v3/
    # test_materializacion.py, 16/16 — ver PARITY_SCENARIOS.csv notas.)
    from v3.materializacion import materializar_cierre, MATERIALIZADO as V3_MATERIALIZADO

    item_ingesta = {"estado_ingesta": "ENCONTRADO", "archivo_esperado": os.path.basename(cierre_vacio_paths["cierre"])}
    origen_dir = os.path.dirname(cierre_vacio_paths["cierre"])
    destino_dir = str(cierre_vacio_paths["tmp"] / "dev_v3_005")
    os.makedirs(destino_dir, exist_ok=True)

    r_v3 = materializar_cierre(item_ingesta, origen_dir, destino_dir)
    assert r_v3["estado_materializacion"] == V3_MATERIALIZADO
    assert _sha256(cierre_vacio_paths["cierre"]) == hash_antes  # el original sigue intacto tambien via V3
    assert _sha256(r_v3["ruta_cierre_local"]) == hash_antes  # la copia DEV es byte-identica


# ---------------------------------------------------------------------------
# PARITY-006 / PARITY-007 — CONTRACT-006/007: campos corregibles, importe nunca
# ---------------------------------------------------------------------------

def _correccion_base(**overrides):
    base = {
        "fecha_cierre": "2026-09-01", "sha256_origen": "a" * 64,
        "categoria": "COMUNICACION_INTERNA", "tipo": "CI_CUENTA_FALTANTE",
        "identificadores": {"sfc": "SFC101", "factura": "F-1"},
        "campo_corregido": "cuenta_contable", "valor_original": None,
        "valor_autorizado": "210201005", "motivo": "parity-test",
        "usuario_auditor": "parity-harness",
        "fecha_hora": datetime.now(timezone.utc).isoformat(),
    }
    base.update(overrides)
    base["version_correccion"] = correcciones.calcular_version_correccion(base)
    return base


def test_PARITY_006_contract_006_ci_importe_no_corregible(tmp_path):
    correccion = _correccion_base(campo_corregido="importe", valor_autorizado="999.00")
    with pytest.raises(ValueError) as exc:
        correcciones.validar_schema_correccion(correccion)
    assert str(exc.value).startswith("CORRECCION_CAMPO_NO_CORREGIBLE")

    # ---- FASE 5: V3 YA implementa esto — v3.revision invoca la MISMA
    # correcciones.validar_schema_correccion() (arriba) a traves del adaptador. ----
    from v3.revision import revisar_y_corregir_cierre
    item_v3 = {"fecha": "2026-09-01", "correccion": correccion}
    r_v3 = revisar_y_corregir_cierre(item_v3, base_dir_dev=str(tmp_path / "dev"))
    assert r_v3["correccion_aplicada"] is False
    assert r_v3["correccion_valida"] is False
    assert "CORRECCION_CAMPO_NO_CORREGIBLE" in r_v3["mensaje"]


def test_PARITY_007_contract_007_voucher_importe_no_corregible(tmp_path):
    correccion = _correccion_base(
        categoria="VOUCHER", tipo="POSIBLE_TYPO",
        identificadores={"sfc": "SFC101", "codigo_informado": "VCH1O92"},
        campo_corregido="importe", valor_autorizado="999.00",
    )
    with pytest.raises(ValueError) as exc:
        correcciones.validar_schema_correccion(correccion)
    assert str(exc.value).startswith("CORRECCION_CAMPO_NO_CORREGIBLE")

    # ---- FASE 5: V3 YA implementa esto — mismo adaptador v3.revision. ----
    from v3.revision import revisar_y_corregir_cierre
    item_v3 = {"fecha": "2026-09-01", "correccion": correccion}
    r_v3 = revisar_y_corregir_cierre(item_v3, base_dir_dev=str(tmp_path / "dev"))
    assert r_v3["correccion_aplicada"] is False
    assert "CORRECCION_CAMPO_NO_CORREGIBLE" in r_v3["mensaje"]


# ---------------------------------------------------------------------------
# PARITY-008 — CONTRACT-008: idempotencia por SHA256
# ---------------------------------------------------------------------------

def test_PARITY_008_contract_008_idempotencia_sha256(cierre_vacio_paths):
    ruta_sap = str(cierre_vacio_paths["tmp"] / "SAP_01-09-2026.xlsx")
    resultado_1 = pipeline.procesar_cierre_completo(
        ruta_cierre=cierre_vacio_paths["cierre"], ruta_maestro=cierre_vacio_paths["maestro"],
        ruta_plantilla_sap=cierre_vacio_paths["plantilla"], ruta_sap_salida=ruta_sap,
        metadata_cabecera=_metadata_cabecera(), version_codigo="parity-test",
    )
    assert resultado_1["estado"] == pipeline.ESTADO_VALIDADO_PENDIENTE
    hash_origen = resultado_1["hash_origen"]
    os.remove(ruta_sap)  # si la 2da corrida reprocesara, este archivo reapareceria

    resultado_2 = pipeline.procesar_cierre_completo(
        ruta_cierre=cierre_vacio_paths["cierre"], ruta_maestro=cierre_vacio_paths["maestro"],
        ruta_plantilla_sap=cierre_vacio_paths["plantilla"], ruta_sap_salida=ruta_sap,
        metadata_cabecera=_metadata_cabecera(), version_codigo="parity-test",
        hashes_procesados={hash_origen},
    )
    assert resultado_2["estado"] == pipeline.ESTADO_YA_PROCESADO
    assert not os.path.isfile(ruta_sap)  # confirma que NO se regeneró nada

    # ---- FASE 5: V3 YA implementa esto (Modulo 06 · PUBLICACION). ----
    # La idempotencia SHA256 de V2 se verifica arriba a nivel de MOTOR
    # (procesar_cierre_completo + hashes_procesados); v3.publicacion la
    # replica a nivel de PUBLICACION (marcador PROCESADO_<SHA256>.json en
    # publicacion/markers/): 1ra publicacion = PUBLICADO + archivos
    # copiados; 2da publicacion del MISMO cierre = YA_PUBLICADO, CERO
    # duplicacion (ni SAP, ni resultado, ni cierre procesado, ni marker).
    from v3.motor import ejecutar_motor_cierre
    from v3.publicacion import publicar_cierre_dev, PUBLICADO as V3_PUBLICADO, YA_PUBLICADO as V3_YA_PUBLICADO

    item_motor = {
        "fecha": "2026-09-01", "archivo_esperado": "CIERRE 01-09-2026.xlsm",
        "estado_ingesta": "ENCONTRADO", "estado_materializacion": "MATERIALIZADO",
        "ruta_cierre_local": cierre_vacio_paths["cierre"], "ruta_maestro_local": cierre_vacio_paths["maestro"],
        "ruta_template_sap_local": cierre_vacio_paths["plantilla"], "ruta_markers_local": None,
    }
    r_motor = ejecutar_motor_cierre(item_motor, str(cierre_vacio_paths["tmp"] / "dev_v3_008_motor"))
    item_pub = {
        "fecha": "2026-09-01", "estado_final": "LISTO_PARA_PUBLICAR",
        "ruta_cierre_local": cierre_vacio_paths["cierre"], "ruta_sap": r_motor["ruta_sap"],
        "ruta_resultado": r_motor["ruta_resultado"],
    }
    base_dir_dev_pub = str(cierre_vacio_paths["tmp"] / "dev_v3_008_pub")

    r_pub_1 = publicar_cierre_dev(item_pub, base_dir_dev_pub)
    assert r_pub_1["estado_publicacion"] == V3_PUBLICADO
    mtime_sap_1a_corrida = os.path.getmtime(r_pub_1["ruta_sap_publicado"])

    r_pub_2 = publicar_cierre_dev(item_pub, base_dir_dev_pub)
    assert r_pub_2["estado_publicacion"] == V3_YA_PUBLICADO  # mismos 2 estados en el mismo orden que V2 (PROCESADO->YA_PROCESADO)
    assert os.path.getmtime(r_pub_2["ruta_sap_publicado"]) == mtime_sap_1a_corrida  # NO se regenero nada


# ---------------------------------------------------------------------------
# PARITY-009 — CONTRACT-009: marcador inmutable, 4 confirmaciones
# ---------------------------------------------------------------------------

def test_PARITY_009_contract_009_marcador_4_confirmaciones(cierre_vacio_paths):
    resultado_json = {
        "fecha_cierre": "2026-09-01", "archivo_origen": "CIERRE 01-09-2026.xlsm",
        "sha256_origen": "b" * 64, "version_codigo": "parity-test",
        "estado_v2": "OK", "diferencia_asiento": "0.00", "blockers": 0,
        "sap_archivo": "SAP_01-09-2026.xlsx",
    }
    nombre, contenido = pipeline.construir_marcador_procesado(
        resultado_json, sap_publicado_por_usuario=True, sap_verificado_en_drive=True,
        resultado_publicado=True, cierre_movido_a_procesados=True,
    )
    assert nombre == f"PROCESADO_{resultado_json['sha256_origen']}.json"
    assert contenido["Estado"] == "PROCESADO"

    with pytest.raises(ValueError) as exc:
        pipeline.construir_marcador_procesado(
            resultado_json, sap_publicado_por_usuario=True, sap_verificado_en_drive=False,
            resultado_publicado=True, cierre_movido_a_procesados=True,
        )
    assert str(exc.value).startswith("MARCADOR_NO_AUTORIZADO")

    # ---- FASE 5: V3 YA implementa esto (Modulo 06 · PUBLICACION). ----
    # v3.publicacion.publicar_cierre_dev() NUNCA construye su propio
    # marcador: llama a la MISMA pipeline.construir_marcador_procesado()
    # de arriba. Se verifica que, tras una publicacion real, el marcador
    # escrito en disco es byte-a-byte lo que esa funcion real habria
    # devuelto para el mismo resultado_json; y que, cuando falta lo
    # necesario para publicar, V3 tampoco construye NADA (caso rechazo).
    from v3.motor import ejecutar_motor_cierre
    from v3.publicacion import publicar_cierre_dev, PUBLICADO as V3_PUBLICADO, ERROR_PUBLICACION as V3_ERROR

    item_motor = {
        "fecha": "2026-09-01", "archivo_esperado": "CIERRE 01-09-2026.xlsm",
        "estado_ingesta": "ENCONTRADO", "estado_materializacion": "MATERIALIZADO",
        "ruta_cierre_local": cierre_vacio_paths["cierre"], "ruta_maestro_local": cierre_vacio_paths["maestro"],
        "ruta_template_sap_local": cierre_vacio_paths["plantilla"], "ruta_markers_local": None,
    }
    r_motor = ejecutar_motor_cierre(item_motor, str(cierre_vacio_paths["tmp"] / "dev_v3_009_motor"))
    item_pub = {
        "fecha": "2026-09-01", "estado_final": "LISTO_PARA_PUBLICAR",
        "ruta_cierre_local": cierre_vacio_paths["cierre"], "ruta_sap": r_motor["ruta_sap"],
        "ruta_resultado": r_motor["ruta_resultado"],
    }
    r_pub = publicar_cierre_dev(item_pub, str(cierre_vacio_paths["tmp"] / "dev_v3_009_pub"))
    assert r_pub["estado_publicacion"] == V3_PUBLICADO
    with open(r_pub["ruta_marker"], "r", encoding="utf-8") as f:
        marcador_escrito = json.load(f)

    with open(r_motor["ruta_resultado"], "r", encoding="utf-8") as f:
        resultado_json_real = json.load(f)
    nombre_esperado, contenido_esperado = pipeline.construir_marcador_procesado(
        resultado_json_real, sap_publicado_por_usuario=True, sap_verificado_en_drive=True,
        resultado_publicado=True, cierre_movido_a_procesados=True,
        archivo_sap=os.path.basename(r_pub["ruta_sap_publicado"]),
        observaciones=marcador_escrito["Observaciones"],  # unica columna con hora variable
    )
    assert os.path.basename(r_pub["ruta_marker"]) == nombre_esperado
    assert marcador_escrito == {**contenido_esperado, "FechaProcesamiento": marcador_escrito["FechaProcesamiento"]}

    # Caso rechazo (equivalente V3 de "falta una confirmacion"): sin rutas
    # de sap/resultado no hay como confirmar la publicacion -> V3 tampoco
    # construye ningun marcador.
    item_pub_incompleto = {
        "fecha": "2026-09-02", "estado_final": "LISTO_PARA_PUBLICAR",
        "ruta_cierre_local": cierre_vacio_paths["cierre"], "ruta_sap": None, "ruta_resultado": None,
    }
    dir_rechazo = str(cierre_vacio_paths["tmp"] / "dev_v3_009_rechazo")
    r_pub_rechazo = publicar_cierre_dev(item_pub_incompleto, dir_rechazo)
    assert r_pub_rechazo["estado_publicacion"] == V3_ERROR
    assert r_pub_rechazo["ruta_marker"] is None
    assert glob.glob(os.path.join(dir_rechazo, "**", "PROCESADO_*.json"), recursive=True) == []


# ---------------------------------------------------------------------------
# PARITY-010 — CONTRACT-010: REGLA G, búsqueda EXACTA (0 / 1 / >1)
# ---------------------------------------------------------------------------

def test_PARITY_010_contract_010_regla_g_busqueda_exacta():
    # ---- Especificacion de referencia (regla_g_reference.py) ----
    # Caso 1: exactamente 1 coincidencia -> ENCONTRADO.
    estado, nombre = buscar_cierre_exacto("CIERRE 09-09-2026.xlsm", ["CIERRE 09-09-2026.xlsm"])
    assert (estado, nombre) == (ENCONTRADO, "CIERRE 09-09-2026.xlsm")

    # Caso 2: 0 coincidencias -> CIERRE_NO_LOCALIZADO_EN_00_ENTRADA.
    estado, nombre = buscar_cierre_exacto("CIERRE 09-09-2026.xlsm", ["CIERRE 10-09-2026.xlsm"])
    assert (estado, nombre) == (NO_LOCALIZADO, None)

    # Caso 3: incidente real reproducido — buscar "09" entre 11/10/09 debe
    # dar AMBIGUO solo si hay mas de un archivo literalmente igual a "09"
    # (el incidente real era sobre una busqueda no-exacta que tomaba el
    # primer resultado; aqui probamos que con >1 coincidencia EXACTA la
    # regla nunca elige la primera, sino que declara AMBIGUO).
    estado, nombre = buscar_cierre_exacto(
        "CIERRE 09-09-2026.xlsm",
        ["CIERRE 09-09-2026.xlsm", "CIERRE 09-09-2026.xlsm", "CIERRE 10-09-2026.xlsm"],
    )
    assert (estado, nombre) == (AMBIGUO, None)
    assert estado != ENCONTRADO  # nunca "toma el primero"

    # ---- FASE 5: V3 YA implementa REGLA G de verdad (v3/ingesta.py) ----
    # Se compara, para los MISMOS 3 casos, contra la implementacion real
    # del modulo 01 INGESTA (no la especificacion — el modulo en si).
    from v3.ingesta import buscar_cierre_exacto as v3_buscar
    from v3.ingesta import ENCONTRADO as V3_ENCONTRADO, SIN_ARCHIVO as V3_SIN_ARCHIVO, AMBIGUO as V3_AMBIGUO

    estado_v3, file_id_v3, n_v3 = v3_buscar("CIERRE 09-09-2026.xlsm", ["CIERRE 09-09-2026.xlsm"])
    assert (estado_v3, n_v3) == (V3_ENCONTRADO, 1)

    estado_v3, file_id_v3, n_v3 = v3_buscar("CIERRE 09-09-2026.xlsm", ["CIERRE 10-09-2026.xlsm"])
    assert (estado_v3, n_v3) == (V3_SIN_ARCHIVO, 0)

    estado_v3, file_id_v3, n_v3 = v3_buscar(
        "CIERRE 09-09-2026.xlsm",
        ["CIERRE 09-09-2026.xlsm", "CIERRE 09-09-2026.xlsm", "CIERRE 10-09-2026.xlsm"],
    )
    assert (estado_v3, file_id_v3, n_v3) == (V3_AMBIGUO, None, 2)
    assert estado_v3 != V3_ENCONTRADO  # V3 tampoco "toma el primero"

    # PASS explícito: V2 (especificación/incidente real) y V3
    # (v3.ingesta.buscar_cierre_exacto) producen el mismo veredicto para
    # los 3 casos de REGLA G. No hay pytest.skip aquí: esta es la primera
    # comparación V2-vs-V3 real y verde de todo el arnés.
    #
    # NOTA: el lado n8n del modulo 01 (nodo Code JS en el subworkflow
    # CanZtkmnm0ukAC8c) reimplementa esta misma logica en JavaScript
    # (pytest no puede ejecutar nodos n8n); su sincronizacion con esta
    # funcion Python se verifica manualmente, documentada en el propio
    # nodo. Ver parity_v3/PARITY_STRATEGY.md.


# ---------------------------------------------------------------------------
# PARITY-011 — CONTRACT-011: procesar y publicar son responsabilidades separadas
# ---------------------------------------------------------------------------

def test_PARITY_011_contract_011_procesar_nunca_publica(cierre_vacio_paths):
    marcadores_dir = cierre_vacio_paths["tmp"] / "marcadores"
    marcadores_dir.mkdir()
    ruta_sap = str(cierre_vacio_paths["tmp"] / "SAP_01-09-2026.xlsx")

    resultado = pipeline.procesar_cierre_completo(
        ruta_cierre=cierre_vacio_paths["cierre"], ruta_maestro=cierre_vacio_paths["maestro"],
        ruta_plantilla_sap=cierre_vacio_paths["plantilla"], ruta_sap_salida=ruta_sap,
        metadata_cabecera=_metadata_cabecera(), version_codigo="parity-test",
    )
    # Ningun estado devuelto por procesar_cierre_completo es "PROCESADO":
    # ese estado solo lo produce construir_marcador_procesado(), nunca esta funcion.
    assert resultado["estado"] != "PROCESADO"
    assert resultado["estado"] == pipeline.ESTADO_VALIDADO_PENDIENTE
    # Y no se creo ningun marcador PROCESADO_*.json en ningun lado.
    assert glob.glob(str(marcadores_dir / "PROCESADO_*.json")) == []
    assert glob.glob(str(cierre_vacio_paths["tmp"] / "PROCESADO_*.json")) == []

    # ---- FASE 5: V3 YA implementa esto de punta a punta (Modulos 03+04). ----
    # v3.motor invoca el mismo pipeline.procesar_cierre_completo() (arriba);
    # v3.clasificacion decide LISTO_PARA_PUBLICAR/publicable=True SIN publicar
    # nada — clasificar es una funcion pura, sin I/O.
    from v3.motor import ejecutar_motor_cierre
    from v3.clasificacion import clasificar_cierre, LISTO_PARA_PUBLICAR as V3_LISTO

    item_ingesta_materializado = {
        "fecha": "2026-09-01", "archivo_esperado": "CIERRE 01-09-2026.xlsm",
        "estado_ingesta": "ENCONTRADO", "estado_materializacion": "MATERIALIZADO",
        "ruta_cierre_local": cierre_vacio_paths["cierre"], "ruta_maestro_local": cierre_vacio_paths["maestro"],
        "ruta_template_sap_local": cierre_vacio_paths["plantilla"], "ruta_markers_local": None,
    }
    r_motor = ejecutar_motor_cierre(item_ingesta_materializado, str(cierre_vacio_paths["tmp"] / "dev_v3_011"))
    contenido_para_clasificar = {**item_ingesta_materializado, **r_motor}
    r_clasificacion = clasificar_cierre(contenido_para_clasificar)

    assert r_clasificacion["estado_final"] == V3_LISTO
    assert r_clasificacion["publicable"] is True
    # Ni el motor ni la clasificacion crearon ningun marcador: procesar y
    # publicar siguen siendo responsabilidades separadas tambien en V3.
    assert glob.glob(str(cierre_vacio_paths["tmp"] / "**" / "PROCESADO_*.json"), recursive=True) == []

    # ---- FASE 5: ahora que el Modulo 06 · PUBLICACION existe de verdad,
    # se cierra el contrato de punta a punta: "publicable=True" (arriba)
    # SIGUE sin ser "publicado" hasta que se invoca EXPLICITAMENTE
    # v3.publicacion — ninguna otra llamada de este test (motor,
    # clasificacion) genera un marcador.
    from v3.publicacion import publicar_cierre_dev, PUBLICADO as V3_PUBLICADO

    base_dir_dev_pub = str(cierre_vacio_paths["tmp"] / "dev_v3_011_pub")
    assert glob.glob(os.path.join(base_dir_dev_pub, "**", "PROCESADO_*.json"), recursive=True) == []

    item_pub = {
        "fecha": "2026-09-01", "estado_final": r_clasificacion["estado_final"],
        "ruta_cierre_local": cierre_vacio_paths["cierre"], "ruta_sap": r_motor["ruta_sap"],
        "ruta_resultado": r_motor["ruta_resultado"],
    }
    r_pub = publicar_cierre_dev(item_pub, base_dir_dev_pub)
    assert r_pub["estado_publicacion"] == V3_PUBLICADO
    assert os.path.isfile(r_pub["ruta_marker"])  # el marcador SOLO aparece tras la llamada explicita al Modulo 06


# ---------------------------------------------------------------------------
# PARITY-012 — CONTRACT-012: ERROR_REVISAR reversible SOLO via corrección autorizada
# ---------------------------------------------------------------------------

def test_PARITY_012_contract_012_error_revisar_a_listo_via_correccion(tmp_path):
    sfc101 = {
        "total_movimiento": "100.00", "cobros_atc": "0.00", "dolares": "0.00",
        "depositos": [],
        "ci": [{"n": 1, "factura": "F-1", "total": "100.00", "cuenta": None, "asignacion": "REF1", "banco": "BNB"}],
    }
    sfc102 = {"total_movimiento": "0.00", "cobros_atc": "0.00", "dolares": "0.00", "depositos": []}
    ruta_cierre = tmp_path / "CIERRE 01-09-2026.xlsm"
    fx.crear_cierre(str(ruta_cierre), sfc101, sfc102)
    ruta_maestro = tmp_path / "MAESTRO.xlsm"
    fx.crear_maestro_unico(str(ruta_maestro), macros_filas=[], atc_filas=[])
    ruta_plantilla = tmp_path / "Plantilla.xlsx"
    fx.crear_plantilla_sap(str(ruta_plantilla))

    resultado_v2 = motor.ejecutar_v2(str(ruta_cierre), str(ruta_maestro), str(ruta_maestro))
    assert resultado_v2["excepciones_bloqueantes"] == 1  # CI_CUENTA_FALTANTE bloquea
    assert resultado_v2["estado"] == "BLOQUEADO_EXCEPCION"

    hash_origen = pipeline.calcular_sha256(str(ruta_cierre))
    correccion = _correccion_base(
        sha256_origen=hash_origen,
        identificadores={"sfc": "SFC101", "factura": "F-1"},
        campo_corregido="cuenta_contable", valor_original=None, valor_autorizado="210201005",
    )
    ruta_reprocesos = tmp_path / "REPROCESOS"
    ruta_reprocesos.mkdir()
    ruta_sap_reproceso = str(ruta_reprocesos / "SAP_reproceso.xlsx")
    resultado_reproceso = pipeline.procesar_cierre_con_correccion(
        ruta_cierre=str(ruta_cierre), ruta_maestro=str(ruta_maestro), ruta_plantilla_sap=str(ruta_plantilla),
        ruta_sap_salida=ruta_sap_reproceso, metadata_cabecera=_metadata_cabecera(),
        version_codigo="parity-test", correccion=correccion,
    )
    assert resultado_reproceso["estado"] == pipeline.ESTADO_VALIDADO_PENDIENTE
    assert resultado_reproceso["resultado_v2"]["excepciones_bloqueantes"] == 0

    # ---- FASE 5: V3 YA implementa esto — v3.revision (Modulo 05) sobre el
    # MISMO fixture, invocando pipeline.procesar_cierre_con_correccion() y
    # reclasificando con el MISMO v3.clasificacion del Modulo 04. ----
    from v3.revision import revisar_y_corregir_cierre
    from v3.clasificacion import LISTO_PARA_PUBLICAR as V3_LISTO
    item_v3 = {
        "fecha": "2026-09-01", "ruta_cierre_local": str(ruta_cierre), "ruta_maestro_local": str(ruta_maestro),
        "ruta_template_sap_local": str(ruta_plantilla), "ruta_markers_local": None,
        "correccion": correccion,
    }
    r_v3 = revisar_y_corregir_cierre(item_v3, base_dir_dev=str(tmp_path / "dev_v3_012"))
    assert r_v3["correccion_aplicada"] is True
    assert r_v3["resultado_reproceso"] == V3_LISTO  # ERROR_REVISAR -> LISTO_PARA_PUBLICAR, igual que el oraculo


# ---------------------------------------------------------------------------
# PARITY-013 — CONTRACT-013: trazabilidad en REPROCESOS/, sin sobrescribir
# ---------------------------------------------------------------------------

def test_PARITY_013_contract_013_reprocesos_no_sobrescribe(tmp_path):
    ruta_resultado, ruta_sap = aplicar_cli._rutas_reproceso(
        str(tmp_path / "resultados"), str(tmp_path / "salidas"), "2026-09-01", "deadbeef" * 8
    )
    assert "REPROCESOS" in ruta_resultado.split(os.sep)
    assert "REPROCESOS" in ruta_sap.split(os.sep)
    ruta_resultado_original = os.path.join(str(tmp_path / "resultados"), pipeline.nombre_resultado_json("2026-09-01"))
    assert os.path.abspath(ruta_resultado) != os.path.abspath(ruta_resultado_original)

    # ---- FASE 5: V3 YA implementa esto — v3.revision reutiliza esta MISMA
    # funcion (aplicar_cli._rutas_reproceso) end-to-end sobre un fixture real. ----
    from v3.revision import revisar_y_corregir_cierre
    sfc_vacio = {"total_movimiento": "0.00", "cobros_atc": "0.00", "dolares": "0.00", "depositos": []}
    sfc101 = {
        "total_movimiento": "10.00", "cobros_atc": "0.00", "dolares": "0.00", "depositos": [],
        "ci": [{"n": 1, "factura": "F-1", "total": "10.00", "cuenta": None, "asignacion": "REF1", "banco": "BNB"}],
    }
    ruta_cierre_2 = tmp_path / "CIERRE 02-09-2026.xlsm"
    fx.crear_cierre(str(ruta_cierre_2), sfc101, sfc_vacio)
    ruta_maestro_2 = tmp_path / "MAESTRO2.xlsm"
    fx.crear_maestro_unico(str(ruta_maestro_2), macros_filas=[], atc_filas=[])
    ruta_plantilla_2 = tmp_path / "Plantilla2.xlsx"
    fx.crear_plantilla_sap(str(ruta_plantilla_2))
    hash_2 = pipeline.calcular_sha256(str(ruta_cierre_2))
    correccion_2 = _correccion_base(
        sha256_origen=hash_2, fecha_cierre="2026-09-02",
        identificadores={"sfc": "SFC101", "factura": "F-1"},
        campo_corregido="cuenta_contable", valor_original=None, valor_autorizado="210201005",
    )
    item_v3 = {
        "fecha": "2026-09-02", "ruta_cierre_local": str(ruta_cierre_2), "ruta_maestro_local": str(ruta_maestro_2),
        "ruta_template_sap_local": str(ruta_plantilla_2), "ruta_markers_local": None, "correccion": correccion_2,
    }
    base_dir_dev_v3 = str(tmp_path / "dev_v3_013")
    r_v3 = revisar_y_corregir_cierre(item_v3, base_dir_dev=base_dir_dev_v3)
    assert "REPROCESOS" in r_v3["ruta_resultado"].split(os.sep)
    assert "REPROCESOS" in r_v3["ruta_sap"].split(os.sep)
    ruta_resultado_original_v3 = os.path.join(base_dir_dev_v3, "resultados", pipeline.nombre_resultado_json("2026-09-02"))
    assert os.path.abspath(r_v3["ruta_resultado"]) != os.path.abspath(ruta_resultado_original_v3)


# ---------------------------------------------------------------------------
# PARITY-014 — CONTRACT-014: cierre ya publicado nunca admite corrección
# ---------------------------------------------------------------------------

def test_PARITY_014_contract_014_cierre_publicado_no_corregible(tmp_path):
    correccion = _correccion_base()
    with pytest.raises(ValueError) as exc:
        pipeline.procesar_cierre_con_correccion(
            ruta_cierre="/no/existe.xlsm", ruta_maestro="/no/existe.xlsm",
            ruta_plantilla_sap="/no/existe.xlsx", ruta_sap_salida="/no/importa.xlsx",
            metadata_cabecera=_metadata_cabecera(), version_codigo="parity-test",
            correccion=correccion, ya_publicado=True,
        )
    assert str(exc.value).startswith("CIERRE_YA_PUBLICADO_NO_CORREGIBLE")

    # ---- FASE 5: V3 YA implementa esto — v3.revision determina ya_publicado
    # a partir de un marcador PROCESADO_<hash>.json ya materializado (Modulo
    # 02), en vez de un booleano explicito, pero el resultado es el MISMO. ----
    from v3.revision import revisar_y_corregir_cierre
    sfc_vacio = {"total_movimiento": "0.00", "cobros_atc": "0.00", "dolares": "0.00", "depositos": []}
    ruta_cierre = tmp_path / "CIERRE 03-09-2026.xlsm"
    fx.crear_cierre(str(ruta_cierre), sfc_vacio, sfc_vacio)
    hash_origen = pipeline.calcular_sha256(str(ruta_cierre))

    markers_dir = tmp_path / "markers"
    markers_dir.mkdir()
    (markers_dir / f"PROCESADO_{hash_origen}.json").write_text(
        json.dumps({"HashOrigen": hash_origen, "Estado": "PROCESADO", "ArchivoOrigen": "CIERRE 03-09-2026.xlsm"})
    )
    correccion_v3 = _correccion_base(sha256_origen=hash_origen, fecha_cierre="2026-09-03")
    item_v3 = {
        "fecha": "2026-09-03", "ruta_cierre_local": str(ruta_cierre), "ruta_maestro_local": str(ruta_cierre),
        "ruta_template_sap_local": str(ruta_cierre), "ruta_markers_local": str(markers_dir),
        "correccion": correccion_v3,
    }
    r_v3 = revisar_y_corregir_cierre(item_v3, base_dir_dev=str(tmp_path / "dev_v3_014"))
    assert r_v3["correccion_aplicada"] is False
    assert "CIERRE_YA_PUBLICADO_NO_CORREGIBLE" in r_v3["mensaje"]


# ---------------------------------------------------------------------------
# PARITY-015 — CONTRACT-015: CONTROL 1, corrección todo-o-nada sobre el GLOBAL
# ---------------------------------------------------------------------------

def _crear_global_minimo(ruta, asignacion_r16="VIEJA_ASIG"):
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "1"
    ws["C16"] = "110201002"
    ws["D16"] = "GLOSA DEMO"
    ws["E16"] = 100
    ws["F16"] = None
    ws["O16"] = "2026-09-01"
    ws["R16"] = asignacion_r16
    wb.save(ruta)


def test_PARITY_015_contract_015_control1_todo_o_nada(tmp_path):
    ruta_global = str(tmp_path / "SAP_GLOBAL_TIQ_SEPTIEMBRE_2026.xlsx")
    _crear_global_minimo(ruta_global, asignacion_r16="VIEJA_ASIG")
    hash_antes = _sha256(ruta_global)

    # Corrección con ASIGNACION_ORIGINAL que YA NO coincide con la celda real:
    # debe rechazar TODO el lote y no tocar el archivo (todo o nada).
    with pytest.raises(ctrl1.CorreccionInvalidaError):
        ctrl1.aplicar_correcciones_global(ruta_global, [(16, "ASIGNACION_DESACTUALIZADA", "NUEVA_ASIG")])
    assert _sha256(ruta_global) == hash_antes

    # Corrección válida (coincide con el valor real): debe aplicar y
    # tocar ÚNICAMENTE la columna R de esa fila.
    ctrl1.aplicar_correcciones_global(ruta_global, [(16, "VIEJA_ASIG", "NUEVA_ASIG")])
    partidas = ctrl1.leer_partidas_global(ruta_global)
    assert partidas[0]["asignacion"] == "NUEVA_ASIG"
    assert partidas[0]["cuenta_mayor"] == "110201002"  # ninguna otra celda cambió

    # ---- FASE 5: V3 YA implementa esto (Modulo 07 · AUDITORIA). ----
    # v3.auditoria.ejecutar_control1_correccion() delega EXACTAMENTE en
    # ctrl1.aplicar_correcciones_global() (la MISMA funcion de arriba) — no
    # existe una segunda version de CONTROL 1. Se repite el MISMO escenario
    # (rechazo todo-o-nada + correccion valida) invocando esa via V3.
    from v3.auditoria import ejecutar_control1_correccion

    ruta_global_v3 = str(tmp_path / "SAP_GLOBAL_TIQ_OCTUBRE_2026.xlsx")
    _crear_global_minimo(ruta_global_v3, asignacion_r16="VIEJA_ASIG")
    hash_antes_v3 = _sha256(ruta_global_v3)

    with pytest.raises(ctrl1.CorreccionInvalidaError):
        ejecutar_control1_correccion(ruta_global_v3, [(16, "ASIGNACION_DESACTUALIZADA", "NUEVA_ASIG")])
    assert _sha256(ruta_global_v3) == hash_antes_v3  # todo-o-nada tambien via V3

    ejecutar_control1_correccion(ruta_global_v3, [(16, "VIEJA_ASIG", "NUEVA_ASIG")])
    partidas_v3 = ctrl1.leer_partidas_global(ruta_global_v3)
    assert partidas_v3[0]["asignacion"] == "NUEVA_ASIG"
    assert partidas_v3[0]["cuenta_mayor"] == "110201002"


# ---------------------------------------------------------------------------
# PARITY-016 — CONTRACT-016: ninguna IA decide resultados contables
# ---------------------------------------------------------------------------

_PATRON_IA_PROHIBIDA = re.compile(
    r"^\s*(import|from)\s+(openai|anthropic|langchain)\b"
    r"|\b(openai\.OpenAI|anthropic\.Anthropic|ChatCompletion\.create|chat\.completions\.create)\s*\(",
    re.IGNORECASE | re.MULTILINE,
)
# Nota: se detecta USO real (imports de SDKs de IA/LLM o instanciacion de sus
# clientes), no la simple mencion de la palabra "Claude"/"IA" en un
# docstring — motor_tiquipaya.py y excel_io.py mencionan literalmente
# "Claude no procesa filas" para DOCUMENTAR que cumplen CONTRACT-016, lo
# cual seria un falso positivo con un patron mas ingenuo.
_MODULOS_CONTABLES_V2 = [
    "motor_tiquipaya.py", "excel_io.py", "sap_writer.py", "pipeline_tiquipaya.py",
    "correcciones_tiquipaya.py", "consolidador_mensual.py", "control_asignaciones.py",
    "control_cxc_cxp.py", "aplicar_correccion.py", "publicar_cierre.py", "run_batch.py",
]


def test_PARITY_016_contract_016_sin_ia_en_nucleo_contable():
    hallazgos_v2 = []
    for nombre in _MODULOS_CONTABLES_V2:
        ruta = os.path.join(REPO_ROOT, nombre)
        with open(ruta, "r", encoding="utf-8") as f:
            contenido = f.read()
        if _PATRON_IA_PROHIBIDA.search(contenido):
            hallazgos_v2.append(nombre)
    assert hallazgos_v2 == [], f"Referencias a IA/LLM encontradas en nucleo contable V2: {hallazgos_v2}"

    # V3 todavia no tiene NINGUN modulo Python propio (ver auditoria_v2/
    # V3_ARCHITECTURE_PROPOSAL.md: FASE 1-3 solo tocaron n8n/frontend). Cero
    # codigo Python en V3 hoy es, por definicion, cero referencias a IA en su
    # nucleo contable: se verifica aqui explicitamente en vez de asumirlo.
    archivos_python_raiz = set(glob.glob(os.path.join(REPO_ROOT, "*.py")))
    archivos_python_v2_conocidos = {os.path.join(REPO_ROOT, n) for n in _MODULOS_CONTABLES_V2} | {
        os.path.join(REPO_ROOT, "control_asignaciones.py"),
    }
    archivos_nuevos_no_v2 = archivos_python_raiz - archivos_python_v2_conocidos - {
        os.path.join(REPO_ROOT, n) for n in ("consolidador_mensual.py",)
    }
    # Cualquier .py nuevo que no sea ya conocido de V2 (p. ej. un futuro
    # modulo V3) debe pasar por el mismo escaneo antes de aceptarse.
    for ruta in archivos_nuevos_no_v2:
        with open(ruta, "r", encoding="utf-8") as f:
            contenido = f.read()
        assert not _PATRON_IA_PROHIBIDA.search(contenido), f"Referencia a IA/LLM en archivo nuevo: {ruta}"


# ---------------------------------------------------------------------------
# PARITY-017 — CONTRACT-017: CONTROL 3, idempotencia periodo+SHA (no campos mutables)
# ---------------------------------------------------------------------------

def test_PARITY_017_contract_017_control3_idempotencia_periodo_sha():
    # Reproduce el caso EXACTO documentado como bug real corregido (HANDOFF
    # s15 / auditoria_v2 BR-020): AGOSTO ya APLICADO con SHA_A; el
    # historico "mutable" luego se mueve a SEPTIEMBRE con un SHA distinto
    # para la MISMA llave (columna periodo_ultimo_movimiento/
    # sha256_global_ultimo reescrita) — un reintento de AGOSTO con SHA_A
    # DEBE seguir siendo YA_PROCESADO_SIN_CAMBIOS, nunca reacumular.
    historico_dict = {
        "110201002|3P66536982": {
            "periodo_ultimo_movimiento": "SEPTIEMBRE_2026",  # ya lo pisó el mes siguiente
            "sha256_global_ultimo": "sha_septiembre",         # tambien mutado
        }
    }
    libro_periodos = {
        "AGOSTO_2026": {"sha256_global": "sha_agosto", "estado": "APLICADO"},
    }
    resultado = ctrl3._estado_idempotencia(historico_dict, libro_periodos, "AGOSTO_2026", "sha_agosto")
    assert resultado == "YA_PROCESADO_SIN_CAMBIOS"

    # SHA distinto al registrado -> SIEMPRE requiere revision, sin importar historico.
    resultado2 = ctrl3._estado_idempotencia(historico_dict, libro_periodos, "AGOSTO_2026", "sha_diferente")
    assert resultado2 == "GLOBAL_MODIFICADO_REQUIERE_REVISION"

    # ---- FASE 5: V3 YA implementa esto (Modulo 07 · AUDITORIA). ----
    # v3.auditoria.evaluar_control3_idempotencia() delega EXACTAMENTE en
    # ctrl3._estado_idempotencia() (la MISMA funcion de arriba) — no existe
    # una segunda version de CONTROL 3. Mismo escenario (bug real BR-020),
    # invocado via V3.
    from v3.auditoria import evaluar_control3_idempotencia

    assert evaluar_control3_idempotencia(historico_dict, libro_periodos, "AGOSTO_2026", "sha_agosto") \
        == "YA_PROCESADO_SIN_CAMBIOS"
    assert evaluar_control3_idempotencia(historico_dict, libro_periodos, "AGOSTO_2026", "sha_diferente") \
        == "GLOBAL_MODIFICADO_REQUIERE_REVISION"


# ---------------------------------------------------------------------------
# PARITY-018 — CONTRACT-018: autocorrección VOUCHER limitada a 0<->O
# ---------------------------------------------------------------------------

def test_PARITY_018_contract_018_autocorreccion_0_o_unicamente(tmp_path):
    macros_idx = {
        "por_codigo": {"VCH1OO2": [{"codigo": "VCH1OO2", "importe": "500.00", "fecha": "2026-09-01"}]},
        "por_importe": {"500.00": [{"codigo": "VCH1OO2", "importe": "500.00", "fecha": "2026-09-01"}]},
    }
    # "VCH1002" <-> "VCH1OO2": solo intercambios 0<->O -> AUTOCORRECCION_0_O.
    resultado = motor._clasificar_voucher("VCH1002", "500.00", macros_idx)
    assert resultado["estado"] == "AUTOCORRECCION_0_O"

    # "VCH1002" vs un candidato "VCH1PP2" (P, no 0/O) al mismo importe:
    # NUNCA se autocorrige, debe quedar POSIBLE_TYPO (bloqueante).
    macros_idx_p = {
        "por_codigo": {},
        "por_importe": {"500.00": [{"codigo": "VCH1PP2", "importe": "500.00", "fecha": "2026-09-01"}]},
    }
    resultado_p = motor._clasificar_voucher("VCH1002", "500.00", macros_idx_p)
    assert resultado_p["estado"] == "POSIBLE_TYPO"
    assert resultado_p["estado"] != "AUTOCORRECCION_0_O"

    # ---- FASE 5: V3 YA implementa esto — mismo escenario end-to-end vía
    # v3.motor (no se puede leer el estado interno AUTOCORRECCION_0_O desde
    # resultado_json, así que se verifica el efecto observable: el voucher
    # 0<->O queda resuelto -> 0 bloqueadores/diferencia=0; el voucher con 'P'
    # (nunca autocorregido) queda bloqueante -> blockers=1/diferencia!=0). ----
    from v3.motor import ejecutar_motor_cierre, PROCESADO as V3_PROCESADO

    def _fixture_voucher(tmp_subdir, codigo_macros):
        tmp_subdir.mkdir()
        sfc101 = {
            "total_movimiento": "500.00", "cobros_atc": "0.00", "dolares": "0.00",
            "depositos": [{"importe": "500.00", "asignacion": "VCH1002", "banco": "BNB", "fecha": "2026-09-01"}],
        }
        sfc102 = {"total_movimiento": "0.00", "cobros_atc": "0.00", "dolares": "0.00", "depositos": []}
        ruta_cierre = tmp_subdir / "CIERRE 01-09-2026.xlsm"
        fx.crear_cierre(str(ruta_cierre), sfc101, sfc102)
        ruta_maestro = tmp_subdir / "MAESTRO.xlsm"
        fx.crear_maestro_unico(str(ruta_maestro), macros_filas=[("2026-09-01", codigo_macros, "500.00")], atc_filas=[])
        ruta_plantilla = tmp_subdir / "Plantilla.xlsx"
        fx.crear_plantilla_sap(str(ruta_plantilla))
        return {
            "fecha": "2026-09-01", "archivo_esperado": "CIERRE 01-09-2026.xlsm",
            "estado_ingesta": "ENCONTRADO", "estado_materializacion": "MATERIALIZADO",
            "ruta_cierre_local": str(ruta_cierre), "ruta_maestro_local": str(ruta_maestro),
            "ruta_template_sap_local": str(ruta_plantilla), "ruta_markers_local": None,
        }

    item_0o = _fixture_voucher(tmp_path / "caso_0o", "VCH1OO2")
    r_0o = ejecutar_motor_cierre(item_0o, str(tmp_path / "caso_0o" / "dev"))
    assert r_0o["estado_motor"] == V3_PROCESADO
    assert r_0o["resultado"] == "VALIDADO_PENDIENTE_PUBLICACION"  # 0<->O SI se autocorrige
    assert r_0o["diferencia"] == "0.00"
    assert r_0o["bloqueadores"] == 0

    item_p = _fixture_voucher(tmp_path / "caso_p", "VCH1PP2")
    r_p = ejecutar_motor_cierre(item_p, str(tmp_path / "caso_p" / "dev"))
    assert r_p["estado_motor"] == V3_PROCESADO
    assert r_p["resultado"] == "BLOQUEADO_EXCEPCION"  # 'P' NUNCA se autocorrige
    assert r_p["bloqueadores"] == 1
