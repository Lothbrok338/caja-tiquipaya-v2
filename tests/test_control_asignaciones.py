"""
test_control_asignaciones.py — CONTROL 1: auditoría de asignaciones (ZUONR)
duplicadas/históricas del SAP GLOBAL mensual, con etapa de validación
humana antes de cerrar el mes.

Usa un SAP GLOBAL sintético construido localmente en este archivo (nunca
datos contables reales). Verifica exclusivamente el comportamiento de
control_asignaciones.py: no repite ninguna regla de excel_io.py/
motor_tiquipaya.py/sap_writer.py/pipeline_tiquipaya.py/run_batch.py.

`estado` conserva la semántica previa a la validación humana
(OK_SIN_DUPLICADOS / REVISAR_DUPLICADOS_ENCONTRADOS), por compatibilidad
con consumidores existentes; `estado_validacion` (PENDIENTE_VALIDACION_
AUDITOR / CERRADO_CON_VALIDACION_AUDITOR) informa si el auditor ya
terminó de revisar las alertas del periodo.

Uso: python -m unittest tests.test_control_asignaciones -v
"""

import csv
import datetime
import json
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


def _leer_csv(ruta):
    if not os.path.isfile(ruta):
        return []
    with open(ruta, "r", encoding="utf-8", newline="") as f:
        return [dict(fila) for fila in csv.DictReader(f)]


class _ControlAsignacionesTestBase(unittest.TestCase):
    NOMBRE_GLOBAL_AGOSTO = "SAP_GLOBAL_TIQ_AGOSTO_2026.xlsx"
    NOMBRE_GLOBAL_SEPTIEMBRE = "SAP_GLOBAL_TIQ_SEPTIEMBRE_2026.xlsx"

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="control_asignaciones_test_")
        self.ruta_historico = os.path.join(self.tmpdir, "HISTORICO_ASIGNACIONES.csv")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _ruta_global(self, nombre=NOMBRE_GLOBAL_AGOSTO):
        return os.path.join(self.tmpdir, nombre)

    def _ruta_revision(self, periodo):
        return ca.ruta_revision_asignaciones(self.tmpdir, periodo)

    def _ejecutar(self, partidas, ruta_global=None, **kwargs):
        ruta_global = ruta_global or self._ruta_global()
        _crear_global(ruta_global, partidas)
        return ca.ejecutar_control(
            ruta_global=ruta_global, ruta_historico=self.ruta_historico, **kwargs
        )

    def _escribir_revision(self, periodo, filas):
        ca.guardar_revision(self._ruta_revision(periodo), filas)

    def _fila_revision(self, periodo, asignacion, sha256_global, tipo_alerta="DUPLICADA_MISMO_MES",
                        validacion="", observacion="", fecha_validacion=""):
        return {
            "PERIODO": periodo, "ASIGNACION": asignacion, "TIPO_ALERTA": tipo_alerta,
            "DETALLE": "detalle de prueba", "VALIDACION_AUDITOR": validacion,
            "OBSERVACION_AUDITOR": observacion, "FECHA_VALIDACION": fecha_validacion,
            "SHA256_GLOBAL": sha256_global,
        }


# ---------------------------------------------------------------------------
# Exclusiones — SIN CAMBIOS respecto de la versión anterior
# ---------------------------------------------------------------------------

