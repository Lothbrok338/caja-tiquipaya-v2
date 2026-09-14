"""tests_v3/test_e2e_v3.py — FASE 8: integración end-to-end de los 7
módulos de Caja Tiquipaya V3 en entorno DEV.

Este archivo verifica algo que ningún test unitario de tests_v3/ verifica:
que la salida REAL de cada módulo (tal como la produce su función Python,
sin retocar nada a mano) es compatible con la entrada REAL del siguiente
módulo, encadenando 01 INGESTA -> 02 MATERIALIZACION -> 03 MOTOR PYTHON ->
04 CLASIFICACION -> [05 REVISION/CORRECCION] -> [06 PUBLICACION] ->
07 AUDITORIA sobre fixtures sintéticos reales (.xlsm/.xlsx vía
tests/xlsx_fixtures.py).

`_ejecutar_pipeline_v3()` es el ÚNICO "pegamento" de este archivo: hace
EXACTAMENTE lo que el workflow n8n principal debe hacer (orquestar) — llama
a cada módulo con la salida del anterior y decide, según el `estado_final`/
`resultado_reproceso` que el módulo 04/05 YA calculó, si el cierre pasa a
05/06. Esa decisión es ROUTING (qué subworkflow invocar después), no una
regla contable: es exactamente lo que un nodo IF/Switch de n8n hace sobre
el campo `estado_final` — nunca se reinterpreta ningún criterio de negocio
aquí. Ningún archivo de V2 se modifica ni se invoca fuera de lo que los
propios módulos v3.* ya hacen.

Uso: python -m pytest tests_v3/test_e2e_v3.py -q
"""

import glob
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tests"))

import xlsx_fixtures as fx  # noqa: E402
import run_batch  # noqa: E402

from v3.ingesta import ejecutar_ingesta  # noqa: E402
from v3.materializacion import ejecutar_materializacion  # noqa: E402
from v3.motor import ejecutar_motor  # noqa: E402
from v3.clasificacion import (  # noqa: E402
    ejecutar_clasificacion, LISTO_PARA_PUBLICAR, ERROR_REVISAR, SIN_ARCHIVO,
    YA_PROCESADO, ERROR_TECNICO,
)
from v3.revision import revisar_y_corregir_cierre  # noqa: E402
from v3.publicacion import publicar_lote, PUBLICADO, YA_PUBLICADO  # noqa: E402
from v3.auditoria import consolidar_auditoria_lote  # noqa: E402
import correcciones_tiquipaya as correcciones  # noqa: E402


_SFC_VACIO = {"total_movimiento": "0.00", "cobros_atc": "0.00", "dolares": "0.00", "depositos": []}


def _correccion(sha256_origen, categoria, tipo, identificadores, campo_corregido, valor_autorizado):
    base = {
        "fecha_cierre": "2026-09-01", "sha256_origen": sha256_origen,
        "categoria": categoria, "tipo": tipo, "identificadores": identificadores,
        "campo_corregido": campo_corregido, "valor_original": None,
        "valor_autorizado": valor_autorizado, "motivo": "E2E FASE 8",
        "usuario_auditor": "auditor.e2e", "fecha_hora": "2026-09-01T10:00:00+00:00",
    }
    base["version_correccion"] = correcciones.calcular_version_correccion(base)
    return base


def _sha256(ruta):
    import hashlib
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        for bloque in iter(lambda: f.read(1 << 16), b""):
            h.update(bloque)
    return h.hexdigest()


