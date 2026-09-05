"""
test_control_asignaciones.py — CONTROL 1: auditoría de asignaciones (ZUONR)
duplicadas/históricas del SAP GLOBAL mensual.

Usa un SAP GLOBAL sintético construido localmente en este archivo (nunca
datos contables reales). Verifica exclusivamente el comportamiento de
control_asignaciones.py: no repite ninguna regla de excel_io.py/
motor_tiquipaya.py/sap_writer.py/pipeline_tiquipaya.py/run_batch.py.

Uso: python -m unittest tests.test_control_asignaciones -v
"""

import csv
import datetime
import os
import shutil
import sys
import tempfile
import unittest
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import openpyxl

import control_asignaciones as ca


# ---------------------------------------------------------------------------
# Fixture: SAP GLOBAL sintético mínimo (hoja "1", partidas desde fila 16).
# ---------------------------------------------------------------------------

def _crear_global(ruta, partidas, hoja="1"):
    """partidas: lista de dicts con asignacion/cuenta_mayor/cargo/haber/
    glosa/fecha_valor (ver _partida)."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = hoja

    fila = 16
    for p in partidas:
        ws[f"C{fila}"] = p.get("cuenta_mayor", "110101001")
        ws[f"D{fila}"] = p.get("glosa")
        cargo = p.get("cargo")
        haber = p.get("haber")
        if cargo is not None:
            ws[f"E{fila}"] = Decimal(str(cargo))
        if haber is not None:
            ws[f"F{fila}"] = Decimal(str(haber))
        fecha_valor = p.get("fecha_valor")
        if fecha_valor is not None:
            ws[f"O{fila}"] = fecha_valor
        ws[f"R{fila}"] = p.get("asignacion")
        fila += 1

    wb.save(ruta)


def _partida(asignacion, cuenta_mayor="110101001", cargo="100.00", haber=None,
             glosa="RECAUDACION CAJA TIQUIPAYA", fecha_valor=None):
    return {
        "asignacion": asignacion,
        "cuenta_mayor": cuenta_mayor,
        "cargo": cargo,
        "haber": haber,
        "glosa": glosa,
        "fecha_valor": fecha_valor or datetime.date(2026, 8, 5),
    }


def _leer_historico_csv(ruta):
    if not os.path.isfile(ruta):
        return []
    with open(ruta, "r", encoding="utf-8", newline="") as f:
        return [dict(fila) for fila in csv.DictReader(f)]


class _ControlAsignacionesTestBase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="control_asignaciones_test_")
        self.ruta_historico = os.path.join(self.tmpdir, "HISTORICO_ASIGNACIONES.csv")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _ruta_global(self, nombre="SAP_GLOBAL_TIQ_AGOSTO_2026.xlsx"):
        return os.path.join(self.tmpdir, nombre)

    def _ejecutar(self, partidas, ruta_global=None, **kwargs):
        ruta_global = ruta_global or self._ruta_global()
        _crear_global(ruta_global, partidas)
        return ca.ejecutar_control(
            ruta_global=ruta_global, ruta_historico=self.ruta_historico, **kwargs
        )


# ---------------------------------------------------------------------------
# 1-6: exclusiones
# ---------------------------------------------------------------------------

class TestExclusiones(_ControlAsignacionesTestBase):
    def test_sfc101_repetido_excluido(self):
        resumen = self._ejecutar([_partida("SFC101"), _partida("SFC101")])
        self.assertEqual(resumen["estado"], "OK_SIN_DUPLICADOS")
        self.assertEqual(resumen["asignaciones_excluidas"], 2)
        self.assertEqual(resumen["cantidad_hallazgos"], 0)

    def test_sfc102_repetido_excluido(self):
        resumen = self._ejecutar([_partida("SFC102"), _partida("SFC102")])
        self.assertEqual(resumen["estado"], "OK_SIN_DUPLICADOS")
        self.assertEqual(resumen["asignaciones_excluidas"], 2)
        self.assertEqual(resumen["cantidad_hallazgos"], 0)

    def test_tiquipaya_ago_repetido_excluido(self):
        resumen = self._ejecutar([_partida("TIQUIPAYA AGO"), _partida("TIQUIPAYA AGO")])
        self.assertEqual(resumen["estado"], "OK_SIN_DUPLICADOS")
        self.assertEqual(resumen["asignaciones_excluidas"], 2)
        self.assertEqual(resumen["cantidad_hallazgos"], 0)

    def test_cuenta_110201008_con_tiquipaya_ago_excluido(self):
        resumen = self._ejecutar([
            _partida("TIQUIPAYA AGO", cuenta_mayor="110201008"),
        ])
        self.assertEqual(resumen["estado"], "OK_SIN_DUPLICADOS")
        self.assertEqual(resumen["asignaciones_excluidas"], 1)
        self.assertEqual(resumen["asignaciones_evaluadas"], 0)

    def test_cuenta_110201008_con_revisar_excluido(self):
        resumen = self._ejecutar([
            _partida("REVISAR", cuenta_mayor="110201008"),
        ])
        self.assertEqual(resumen["estado"], "OK_SIN_DUPLICADOS")
        self.assertEqual(resumen["asignaciones_excluidas"], 1)
        self.assertEqual(resumen["asignaciones_evaluadas"], 0)

    def test_cuenta_110201008_con_cualquier_otra_asignacion_excluido(self):
        resumen = self._ejecutar([
            _partida("OTRA-CUALQUIERA-1", cuenta_mayor="110201008"),
            _partida("OTRA-CUALQUIERA-1", cuenta_mayor="110201008"),
        ])
        self.assertEqual(resumen["estado"], "OK_SIN_DUPLICADOS")
        self.assertEqual(resumen["asignaciones_excluidas"], 2)
        self.assertEqual(resumen["cantidad_hallazgos"], 0)

    def test_cuenta_110201008_normaliza_float_excel(self):
        # Excel puede entregar la cuenta como float (110201008.0).
        self.assertTrue(ca.es_excluida("FORTALEZA", 110201008.0))
        self.assertTrue(ca.es_excluida("FORTALEZA", "110201008.0"))
        self.assertTrue(ca.es_excluida("FORTALEZA", "110201008"))
        self.assertFalse(ca.es_excluida("FORTALEZA", "110101001"))


# ---------------------------------------------------------------------------
# 7-8: FORTALEZA y otras asignaciones repetidas dentro del mismo GLOBAL
# ---------------------------------------------------------------------------

class TestDuplicadosMismoGlobal(_ControlAsignacionesTestBase):
    def test_fortaleza_repetida_revisar(self):
        resumen = self._ejecutar([_partida("FORTALEZA"), _partida("FORTALEZA")])
        self.assertEqual(resumen["estado"], "REVISAR_DUPLICADOS_ENCONTRADOS")
        self.assertEqual(resumen["asignaciones_duplicadas"], ["FORTALEZA"])
        self.assertEqual(resumen["cantidad_hallazgos"], 1)

    def test_otra_asignacion_repetida_mismo_global_revisar(self):
        resumen = self._ejecutar([_partida("ASIG-X"), _partida("ASIG-X")])
        self.assertEqual(resumen["estado"], "REVISAR_DUPLICADOS_ENCONTRADOS")
        self.assertEqual(resumen["asignaciones_duplicadas"], ["ASIG-X"])


# ---------------------------------------------------------------------------
# 9-13: hallazgo contra histórico y preservación de datos
# ---------------------------------------------------------------------------

class TestHallazgoContraHistorico(_ControlAsignacionesTestBase):
    def test_asignacion_repetida_contra_historico_revisar(self):
        ca.guardar_historico(self.ruta_historico, [{
            "asignacion": "ASIG-HIST", "fecha_valor": "2026-07-01",
            "cuenta_mayor": "110101001", "glosa": "GLOSA PREVIA", "monto": "50.00",
            "archivo_global": "SAP_GLOBAL_TIQ_JULIO_2026.xlsx", "fila_sap": 16,
            "sha256_archivo": "sha_previo", "fecha_incorporacion": "2026-07-31T00:00:00",
        }])
        resumen = self._ejecutar([_partida("ASIG-HIST", glosa="GLOSA NUEVA",
                                            fecha_valor=datetime.date(2026, 8, 3),
                                            cargo="75.00")])
        self.assertEqual(resumen["estado"], "REVISAR_DUPLICADOS_ENCONTRADOS")
        self.assertFalse(resumen["historico_actualizado"])
        self.assertEqual(resumen["filas_incorporadas_historico"], 0)

    def test_glosa_completa_preservada_en_hallazgo(self):
        glosa_larga = "RECAUDACION CAJA SFC101 - GLOSA COMPLETA DE PRUEBA CON DETALLE"
        resumen = self._ejecutar([
            _partida("ASIG-Y", glosa=glosa_larga),
            _partida("ASIG-Y", glosa=glosa_larga),
        ], ruta_detalle_json=os.path.join(self.tmpdir, "detalle.json"))
        import json
        with open(resumen["detalle_json"], encoding="utf-8") as f:
            detalle = json.load(f)
        self.assertEqual(detalle["hallazgos"][0]["glosa"], glosa_larga)

    def test_fecha_preservada_en_hallazgo(self):
        fecha = datetime.date(2026, 8, 15)
        resumen = self._ejecutar([
            _partida("ASIG-Z", fecha_valor=fecha),
            _partida("ASIG-Z", fecha_valor=fecha),
        ], ruta_detalle_json=os.path.join(self.tmpdir, "detalle.json"))
        import json
        with open(resumen["detalle_json"], encoding="utf-8") as f:
            detalle = json.load(f)
        self.assertEqual(detalle["hallazgos"][0]["fecha"], fecha.isoformat())

    def test_monto_preservado_en_hallazgo(self):
        resumen = self._ejecutar([
            _partida("ASIG-M", cargo="1234.56"),
            _partida("ASIG-M", cargo="1234.56"),
        ], ruta_detalle_json=os.path.join(self.tmpdir, "detalle.json"))
        import json
        with open(resumen["detalle_json"], encoding="utf-8") as f:
            detalle = json.load(f)
        self.assertEqual(detalle["hallazgos"][0]["monto"], "1234.56")

    def test_archivo_y_filas_relacionadas_preservadas(self):
        resumen = self._ejecutar([
            _partida("ASIG-R"),
            _partida("ASIG-R"),
        ], nombre_archivo_global="SAP_GLOBAL_TIQ_AGOSTO_2026.xlsx",
           ruta_detalle_json=os.path.join(self.tmpdir, "detalle.json"))
        import json
        with open(resumen["detalle_json"], encoding="utf-8") as f:
            detalle = json.load(f)
        hallazgo = detalle["hallazgos"][0]
        self.assertEqual(hallazgo["archivo_global"], "SAP_GLOBAL_TIQ_AGOSTO_2026.xlsx")
        self.assertEqual(hallazgo["archivo_relacionado"], "SAP_GLOBAL_TIQ_AGOSTO_2026.xlsx")
        self.assertEqual(hallazgo["fila_sap"], 16)
        self.assertEqual(hallazgo["fila_sap_relacionada"], 17)


# ---------------------------------------------------------------------------
# 14-16: idempotencia (SHA idéntico / archivo_global con SHA distinto)
# ---------------------------------------------------------------------------

class TestIdempotencia(_ControlAsignacionesTestBase):
    def test_mismo_sha256_ya_procesado_sin_cambios(self):
        ruta_global = self._ruta_global()
        _crear_global(ruta_global, [_partida("ASIG-1")])
        primero = ca.ejecutar_control(ruta_global=ruta_global, ruta_historico=self.ruta_historico)
        self.assertEqual(primero["estado"], "OK_SIN_DUPLICADOS")

        segundo = ca.ejecutar_control(ruta_global=ruta_global, ruta_historico=self.ruta_historico)
        self.assertEqual(segundo["estado"], "YA_PROCESADO_SIN_CAMBIOS")

    def test_mismo_archivo_global_sha_diferente_requiere_revision(self):
        nombre = "SAP_GLOBAL_TIQ_AGOSTO_2026.xlsx"
        ca.guardar_historico(self.ruta_historico, [{
            "asignacion": "ASIG-1", "fecha_valor": "2026-08-01",
            "cuenta_mayor": "110101001", "glosa": "GLOSA", "monto": "10.00",
            "archivo_global": nombre, "fila_sap": 16,
            "sha256_archivo": "sha_diferente_al_actual",
            "fecha_incorporacion": "2026-08-31T00:00:00",
        }])
        resumen = self._ejecutar([_partida("ASIG-1")],
                                  ruta_global=self._ruta_global(nombre))
        self.assertEqual(resumen["estado"], "GLOBAL_MODIFICADO_REQUIERE_REVISION")
        self.assertEqual(resumen["sha256_historico_existente"], "sha_diferente_al_actual")

    def test_global_modificado_no_modifica_historico(self):
        nombre = "SAP_GLOBAL_TIQ_AGOSTO_2026.xlsx"
        fila_previa = {
            "asignacion": "ASIG-1", "fecha_valor": "2026-08-01",
            "cuenta_mayor": "110101001", "glosa": "GLOSA", "monto": "10.00",
            "archivo_global": nombre, "fila_sap": 16,
            "sha256_archivo": "sha_diferente_al_actual",
            "fecha_incorporacion": "2026-08-31T00:00:00",
        }
        ca.guardar_historico(self.ruta_historico, [fila_previa])
        self._ejecutar([_partida("ASIG-1")], ruta_global=self._ruta_global(nombre))

        historico_final = _leer_historico_csv(self.ruta_historico)
        self.assertEqual(len(historico_final), 1)
        self.assertEqual(historico_final[0]["sha256_archivo"], "sha_diferente_al_actual")


# ---------------------------------------------------------------------------
# 17-18: hoja EXACTA "1" obligatoria, sin fallback
# ---------------------------------------------------------------------------

class TestHojaExacta(_ControlAsignacionesTestBase):
    def test_global_sin_hoja_1_error_tecnico(self):
        ruta_global = self._ruta_global()
        _crear_global(ruta_global, [_partida("ASIG-1")], hoja="OTRA_HOJA")
        resumen = ca.ejecutar_control(ruta_global=ruta_global, ruta_historico=self.ruta_historico)
        self.assertEqual(resumen["estado"], "ERROR_TECNICO")
        self.assertIn("GLOBAL_HOJA_1_NO_ENCONTRADA", resumen["problemas"])

    def test_nunca_hace_fallback_a_otra_hoja(self):
        ruta_global = self._ruta_global()
        # La única hoja del libro trae partidas válidas, pero NO se llama "1".
        _crear_global(ruta_global, [_partida("ASIG-1"), _partida("ASIG-1")], hoja="Hoja1")
        resumen = ca.ejecutar_control(ruta_global=ruta_global, ruta_historico=self.ruta_historico)
        self.assertEqual(resumen["estado"], "ERROR_TECNICO")
        self.assertIn("GLOBAL_HOJA_1_NO_ENCONTRADA", resumen["problemas"])
        self.assertNotIn("filas_leidas_global", resumen)


# ---------------------------------------------------------------------------
# 19-21: política de escritura del histórico (duplicados / OK / dry-run)
# ---------------------------------------------------------------------------

class TestPoliticaEscrituraHistorico(_ControlAsignacionesTestBase):
    def test_global_con_duplicados_no_actualiza_historico(self):
        resumen = self._ejecutar([_partida("ASIG-DUP"), _partida("ASIG-DUP")])
        self.assertEqual(resumen["estado"], "REVISAR_DUPLICADOS_ENCONTRADOS")
        self.assertFalse(resumen["historico_actualizado"])
        self.assertEqual(resumen["filas_incorporadas_historico"], 0)
        self.assertFalse(os.path.isfile(self.ruta_historico))

    def test_global_sin_duplicados_actualiza_historico(self):
        resumen = self._ejecutar([_partida("ASIG-OK-1"), _partida("ASIG-OK-2")])
        self.assertEqual(resumen["estado"], "OK_SIN_DUPLICADOS")
        self.assertTrue(resumen["historico_actualizado"])
        self.assertEqual(resumen["filas_incorporadas_historico"], 2)
        self.assertEqual(len(_leer_historico_csv(self.ruta_historico)), 2)

    def test_dry_run_nunca_actualiza_historico(self):
        resumen = self._ejecutar([_partida("ASIG-OK-1")], dry_run=True)
        self.assertEqual(resumen["estado"], "OK_SIN_DUPLICADOS")
        self.assertTrue(resumen["dry_run"])
        self.assertFalse(resumen["historico_actualizado"])
        self.assertEqual(resumen["filas_incorporadas_historico"], 0)
        self.assertFalse(os.path.isfile(self.ruta_historico))


# ---------------------------------------------------------------------------
# 22-24: reproceso, inmutabilidad del origen, preservación del histórico
# ---------------------------------------------------------------------------

class TestReprocesoEInmutabilidad(_ControlAsignacionesTestBase):
    def test_reproceso_identico_historico_sin_cambios(self):
        ruta_global = self._ruta_global()
        _crear_global(ruta_global, [_partida("ASIG-1"), _partida("ASIG-2")])
        ca.ejecutar_control(ruta_global=ruta_global, ruta_historico=self.ruta_historico)
        historico_tras_primero = _leer_historico_csv(self.ruta_historico)

        ca.ejecutar_control(ruta_global=ruta_global, ruta_historico=self.ruta_historico)
        historico_tras_segundo = _leer_historico_csv(self.ruta_historico)

        self.assertEqual(historico_tras_primero, historico_tras_segundo)

    def test_global_origen_no_cambia_de_hash(self):
        ruta_global = self._ruta_global()
        _crear_global(ruta_global, [_partida("ASIG-1")])
        hash_antes = ca._hash_archivo(ruta_global)
        ca.ejecutar_control(ruta_global=ruta_global, ruta_historico=self.ruta_historico)
        hash_despues = ca._hash_archivo(ruta_global)
        self.assertEqual(hash_antes, hash_despues)

    def test_historico_conserva_filas_anteriores_al_agregar_global_valido(self):
        fila_previa = {
            "asignacion": "ASIG-VIEJA", "fecha_valor": "2026-07-01",
            "cuenta_mayor": "110101001", "glosa": "GLOSA VIEJA", "monto": "20.00",
            "archivo_global": "SAP_GLOBAL_TIQ_JULIO_2026.xlsx", "fila_sap": "16",
            "sha256_archivo": "sha_julio", "fecha_incorporacion": "2026-07-31T00:00:00",
        }
        ca.guardar_historico(self.ruta_historico, [fila_previa])

        self._ejecutar([_partida("ASIG-NUEVA")])

        historico_final = _leer_historico_csv(self.ruta_historico)
        self.assertEqual(len(historico_final), 2)
        self.assertIn(fila_previa["asignacion"], [f["asignacion"] for f in historico_final])
        self.assertEqual(historico_final[0], fila_previa)


# ---------------------------------------------------------------------------
# 25-27: sin dependencias externas / sin acoplamiento con el V2 diario
# ---------------------------------------------------------------------------

class TestSinDependenciasExternas(unittest.TestCase):
    """Verifica el CÓDIGO EJECUTABLE (imports reales vía AST), no el texto
    de docstrings/comentarios —el módulo documenta a propósito que NO usa
    Google Drive/Base64 y que layout replica el de sap_writer.py."""

    def setUp(self):
        import ast
        ruta_modulo = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "control_asignaciones.py",
        )
        with open(ruta_modulo, "r", encoding="utf-8") as f:
            arbol = ast.parse(f.read(), filename=ruta_modulo)

        self.modulos_importados = set()
        for nodo in ast.walk(arbol):
            if isinstance(nodo, ast.Import):
                for alias in nodo.names:
                    self.modulos_importados.add(alias.name.split(".")[0])
            elif isinstance(nodo, ast.ImportFrom) and nodo.module:
                self.modulos_importados.add(nodo.module.split(".")[0])

    def test_ninguna_dependencia_google_drive(self):
        prohibidos = {"google", "googleapiclient", "gspread", "pydrive", "pydrive2"}
        self.assertEqual(self.modulos_importados & prohibidos, set())

    def test_ninguna_dependencia_base64(self):
        self.assertNotIn("base64", self.modulos_importados)

    def test_ningun_import_del_motor_diario(self):
        modulos_v2_diario = {
            "motor_tiquipaya", "pipeline_tiquipaya", "sap_writer",
            "excel_io", "run_batch",
        }
        self.assertEqual(self.modulos_importados & modulos_v2_diario, set())


if __name__ == "__main__":
    unittest.main()