class TestExclusiones(_ControlAsignacionesTestBase):
    def test_sfc101_repetido_excluido(self):
        resumen = self._ejecutar([_partida("SFC101"), _partida("SFC101")])
        self.assertEqual(resumen["estado"], "OK_SIN_DUPLICADOS")
        self.assertIsNone(resumen["estado_validacion"])
        self.assertEqual(resumen["asignaciones_excluidas"], 2)
        self.assertEqual(resumen["cantidad_hallazgos"], 0)

    def test_sfc102_repetido_excluido(self):
        resumen = self._ejecutar([_partida("SFC102"), _partida("SFC102")])
        self.assertEqual(resumen["estado"], "OK_SIN_DUPLICADOS")
        self.assertEqual(resumen["asignaciones_excluidas"], 2)

    def test_tiquipaya_ago_repetido_excluido(self):
        resumen = self._ejecutar([_partida("TIQUIPAYA AGO"), _partida("TIQUIPAYA AGO")])
        self.assertEqual(resumen["estado"], "OK_SIN_DUPLICADOS")
        self.assertEqual(resumen["asignaciones_excluidas"], 2)

    def test_cuenta_110201008_con_tiquipaya_ago_excluido(self):
        resumen = self._ejecutar([_partida("TIQUIPAYA AGO", cuenta_mayor="110201008")])
        self.assertEqual(resumen["estado"], "OK_SIN_DUPLICADOS")
        self.assertEqual(resumen["asignaciones_excluidas"], 1)
        self.assertEqual(resumen["asignaciones_evaluadas"], 0)

    def test_cuenta_110201008_con_revisar_excluido(self):
        resumen = self._ejecutar([_partida("REVISAR", cuenta_mayor="110201008")])
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

    def test_fortaleza_siempre_se_evalua(self):
        # FORTALEZA nunca está en las exclusiones: una única aparición no
        # genera alerta, pero SÍ se cuenta como evaluada (no excluida).
        resumen = self._ejecutar([_partida("FORTALEZA")])
        self.assertEqual(resumen["estado"], "OK_SIN_DUPLICADOS")
        self.assertEqual(resumen["asignaciones_evaluadas"], 1)
        self.assertEqual(resumen["asignaciones_excluidas"], 0)


# ---------------------------------------------------------------------------
# FORTALEZA y otras asignaciones repetidas dentro del mismo GLOBAL
# ---------------------------------------------------------------------------

class TestDuplicadosMismoGlobal(_ControlAsignacionesTestBase):
    def test_fortaleza_repetida_revisar(self):
        resumen = self._ejecutar([_partida("FORTALEZA"), _partida("FORTALEZA")])
        self.assertEqual(resumen["estado"], "REVISAR_DUPLICADOS_ENCONTRADOS")
        self.assertEqual(resumen["estado_validacion"], "PENDIENTE_VALIDACION_AUDITOR")
        self.assertEqual(resumen["asignaciones_duplicadas"], ["FORTALEZA"])
        self.assertEqual(resumen["cantidad_hallazgos"], 1)

    def test_otra_asignacion_repetida_mismo_global_revisar(self):
        resumen = self._ejecutar([_partida("ASIG-X"), _partida("ASIG-X")])
        self.assertEqual(resumen["estado"], "REVISAR_DUPLICADOS_ENCONTRADOS")
        self.assertEqual(resumen["estado_validacion"], "PENDIENTE_VALIDACION_AUDITOR")
        self.assertEqual(resumen["asignaciones_duplicadas"], ["ASIG-X"])


# ---------------------------------------------------------------------------
# Hallazgo contra histórico y preservación de datos en el JSON "por par"
# ---------------------------------------------------------------------------

