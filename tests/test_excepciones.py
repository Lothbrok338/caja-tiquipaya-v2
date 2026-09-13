"""test_excepciones.py — FASE 1: excepciones[] estructuradas (Voucher /
Comunicación Interna / ATC).

No prueba reglas de validación nuevas: cada caso reutiliza exactamente el
mismo fixture/estado que ya cubren tests/test_cruces.py,
tests/test_asiento.py, tests/test_atc_preconciliado.py,
tests/test_pipeline_tiquipaya.py y tests/test_run_batch.py, y confirma
primero que el estado/bloqueo (estado del voucher, tipo de bloqueante CI,
estado_validacion ATC, excepciones_bloqueantes, estado final del cierre)
es EXACTAMENTE el mismo que antes de la Fase 1. Solo después verifica que
se agregó el detalle estructurado nuevo (excepciones[]), y que ese detalle
llega tal cual hasta RESULTADO_TIQ_<fecha>.json y resultado_batch.json.

Uso: python -m unittest tests.test_excepciones -v
"""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import motor_tiquipaya as motor
import pipeline_tiquipaya as pipeline
import run_batch
from tests import xlsx_fixtures as fx
from tests.test_cruces import FECHA_CIERRE, _cierre_voucher, _macros_por_importe, _cierre_atc
from tests.test_pipeline_tiquipaya import _BasePipeline
from tests.test_regresion_sintetica import _baseline_sfc101, _baseline_sfc102
from tests.test_atc_preconciliado import _fila_neto, _fila_comision
from tests.test_run_batch import _BaseDosDias, FECHA_A


# ---------------------------------------------------------------------------
# Voucher: NO_ENCONTRADO / MULTIPLE / POSIBLE_TYPO
# ---------------------------------------------------------------------------

class TestExcepcionesVoucher(unittest.TestCase):
    def test_no_encontrado(self):
        macros_idx = _macros_por_importe([])
        cierre = _cierre_voucher("VCH-INEXISTENTE", "500.00")
        vouchers = motor.cruzar_vouchers(cierre, macros_idx)
        r = vouchers["detalle"][0]

        # Bloqueo sin cambios: mismo estado que ya validaba test_cruces.py.
        self.assertEqual(r["estado"], "NO_ENCONTRADO")
        self.assertEqual(vouchers["conteo"]["NO_ENCONTRADO"], 1)

        excepciones = motor._excepciones_voucher(vouchers)
        self.assertEqual(len(excepciones), 1)
        exc = excepciones[0]
        self.assertEqual(exc["categoria"], "VOUCHER")
        self.assertEqual(exc["tipo"], "NO_ENCONTRADO")
        self.assertEqual(exc["sfc"], "SFC101")
        self.assertEqual(exc["codigo_informado"], "VCH-INEXISTENTE")
        self.assertEqual(exc["importe"], "500.00")
        self.assertEqual(exc["candidatos"], [])  # normalizado: siempre lista, vacía aquí
        self.assertEqual(exc["cantidad_candidatos"], 0)
        self.assertTrue(exc["motivo_legible"])

    def test_multiple(self):
        macros_idx = _macros_por_importe([
            {"codigo": "XOO1", "importe": "500.00", "fecha": FECHA_CIERRE},
            {"codigo": "X001", "importe": "500.00", "fecha": FECHA_CIERRE},
        ])
        cierre = _cierre_voucher("X0O1", "500.00")
        vouchers = motor.cruzar_vouchers(cierre, macros_idx)
        r = vouchers["detalle"][0]

        self.assertEqual(r["estado"], "MULTIPLE")

        excepciones = motor._excepciones_voucher(vouchers)
        exc = excepciones[0]
        self.assertEqual(exc["tipo"], "MULTIPLE")
        # Normalizado: lista real de candidatos (antes solo se exponía el
        # conteo), más cantidad_candidatos como entero derivado.
        self.assertIsInstance(exc["candidatos"], list)
        self.assertEqual(exc["cantidad_candidatos"], 2)
        self.assertEqual(
            {c["codigo"] for c in exc["candidatos"]}, {"XOO1", "X001"}
        )

    def test_posible_typo(self):
        macros_idx = _macros_por_importe([
            {"codigo": "ABO123", "importe": "500.00", "fecha": FECHA_CIERRE},
        ])
        cierre = _cierre_voucher("ABP123", "500.00")
        vouchers = motor.cruzar_vouchers(cierre, macros_idx)
        r = vouchers["detalle"][0]

        self.assertEqual(r["estado"], "POSIBLE_TYPO")

        excepciones = motor._excepciones_voucher(vouchers)
        exc = excepciones[0]
        self.assertEqual(exc["tipo"], "POSIBLE_TYPO")
        self.assertEqual(exc["candidatos"], [{"codigo": "ABO123", "fecha": FECHA_CIERRE}])
        self.assertEqual(exc["cantidad_candidatos"], 1)