def _ejecutar_pipeline_v3(fecha_inicio, fecha_fin, candidatos_por_fecha, origen_cierres_dir,
                           ruta_maestro_origen, ruta_plantilla_origen, base_dir_dev,
                           correcciones_por_fecha=None, usuario_auditor="auditor.e2e", mes_rango=9):
    """Orquestación PURA (routing, no lógica contable) que refleja lo que
    hará el workflow n8n principal: 01->02->03->04, luego 05 SOLO para
    ERROR_REVISAR con una corrección ya autorizada, luego 06 SOLO para lo
    que quede LISTO_PARA_PUBLICAR (directo desde 04, o vía reproceso desde
    05), y finalmente 07 sobre TODOS los cierres, publicados o no."""
    correcciones_por_fecha = correcciones_por_fecha or {}

    ingesta = ejecutar_ingesta(fecha_inicio, fecha_fin, candidatos_por_fecha)
    materializados = ejecutar_materializacion(ingesta, {
        "base_dir_dev": base_dir_dev, "origen_cierres_dir": origen_cierres_dir,
        "ruta_maestro_origen": ruta_maestro_origen, "ruta_plantilla_origen": ruta_plantilla_origen,
        "markers_origen_dir": None, "mes_rango": mes_rango,
    })
    procesados = ejecutar_motor(materializados, base_dir_dev)
    clasificados = ejecutar_clasificacion(procesados)

    finales = []
    para_publicar = []
    revisados_por_fecha = {}
    for item in clasificados:
        if item["estado_final"] == ERROR_REVISAR:
            correccion = correcciones_por_fecha.get(item["fecha"])
            item_revisado = revisar_y_corregir_cierre(dict(item, correccion=correccion), base_dir_dev)
            revisados_por_fecha[item["fecha"]] = item_revisado
            if item_revisado.get("resultado_reproceso") == LISTO_PARA_PUBLICAR:
                para_publicar.append(item_revisado)
            finales.append(item_revisado)
        elif item["estado_final"] == LISTO_PARA_PUBLICAR:
            para_publicar.append(item)
            finales.append(item)
        else:
            finales.append(item)

    publicados = publicar_lote(para_publicar, base_dir_dev, usuario_auditor) if para_publicar else []
    publicados_por_fecha = {p["fecha"]: p for p in publicados}
    finales = [publicados_por_fecha.get(f["fecha"], f) for f in finales]

    auditoria = consolidar_auditoria_lote(finales, base_dir_dev, usuario_auditor)

    return {
        "ingesta": ingesta, "materializados": materializados, "procesados": procesados,
        "clasificados": clasificados, "revisados": revisados_por_fecha,
        "publicados": publicados, "finales": {f["fecha"]: f for f in finales},
        "auditoria": auditoria,
    }


def _crear_origen(tmp_path, cierres_por_fecha):
    """cierres_por_fecha: {fecha: (sfc101, sfc102)} -> escribe los .xlsm
    "ya en Drive" (simulados) bajo un directorio de origen de solo lectura."""
    origen_dir = tmp_path / "origen_drive"
    origen_dir.mkdir(exist_ok=True)
    candidatos_por_fecha = {}
    for fecha, (sfc101, sfc102) in cierres_por_fecha.items():
        nombre = run_batch.nombre_cierre_esperado(fecha)
        fx.crear_cierre(str(origen_dir / nombre), sfc101, sfc102)
        candidatos_por_fecha[fecha] = [nombre]
    return str(origen_dir), candidatos_por_fecha


# ---------------------------------------------------------------------------
# E2E-001 — Cierre válido sin incidencias -> LISTO/PUBLICADO DEV + auditoría
# ---------------------------------------------------------------------------

