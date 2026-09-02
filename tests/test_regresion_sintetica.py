"""test_regresion_sintetica.py — regresión end-to-end (excel_io + motor)
sobre archivos .xlsx/.xlsm SINTÉTICOS que reproducen los totales conocidos
de la regresión real 19-08-2026 (ver HANDOFF_CODE_V2.md), sin usar ningún
Excel real ni datos contables reales. Ejercita el parseo real de openpyxl,
no solo fixtures de diccionarios.

Uso: python -m unittest tests.test_regresion_sintetica -v
"""

import os
import sys
import tempfile
import unittest
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import motor_tiquipaya as motor
import excel_io as io
from tests import xlsx_fixtures as fx


FECHA_CIERRE = "2026-08-19"
NOMBRE_CIERRE = f"CIERRE {FECHA_CIERRE[8:10]}-{FECHA_CIERRE[5:7]}-{FECHA_CIERRE[0:4]}.xlsm"


def _baseline_sfc101():
    return {
        "total_movimiento": "137504.96",
        "cobros_atc": "70000.00",
        "dolares": "0.00",
        "depositos": [
            {"importe": "20000.00", "fecha": FECHA_CIERRE, "asignacion": "VCH1001", "banco": "BNB"},
            {"importe": "20805.00", "fecha": FECHA_CIERRE, "asignacion": "VCH1002", "banco": "BNB"},
        ],
        "ci": [
            {"total": "35000.00", "cuenta": "210201005", "asignacion": "CI0001", "banco": "BNB"},
            {"total": "15368.96", "cuenta": "210201005", "asignacion": "CI0002", "banco": "BNB"},
        ],
    }


def _baseline_sfc102():
    return {
        "total_movimiento": "144552.00",
        "cobros_atc": "60883.00",
        "dolares": "0.00",
        "depositos": [
            {"importe": "20000.00", "fecha": FECHA_CIERRE, "asignacion": "VCH1003", "banco": "BNB"},
            {"importe": "20000.00", "fecha": FECHA_CIERRE, "asignacion": "VCH1004", "banco": "BNB"},
        ],
        "ci": [
            {"total": "10000.00", "cuenta": "210201005", "asignacion": "CI0003", "banco": "BNB"},
            {"total": "10000.00", "cuenta": "210201005", "asignacion": "CI0004", "banco": "BNB"},
        ],
    }


def _baseline_macros_filas():
    return [
        (FECHA_CIERRE, "VCH1001", "20000.00"),
        (FECHA_CIERRE, "VCH1002", "20805.00"),
        (FECHA_CIERRE, "VCH1003", "20000.00"),
        (FECHA_CIERRE, "VCH1004", "20000.00"),
        (FECHA_CIERRE, "ATC-19082026", "130246.43"),
    ]


def _baseline_atc_filas():
    return [
        (FECHA_CIERRE, "BANCO (NETO)", "130246.43"),
        (FECHA_CIERRE, "COMISIÓN ATC", "636.57"),
    ]