# ---------------------------------------------------------------------------
# Comunicación Interna: CI_CUENTA_FALTANTE / CI_ASIGNACION_FALTANTE /
# CI_IMPORTE_NEGATIVO
# ---------------------------------------------------------------------------

class TestExcepcionesCi(unittest.TestCase):
    def test_ci_cuenta_faltante(self):
        cierre = {"comunicaciones_internas": [{
            "sfc": "SFC101", "referencia": "F-1", "importe": "100.00",
            "cuenta_contable": None, "asignacion": "CI0001",
            "banco": "BNB", "alquileres": False,
            "glosa": "AJUSTE VARIOS", "fecha_ci": "2026-09-02",
        }]}
        resultado = motor.validar_ci(cierre)

        # Bloqueo sin cambios: mismo tipo que ya validaba test_asiento.py.
        self.assertEqual(len(resultado["bloqueantes"]), 1)
        self.assertEqual(resultado["bloqueantes"][0]["tipo"], "CI_CUENTA_FALTANTE")

        excepciones = motor._excepciones_ci(resultado)
        self.assertEqual(len(excepciones), 1)
        exc = excepciones[0]
        self.assertEqual(exc["categoria"], "COMUNICACION_INTERNA")
        self.assertEqual(exc["tipo"], "CI_CUENTA_FALTANTE")
        self.assertEqual(exc["sfc"], "SFC101")
        self.assertEqual(exc["factura"], "F-1")
        self.assertEqual(exc["importe"], "100.00")
        self.assertEqual(exc["fecha"], "2026-09-02")
        self.assertEqual(exc["glosa"], "AJUSTE VARIOS")
        self.assertIsNone(exc["cuenta_contable"])  # motivo real del bloqueo
        self.assertEqual(exc["asignacion"], "CI0001")  # disponible aunque no sea la causa
        self.assertTrue(exc["motivo_legible"])

    def test_ci_asignacion_faltante(self):
        cierre = {"comunicaciones_internas": [{
            "sfc": "SFC101", "referencia": "F-1", "importe": "100.00",
            "cuenta_contable": "210201005", "asignacion": None,
            "banco": "BNB", "alquileres": False,
        }]}
        resultado = motor.validar_ci(cierre)

        self.assertEqual(resultado["bloqueantes"][0]["tipo"], "CI_ASIGNACION_FALTANTE")

        exc = motor._excepciones_ci(resultado)[0]
        self.assertEqual(exc["tipo"], "CI_ASIGNACION_FALTANTE")
        self.assertEqual(exc["cuenta_contable"], "210201005")  # disponible
        self.assertIsNone(exc["asignacion"])  # motivo real del bloqueo

    def test_ci_importe_negativo(self):
        cierre = {"comunicaciones_internas": [{
            "sfc": "SFC101", "referencia": "F-1", "importe": "-50.00",
            "cuenta_contable": "210201005", "asignacion": "CI0001",
            "banco": "BNB", "alquileres": False,
        }]}
        resultado = motor.validar_ci(cierre)

        self.assertEqual(resultado["bloqueantes"][0]["tipo"], "CI_IMPORTE_NEGATIVO")

        exc = motor._excepciones_ci(resultado)[0]
        self.assertEqual(exc["tipo"], "CI_IMPORTE_NEGATIVO")
        self.assertEqual(exc["importe"], "-50.00")
        self.assertEqual(exc["cuenta_contable"], "210201005")
        self.assertEqual(exc["asignacion"], "CI0001")