class TestHallazgoContraHistorico(_ControlAsignacionesTestBase):
    def test_asignacion_repetida_contra_historico_revisar(self):
        ca.guardar_historico(self.ruta_historico, [{
            "asignacion": "ASIG-HIST", "fecha_valor": "2026-07-01",
            "cuenta_mayor": "110101001", "glosa": "GLOSA PREVIA", "monto": "50.00",
            "archivo_global": "SAP_GLOBAL_TIQ_JULIO_2026.xlsx", "fila_sap": "16",
            "sha256_archivo": "sha_previo", "fecha_incorporacion": "2026-07-31T00:00:00",
            "alerta_duplicado": "SIN_ALERTA", "validacion_auditor": "",
            "observacion_auditor": "", "fecha_validacion": "",
        }])
        resumen = self._ejecutar([_partida("ASIG-HIST", glosa="GLOSA NUEVA",
                                            fecha_valor=datetime.date(2026, 8, 3),
                                            cargo="75.00")])
        self.assertEqual(resumen["estado"], "REVISAR_DUPLICADOS_ENCONTRADOS")
        self.assertEqual(resumen["estado_validacion"], "PENDIENTE_VALIDACION_AUDITOR")
        self.assertFalse(resumen["historico_actualizado"])
        self.assertEqual(resumen["filas_incorporadas_historico"], 0)

    def test_glosa_completa_preservada_en_hallazgo(self):
        glosa_larga = "RECAUDACION CAJA SFC101 - GLOSA COMPLETA DE PRUEBA CON DETALLE"
        resumen = self._ejecutar([
            _partida("ASIG-Y", glosa=glosa_larga),
            _partida("ASIG-Y", glosa=glosa_larga),
        ], ruta_detalle_json=os.path.join(self.tmpdir, "detalle.json"))
        with open(resumen["detalle_json"], encoding="utf-8") as f:
            detalle = json.load(f)
        self.assertEqual(detalle["hallazgos"][0]["glosa"], glosa_larga)

    def test_fecha_preservada_en_hallazgo(self):
        fecha = datetime.date(2026, 8, 15)
        resumen = self._ejecutar([
            _partida("ASIG-Z", fecha_valor=fecha),
            _partida("ASIG-Z", fecha_valor=fecha),
        ], ruta_detalle_json=os.path.join(self.tmpdir, "detalle.json"))
        with open(resumen["detalle_json"], encoding="utf-8") as f:
            detalle = json.load(f)
        self.assertEqual(detalle["hallazgos"][0]["fecha"], fecha.isoformat())

    def test_monto_preservado_en_hallazgo(self):
        resumen = self._ejecutar([
            _partida("ASIG-M", cargo="1234.56"),
            _partida("ASIG-M", cargo="1234.56"),
        ], ruta_detalle_json=os.path.join(self.tmpdir, "detalle.json"))
        with open(resumen["detalle_json"], encoding="utf-8") as f:
            detalle = json.load(f)
        self.assertEqual(detalle["hallazgos"][0]["monto"], "1234.56")

    def test_archivo_y_filas_relacionadas_preservadas(self):
        resumen = self._ejecutar([
            _partida("ASIG-R"),
            _partida("ASIG-R"),
        ], nombre_archivo_global=self.NOMBRE_GLOBAL_AGOSTO,
           ruta_detalle_json=os.path.join(self.tmpdir, "detalle.json"))
        with open(resumen["detalle_json"], encoding="utf-8") as f:
            detalle = json.load(f)
        hallazgo = detalle["hallazgos"][0]
        self.assertEqual(hallazgo["archivo_global"], self.NOMBRE_GLOBAL_AGOSTO)
        self.assertEqual(hallazgo["archivo_relacionado"], self.NOMBRE_GLOBAL_AGOSTO)
        self.assertEqual(hallazgo["fila_sap"], 16)
        self.assertEqual(hallazgo["fila_sap_relacionada"], 17)


# ---------------------------------------------------------------------------
# Detalle JSON: "hallazgos" (por par, compatibilidad) + "alertas" (nuevo,
# por asignación) coexisten.
# ---------------------------------------------------------------------------

class TestDetalleJson(_ControlAsignacionesTestBase):
    def test_json_conserva_hallazgos_por_par_y_agrega_alertas_por_asignacion(self):
        glosa_larga = "RECAUDACION CAJA SFC101 - GLOSA COMPLETA DE PRUEBA CON DETALLE"
        resumen = self._ejecutar([
            _partida("ASIG-Y", glosa=glosa_larga),
            _partida("ASIG-Y", glosa=glosa_larga),
        ], ruta_detalle_json=os.path.join(self.tmpdir, "detalle.json"))

        with open(resumen["detalle_json"], encoding="utf-8") as f:
            detalle = json.load(f)

        self.assertEqual(detalle["hallazgos"][0]["glosa"], glosa_larga)
        self.assertEqual(len(detalle["alertas"]), 1)
        self.assertEqual(detalle["alertas"][0]["ASIGNACION"], "ASIG-Y")


