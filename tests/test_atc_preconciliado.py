"""
test_atc_preconciliado.py — OPTIMIZACIÓN MAESTRO ÚNICO + ATC PRECONCILIADO
(ETAPA 6).

Prueba el flujo NUEVO: ATC ya conciliado en la hoja "ATC TIQUIPAYA"
(excel_io.leer_atc_mensual en modo PRECONCILIADO,
motor_tiquipaya.cruzar_atc_preconciliado), sin cruzar contra MACROS. No
sube datos contables reales; usa fixtures sintéticos de
tests/xlsx_fixtures.py.

El flujo LEGADO (motor_tiquipaya.cruzar_atc, ATC mensual separado + cruce
contra MACROS) NO se toca: sigue cubierto, sin cambios, por
tests/test_cruces.py y tests/test_regresion_sintetica.py.

Uso: python -m unittest tests.test_atc_preconciliado -v
"""

import inspect
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import motor_tiquipaya as motor
import excel_io as io
from tests import xlsx_fixtures as fx
from tests.test_regresion_sintetica import (
    FECHA_CIERRE, NOMBRE_CIERRE, _baseline_sfc101, _baseline_sfc102,
)


def _macros_filas_solo_vouchers():
    """A propósito SIN ninguna fila con el importe del NETO ATC: si el
    motor intentara cruzar el NETO contra MACROS pese a venir
    preconciliado, no lo encontraría y el cierre quedaría bloqueado."""
    return [
        (FECHA_CIERRE, "VCH1001", "20000.00"),
        (FECHA_CIERRE, "VCH1002", "20805.00"),
        (FECHA_CIERRE, "VCH1003", "20000.00"),
        (FECHA_CIERRE, "VCH1004", "20000.00"),
    ]


def _fila_neto(fecha=FECHA_CIERRE, cuenta="110103012",
               detalle="ATC COCHABAMBA 19/08/2026", monto="130246.43",
               asignacion="3P02891953"):
    return (fecha, "BANCO (NETO)", cuenta, detalle, monto, asignacion)


def _fila_comision(fecha=FECHA_CIERRE, cuenta="110201008",
                    detalle="COMISION ATC 19/08/2026", monto="636.57",
                    asignacion="TIQUIPAYA AGO"):
    return (fecha, "COMISION ATC", cuenta, detalle, monto, asignacion)


def _cierre_atc(bruto="130883.00"):
    mitad = str(round(float(bruto) / 2, 2))
    return {
        "fecha_cierre": FECHA_CIERRE,
        "sfc101": {"cobros_atc": mitad},
        "sfc102": {"cobros_atc": mitad},
    }


def _entrada(monto, cuenta="110103012", detalle=None, asignacion="X"):
    return {"monto": monto, "cuenta_contable": cuenta, "detalle": detalle, "asignacion": asignacion}


# ---------------------------------------------------------------------------
# 1. Lector: hoja "ATC TIQUIPAYA" dentro del mismo maestro
# ---------------------------------------------------------------------------

class TestLectorPreconciliado(unittest.TestCase):
    def test_lee_desde_hoja_atc_tiquipaya_del_maestro(self):
        with tempfile.TemporaryDirectory() as tmp:
            ruta = os.path.join(tmp, "MACROS AGOSTO 2026.xlsm")
            fx.crear_maestro_unico(
                ruta,
                macros_filas=_macros_filas_solo_vouchers(),
                atc_filas=[_fila_neto(), _fila_comision()],
            )
            resultado = io.leer_atc_mensual(ruta)
            self.assertEqual(resultado["modo"], "PRECONCILIADO")
            registro = resultado["por_fecha"][FECHA_CIERRE]
            self.assertEqual(registro["neto"]["monto"], "130246.43")
            self.assertEqual(registro["neto"]["cuenta_contable"], "110103012")
            self.assertEqual(registro["neto"]["asignacion"], "3P02891953")
            self.assertEqual(registro["comision"]["monto"], "636.57")
            self.assertEqual(registro["comision"]["cuenta_contable"], "110201008")
            self.assertEqual(registro["comision"]["asignacion"], "TIQUIPAYA AGO")

    def test_deteccion_de_hoja_tolera_mayusculas_y_espacios(self):
        """El nombre de hoja se busca normalizado (igual que
        _find_sfc_sheet/_find_ci_sheet), no con comparación exacta."""
        with tempfile.TemporaryDirectory() as tmp:
            ruta = os.path.join(tmp, "MAESTRO.xlsm")
            fx.crear_maestro_unico(
                ruta,
                macros_filas=_macros_filas_solo_vouchers(),
                atc_filas=[_fila_neto(), _fila_comision()],
                hoja_atc="Atc Tiquipaya ",  # distinta capitalización + espacio final
            )
            resultado = io.leer_atc_mensual(ruta)
            self.assertEqual(resultado["modo"], "PRECONCILIADO")

    def test_fila_neto_duplicada_lanza_excepcion(self):
        with tempfile.TemporaryDirectory() as tmp:
            ruta = os.path.join(tmp, "ATC.xlsx")
            fx.crear_atc_preconciliado(ruta, [
                _fila_neto(), _fila_neto(monto="999999.99"), _fila_comision(),
            ])
            with self.assertRaises(ValueError):
                io.leer_atc_mensual(ruta)


