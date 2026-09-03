"""test_run_batch.py — pruebas de run_batch.py (RUNNER BATCH CANÓNICO Y
GENÉRICO). Usa exclusivamente fixtures sintéticos (tests/xlsx_fixtures.py)
y no sube/lee nada de Google Drive: run_batch.py solo trabaja sobre rutas
locales ya materializadas. No reimplementa ninguna regla contable: solo
ejercita la orquestación del rango, la cabecera automática, la
idempotencia dinámica y que un blocker no detiene el batch.

Uso: python -m unittest tests.test_run_batch -v
"""

import ast
import inspect
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pipeline_tiquipaya as pipeline
import motor_tiquipaya as motor
import sap_writer as sap
import run_batch
from tests import xlsx_fixtures as fx
from tests.test_atc_preconciliado import _fila_neto, _fila_comision


# ---------------------------------------------------------------------------
# 1-3. Rango dinámico / SIN_ARCHIVO / rango cruzando mes
# ---------------------------------------------------------------------------

class TestRangoDinamico(unittest.TestCase):
    def test_rango_de_tres_dias(self):
        fechas = run_batch.generar_rango_fechas("2026-09-01", "2026-09-03")
        self.assertEqual(fechas, ["2026-09-01", "2026-09-02", "2026-09-03"])

    def test_rango_de_un_solo_dia(self):
        fechas = run_batch.generar_rango_fechas("2026-09-05", "2026-09-05")
        self.assertEqual(fechas, ["2026-09-05"])

    def test_fecha_fin_anterior_a_inicio_da_error(self):
        with self.assertRaises(ValueError):
            run_batch.generar_rango_fechas("2026-09-05", "2026-09-01")

    def test_nombre_cierre_esperado(self):
        self.assertEqual(
            run_batch.nombre_cierre_esperado("2026-09-03"), "CIERRE 03-09-2026.xlsm"
        )


class TestRangoCruzaMes(unittest.TestCase):
    def test_rango_cruzando_mes_da_error_claro(self):
        with self.assertRaises(ValueError) as ctx:
            run_batch.generar_rango_fechas("2026-08-30", "2026-09-02")
        self.assertIn("RANGO_CRUZA_MES", str(ctx.exception))


# ---------------------------------------------------------------------------
# 2. Texto cabecera automático (G10)
# ---------------------------------------------------------------------------

class TestTextoCabeceraAutomatico(unittest.TestCase):
    def test_agosto(self):
        self.assertEqual(run_batch.texto_cabecera_ingresos("2026-08-19"), "INGRESOS AGO CBBA")

    def test_septiembre(self):
        self.assertEqual(run_batch.texto_cabecera_ingresos("2026-09-01"), "INGRESOS SEP CBBA")

    def test_diciembre(self):
        self.assertEqual(run_batch.texto_cabecera_ingresos("2026-12-25"), "INGRESOS DIC CBBA")

    def test_referencia_fija_caja_tiquipaya(self):
        metadata = run_batch.construir_metadata_cabecera("2026-09-01")
        self.assertEqual(metadata["referencia"], "CAJA TIQUIPAYA")
        self.assertEqual(metadata["texto_cabecera"], "INGRESOS SEP CBBA")


# ---------------------------------------------------------------------------
# Fixtures de escenario multi-día (2 fechas del mismo mes, mismo maestro)
# ---------------------------------------------------------------------------

FECHA_A = "2026-08-19"
FECHA_B = "2026-08-20"


def _sfc101(fecha, vch_prefix, ci_prefix):
    return {
        "total_movimiento": "137504.96",
        "cobros_atc": "70000.00",
        "dolares": "0.00",
        "depositos": [
            {"importe": "20000.00", "fecha": fecha, "asignacion": f"{vch_prefix}1", "banco": "BNB"},
            {"importe": "20805.00", "fecha": fecha, "asignacion": f"{vch_prefix}2", "banco": "BNB"},
        ],
        "ci": [
            {"total": "35000.00", "cuenta": "210201005", "asignacion": f"{ci_prefix}1", "banco": "BNB"},
            {"total": "15368.96", "cuenta": "210201005", "asignacion": f"{ci_prefix}2", "banco": "BNB"},
        ],
    }