# ---------------------------------------------------------------------------
# Idempotencia (SHA idéntico / archivo_global con SHA distinto / revisión
# de un SHA anterior que no se aplica en silencio)
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
        nombre = self.NOMBRE_GLOBAL_AGOSTO
        ca.guardar_historico(self.ruta_historico, [{
            "asignacion": "ASIG-1", "fecha_valor": "2026-08-01",
            "cuenta_mayor": "110101001", "glosa": "GLOSA", "monto": "10.00",
            "archivo_global": nombre, "fila_sap": "16",
            "sha256_archivo": "sha_diferente_al_actual",
            "fecha_incorporacion": "2026-08-31T00:00:00",
            "alerta_duplicado": "SIN_ALERTA", "validacion_auditor": "",
            "observacion_auditor": "", "fecha_validacion": "",
        }])
        resumen = self._ejecutar([_partida("ASIG-1")], ruta_global=self._ruta_global(nombre))
        self.assertEqual(resumen["estado"], "GLOBAL_MODIFICADO_REQUIERE_REVISION")
        self.assertEqual(resumen["sha256_historico_existente"], "sha_diferente_al_actual")
        self.assertFalse(resumen["historico_actualizado"])

    def test_global_modificado_no_modifica_historico(self):
        nombre = self.NOMBRE_GLOBAL_AGOSTO
        fila_previa = {
            "asignacion": "ASIG-1", "fecha_valor": "2026-08-01",
            "cuenta_mayor": "110101001", "glosa": "GLOSA", "monto": "10.00",
            "archivo_global": nombre, "fila_sap": "16",
            "sha256_archivo": "sha_diferente_al_actual",
            "fecha_incorporacion": "2026-08-31T00:00:00",
            "alerta_duplicado": "SIN_ALERTA", "validacion_auditor": "",
            "observacion_auditor": "", "fecha_validacion": "",
        }
        ca.guardar_historico(self.ruta_historico, [fila_previa])
        self._ejecutar([_partida("ASIG-1")], ruta_global=self._ruta_global(nombre))

        historico_final = _leer_csv(self.ruta_historico)
        self.assertEqual(len(historico_final), 1)
        self.assertEqual(historico_final[0]["sha256_archivo"], "sha_diferente_al_actual")

    def test_revision_de_sha_anterior_no_se_aplica_en_silencio(self):
        # El auditor ya había validado CORRECTA para una versión anterior
        # (otro SHA) del GLOBAL de agosto; el GLOBAL cambia de contenido
        # antes de cerrarse -> esa validación NO debe reutilizarse.
        ruta_global = self._ruta_global()
        _crear_global(ruta_global, [_partida("ASIG-A"), _partida("ASIG-A")])
        sha_actual = ca._hash_archivo(ruta_global)
        self._escribir_revision("AGOSTO_2026", [
            self._fila_revision("AGOSTO_2026", "ASIG-A", "sha_anterior_distinto",
                                 validacion="CORRECTA"),
        ])
        resumen = ca.ejecutar_control(ruta_global=ruta_global, ruta_historico=self.ruta_historico)
        self.assertEqual(resumen["estado"], "REVISAR_DUPLICADOS_ENCONTRADOS")
        self.assertEqual(resumen["estado_validacion"], "PENDIENTE_VALIDACION_AUDITOR")
        revision = _leer_csv(self._ruta_revision("AGOSTO_2026"))
        self.assertEqual(revision[0]["VALIDACION_AUDITOR"], "")
        self.assertEqual(revision[0]["SHA256_GLOBAL"], sha_actual)


# ---------------------------------------------------------------------------
# hoja EXACTA "1" obligatoria, sin fallback — sin cambios
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
        _crear_global(ruta_global, [_partida("ASIG-1"), _partida("ASIG-1")], hoja="Hoja1")
        resumen = ca.ejecutar_control(ruta_global=ruta_global, ruta_historico=self.ruta_historico)
        self.assertEqual(resumen["estado"], "ERROR_TECNICO")
        self.assertIn("GLOBAL_HOJA_1_NO_ENCONTRADA", resumen["problemas"])
        self.assertNotIn("filas_leidas_global", resumen)


# ---------------------------------------------------------------------------
# Periodo canónico OBLIGATORIO — SIN fallback
# ---------------------------------------------------------------------------