# ---------------------------------------------------------------------------
# ATC: ATC_DIFERENCIA / ATC_FECHA_NO_ENCONTRADA (modo PRECONCILIADO, el
# actual — ver auditoría: modo LEGADO no expone estas cuentas/asignaciones
# porque esa hoja nunca las trae).
# ---------------------------------------------------------------------------

class TestExcepcionesAtc(unittest.TestCase):
    def test_atc_diferencia(self):
        cierre = _cierre_atc("130883.00")
        atc_por_fecha = {
            FECHA_CIERRE: {
                "neto": {"monto": "130246.43", "cuenta_contable": "110103012",
                         "detalle": "ATC COCHABAMBA", "asignacion": "3P02891953"},
                # comision manipulada para que NETO + COMISION != BRUTO.
                "comision": {"monto": "1.00", "cuenta_contable": "110201008",
                             "detalle": "COMISION ATC", "asignacion": "TIQUIPAYA AGO"},
            }
        }
        atc = motor.cruzar_atc_preconciliado(cierre, atc_por_fecha)

        # Bloqueo sin cambios: misma validación de siempre (NETO+COMISION==BRUTO).
        self.assertEqual(atc["estado_validacion"], "ATC_DIFERENCIA")
        self.assertTrue(atc["excepcion"])

        excepciones = motor._excepciones_atc(atc)
        self.assertEqual(len(excepciones), 1)
        exc = excepciones[0]
        self.assertEqual(exc["categoria"], "ATC")
        self.assertEqual(exc["tipo"], "ATC_DIFERENCIA")
        self.assertEqual(exc["bruto"], "130883.00")
        self.assertEqual(exc["neto"], "130246.43")
        self.assertEqual(exc["comision"], "1.00")
        self.assertEqual(exc["diferencia"], "-635.57")
        # La fila SÍ existe (solo el importe no cuadra): todos los campos
        # de la fila están disponibles, confirmado por lectura directa.
        self.assertEqual(exc["neto_cuenta_contable"], "110103012")
        self.assertEqual(exc["neto_asignacion"], "3P02891953")
        self.assertEqual(exc["comision_cuenta_contable"], "110201008")
        self.assertEqual(exc["comision_asignacion"], "TIQUIPAYA AGO")

    def test_atc_fecha_no_encontrada(self):
        cierre = _cierre_atc("130883.00")
        atc = motor.cruzar_atc_preconciliado(cierre, {})  # sin fila para la fecha

        self.assertEqual(atc["estado_validacion"], "ATC_FECHA_NO_ENCONTRADA")
        self.assertTrue(atc["excepcion"])

        exc = motor._excepciones_atc(atc)[0]
        self.assertEqual(exc["tipo"], "ATC_FECHA_NO_ENCONTRADA")
        self.assertEqual(exc["bruto"], "130883.00")  # siempre disponible
        # No hay fila: genuinamente no existe nada más que leer.
        self.assertIsNone(exc["neto"])
        self.assertIsNone(exc["comision"])
        self.assertIsNone(exc["diferencia"])
        self.assertIsNone(exc["neto_cuenta_contable"])
        self.assertIsNone(exc["neto_asignacion"])
        self.assertIsNone(exc["comision_cuenta_contable"])
        self.assertIsNone(exc["comision_asignacion"])


# ---------------------------------------------------------------------------
# Propagación end-to-end: motor -> pipeline -> RESULTADO_TIQ_<fecha>.json
# ---------------------------------------------------------------------------

