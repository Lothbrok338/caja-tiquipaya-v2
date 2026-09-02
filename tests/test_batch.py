"""test_batch.py — pruebas de ejecutar_lote_v2() (optimización PRE-SAP de
procesamiento en lote). Verifica que:

- ejecutar_v2() individual y ejecutar_lote_v2() sobre ese mismo cierre
  producen exactamente el mismo resultado_v2 y asiento;
- MACROS y ATC se abren UNA sola vez por lote, sin importar cuántos
  cierres traiga;
- cada CIERRE se abre UNA sola vez;
- un cierre OK y un cierre bloqueado conviven en el mismo lote sin
  contaminarse;
- el lote no es más lento que repetir aperturas individuales (medición
  referencial, no es un benchmark científico).

No usa Excel reales ni datos contables reales: reutiliza los fixtures
sintéticos de tests/xlsx_fixtures.py y el baseline 19-08-2026 ya definido
en tests/test_regresion_sintetica.py.

Uso: python -m unittest tests.test_batch -v
"""

import os
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import motor_tiquipaya as motor
import excel_io as io
from tests import xlsx_fixtures as fx
from tests.test_regresion_sintetica import (
    FECHA_CIERRE,
    _baseline_sfc101,
    _baseline_sfc102,
    _baseline_macros_filas,
    _baseline_atc_filas,
)


_SUFIJO_FECHA = f"{FECHA_CIERRE[8:10]}-{FECHA_CIERRE[5:7]}-{FECHA_CIERRE[0:4]}"


def _crear_cierre_baseline(directorio, nombre, bloqueado=False):
    """Cierre sintético con los totales conocidos del baseline 19-08-2026.
    `bloqueado=True` vacía la cuenta contable de una CI para forzar
    BLOQUEADO_EXCEPCION, sin tocar ninguna otra regla."""
    sfc101 = _baseline_sfc101()
    sfc102 = _baseline_sfc102()
    if bloqueado:
        sfc101["ci"][0]["cuenta"] = None
    ruta = os.path.join(directorio, nombre)
    fx.crear_cierre(ruta, sfc101, sfc102)
    return ruta


class _LoteMaestrosBase(unittest.TestCase):
    """Arma MACROS + ATC del baseline y N cierres idénticos (mismo
    contenido, distinto nombre de archivo) en un directorio temporal."""

    N_CIERRES = 6

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.ruta_macros = os.path.join(self._tmp.name, "MACROS.xlsm")
        self.ruta_atc = os.path.join(self._tmp.name, "ATC.xlsx")
        fx.crear_macros(self.ruta_macros, _baseline_macros_filas())
        fx.crear_atc(self.ruta_atc, _baseline_atc_filas())

        self.rutas_cierres = [
            _crear_cierre_baseline(self._tmp.name, f"CIERRE {_SUFIJO_FECHA} ({i}).xlsm")
            for i in range(self.N_CIERRES)
        ]


class TestEquivalenciaIndividualVsLote(_LoteMaestrosBase):
    """A. ejecutar_v2() individual y ejecutar_lote_v2([ese cierre]) deben
    producir exactamente el mismo resultado_v2 y el mismo asiento."""

    N_CIERRES = 1

    def test_mismo_resultado_v2_y_asiento(self):
        ruta_cierre = self.rutas_cierres[0]

        resultado_individual = motor.ejecutar_v2(ruta_cierre, self.ruta_macros, self.ruta_atc)
        asiento_individual = motor.construir_asiento(resultado_individual)

        lote = motor.ejecutar_lote_v2([ruta_cierre], self.ruta_macros, self.ruta_atc)
        self.assertEqual(lote["estado"], "LOTE_OK")
        self.assertEqual(lote["cantidad"], 1)
        entrada = lote["cierres"][0]

        self.assertEqual(entrada["ruta"], ruta_cierre)
        self.assertEqual(entrada["resultado_v2"], resultado_individual)
        self.assertEqual(entrada["asiento"], asiento_individual)
        # Confirmamos además que el individual sigue dando el baseline
        # 19-08-2026 conocido, para que la equivalencia no sea trivial.
        self.assertEqual(resultado_individual["estado"], "OK")
        self.assertEqual(resultado_individual["universo_ajustado"], "282056.96")