class TestPeriodoCanonico(_ControlAsignacionesTestBase):
    def test_nombre_no_canonico_detiene_el_control(self):
        ruta_global = self._ruta_global("GLOBAL_AGOSTO_2026.xlsx")  # no sigue SAP_GLOBAL_TIQ_...
        _crear_global(ruta_global, [_partida("ASIG-1"), _partida("ASIG-1")])
        resumen = ca.ejecutar_control(ruta_global=ruta_global, ruta_historico=self.ruta_historico)

        self.assertEqual(resumen["estado"], "ERROR_TECNICO")
        self.assertIn("GLOBAL_NOMBRE_NO_CANONICO", resumen["problemas"])
        self.assertFalse(os.path.isfile(self.ruta_historico))
        revisiones = [f for f in os.listdir(self.tmpdir) if f.startswith("REVISION_ASIGNACIONES_")]
        self.assertEqual(revisiones, [])

    def test_nombre_no_canonico_sin_anio_detiene_el_control(self):
        ruta_global = self._ruta_global("SAP_GLOBAL_TIQ_AGOSTO.xlsx")  # falta el año
        _crear_global(ruta_global, [_partida("ASIG-1")])
        resumen = ca.ejecutar_control(ruta_global=ruta_global, ruta_historico=self.ruta_historico)
        self.assertEqual(resumen["estado"], "ERROR_TECNICO")
        self.assertIn("GLOBAL_NOMBRE_NO_CANONICO", resumen["problemas"])

    def test_nombre_canonico_deriva_periodo_correctamente(self):
        resumen = self._ejecutar([_partida("ASIG-1")])
        self.assertEqual(resumen["periodo"], "AGOSTO_2026")


# ---------------------------------------------------------------------------
# Política de escritura del histórico (duplicados / OK / dry-run) — SIN
# CAMBIOS de comportamiento, solo de nombre de estado (ver estado_validacion)
# ---------------------------------------------------------------------------

class TestPoliticaEscrituraHistorico(_ControlAsignacionesTestBase):
    def test_global_con_duplicados_no_actualiza_historico(self):
        resumen = self._ejecutar([_partida("ASIG-DUP"), _partida("ASIG-DUP")])
        self.assertEqual(resumen["estado"], "REVISAR_DUPLICADOS_ENCONTRADOS")
        self.assertEqual(resumen["estado_validacion"], "PENDIENTE_VALIDACION_AUDITOR")
        self.assertFalse(resumen["historico_actualizado"])
        self.assertEqual(resumen["filas_incorporadas_historico"], 0)
        self.assertFalse(os.path.isfile(self.ruta_historico))

        revision = _leer_csv(self._ruta_revision("AGOSTO_2026"))
        self.assertEqual(len(revision), 1)  # una fila por asignación, no por par
        self.assertEqual(revision[0]["ASIGNACION"], "ASIG-DUP")
        self.assertEqual(revision[0]["TIPO_ALERTA"], "DUPLICADA_MISMO_MES")
        self.assertEqual(revision[0]["VALIDACION_AUDITOR"], "")

    def test_global_sin_duplicados_actualiza_historico(self):
        resumen = self._ejecutar([_partida("ASIG-OK-1"), _partida("ASIG-OK-2")])
        self.assertEqual(resumen["estado"], "OK_SIN_DUPLICADOS")
        self.assertTrue(resumen["historico_actualizado"])
        self.assertEqual(resumen["filas_incorporadas_historico"], 2)
        historico = _leer_csv(self.ruta_historico)
        self.assertEqual(len(historico), 2)
        for fila in historico:
            self.assertEqual(fila["alerta_duplicado"], "SIN_ALERTA")
            self.assertEqual(fila["validacion_auditor"], "")

    def test_dry_run_nunca_actualiza_historico(self):
        resumen = self._ejecutar([_partida("ASIG-OK-1")], dry_run=True)
        self.assertEqual(resumen["estado"], "OK_SIN_DUPLICADOS")
        self.assertTrue(resumen["dry_run"])
        self.assertFalse(resumen["historico_actualizado"])
        self.assertEqual(resumen["filas_incorporadas_historico"], 0)
        self.assertFalse(os.path.isfile(self.ruta_historico))

    def test_dry_run_con_duplicados_no_escribe_revision_ni_historico(self):
        resumen = self._ejecutar([_partida("ASIG-DUP"), _partida("ASIG-DUP")], dry_run=True)
        self.assertEqual(resumen["estado"], "REVISAR_DUPLICADOS_ENCONTRADOS")
        self.assertEqual(resumen["estado_validacion"], "PENDIENTE_VALIDACION_AUDITOR")
        self.assertTrue(resumen["dry_run"])
        self.assertFalse(resumen["historico_actualizado"])
        self.assertFalse(resumen["revision_actualizada"])
        self.assertFalse(os.path.isfile(self.ruta_historico))
        self.assertFalse(os.path.isfile(self._ruta_revision("AGOSTO_2026")))