class TestPropagacionResultadoJson(_BasePipeline):
    def test_voucher_no_encontrado_llega_a_resultado_json(self):
        sfc101 = _baseline_sfc101()
        sfc101["depositos"][0]["asignacion"] = "VCH-INEXISTENTE"
        fx.crear_cierre(self.ruta_cierre, sfc101, _baseline_sfc102())

        resultado = self._procesar()

        # Mismo bloqueo que ya cubre test_pipeline_tiquipaya.py.
        self.assertIn(resultado["estado"], (pipeline.ESTADO_BLOQUEADO, pipeline.ESTADO_ERROR))
        self.assertEqual(resultado["resultado_json"]["blockers"], 1)

        with open(self.ruta_resultado, "r", encoding="utf-8") as f:
            resultado_json_en_disco = json.load(f)

        self.assertEqual(resultado_json_en_disco["blockers"], 1)
        excepciones = resultado_json_en_disco["excepciones"]
        self.assertEqual(len(excepciones), 1)
        self.assertEqual(excepciones[0]["categoria"], "VOUCHER")
        self.assertEqual(excepciones[0]["tipo"], "NO_ENCONTRADO")
        self.assertEqual(excepciones[0]["codigo_informado"], "VCH-INEXISTENTE")

    def test_ci_cuenta_faltante_llega_a_resultado_json(self):
        sfc101 = _baseline_sfc101()
        sfc101["ci"][0]["cuenta"] = None
        fx.crear_cierre(self.ruta_cierre, sfc101, _baseline_sfc102())

        resultado = self._procesar()
        self.assertIn(resultado["estado"], (pipeline.ESTADO_BLOQUEADO, pipeline.ESTADO_ERROR))

        with open(self.ruta_resultado, "r", encoding="utf-8") as f:
            resultado_json_en_disco = json.load(f)

        excepciones = resultado_json_en_disco["excepciones"]
        self.assertEqual(len(excepciones), 1)
        self.assertEqual(excepciones[0]["categoria"], "COMUNICACION_INTERNA")
        self.assertEqual(excepciones[0]["tipo"], "CI_CUENTA_FALTANTE")

    def test_cierre_ok_no_genera_excepciones(self):
        # Control: un cierre sin bloqueos debe seguir dando
        # excepciones=[] (no aparece detalle donde no hay excepción).
        resultado = self._procesar()
        self.assertEqual(resultado["estado"], pipeline.ESTADO_VALIDADO_PENDIENTE)
        self.assertEqual(resultado["resultado_json"]["excepciones"], [])


# ---------------------------------------------------------------------------
# Propagación end-to-end: run_batch -> resultado_batch.json
# ---------------------------------------------------------------------------

class TestPropagacionResultadoBatch(_BaseDosDias):
    def test_excepciones_en_resultado_batch_json(self):
        self._crear_cierre(FECHA_A, "VCHA", "CIA", bloqueado=True)

        resultado = run_batch.ejecutar_batch(self._args(FECHA_A, FECHA_A))
        entrada = resultado["cierres"][0]

        # Mismo bloqueo que ya cubre test_run_batch.py.
        self.assertEqual(entrada["estado"], "ERROR_REVISAR")
        self.assertEqual(entrada["blockers"], 1)

        self.assertEqual(len(entrada["excepciones"]), 1)
        self.assertEqual(entrada["excepciones"][0]["categoria"], "VOUCHER")
        self.assertEqual(entrada["excepciones"][0]["tipo"], "NO_ENCONTRADO")

        ruta_batch = os.path.join(self.resultados_dir, "resultado_batch.json")
        with open(ruta_batch, "r", encoding="utf-8") as f:
            leido = json.load(f)
        c_en_disco = leido["cierres"][0]
        self.assertEqual(c_en_disco["excepciones"][0]["tipo"], "NO_ENCONTRADO")

    def test_cierre_listo_tiene_excepciones_vacio(self):
        self._crear_cierre(FECHA_A, "VCHA", "CIA", bloqueado=False)

        resultado = run_batch.ejecutar_batch(self._args(FECHA_A, FECHA_A))
        entrada = resultado["cierres"][0]

        self.assertEqual(entrada["estado"], "LISTO_PARA_PUBLICAR")
        self.assertEqual(entrada["excepciones"], [])


if __name__ == "__main__":
    unittest.main()