def _sfc102(fecha, vch_prefix, ci_prefix):
    return {
        "total_movimiento": "144552.00",
        "cobros_atc": "60883.00",
        "dolares": "0.00",
        "depositos": [
            {"importe": "20000.00", "fecha": fecha, "asignacion": f"{vch_prefix}3", "banco": "BNB"},
            {"importe": "20000.00", "fecha": fecha, "asignacion": f"{vch_prefix}4", "banco": "BNB"},
        ],
        "ci": [
            {"total": "10000.00", "cuenta": "210201005", "asignacion": f"{ci_prefix}3", "banco": "BNB"},
            {"total": "10000.00", "cuenta": "210201005", "asignacion": f"{ci_prefix}4", "banco": "BNB"},
        ],
    }


def _macros_filas(fecha, vch_prefix):
    return [
        (fecha, f"{vch_prefix}1", "20000.00"),
        (fecha, f"{vch_prefix}2", "20805.00"),
        (fecha, f"{vch_prefix}3", "20000.00"),
        (fecha, f"{vch_prefix}4", "20000.00"),
    ]


def _nombre_cierre(fecha):
    anio, mes, dia = fecha.split("-")
    return f"CIERRE {dia}-{mes}-{anio}.xlsm"


class _BaseDosDias(unittest.TestCase):
    """Arma un maestro único que cubre FECHA_A y FECHA_B (mismo mes),
    más una plantilla SAP sintética, en un directorio temporal. Los
    cierres concretos los arma cada subclase."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = self._tmp.name

        self.cierres_dir = os.path.join(self.tmp, "cierres")
        self.salidas_dir = os.path.join(self.tmp, "salidas")
        self.resultados_dir = os.path.join(self.tmp, "resultados")
        os.makedirs(self.cierres_dir)

        self.ruta_maestro = os.path.join(self.tmp, "MACROS AGOSTO.xlsm")
        self.ruta_plantilla = os.path.join(self.tmp, "plantilla_sap.xlsx")

        macros_filas = _macros_filas(FECHA_A, "VCHA") + _macros_filas(FECHA_B, "VCHB")
        atc_filas = [
            _fila_neto(fecha=FECHA_A), _fila_comision(fecha=FECHA_A),
            _fila_neto(fecha=FECHA_B), _fila_comision(fecha=FECHA_B),
        ]
        fx.crear_maestro_unico(self.ruta_maestro, macros_filas=macros_filas, atc_filas=atc_filas)
        fx.crear_plantilla_sap(self.ruta_plantilla)

    def _crear_cierre(self, fecha, vch_prefix, ci_prefix, bloqueado=False):
        sfc101 = _sfc101(fecha, vch_prefix, ci_prefix)
        sfc102 = _sfc102(fecha, vch_prefix, ci_prefix)
        if bloqueado:
            sfc101["depositos"][0]["asignacion"] = "VCH-INEXISTENTE"
        ruta = os.path.join(self.cierres_dir, _nombre_cierre(fecha))
        fx.crear_cierre(ruta, sfc101, sfc102)
        return ruta

    def _args(self, fecha_inicio, fecha_fin, controles_dir=None):
        return argparse_namespace(
            fecha_inicio=fecha_inicio, fecha_fin=fecha_fin,
            cierres_dir=self.cierres_dir, maestro=self.ruta_maestro,
            plantilla=self.ruta_plantilla, salidas_dir=self.salidas_dir,
            resultados_dir=self.resultados_dir, controles_dir=controles_dir,
            version_codigo="TEST-VERSION",
        )


def argparse_namespace(**kwargs):
    import argparse
    return argparse.Namespace(**kwargs)


# ---------------------------------------------------------------------------
# SIN_ARCHIVO
# ---------------------------------------------------------------------------

class TestSinArchivo(_BaseDosDias):
    def test_dia_sin_cierre_da_sin_archivo_y_continua(self):
        # Solo se materializa FECHA_B; FECHA_A (dentro del rango) no existe.
        self._crear_cierre(FECHA_B, "VCHB", "CIB")

        resultado = run_batch.ejecutar_batch(self._args(FECHA_A, FECHA_B))
        por_fecha = {c["fecha"]: c for c in resultado["cierres"]}

        self.assertEqual(por_fecha[FECHA_A]["estado"], "SIN_ARCHIVO")
        self.assertIsNone(por_fecha[FECHA_A]["hash"])
        self.assertEqual(por_fecha[FECHA_B]["estado"], "LISTO_PARA_PUBLICAR")


# ---------------------------------------------------------------------------
# Hash nuevo procesa / idempotencia dinámica (PROCESADO_<SHA>.json)
# ---------------------------------------------------------------------------

class TestHashNuevoProcesa(_BaseDosDias):
    def test_hash_nuevo_procesa_de_punta_a_punta(self):
        self._crear_cierre(FECHA_A, "VCHA", "CIA")

        resultado = run_batch.ejecutar_batch(self._args(FECHA_A, FECHA_A))
        entrada = resultado["cierres"][0]

        self.assertEqual(entrada["estado"], "LISTO_PARA_PUBLICAR")
        self.assertIsNotNone(entrada["hash"])
        self.assertTrue(os.path.isfile(entrada["ruta_sap"]))
        self.assertTrue(os.path.isfile(entrada["ruta_resultado"]))
        self.assertEqual(entrada["diferencia"], "0.00")
        self.assertEqual(entrada["blockers"], 0)
        self.assertGreater(entrada["lineas_sap"], 0)


class TestIdempotenciaDinamica(_BaseDosDias):
    def test_marcador_procesado_da_ya_procesado_sin_ejecutar_motor(self):
        ruta_cierre = self._crear_cierre(FECHA_A, "VCHA", "CIA")
        hash_origen = pipeline.calcular_sha256(ruta_cierre)

        controles_dir = os.path.join(self.tmp, "controles")
        os.makedirs(controles_dir)
        marcador = {
            "FechaCierre": FECHA_A, "ArchivoOrigen": os.path.basename(ruta_cierre),
            "HashOrigen": hash_origen, "Estado": "PROCESADO",
            "FechaProcesamiento": "2026-08-19 12:00:00", "VersionCodigo": "x",
            "Resultado": "OK", "Diferencia": "0.00", "Blockers": "0",
            "ArchivoSAP": "", "Observaciones": "",
        }
        with open(os.path.join(controles_dir, f"PROCESADO_{hash_origen}.json"), "w", encoding="utf-8") as f:
            json.dump(marcador, f)

        resultado = run_batch.ejecutar_batch(self._args(FECHA_A, FECHA_A, controles_dir=controles_dir))
        entrada = resultado["cierres"][0]

        self.assertEqual(entrada["estado"], "YA_PROCESADO")
        self.assertEqual(entrada["hash"], hash_origen)
        self.assertIsNone(entrada["ruta_sap"])
        # El motor no llegó a ejecutarse: no se generó SAP en disco.
        ruta_sap_esperada = os.path.join(self.salidas_dir, run_batch._nombre_sap_esperado(FECHA_A))
        self.assertFalse(os.path.isfile(ruta_sap_esperada))
        self.assertEqual(resultado["idempotencia"]["fuente"], "controles_dir")
        self.assertEqual(resultado["idempotencia"]["hashes_cargados"], 1)

    def test_sin_controles_dir_usa_set_vacio_explicito(self):
        self._crear_cierre(FECHA_A, "VCHA", "CIA")
        resultado = run_batch.ejecutar_batch(self._args(FECHA_A, FECHA_A, controles_dir=None))
        self.assertIn("SIN_CONTROLES_DIR", resultado["idempotencia"]["fuente"])
        self.assertEqual(resultado["idempotencia"]["hashes_cargados"], 0)
        self.assertEqual(resultado["cierres"][0]["estado"], "LISTO_PARA_PUBLICAR")

    def test_marcador_con_estado_distinto_de_procesado_se_ignora(self):
        ruta_cierre = self._crear_cierre(FECHA_A, "VCHA", "CIA")
        hash_origen = pipeline.calcular_sha256(ruta_cierre)

        controles_dir = os.path.join(self.tmp, "controles")
        os.makedirs(controles_dir)
        marcador = {"HashOrigen": hash_origen, "Estado": "PENDIENTE"}
        with open(os.path.join(controles_dir, f"PROCESADO_{hash_origen}.json"), "w", encoding="utf-8") as f:
            json.dump(marcador, f)

        resultado = run_batch.ejecutar_batch(self._args(FECHA_A, FECHA_A, controles_dir=controles_dir))
        self.assertEqual(resultado["cierres"][0]["estado"], "LISTO_PARA_PUBLICAR")
        self.assertEqual(resultado["idempotencia"]["hashes_cargados"], 0)
        self.assertTrue(any("MARCADOR_INCOMPLETO" in a for a in resultado["idempotencia"]["advertencias"]))


# ---------------------------------------------------------------------------
# Blocker no detiene el batch
# ---------------------------------------------------------------------------

class TestBlockerNoDetieneBatch(_BaseDosDias):
    def test_dia_bloqueado_no_detiene_el_siguiente(self):
        self._crear_cierre(FECHA_A, "VCHA", "CIA", bloqueado=True)
        self._crear_cierre(FECHA_B, "VCHB", "CIB", bloqueado=False)

        resultado = run_batch.ejecutar_batch(self._args(FECHA_A, FECHA_B))
        por_fecha = {c["fecha"]: c for c in resultado["cierres"]}

        self.assertEqual(por_fecha[FECHA_A]["estado"], "ERROR_REVISAR")
        self.assertIsNotNone(por_fecha[FECHA_A]["hash"])  # sí se calculó, no se abortó
        self.assertEqual(por_fecha[FECHA_B]["estado"], "LISTO_PARA_PUBLICAR")
        self.assertTrue(os.path.isfile(por_fecha[FECHA_B]["ruta_sap"]))


# ---------------------------------------------------------------------------
# Maestro y plantilla se reutilizan en todo el batch
# ---------------------------------------------------------------------------

class TestMaestroYPlantillaReutilizados(_BaseDosDias):
    def test_maestro_se_reutiliza_para_cada_cierre(self):
        self._crear_cierre(FECHA_A, "VCHA", "CIA")
        self._crear_cierre(FECHA_B, "VCHB", "CIB")

        with mock.patch.object(motor, "ejecutar_v2", wraps=motor.ejecutar_v2) as m:
            run_batch.ejecutar_batch(self._args(FECHA_A, FECHA_B))

        self.assertEqual(m.call_count, 2)
        for llamada in m.call_args_list:
            _, ruta_macros, ruta_atc = llamada.args
            self.assertEqual(ruta_macros, self.ruta_maestro)
            self.assertEqual(ruta_atc, self.ruta_maestro)

    def test_plantilla_se_reutiliza_para_cada_cierre(self):
        self._crear_cierre(FECHA_A, "VCHA", "CIA")
        self._crear_cierre(FECHA_B, "VCHB", "CIB")

        with mock.patch.object(sap, "generar_y_validar_sap", wraps=sap.generar_y_validar_sap) as m:
            run_batch.ejecutar_batch(self._args(FECHA_A, FECHA_B))

        self.assertEqual(m.call_count, 2)
        for llamada in m.call_args_list:
            ruta_plantilla_usada = llamada.args[1]
            self.assertEqual(ruta_plantilla_usada, self.ruta_plantilla)


# ---------------------------------------------------------------------------
# Validación de maestro (mes / hoja ATC TIQUIPAYA)
# ---------------------------------------------------------------------------

class TestValidacionMaestro(_BaseDosDias):
    def test_maestro_sin_hoja_atc_tiquipaya_da_error(self):
        ruta_sin_atc = os.path.join(self.tmp, "SIN_ATC.xlsm")
        fx.crear_macros(ruta_sin_atc, _macros_filas(FECHA_A, "VCHA"))

        args = self._args(FECHA_A, FECHA_A)
        args.maestro = ruta_sin_atc
        with self.assertRaises(RuntimeError) as ctx:
            run_batch.ejecutar_batch(args)
        self.assertIn("MAESTRO_SIN_HOJA_ATC_TIQUIPAYA", str(ctx.exception))

    def test_maestro_con_mes_distinto_en_nombre_da_error(self):
        ruta_octubre = os.path.join(self.tmp, "MACROS_OCTUBRE.xlsm")
        macros_filas = _macros_filas(FECHA_A, "VCHA")
        fx.crear_maestro_unico(
            ruta_octubre, macros_filas=macros_filas,
            atc_filas=[_fila_neto(fecha=FECHA_A), _fila_comision(fecha=FECHA_A)],
        )

        args = self._args(FECHA_A, FECHA_A)
        args.maestro = ruta_octubre
        with self.assertRaises(RuntimeError) as ctx:
            run_batch.ejecutar_batch(args)
        self.assertIn("MAESTRO_MES_NO_COINCIDE", str(ctx.exception))

    def test_maestro_inexistente_da_error(self):
        args = self._args(FECHA_A, FECHA_A)
        args.maestro = os.path.join(self.tmp, "NO_EXISTE.xlsm")
        with self.assertRaises(RuntimeError) as ctx:
            run_batch.ejecutar_batch(args)
        self.assertIn("MAESTRO_NO_ENCONTRADO", str(ctx.exception))


# ---------------------------------------------------------------------------
# resultado_batch.json — salida y estructura
# ---------------------------------------------------------------------------

class TestResultadoBatchJson(_BaseDosDias):
    def test_resultado_batch_json_se_escribe_y_es_valido(self):
        self._crear_cierre(FECHA_A, "VCHA", "CIA")
        resultado = run_batch.ejecutar_batch(self._args(FECHA_A, FECHA_A))

        ruta = os.path.join(self.resultados_dir, "resultado_batch.json")
        self.assertTrue(os.path.isfile(ruta))
        with open(ruta, "r", encoding="utf-8") as f:
            leido = json.load(f)
        self.assertEqual(leido["total_cierres_rango"], 1)
        self.assertEqual(leido["resumen_estados"], {"LISTO_PARA_PUBLICAR": 1})
        self.assertEqual(leido["parametros"]["version_codigo"], "TEST-VERSION")


# ---------------------------------------------------------------------------
# Sin dependencia de Google Drive
# ---------------------------------------------------------------------------

class TestSinDependenciaGoogleDrive(unittest.TestCase):
    def test_no_importa_ningun_cliente_de_google_ni_drive(self):
        # El docstring explica la separación de responsabilidades con
        # Cowork/Drive (texto legítimo); lo que nunca debe existir es una
        # dependencia real: imports de clientes de Google/Drive o llamadas
        # de red hacia esas APIs.
        codigo_fuente = inspect.getsource(run_batch)
        for modulo in ("googleapiclient", "google.oauth2", "pydrive", "google.auth", "requests", "httplib2", "urllib"):
            self.assertNotIn(f"import {modulo}", codigo_fuente)
        self.assertNotIn("drive.googleapis.com", codigo_fuente)
        self.assertNotIn("googleapiclient", sys.modules)

    def test_run_batch_solo_importa_modulos_estandar_y_locales(self):
        permitidos = {
            "argparse", "json", "os", "re", "subprocess", "sys", "time",
            "datetime", "openpyxl", "pipeline_tiquipaya", "excel_io",
        }
        arbol = ast.parse(inspect.getsource(run_batch))
        importados = set()
        for nodo in ast.walk(arbol):
            if isinstance(nodo, ast.Import):
                importados.update(alias.name.split(".")[0] for alias in nodo.names)
            elif isinstance(nodo, ast.ImportFrom) and nodo.module:
                importados.add(nodo.module.split(".")[0])
        self.assertTrue(importados.issubset(permitidos), importados - permitidos)


if __name__ == "__main__":
    unittest.main()