# ---------------------------------------------------------------------------
# Cierre del mes: revisión parcial / total, CORRECTA/INCORRECTA, y una
# validación anterior que NUNCA evita una alerta futura.
# ---------------------------------------------------------------------------

class TestValidacionHumana(_ControlAsignacionesTestBase):
    def test_revision_parcial_no_actualiza_historico(self):
        ruta_global = self._ruta_global()
        _crear_global(ruta_global, [
            _partida("ASIG-A"), _partida("ASIG-A"),
            _partida("ASIG-B"), _partida("ASIG-B"),
        ])
        sha = ca._hash_archivo(ruta_global)
        self._escribir_revision("AGOSTO_2026", [
            self._fila_revision("AGOSTO_2026", "ASIG-A", sha, validacion="CORRECTA"),
            self._fila_revision("AGOSTO_2026", "ASIG-B", sha, validacion=""),
        ])
        resumen = ca.ejecutar_control(ruta_global=ruta_global, ruta_historico=self.ruta_historico)
        self.assertEqual(resumen["estado"], "REVISAR_DUPLICADOS_ENCONTRADOS")
        self.assertEqual(resumen["estado_validacion"], "PENDIENTE_VALIDACION_AUDITOR")
        self.assertFalse(resumen["historico_actualizado"])
        self.assertEqual(resumen["alertas_correctas"], 1)
        self.assertEqual(resumen["alertas_pendientes_validacion"], 1)

    def test_todas_correctas_actualiza_historico(self):
        ruta_global = self._ruta_global()
        _crear_global(ruta_global, [_partida("ASIG-A"), _partida("ASIG-A")])
        sha = ca._hash_archivo(ruta_global)
        self._escribir_revision("AGOSTO_2026", [
            self._fila_revision("AGOSTO_2026", "ASIG-A", sha, validacion="CORRECTA",
                                 observacion="Confirmado con banco"),
        ])
        resumen = ca.ejecutar_control(ruta_global=ruta_global, ruta_historico=self.ruta_historico)
        self.assertEqual(resumen["estado"], "REVISAR_DUPLICADOS_ENCONTRADOS")
        self.assertEqual(resumen["estado_validacion"], "CERRADO_CON_VALIDACION_AUDITOR")
        self.assertTrue(resumen["historico_actualizado"])
        self.assertEqual(resumen["filas_incorporadas_historico"], 2)

        historico = _leer_csv(self.ruta_historico)
        self.assertEqual(len(historico), 2)
        for fila in historico:
            self.assertEqual(fila["validacion_auditor"], "CORRECTA")
            self.assertEqual(fila["observacion_auditor"], "Confirmado con banco")
            self.assertEqual(fila["alerta_duplicado"], "DUPLICADA_MISMO_MES")

    def test_alguna_incorrecta_pero_todas_revisadas_registra_hechos_y_decisiones(self):
        ruta_global = self._ruta_global()
        _crear_global(ruta_global, [
            _partida("ASIG-A"), _partida("ASIG-A"),
            _partida("ASIG-B"), _partida("ASIG-B"),
        ])
        sha = ca._hash_archivo(ruta_global)
        self._escribir_revision("AGOSTO_2026", [
            self._fila_revision("AGOSTO_2026", "ASIG-A", sha, validacion="CORRECTA"),
            self._fila_revision("AGOSTO_2026", "ASIG-B", sha, validacion="INCORRECTA",
                                 observacion="Error de digitación, corregir el próximo mes"),
        ])
        resumen = ca.ejecutar_control(ruta_global=ruta_global, ruta_historico=self.ruta_historico)
        self.assertEqual(resumen["estado"], "REVISAR_DUPLICADOS_ENCONTRADOS")
        self.assertEqual(resumen["estado_validacion"], "CERRADO_CON_VALIDACION_AUDITOR")
        self.assertTrue(resumen["historico_actualizado"])
        self.assertEqual(resumen["alertas_correctas"], 1)
        self.assertEqual(resumen["alertas_incorrectas"], 1)
        self.assertEqual(resumen["alertas_pendientes_validacion"], 0)

        historico = _leer_csv(self.ruta_historico)
        por_asignacion = {}
        for fila in historico:
            por_asignacion.setdefault(fila["asignacion"], []).append(fila)
        for fila in por_asignacion["ASIG-A"]:
            self.assertEqual(fila["validacion_auditor"], "CORRECTA")
        for fila in por_asignacion["ASIG-B"]:
            self.assertEqual(fila["validacion_auditor"], "INCORRECTA")
            self.assertEqual(fila["observacion_auditor"],
                              "Error de digitación, corregir el próximo mes")

    def test_validada_correcta_en_agosto_vuelve_a_alertar_en_septiembre(self):
        # AGOSTO: se cierra con 3P66536982 validada CORRECTA.
        ruta_agosto = self._ruta_global(self.NOMBRE_GLOBAL_AGOSTO)
        _crear_global(ruta_agosto, [_partida("3P66536982"), _partida("3P66536982")])
        sha_agosto = ca._hash_archivo(ruta_agosto)
        self._escribir_revision("AGOSTO_2026", [
            self._fila_revision("AGOSTO_2026", "3P66536982", sha_agosto, validacion="CORRECTA",
                                 observacion="Cliente confirmó doble depósito legítimo"),
        ])
        resumen_agosto = ca.ejecutar_control(ruta_global=ruta_agosto, ruta_historico=self.ruta_historico)
        self.assertEqual(resumen_agosto["estado"], "REVISAR_DUPLICADOS_ENCONTRADOS")
        self.assertEqual(resumen_agosto["estado_validacion"], "CERRADO_CON_VALIDACION_AUDITOR")
        self.assertTrue(resumen_agosto["historico_actualizado"])

        # SEPTIEMBRE: la misma asignación reaparece una sola vez -> alerta
        # DUPLICADA_CON_HISTORICO, PENDIENTE de nueva validación.
        ruta_septiembre = self._ruta_global(self.NOMBRE_GLOBAL_SEPTIEMBRE)
        _crear_global(ruta_septiembre, [_partida("3P66536982", fecha_valor=datetime.date(2026, 9, 3))])
        resumen_sept = ca.ejecutar_control(ruta_global=ruta_septiembre, ruta_historico=self.ruta_historico)

        self.assertEqual(resumen_sept["estado"], "REVISAR_DUPLICADOS_ENCONTRADOS")
        self.assertEqual(resumen_sept["estado_validacion"], "PENDIENTE_VALIDACION_AUDITOR")
        self.assertFalse(resumen_sept["historico_actualizado"])

        revision_sept = _leer_csv(self._ruta_revision("SEPTIEMBRE_2026"))
        self.assertEqual(len(revision_sept), 1)
        self.assertEqual(revision_sept[0]["TIPO_ALERTA"], "DUPLICADA_CON_HISTORICO")
        self.assertEqual(revision_sept[0]["VALIDACION_AUDITOR"], "")
        # El antecedente (agosto, CORRECTA) queda como contexto en el DETALLE.
        self.assertIn("AGOSTO_2026", revision_sept[0]["DETALLE"])
        self.assertIn("CORRECTA", revision_sept[0]["DETALLE"])

    def test_conserva_observacion_humana_al_reejecutar(self):
        ruta_global = self._ruta_global()
        _crear_global(ruta_global, [_partida("ASIG-A"), _partida("ASIG-A")])
        sha = ca._hash_archivo(ruta_global)
        self._escribir_revision("AGOSTO_2026", [
            self._fila_revision("AGOSTO_2026", "ASIG-A", sha, validacion="",
                                 observacion="Pendiente de confirmar con el cliente"),
        ])
        resumen = ca.ejecutar_control(ruta_global=ruta_global, ruta_historico=self.ruta_historico)
        self.assertEqual(resumen["estado_validacion"], "PENDIENTE_VALIDACION_AUDITOR")

        revision = _leer_csv(self._ruta_revision("AGOSTO_2026"))
        self.assertEqual(revision[0]["OBSERVACION_AUDITOR"], "Pendiente de confirmar con el cliente")