def test_e2e_001_cierre_valido_termina_publicado_y_auditado(tmp_path):
    origen_dir, candidatos = _crear_origen(tmp_path, {"2026-09-01": (_SFC_VACIO, _SFC_VACIO)})
    ruta_maestro = tmp_path / "MAESTRO.xlsm"
    fx.crear_maestro_unico(str(ruta_maestro), macros_filas=[], atc_filas=[])
    ruta_plantilla = tmp_path / "Plantilla.xlsx"
    fx.crear_plantilla_sap(str(ruta_plantilla))

    r = _ejecutar_pipeline_v3("2026-09-01", "2026-09-01", candidatos, origen_dir,
                               str(ruta_maestro), str(ruta_plantilla), str(tmp_path / "dev"))

    final = r["finales"]["2026-09-01"]
    assert final["estado_final"] == LISTO_PARA_PUBLICAR
    assert final["estado_publicacion"] == PUBLICADO
    assert final["publicado"] is True
    assert os.path.isfile(final["ruta_marker"])

    registro_auditoria = r["auditoria"]["cierres"][0]
    assert registro_auditoria["estado_final"] == LISTO_PARA_PUBLICAR
    assert registro_auditoria["estado_publicacion"] == PUBLICADO
    assert registro_auditoria["sha256"] == final["sha256"]
    assert os.path.isfile(registro_auditoria["ruta_auditoria"])


# ---------------------------------------------------------------------------
# E2E-002 — SIN_ARCHIVO -> no debe materializar/procesar/publicar
# ---------------------------------------------------------------------------

def test_e2e_002_sin_archivo_no_avanza(tmp_path):
    origen_dir, _ = _crear_origen(tmp_path, {})  # carpeta de origen vacia
    ruta_maestro = tmp_path / "MAESTRO.xlsm"
    fx.crear_maestro_unico(str(ruta_maestro), macros_filas=[], atc_filas=[])
    ruta_plantilla = tmp_path / "Plantilla.xlsx"
    fx.crear_plantilla_sap(str(ruta_plantilla))

    r = _ejecutar_pipeline_v3("2026-09-01", "2026-09-01", {}, origen_dir,
                               str(ruta_maestro), str(ruta_plantilla), str(tmp_path / "dev"))

    final = r["finales"]["2026-09-01"]
    assert r["materializados"][0]["estado_materializacion"] == SIN_ARCHIVO
    assert r["procesados"][0]["estado_motor"] == "NO_PROCESADO"
    assert final["estado_final"] == SIN_ARCHIVO
    assert final.get("estado_publicacion") is None  # nunca se intento publicar
    assert glob.glob(str(tmp_path / "dev" / "publicacion" / "**"), recursive=True) == []


# ---------------------------------------------------------------------------
# E2E-003 — AMBIGUO por REGLA G -> termina en revision/no publicacion
# ---------------------------------------------------------------------------

def test_e2e_003_ambiguo_regla_g_no_publica(tmp_path):
    origen_dir = tmp_path / "origen_drive"
    origen_dir.mkdir()
    nombre = run_batch.nombre_cierre_esperado("2026-09-01")
    fx.crear_cierre(str(origen_dir / nombre), _SFC_VACIO, _SFC_VACIO)
    # 2 candidatos EXACTOS con el mismo nombre -> AMBIGUO (nunca "el primero")
    candidatos = {"2026-09-01": [
        {"nombre": nombre, "file_id": "file-1"}, {"nombre": nombre, "file_id": "file-2"},
    ]}
    ruta_maestro = tmp_path / "MAESTRO.xlsm"
    fx.crear_maestro_unico(str(ruta_maestro), macros_filas=[], atc_filas=[])
    ruta_plantilla = tmp_path / "Plantilla.xlsx"
    fx.crear_plantilla_sap(str(ruta_plantilla))

    r = _ejecutar_pipeline_v3("2026-09-01", "2026-09-01", candidatos, str(origen_dir),
                               str(ruta_maestro), str(ruta_plantilla), str(tmp_path / "dev"))

    assert r["ingesta"][0]["estado_ingesta"] == "AMBIGUO"
    final = r["finales"]["2026-09-01"]
    assert final["estado_final"] == ERROR_REVISAR
    assert final["requiere_revision"] is True
    # sin correccion aportada (AMBIGUO no es un campo corregible via 05) -> nunca se publica
    assert final.get("estado_publicacion") is None
    assert glob.glob(str(tmp_path / "dev" / "publicacion" / "**"), recursive=True) == []