# ---------------------------------------------------------------------------
# 2 y 9. Fin a fin (ejecutar_v2 + construir_asiento) con maestro único:
# NETO/COMISION/BRUTO correctos y cuenta de comisión 110201008.
# ---------------------------------------------------------------------------

class TestEjecutarV2ConMaestroUnico(unittest.TestCase):
    def test_neto_comision_bruto_resultado_correcto(self):
        with tempfile.TemporaryDirectory() as tmp:
            ruta_cierre = os.path.join(tmp, NOMBRE_CIERRE)
            ruta_maestro = os.path.join(tmp, "MACROS AGOSTO 2026.xlsm")
            fx.crear_cierre(ruta_cierre, _baseline_sfc101(), _baseline_sfc102())
            fx.crear_maestro_unico(
                ruta_maestro,
                macros_filas=_macros_filas_solo_vouchers(),
                atc_filas=[_fila_neto(), _fila_comision()],
            )

            # Un solo archivo para MACROS y para ATC: la "segunda
            # descarga" desde Drive queda eliminada.
            resultado = motor.ejecutar_v2(ruta_cierre, ruta_maestro, ruta_maestro)
            self.assertEqual(resultado["estado"], "OK")
            self.assertEqual(resultado["componentes"]["atc_bruto"], "130883.00")
            self.assertEqual(resultado["detalle"]["atc_neto"]["importe"], "130246.43")
            self.assertEqual(resultado["detalle"]["atc_comision"]["importe"], "636.57")
            self.assertEqual(resultado["diferencia"], "0.00")

            asiento = motor.construir_asiento(resultado)
            self.assertEqual(asiento["estado"], "OK")
            atc_neto_p = next(p for p in asiento["partidas"] if p["origen"] == "ATC_NETO")
            atc_com_p = next(p for p in asiento["partidas"] if p["origen"] == "ATC_COMISION")
            self.assertEqual(atc_neto_p["cuenta_mayor"], "110103012")
            self.assertEqual(atc_neto_p["asignacion"], "3P02891953")
            # ETAPA 8: sin columna de fecha bancaria propia en ATC
            # TIQUIPAYA, fecha_valor usa el fallback autorizado (fecha
            # del cierre) en vez de quedar vacío.
            self.assertEqual(atc_neto_p["fecha_valor"], FECHA_CIERRE)
            self.assertEqual(atc_com_p["cuenta_mayor"], "110201008")
            self.assertEqual(atc_com_p["asignacion"], "TIQUIPAYA AGO")


# ---------------------------------------------------------------------------
# 3. ATC ya conciliado: nunca se cruza/busca NETO en MACROS.
# ---------------------------------------------------------------------------

class TestNoConsultaMacros(unittest.TestCase):
    def test_cruzar_atc_preconciliado_no_recibe_macros_idx(self):
        firma = inspect.signature(motor.cruzar_atc_preconciliado)
        self.assertNotIn("macros_idx", firma.parameters)

    def test_resuelve_atc_aunque_macros_no_tenga_esa_fila(self):
        cierre = _cierre_atc("130883.00")
        atc_por_fecha = {
            FECHA_CIERRE: {
                "neto": _entrada("130246.43", cuenta="110103012", asignacion="3P02891953"),
                "comision": _entrada("636.57", cuenta="110201008", asignacion="TIQUIPAYA AGO"),
            }
        }
        resultado = motor.cruzar_atc_preconciliado(cierre, atc_por_fecha)
        self.assertEqual(resultado["estado_validacion"], "OK")
        self.assertFalse(resultado["excepcion"])
        self.assertEqual(resultado["neto_asignacion"], "3P02891953")


# ---------------------------------------------------------------------------
# 4. ATC bruto = 0: ATC_NO_APLICA, sin blocker, sin exigir filas.
# ---------------------------------------------------------------------------