# ---------------------------------------------------------------------------
# Reproceso, inmutabilidad del origen, preservación del histórico
# ---------------------------------------------------------------------------

class TestReprocesoEInmutabilidad(_ControlAsignacionesTestBase):
    def test_reproceso_identico_historico_sin_cambios(self):
        ruta_global = self._ruta_global()
        _crear_global(ruta_global, [_partida("ASIG-1"), _partida("ASIG-2")])
        ca.ejecutar_control(ruta_global=ruta_global, ruta_historico=self.ruta_historico)
        historico_tras_primero = _leer_csv(self.ruta_historico)

        ca.ejecutar_control(ruta_global=ruta_global, ruta_historico=self.ruta_historico)
        historico_tras_segundo = _leer_csv(self.ruta_historico)

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
            "alerta_duplicado": "SIN_ALERTA", "validacion_auditor": "",
            "observacion_auditor": "", "fecha_validacion": "",
        }
        ca.guardar_historico(self.ruta_historico, [fila_previa])

        self._ejecutar([_partida("ASIG-NUEVA")])

        historico_final = _leer_csv(self.ruta_historico)
        self.assertEqual(len(historico_final), 2)
        self.assertIn(fila_previa["asignacion"], [f["asignacion"] for f in historico_final])
        self.assertEqual(historico_final[0], fila_previa)