# ---------------------------------------------------------------------------
# E2E-004 — Error de materializacion -> no debe ejecutar motor
# ---------------------------------------------------------------------------

def test_e2e_004_error_materializacion_no_ejecuta_motor(tmp_path):
    origen_dir = tmp_path / "origen_drive"
    origen_dir.mkdir()  # existe pero NUNCA se escribe el archivo -> "listado" pero descarga fallida
    nombre = run_batch.nombre_cierre_esperado("2026-09-01")
    candidatos = {"2026-09-01": [nombre]}  # ingesta cree que esta ENCONTRADO
    ruta_maestro = tmp_path / "MAESTRO.xlsm"
    fx.crear_maestro_unico(str(ruta_maestro), macros_filas=[], atc_filas=[])
    ruta_plantilla = tmp_path / "Plantilla.xlsx"
    fx.crear_plantilla_sap(str(ruta_plantilla))

    r = _ejecutar_pipeline_v3("2026-09-01", "2026-09-01", candidatos, str(origen_dir),
                               str(ruta_maestro), str(ruta_plantilla), str(tmp_path / "dev"))

    assert r["ingesta"][0]["estado_ingesta"] == "ENCONTRADO"
    assert r["materializados"][0]["estado_materializacion"] == "ERROR_MATERIALIZACION"
    procesado = r["procesados"][0]
    assert procesado["estado_motor"] == "NO_PROCESADO"  # el motor NUNCA se invoco
    assert procesado["ruta_resultado"] is None and procesado["ruta_sap"] is None
    final = r["finales"]["2026-09-01"]
    assert final["estado_final"] == ERROR_TECNICO
    assert final.get("estado_publicacion") is None


# ---------------------------------------------------------------------------
# E2E-005 — Bloqueo contable -> ERROR_REVISAR -> no publicacion (sin correccion)
# ---------------------------------------------------------------------------

def _cierre_ci_bloqueante(tmp_path, nombre_dir="e2e005"):
    carpeta = tmp_path / nombre_dir
    carpeta.mkdir()
    sfc101 = {
        "total_movimiento": "100.00", "cobros_atc": "0.00", "dolares": "0.00", "depositos": [],
        "ci": [{"n": 1, "factura": "F-1", "total": "100.00", "cuenta": None,
                "asignacion": "REF1", "banco": "BNB"}],
    }
    origen_dir, candidatos = _crear_origen(carpeta, {"2026-09-01": (sfc101, _SFC_VACIO)})
    ruta_maestro = carpeta / "MAESTRO.xlsm"
    fx.crear_maestro_unico(str(ruta_maestro), macros_filas=[], atc_filas=[])
    ruta_plantilla = carpeta / "Plantilla.xlsx"
    fx.crear_plantilla_sap(str(ruta_plantilla))
    hash_origen = _sha256(str(carpeta / "origen_drive" / run_batch.nombre_cierre_esperado("2026-09-01")))
    return origen_dir, candidatos, str(ruta_maestro), str(ruta_plantilla), hash_origen


def test_e2e_005_bloqueo_contable_sin_correccion_no_publica(tmp_path):
    origen_dir, candidatos, ruta_maestro, ruta_plantilla, _hash = _cierre_ci_bloqueante(tmp_path)

    r = _ejecutar_pipeline_v3("2026-09-01", "2026-09-01", candidatos, origen_dir,
                               ruta_maestro, ruta_plantilla, str(tmp_path / "dev"))

    assert r["procesados"][0]["resultado"] == "BLOQUEADO_EXCEPCION"
    final = r["finales"]["2026-09-01"]
    assert final["estado_final"] == ERROR_REVISAR
    assert final["correccion_aplicada"] is False
    assert "pendiente de decisión del auditor" in final["mensaje"]
    assert final.get("estado_publicacion") is None
    assert glob.glob(str(tmp_path / "dev" / "publicacion" / "**"), recursive=True) == []