class TestAperturasEnLote(_LoteMaestrosBase):
    """B, C, D. MACROS y ATC se abren exactamente 1 vez por lote; cada
    CIERRE se abre exactamente 1 vez, sin importar cuántos cierres traiga
    el lote (6 en este caso)."""

    def test_macros_se_lee_una_sola_vez(self):
        with mock.patch.object(io, "leer_macros_bnb", wraps=io.leer_macros_bnb) as m:
            resultado = motor.ejecutar_lote_v2(self.rutas_cierres, self.ruta_macros, self.ruta_atc)
        self.assertEqual(m.call_count, 1)
        self.assertEqual(resultado["cantidad"], self.N_CIERRES)

    def test_atc_se_lee_una_sola_vez(self):
        with mock.patch.object(io, "leer_atc_mensual", wraps=io.leer_atc_mensual) as m:
            motor.ejecutar_lote_v2(self.rutas_cierres, self.ruta_macros, self.ruta_atc)
        self.assertEqual(m.call_count, 1)

    def test_cada_cierre_se_lee_una_sola_vez(self):
        with mock.patch.object(io, "leer_cierre", wraps=io.leer_cierre) as m:
            motor.ejecutar_lote_v2(self.rutas_cierres, self.ruta_macros, self.ruta_atc)
        self.assertEqual(m.call_count, self.N_CIERRES)

    def test_todos_los_cierres_del_lote_dan_ok(self):
        # Con macros/atc/cierres idénticos, los 6 cierres del lote deben
        # dar el mismo resultado OK que el baseline individual.
        lote = motor.ejecutar_lote_v2(self.rutas_cierres, self.ruta_macros, self.ruta_atc)
        for entrada in lote["cierres"]:
            self.assertEqual(entrada["resultado_v2"]["estado"], "OK")
            self.assertEqual(entrada["asiento"]["estado"], "OK")
            self.assertEqual(entrada["asiento"]["diferencia"], "0.00")


class TestCierreOkYBloqueadoConviven(unittest.TestCase):
    """E. Un cierre OK y un cierre bloqueado en el mismo lote no se
    contaminan entre sí."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.ruta_macros = os.path.join(self._tmp.name, "MACROS.xlsm")
        self.ruta_atc = os.path.join(self._tmp.name, "ATC.xlsx")
        fx.crear_macros(self.ruta_macros, _baseline_macros_filas())
        fx.crear_atc(self.ruta_atc, _baseline_atc_filas())

        self.ruta_ok = _crear_cierre_baseline(self._tmp.name, f"CIERRE {_SUFIJO_FECHA} (OK).xlsm")
        self.ruta_bloqueado = _crear_cierre_baseline(
            self._tmp.name, f"CIERRE {_SUFIJO_FECHA} (BLOQ).xlsm", bloqueado=True
        )

    def test_no_se_contaminan_entre_si(self):
        lote = motor.ejecutar_lote_v2(
            [self.ruta_ok, self.ruta_bloqueado], self.ruta_macros, self.ruta_atc
        )
        self.assertEqual(lote["estado"], "LOTE_OK")
        self.assertEqual(lote["cantidad"], 2)
        por_ruta = {c["ruta"]: c for c in lote["cierres"]}

        ok = por_ruta[self.ruta_ok]
        self.assertEqual(ok["resultado_v2"]["estado"], "OK")
        self.assertEqual(ok["resultado_v2"]["universo_ajustado"], "282056.96")
        self.assertEqual(ok["asiento"]["estado"], "OK")
        self.assertEqual(ok["asiento"]["diferencia"], "0.00")

        bloqueado = por_ruta[self.ruta_bloqueado]
        self.assertEqual(bloqueado["resultado_v2"]["estado"], "BLOQUEADO_EXCEPCION")
        self.assertGreater(bloqueado["resultado_v2"]["excepciones_bloqueantes"], 0)
        self.assertEqual(bloqueado["asiento"]["estado"], "NO_ASIENTO")
        self.assertEqual(bloqueado["asiento"]["partidas"], [])

        # El cierre bloqueado no afecta al cierre OK, ni viceversa.
        self.assertNotEqual(ok["resultado_v2"]["estado"], bloqueado["resultado_v2"]["estado"])


class TestRendimientoLote(_LoteMaestrosBase):
    """Sección 5: medición referencial (no es benchmark científico). Solo
    confirma que ambas rutas terminan con resultados correctos y deja
    constancia de los tiempos con time.perf_counter()."""

    def test_tiempos_referenciales_y_resultados_correctos(self):
        inicio_individual = time.perf_counter()
        resultados_individuales = [
            motor.ejecutar_v2(ruta, self.ruta_macros, self.ruta_atc)
            for ruta in self.rutas_cierres
        ]
        tiempo_individual = time.perf_counter() - inicio_individual

        inicio_lote = time.perf_counter()
        lote = motor.ejecutar_lote_v2(self.rutas_cierres, self.ruta_macros, self.ruta_atc)
        tiempo_lote = time.perf_counter() - inicio_lote

        print(
            f"\n[rendimiento] {self.N_CIERRES} cierres — "
            f"individual (ejecutar_v2 x{self.N_CIERRES}): {tiempo_individual:.4f}s | "
            f"lote (ejecutar_lote_v2): {tiempo_lote:.4f}s"
        )

        self.assertEqual(len(resultados_individuales), self.N_CIERRES)
        self.assertEqual(lote["cantidad"], self.N_CIERRES)
        for individual, entrada in zip(resultados_individuales, lote["cierres"]):
            self.assertEqual(individual, entrada["resultado_v2"])


if __name__ == "__main__":
    unittest.main()