# ---------------------------------------------------------------------------
# Histórico con esquema antiguo (sin columnas de validación) se lee y se
# reescribe sin perder información.
# ---------------------------------------------------------------------------

class TestMigracionEsquemaAntiguo(_ControlAsignacionesTestBase):
    ESQUEMA_ANTIGUO = [
        "asignacion", "fecha_valor", "cuenta_mayor", "glosa", "monto",
        "archivo_global", "fila_sap", "sha256_archivo", "fecha_incorporacion",
    ]

    def _escribir_historico_esquema_antiguo(self, filas):
        with open(self.ruta_historico, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=self.ESQUEMA_ANTIGUO)
            writer.writeheader()
            for fila in filas:
                writer.writerow(fila)

    def test_historico_esquema_antiguo_se_lee_y_conserva_al_actualizar(self):
        fila_vieja = {
            "asignacion": "ASIG-VIEJA", "fecha_valor": "2026-07-01",
            "cuenta_mayor": "110101001", "glosa": "GLOSA VIEJA", "monto": "20.00",
            "archivo_global": "SAP_GLOBAL_TIQ_JULIO_2026.xlsx", "fila_sap": "16",
            "sha256_archivo": "sha_julio", "fecha_incorporacion": "2026-07-31T00:00:00",
        }
        self._escribir_historico_esquema_antiguo([fila_vieja])

        resumen = self._ejecutar([_partida("ASIG-NUEVA")])
        self.assertEqual(resumen["estado"], "OK_SIN_DUPLICADOS")

        historico_final = _leer_csv(self.ruta_historico)
        self.assertEqual(len(historico_final), 2)
        fila_vieja_final = next(f for f in historico_final if f["asignacion"] == "ASIG-VIEJA")
        for col, valor in fila_vieja.items():
            self.assertEqual(fila_vieja_final[col], valor)
        # Columnas nuevas: vacías para la fila vieja (nunca se inventan).
        self.assertEqual(fila_vieja_final["validacion_auditor"], "")

        fila_nueva_final = next(f for f in historico_final if f["asignacion"] == "ASIG-NUEVA")
        self.assertEqual(fila_nueva_final["alerta_duplicado"], "SIN_ALERTA")


# ---------------------------------------------------------------------------
# Sin dependencias externas / sin acoplamiento con el V2 diario
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