# ---------------------------------------------------------------------------
# E2E-006 — Correccion CI valida -> reproceso -> publicable
# ---------------------------------------------------------------------------

def test_e2e_006_correccion_ci_valida_reprocesa_y_publica(tmp_path):
    origen_dir, candidatos, ruta_maestro, ruta_plantilla, hash_origen = _cierre_ci_bloqueante(tmp_path)
    correccion = _correccion(hash_origen, "COMUNICACION_INTERNA", "CI_CUENTA_FALTANTE",
                              {"sfc": "SFC101", "factura": "F-1"}, "cuenta_contable", "210201005")

    r = _ejecutar_pipeline_v3("2026-09-01", "2026-09-01", candidatos, origen_dir,
                               ruta_maestro, ruta_plantilla, str(tmp_path / "dev"),
                               correcciones_por_fecha={"2026-09-01": correccion})

    revisado = r["revisados"]["2026-09-01"]
    assert revisado["correccion_aplicada"] is True
    assert revisado["resultado_reproceso"] == LISTO_PARA_PUBLICAR
    assert revisado["usuario_auditor"] == "auditor.e2e"  # quien corrigio, preservado

    final = r["finales"]["2026-09-01"]
    assert final["estado_publicacion"] == PUBLICADO
    assert final["publicado"] is True
    registro_auditoria = r["auditoria"]["cierres"][0]
    assert registro_auditoria["correccion_aplicada"] is True
    assert registro_auditoria["resultado_reproceso"] == LISTO_PARA_PUBLICAR
    assert registro_auditoria["estado_publicacion"] == PUBLICADO


# ---------------------------------------------------------------------------
# E2E-007 — Correccion VOUCHER valida -> reproceso -> publicable
# ---------------------------------------------------------------------------

def test_e2e_007_correccion_voucher_valida_reprocesa_y_publica(tmp_path):
    carpeta = tmp_path / "e2e007"
    carpeta.mkdir()
    sfc101 = {
        "total_movimiento": "500.00", "cobros_atc": "0.00", "dolares": "0.00",
        "depositos": [{"importe": "500.00", "asignacion": "VCH1O92", "banco": "BNB", "fecha": "2026-09-01"}],
    }
    origen_dir, candidatos = _crear_origen(carpeta, {"2026-09-01": (sfc101, _SFC_VACIO)})
    ruta_maestro = carpeta / "MAESTRO.xlsm"
    # "VCH1P92" es el UNICO candidato real en macros (no 0<->O, requiere decision humana)
    fx.crear_maestro_unico(str(ruta_maestro), macros_filas=[("2026-09-01", "VCH1P92", "500.00")], atc_filas=[])
    ruta_plantilla = carpeta / "Plantilla.xlsx"
    fx.crear_plantilla_sap(str(ruta_plantilla))
    hash_origen = _sha256(str(origen_dir) + "/" + run_batch.nombre_cierre_esperado("2026-09-01"))

    correccion = _correccion(hash_origen, "VOUCHER", "POSIBLE_TYPO",
                              {"sfc": "SFC101", "codigo_informado": "VCH1O92"},
                              "codigo_informado", "VCH1P92")

    r = _ejecutar_pipeline_v3("2026-09-01", "2026-09-01", candidatos, origen_dir,
                               str(ruta_maestro), str(ruta_plantilla), str(tmp_path / "dev"),
                               correcciones_por_fecha={"2026-09-01": correccion})

    revisado = r["revisados"]["2026-09-01"]
    assert revisado["correccion_aplicada"] is True
    assert revisado["resultado_reproceso"] == LISTO_PARA_PUBLICAR
    final = r["finales"]["2026-09-01"]
    assert final["estado_publicacion"] == PUBLICADO


# ---------------------------------------------------------------------------
# E2E-008 — Intento de modificar importe -> rechazado
# ---------------------------------------------------------------------------