class TestBrutoCeroPreconciliado(unittest.TestCase):
    def test_bruto_cero_no_aplica_sin_filas(self):
        cierre = _cierre_atc("0.00")
        resultado = motor.cruzar_atc_preconciliado(cierre, {})
        self.assertEqual(resultado["estado_validacion"], "ATC_NO_APLICA")
        self.assertFalse(resultado["excepcion"])
        self.assertEqual(resultado["neto"], "0.00")
        self.assertEqual(resultado["comision"], "0.00")
        self.assertEqual(resultado["diferencia"], "0.00")


# ---------------------------------------------------------------------------
# 5. ASIGNACION = "REVISAR": advertencia, nunca blocker, asiento OK.
# ---------------------------------------------------------------------------

class TestRevisar(unittest.TestCase):
    def test_revisar_es_advertencia_no_blocker(self):
        cierre = _cierre_atc("130883.00")
        atc_por_fecha = {
            FECHA_CIERRE: {
                "neto": _entrada("130246.43", cuenta="110103012", asignacion="REVISAR"),
                "comision": _entrada("636.57", cuenta="110201008", asignacion="TIQUIPAYA AGO"),
            }
        }
        resultado = motor.cruzar_atc_preconciliado(cierre, atc_por_fecha)
        self.assertEqual(resultado["estado_validacion"], "OK")
        self.assertFalse(resultado["excepcion"])
        self.assertIn("ATC_ASIGNACION_REVISAR", resultado["advertencias"])

    def test_asiento_ok_con_revisar_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            ruta_cierre = os.path.join(tmp, NOMBRE_CIERRE)
            ruta_maestro = os.path.join(tmp, "MACROS AGOSTO 2026.xlsm")
            fx.crear_cierre(ruta_cierre, _baseline_sfc101(), _baseline_sfc102())
            fx.crear_maestro_unico(
                ruta_maestro,
                macros_filas=_macros_filas_solo_vouchers(),
                atc_filas=[_fila_neto(asignacion="REVISAR"), _fila_comision()],
            )

            resultado = motor.ejecutar_v2(ruta_cierre, ruta_maestro, ruta_maestro)
            self.assertEqual(resultado["estado"], "OK")
            asiento = motor.construir_asiento(resultado)
            self.assertEqual(asiento["estado"], "OK")
            self.assertIn("ATC_ASIGNACION_REVISAR", asiento["advertencias"])
            atc_neto_p = next(p for p in asiento["partidas"] if p["origen"] == "ATC_NETO")
            self.assertEqual(atc_neto_p["asignacion"], "REVISAR")


# ---------------------------------------------------------------------------
# 7 y 8. Control de suma NETO+COMISION=BRUTO y líneas faltantes: blocker.
# ---------------------------------------------------------------------------

class TestControlSumaYLineasFaltantes(unittest.TestCase):
    def test_suma_no_coincide_bloquea(self):
        cierre = _cierre_atc("130883.00")
        atc_por_fecha = {
            FECHA_CIERRE: {
                "neto": _entrada("100000.00"),
                "comision": _entrada("636.57", cuenta="110201008"),
            }
        }
        resultado = motor.cruzar_atc_preconciliado(cierre, atc_por_fecha)
        self.assertEqual(resultado["estado_validacion"], "ATC_DIFERENCIA")
        self.assertTrue(resultado["excepcion"])

    def test_falta_neto_bloquea(self):
        cierre = _cierre_atc("130883.00")
        atc_por_fecha = {
            FECHA_CIERRE: {"neto": None, "comision": _entrada("636.57", cuenta="110201008")}
        }
        resultado = motor.cruzar_atc_preconciliado(cierre, atc_por_fecha)
        self.assertTrue(resultado["excepcion"])
        self.assertNotEqual(resultado["estado_validacion"], "OK")

    def test_falta_comision_bloquea(self):
        cierre = _cierre_atc("130883.00")
        atc_por_fecha = {
            FECHA_CIERRE: {"neto": _entrada("130246.43"), "comision": None}
        }
        resultado = motor.cruzar_atc_preconciliado(cierre, atc_por_fecha)
        self.assertTrue(resultado["excepcion"])
        self.assertNotEqual(resultado["estado_validacion"], "OK")

    def test_fecha_ausente_por_completo_bloquea(self):
        cierre = _cierre_atc("130883.00")
        resultado = motor.cruzar_atc_preconciliado(cierre, {})
        self.assertEqual(resultado["estado_validacion"], "ATC_FECHA_NO_ENCONTRADA")
        self.assertTrue(resultado["excepcion"])