class _BaseRegresion(unittest.TestCase):
    """Arma los tres archivos sintéticos en un directorio temporal.
    Las subclases pueden sobreescribir _sfc101/_sfc102/_macros/_atc para
    variar el escenario manteniendo el resto del baseline."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.ruta_cierre = os.path.join(self._tmp.name, NOMBRE_CIERRE)
        self.ruta_macros = os.path.join(self._tmp.name, "MACROS.xlsm")
        self.ruta_atc = os.path.join(self._tmp.name, "ATC.xlsx")

        fx.crear_cierre(self.ruta_cierre, self._sfc101(), self._sfc102())
        fx.crear_macros(self.ruta_macros, self._macros_filas(),
                         header_repetido_en=self._header_repetido_en())
        fx.crear_atc(self.ruta_atc, self._atc_filas())

    def _sfc101(self):
        return _baseline_sfc101()

    def _sfc102(self):
        return _baseline_sfc102()

    def _macros_filas(self):
        return _baseline_macros_filas()

    def _atc_filas(self):
        return _baseline_atc_filas()

    def _header_repetido_en(self):
        return None

    def _ejecutar(self):
        return motor.ejecutar_v2(self.ruta_cierre, self.ruta_macros, self.ruta_atc)


class TestRegresionSintetica190826(_BaseRegresion):
    """1. Cierre normal 19-08 equivalente: sigue cuadrando (extracción real
    vía openpyxl, no solo fixtures de diccionario)."""

    def test_totales_y_cuadre(self):
        resultado = self._ejecutar()
        self.assertEqual(resultado["estado"], "OK")
        self.assertEqual(resultado["fecha"], FECHA_CIERRE)
        self.assertEqual(resultado["universo_original"], "282056.96")
        self.assertEqual(resultado["universo_ajustado"], "282056.96")
        self.assertEqual(resultado["componentes"]["vouchers"], "80805.00")
        self.assertEqual(resultado["componentes"]["ci_operativas"], "70368.96")
        self.assertEqual(resultado["componentes"]["atc_bruto"], "130883.00")
        self.assertEqual(resultado["detalle"]["atc_neto"]["importe"], "130246.43")
        self.assertEqual(resultado["detalle"]["atc_comision"]["importe"], "636.57")
        self.assertEqual(resultado["diferencia"], "0.00")
        self.assertEqual(resultado["excepciones_bloqueantes"], 0)

    def test_asiento_cuadra(self):
        resultado = self._ejecutar()
        asiento = motor.construir_asiento(resultado)
        self.assertEqual(asiento["estado"], "OK")
        self.assertEqual(asiento["problemas"], [])
        self.assertEqual(asiento["total_cargo"], "282056.96")
        self.assertEqual(asiento["total_haber"], "282056.96")
        self.assertEqual(asiento["diferencia"], "0.00")
        haber = {p["sfc_origen"]: p["haber"] for p in asiento["partidas"]
                 if p["origen"] in ("UNIVERSO_SFC101", "UNIVERSO_SFC102")}
        self.assertEqual(haber["SFC101"], "137504.96")
        self.assertEqual(haber["SFC102"], "144552.00")
        self.assertFalse(any(p["origen"] == "ALQUILERES" for p in asiento["partidas"]))


class TestEncabezadosRepetidosMacros(TestRegresionSintetica190826):
    """21. MACROS con encabezado repetido dentro del rango de datos:
    sigue funcionando (reutiliza toda la regresión 19-08)."""

    def _header_repetido_en(self):
        return 2


class TestUsdBloqueaEjecutarV2(_BaseRegresion):
    """9. DOLARES > 0.00 y cuenta USD no parametrizada: ejecutar_v2 nunca
    devuelve "OK"; construir_asiento no genera partidas."""

    def _sfc101(self):
        datos = _baseline_sfc101()
        datos["dolares"] = "50.00"
        return datos

    def test_usd_cuenta_pendiente(self):
        resultado = self._ejecutar()
        self.assertEqual(resultado["estado"], "USD_CUENTA_PENDIENTE")
        self.assertNotEqual(resultado["estado"], "OK")
        asiento = motor.construir_asiento(resultado)
        self.assertEqual(asiento["estado"], "USD_CUENTA_PENDIENTE")
        self.assertEqual(asiento["partidas"], [])


class TestCierreBloqueadoPorExcepcion(_BaseRegresion):
    """19. Cierre bloqueado (CI sin cuenta contable): NO_ASIENTO."""

    def _sfc101(self):
        datos = _baseline_sfc101()
        datos["ci"][0]["cuenta"] = None
        return datos

    def test_no_asiento_si_bloqueado(self):
        resultado = self._ejecutar()
        self.assertEqual(resultado["estado"], "BLOQUEADO_EXCEPCION")
        self.assertGreater(resultado["excepciones_bloqueantes"], 0)
        asiento = motor.construir_asiento(resultado)
        self.assertEqual(asiento["estado"], "NO_ASIENTO")
        self.assertEqual(asiento["partidas"], [])


class TestDiferenciaDistintaDeCero(_BaseRegresion):
    """18. Diferencia distinta de cero: NO_ASIENTO."""

    def _sfc101(self):
        datos = _baseline_sfc101()
        datos["total_movimiento"] = "137604.96"  # +100.00 sin contrapartida
        return datos

    def test_no_asiento_si_diferencia(self):
        resultado = self._ejecutar()
        self.assertEqual(resultado["estado"], "DIFERENCIA")
        self.assertNotEqual(resultado["diferencia"], "0.00")
        asiento = motor.construir_asiento(resultado)
        self.assertEqual(asiento["estado"], "NO_ASIENTO")
        self.assertEqual(asiento["partidas"], [])


class TestDepositosConFilaSeparadora(_BaseRegresion):
    """20. Fila vacía/separadora entre depósitos: los depósitos
    posteriores NO se pierden."""

    def _sfc101(self):
        datos = _baseline_sfc101()
        datos["depositos"] = [
            {"importe": "20000.00", "fecha": FECHA_CIERRE, "asignacion": "VCH1001", "banco": "BNB"},
            {"separador": True},
            {"importe": "20805.00", "fecha": FECHA_CIERRE, "asignacion": "VCH1002", "banco": "BNB"},
        ]
        return datos

    def test_depositos_posteriores_a_separador_no_se_pierden(self):
        cierre = io.leer_cierre(self.ruta_cierre)
        importes = sorted(d["importe"] for d in cierre["sfc101"]["depositos"])
        self.assertEqual(importes, ["20000.00", "20805.00"])

        resultado = self._ejecutar()
        self.assertEqual(resultado["estado"], "OK")
        self.assertEqual(resultado["componentes"]["vouchers"], "80805.00")


class TestFechaBancariaInvalidaEnMacros(_BaseRegresion):
    """22. Fecha bancaria inválida en MACROS: falla cerrado y de forma
    estructurada (no viaja una cadena arbitraria hasta el asiento)."""

    def _macros_filas(self):
        filas = _baseline_macros_filas()
        filas[0] = ("no-es-una-fecha", "VCH1001", "20000.00")
        return filas

    def test_leer_macros_lanza_excepcion(self):
        with self.assertRaises(ValueError):
            io.leer_macros_bnb(self.ruta_macros)

    def test_ejecutar_v2_devuelve_estado_estructurado(self):
        resultado = self._ejecutar()
        self.assertEqual(resultado["estado"], "INDETERMINADO")
        self.assertIn("error", resultado)


class TestAtcBrutoCeroSinFilaEnMaestro(_BaseRegresion):
    """23. Corrección PRE-SAP: ATC BRUTO = 0.00 (día sin cobros con
    tarjeta) y la fecha del cierre NO existe en el ATC mensual real
    (openpyxl, no fixture de diccionario): no es excepción, no se busca
    NETO en MACROS, y el cierre completo (extracción + cruces + cuadre +
    asiento) queda OK sin las 2 líneas ATC."""

    def _sfc101(self):
        datos = _baseline_sfc101()
        datos["cobros_atc"] = "0.00"
        # El total del día baja en la misma medida que el ATC que deja de
        # existir: el resto de componentes (vouchers, CI) no cambia.
        datos["total_movimiento"] = "67504.96"  # 137504.96 - 70000.00
        return datos

    def _sfc102(self):
        datos = _baseline_sfc102()
        datos["cobros_atc"] = "0.00"
        datos["total_movimiento"] = "83669.00"  # 144552.00 - 60883.00
        return datos

    def _macros_filas(self):
        # Sin la fila ATC-19082026: solo quedan los vouchers. Si el motor
        # intentara buscar el NETO en MACROS pese a ATC BRUTO=0.00, no lo
        # encontraría y el cierre quedaría bloqueado (lo que estas pruebas
        # descartan).
        return [f for f in _baseline_macros_filas() if f[1] != "ATC-19082026"]

    def _atc_filas(self):
        # El ATC mensual real no trae ninguna fila para la fecha del
        # cierre (día sin cobros con tarjeta).
        return []

    def test_A_sin_blocker_cierre_queda_ok(self):
        resultado = self._ejecutar()
        self.assertEqual(resultado["componentes"]["atc_bruto"], "0.00")
        self.assertEqual(resultado["excepciones_bloqueantes"], 0)
        self.assertEqual(resultado["estado"], "OK")
        self.assertEqual(resultado["diferencia"], "0.00")
        self.assertEqual(resultado["detalle"]["atc_estado"], "ATC_NO_APLICA")
        self.assertFalse(resultado["detalle"]["atc_aplica"])
        self.assertIsNone(resultado["detalle"]["atc_neto"])
        self.assertIsNone(resultado["detalle"]["atc_comision"])

    def test_C_D_asiento_ok_sin_lineas_atc(self):
        resultado = self._ejecutar()
        asiento = motor.construir_asiento(resultado)
        self.assertEqual(asiento["estado"], "OK")
        self.assertEqual(asiento["problemas"], [])
        origenes = {p["origen"] for p in asiento["partidas"]}
        self.assertNotIn("ATC_NETO", origenes)
        self.assertNotIn("ATC_COMISION", origenes)
        self.assertEqual(asiento["total_cargo"], asiento["total_haber"])
        self.assertEqual(asiento["diferencia"], "0.00")


class TestAtcDuplicadoEnMaestro(_BaseRegresion):
    """8. ATC con NETO duplicado para la misma fecha en el maestro: no se
    sobrescribe silenciosamente ("la última fila"), falla de forma
    explícita."""

    def _atc_filas(self):
        return [
            (FECHA_CIERRE, "BANCO (NETO)", "130246.43"),
            (FECHA_CIERRE, "BANCO (NETO)", "999999.99"),
            (FECHA_CIERRE, "COMISIÓN ATC", "636.57"),
        ]

    def test_leer_atc_lanza_excepcion(self):
        with self.assertRaises(ValueError):
            io.leer_atc_mensual(self.ruta_atc)

    def test_ejecutar_v2_devuelve_estado_estructurado(self):
        resultado = self._ejecutar()
        self.assertEqual(resultado["estado"], "INDETERMINADO")
        self.assertIn("error", resultado)


if __name__ == "__main__":
    unittest.main()