def test_e2e_008_intento_modificar_importe_rechazado(tmp_path):
    origen_dir, candidatos, ruta_maestro, ruta_plantilla, hash_origen = _cierre_ci_bloqueante(tmp_path)
    correccion_importe = _correccion(hash_origen, "COMUNICACION_INTERNA", "CI_CUENTA_FALTANTE",
                                      {"sfc": "SFC101", "factura": "F-1"}, "importe", "999.00")

    r = _ejecutar_pipeline_v3("2026-09-01", "2026-09-01", candidatos, origen_dir,
                               ruta_maestro, ruta_plantilla, str(tmp_path / "dev"),
                               correcciones_por_fecha={"2026-09-01": correccion_importe})

    revisado = r["revisados"]["2026-09-01"]
    assert revisado["correccion_aplicada"] is False
    assert revisado["correccion_valida"] is False
    assert "CORRECCION_CAMPO_NO_CORREGIBLE" in revisado["mensaje"]
    final = r["finales"]["2026-09-01"]
    assert final.get("estado_publicacion") is None  # nunca se publico


# ---------------------------------------------------------------------------
# E2E-009 — Publicacion repetida -> idempotencia / YA_PUBLICADO
# ---------------------------------------------------------------------------

def test_e2e_009_publicacion_repetida_es_idempotente(tmp_path):
    origen_dir, candidatos = _crear_origen(tmp_path, {"2026-09-01": (_SFC_VACIO, _SFC_VACIO)})
    ruta_maestro = tmp_path / "MAESTRO.xlsm"
    fx.crear_maestro_unico(str(ruta_maestro), macros_filas=[], atc_filas=[])
    ruta_plantilla = tmp_path / "Plantilla.xlsx"
    fx.crear_plantilla_sap(str(ruta_plantilla))
    base_dir_dev = str(tmp_path / "dev")

    r1 = _ejecutar_pipeline_v3("2026-09-01", "2026-09-01", candidatos, origen_dir,
                                str(ruta_maestro), str(ruta_plantilla), base_dir_dev)
    assert r1["finales"]["2026-09-01"]["estado_publicacion"] == PUBLICADO
    mtime_marker_1 = os.path.getmtime(r1["finales"]["2026-09-01"]["ruta_marker"])

    # Se vuelve a correr el pipeline COMPLETO desde 01 sobre el MISMO
    # origen/base_dir_dev (simula una segunda ejecucion manual del dia):
    # el motor ya detecta YA_PROCESADO via marcadores? En este pipeline no
    # se pasan markers_origen_dir, asi que se re-simula directamente la
    # republicacion sobre el MISMO item final (lo que Modulo 06 SIEMPRE
    # debe resolver como YA_PUBLICADO sin importar cuantas veces se invoque).
    from v3.publicacion import publicar_cierre_dev
    r2 = publicar_cierre_dev(r1["finales"]["2026-09-01"], base_dir_dev)
    assert r2["estado_publicacion"] == YA_PUBLICADO
    assert r2["publicado"] is False
    assert os.path.getmtime(r2["ruta_marker"]) == mtime_marker_1  # nada se regenero


# ---------------------------------------------------------------------------
# E2E-010 — Lote mixto: valido + sin_archivo + bloqueado + error tecnico
# ---------------------------------------------------------------------------