# ---------------------------------------------------------------------------
# 10. ATC_COMISION con cuenta 110201003: bloquea el asiento (defensa ya
# existente de ETAPA 5, ejercida ahora vía enrutamiento dinámico).
# ---------------------------------------------------------------------------

class TestCuentaComisionInvalida(unittest.TestCase):
    def test_comision_110201003_bloquea_asiento(self):
        with tempfile.TemporaryDirectory() as tmp:
            ruta_cierre = os.path.join(tmp, NOMBRE_CIERRE)
            ruta_maestro = os.path.join(tmp, "MACROS AGOSTO 2026.xlsm")
            fx.crear_cierre(ruta_cierre, _baseline_sfc101(), _baseline_sfc102())
            fx.crear_maestro_unico(
                ruta_maestro,
                macros_filas=_macros_filas_solo_vouchers(),
                atc_filas=[_fila_neto(), _fila_comision(cuenta="110201003")],
            )

            resultado = motor.ejecutar_v2(ruta_cierre, ruta_maestro, ruta_maestro)
            asiento = motor.construir_asiento(resultado)
            self.assertEqual(asiento["estado"], "ERROR")
            self.assertIn("ATC_COMISION_CUENTA_INVALIDA", asiento["problemas"])


# ---------------------------------------------------------------------------
# 12. Vouchers siguen leyendo EXCLUSIVAMENTE "Tablas Dinamicas Profesional",
# aun cuando el maestro también trae "ATC TIQUIPAYA".
# ---------------------------------------------------------------------------

class TestVouchersSoloTablasDinamicas(unittest.TestCase):
    def test_leer_macros_bnb_ignora_hoja_atc_tiquipaya(self):
        with tempfile.TemporaryDirectory() as tmp:
            ruta_maestro = os.path.join(tmp, "MACROS AGOSTO 2026.xlsm")
            fx.crear_maestro_unico(
                ruta_maestro,
                macros_filas=_macros_filas_solo_vouchers(),
                atc_filas=[_fila_neto(), _fila_comision()],
            )
            macros_idx = io.leer_macros_bnb(ruta_maestro)
            codigos = set(macros_idx["por_codigo"].keys())
            self.assertEqual(codigos, {"VCH1001", "VCH1002", "VCH1003", "VCH1004"})
            self.assertNotIn(io.normalize_codigo("3P02891953"), codigos)


# ---------------------------------------------------------------------------
# 13. Compatibilidad: el flujo anterior con ATC separado sigue
# funcionando (formato legado Y el nuevo formato preconciliado también
# como archivo separado — lo único que decide el modo es el NOMBRE de
# hoja "ATC TIQUIPAYA", nunca si es o no el mismo archivo que MACROS).
# ---------------------------------------------------------------------------

class TestCompatibilidadFlujoAnterior(unittest.TestCase):
    def test_atc_separado_formato_antiguo_sigue_en_modo_legado(self):
        with tempfile.TemporaryDirectory() as tmp:
            ruta_atc = os.path.join(tmp, "ATC.xlsx")
            fx.crear_atc(ruta_atc, [
                (FECHA_CIERRE, "BANCO (NETO)", "130246.43"),
                (FECHA_CIERRE, "COMISIÓN ATC", "636.57"),
            ])
            resultado = io.leer_atc_mensual(ruta_atc)
            self.assertEqual(resultado["modo"], "LEGADO")
            self.assertEqual(resultado["por_fecha"][FECHA_CIERRE]["neto"], "130246.43")

    def test_atc_preconciliado_como_archivo_separado_tambien_funciona(self):
        with tempfile.TemporaryDirectory() as tmp:
            ruta_cierre = os.path.join(tmp, NOMBRE_CIERRE)
            ruta_macros = os.path.join(tmp, "MACROS.xlsm")
            ruta_atc = os.path.join(tmp, "ATC TIQUIPAYA.xlsx")
            fx.crear_cierre(ruta_cierre, _baseline_sfc101(), _baseline_sfc102())
            fx.crear_macros(ruta_macros, _macros_filas_solo_vouchers())
            fx.crear_atc_preconciliado(ruta_atc, [_fila_neto(), _fila_comision()])

            resultado = motor.ejecutar_v2(ruta_cierre, ruta_macros, ruta_atc)
            self.assertEqual(resultado["estado"], "OK")
            self.assertEqual(resultado["detalle"]["atc_neto"]["importe"], "130246.43")


if __name__ == "__main__":
    unittest.main()