def test_e2e_010_lote_mixto_aisla_cada_cierre(tmp_path):
    origen_dir = tmp_path / "origen_drive"
    origen_dir.mkdir()

    # 01: valido (01-09), CI bloqueante (04-09). 03 y 05 quedan sin archivo
    # (nunca se escriben en origen_dir) y sin candidatos, respectivamente.
    fx.crear_cierre(str(origen_dir / run_batch.nombre_cierre_esperado("2026-09-01")), _SFC_VACIO, _SFC_VACIO)
    sfc101_bloqueante = {
        "total_movimiento": "100.00", "cobros_atc": "0.00", "dolares": "0.00", "depositos": [],
        "ci": [{"n": 1, "factura": "F-1", "total": "100.00", "cuenta": None,
                "asignacion": "REF1", "banco": "BNB"}],
    }
    fx.crear_cierre(str(origen_dir / run_batch.nombre_cierre_esperado("2026-09-04")), sfc101_bloqueante, _SFC_VACIO)
    # 03-09: "ENCONTRADO" segun ingesta pero el archivo NUNCA se crea -> ERROR_MATERIALIZACION
    candidatos = {
        "2026-09-01": [run_batch.nombre_cierre_esperado("2026-09-01")],
        "2026-09-02": [],  # SIN_ARCHIVO
        "2026-09-03": [run_batch.nombre_cierre_esperado("2026-09-03")],  # ERROR_MATERIALIZACION (no se crea el archivo)
        "2026-09-04": [run_batch.nombre_cierre_esperado("2026-09-04")],  # bloqueado -> ERROR_REVISAR
    }
    ruta_maestro = tmp_path / "MAESTRO.xlsm"
    fx.crear_maestro_unico(str(ruta_maestro), macros_filas=[], atc_filas=[])
    ruta_plantilla = tmp_path / "Plantilla.xlsx"
    fx.crear_plantilla_sap(str(ruta_plantilla))

    r = _ejecutar_pipeline_v3("2026-09-01", "2026-09-04", candidatos, str(origen_dir),
                               str(ruta_maestro), str(ruta_plantilla), str(tmp_path / "dev"))

    assert r["finales"]["2026-09-01"]["estado_final"] == LISTO_PARA_PUBLICAR
    assert r["finales"]["2026-09-01"]["estado_publicacion"] == PUBLICADO

    assert r["finales"]["2026-09-02"]["estado_final"] == SIN_ARCHIVO
    assert r["finales"]["2026-09-02"].get("estado_publicacion") is None

    assert r["finales"]["2026-09-03"]["estado_final"] == ERROR_TECNICO
    assert r["finales"]["2026-09-03"].get("estado_publicacion") is None

    assert r["finales"]["2026-09-04"]["estado_final"] == ERROR_REVISAR
    assert r["finales"]["2026-09-04"].get("estado_publicacion") is None

    # 4 cierres, 4 registros de auditoria, ninguno contamino a otro.
    assert r["auditoria"]["total_cierres"] == 4
    fechas_auditadas = {c["fecha"] for c in r["auditoria"]["cierres"]}
    assert fechas_auditadas == {"2026-09-01", "2026-09-02", "2026-09-03", "2026-09-04"}


# ---------------------------------------------------------------------------
# Revisión explícita de contratos entre módulos (campos/tipos/estados/rutas)
# ---------------------------------------------------------------------------

def test_contrato_01_a_02_campos_compatibles(tmp_path):
    origen_dir, candidatos = _crear_origen(tmp_path, {"2026-09-01": (_SFC_VACIO, _SFC_VACIO)})
    ingesta = ejecutar_ingesta("2026-09-01", "2026-09-01", candidatos)
    assert {"fecha", "archivo_esperado", "estado_ingesta"}.issubset(ingesta[0].keys())
    assert isinstance(ingesta, list)


def test_contrato_02_a_03_rutas_locales_presentes_cuando_materializado(tmp_path):
    origen_dir, candidatos = _crear_origen(tmp_path, {"2026-09-01": (_SFC_VACIO, _SFC_VACIO)})
    ruta_maestro = tmp_path / "MAESTRO.xlsm"
    fx.crear_maestro_unico(str(ruta_maestro), macros_filas=[], atc_filas=[])
    ruta_plantilla = tmp_path / "Plantilla.xlsx"
    fx.crear_plantilla_sap(str(ruta_plantilla))

    ingesta = ejecutar_ingesta("2026-09-01", "2026-09-01", candidatos)
    materializados = ejecutar_materializacion(ingesta, {
        "base_dir_dev": str(tmp_path / "dev"), "origen_cierres_dir": origen_dir,
        "ruta_maestro_origen": str(ruta_maestro), "ruta_plantilla_origen": str(ruta_plantilla),
        "markers_origen_dir": None, "mes_rango": 9,
    })
    item = materializados[0]
    assert item["estado_materializacion"] == "MATERIALIZADO"
    for clave in ("ruta_cierre_local", "ruta_maestro_local", "ruta_template_sap_local"):
        assert item[clave] and os.path.isfile(item[clave])


def test_contrato_03_a_04_estado_ingesta_y_materializacion_sobreviven(tmp_path):
    # Este es el hallazgo real de FASE 8: antes de la correccion, el
    # Modulo 03 no reenviaba estado_ingesta/estado_materializacion, y el
    # Modulo 04 los necesita para distinguir SIN_ARCHIVO/AMBIGUO de un
    # simple ERROR_TECNICO.
    origen_dir, candidatos = _crear_origen(tmp_path, {"2026-09-01": (_SFC_VACIO, _SFC_VACIO)})
    ruta_maestro = tmp_path / "MAESTRO.xlsm"
    fx.crear_maestro_unico(str(ruta_maestro), macros_filas=[], atc_filas=[])
    ruta_plantilla = tmp_path / "Plantilla.xlsx"
    fx.crear_plantilla_sap(str(ruta_plantilla))

    ingesta = ejecutar_ingesta("2026-09-01", "2026-09-01", candidatos)
    materializados = ejecutar_materializacion(ingesta, {
        "base_dir_dev": str(tmp_path / "dev"), "origen_cierres_dir": origen_dir,
        "ruta_maestro_origen": str(ruta_maestro), "ruta_plantilla_origen": str(ruta_plantilla),
        "markers_origen_dir": None, "mes_rango": 9,
    })
    procesados = ejecutar_motor(materializados, str(tmp_path / "dev"))
    assert procesados[0]["estado_ingesta"] == "ENCONTRADO"
    assert procesados[0]["estado_materializacion"] == "MATERIALIZADO"

    clasificados = ejecutar_clasificacion(procesados)
    assert clasificados[0]["estado_final"] == LISTO_PARA_PUBLICAR


def test_contrato_04_a_06_ruta_cierre_local_sobrevive_para_sha256(tmp_path):
    # Segundo hallazgo real de FASE 8: el Modulo 04 no reenviaba
    # ruta_cierre_local, que el Modulo 06 necesita para calcular el SHA256
    # de idempotencia (pipeline.calcular_sha256).
    origen_dir, candidatos = _crear_origen(tmp_path, {"2026-09-01": (_SFC_VACIO, _SFC_VACIO)})
    ruta_maestro = tmp_path / "MAESTRO.xlsm"
    fx.crear_maestro_unico(str(ruta_maestro), macros_filas=[], atc_filas=[])
    ruta_plantilla = tmp_path / "Plantilla.xlsx"
    fx.crear_plantilla_sap(str(ruta_plantilla))

    ingesta = ejecutar_ingesta("2026-09-01", "2026-09-01", candidatos)
    materializados = ejecutar_materializacion(ingesta, {
        "base_dir_dev": str(tmp_path / "dev"), "origen_cierres_dir": origen_dir,
        "ruta_maestro_origen": str(ruta_maestro), "ruta_plantilla_origen": str(ruta_plantilla),
        "markers_origen_dir": None, "mes_rango": 9,
    })
    procesados = ejecutar_motor(materializados, str(tmp_path / "dev"))
    clasificados = ejecutar_clasificacion(procesados)
    assert clasificados[0].get("ruta_cierre_local")  # sobrevivio intacto desde el Modulo 02

    publicados = publicar_lote(clasificados, str(tmp_path / "dev"))
    assert publicados[0]["estado_publicacion"] == PUBLICADO
    assert publicados[0]["sha256"]
