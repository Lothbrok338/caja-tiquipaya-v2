"""test_facturas_anuladas.py — BLOQUE 1: FACTURAS ANULADAS como CxP
transitoria (cuenta 210103003).

Ningún dato contable real: todos los importes, cuentas, números de
factura y códigos son inventados exclusivamente para estas pruebas.

Cobertura (letras del encargo):
  A. cierre sin fila FACTURAS ANULADAS -> resultado histórico idéntico.
  B. FACTURAS ANULADAS=0.00           -> resultado histórico idéntico.
  C. importe>0, una anulada           -> entra correctamente al cuadre.
  D. importe>0                        -> genera HABER 210103003.
  E. asignación exactamente "F-<numero> ANULADA" (sin ".0" aunque Excel
     traiga el número como float).
  F. CONTROL 3 reconoce la partida como CxP EMPRESAS (integración).
  G. POSGRADO RESERVA de América sigue funcionando igual.
  H. importe negativo (total o de una factura) -> fail closed.
  I. número de factura vacío -> nunca se inventa, fail closed.
  + varias anuladas -> partidas independientes.
  + suma del detalle != resumen -> bloquea.
  + factura duplicada dentro del detalle -> bloquea.
"""

import os
import sys
import tempfile
import unittest
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import excel_io as io  # noqa: E402
import motor_tiquipaya as motor  # noqa: E402
import control_cxc_cxp as c3  # noqa: E402

from tests.xlsx_fixtures import crear_cierre, crear_maestro_unico  # noqa: E402
from tests.test_caja_america import (  # noqa: E402
    _procesar_america,
    _partidas_por_origen as _partidas_por_origen_america,
)
from tests.test_control_cxc_cxp import _crear_global, _partida  # noqa: E402


NOMBRE_CIERRE = "CIERRE 20-09-2026.xlsm"


def _partidas_por_origen(asiento, origen):
    return [p for p in asiento["partidas"] if p["origen"] == origen]


class _TmpMixin:
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmpdir = self._tmp.name
        self.addCleanup(self._tmp.cleanup)


def _procesar(tmpdir, sfc101, sfc102):
    ruta_cierre = os.path.join(tmpdir, NOMBRE_CIERRE)
    ruta_maestro = os.path.join(tmpdir, "MAESTRO SEPTIEMBRE.xlsm")
    crear_cierre(ruta_cierre, sfc101, sfc102)
    crear_maestro_unico(ruta_maestro, [], [])
    resultado = motor.ejecutar_v2(ruta_cierre, ruta_maestro, ruta_maestro)
    asiento = motor.construir_asiento(resultado)
    return resultado, asiento


# CI que explica la recaudación FÍSICA real del día (vouchers/CI/ATC/
# dolares, tal como el cierre los trae: incluyen el efectivo cobrado por
# la factura anulada, como cualquier otro cobro real). Cuando no hay
# FACTURAS ANULADAS, física == universo (1677.00). Cuando sí hay
# (2677.00 + 1000.00 anulada), física == universo + facturas_anuladas
# (3677.00, el ejemplo exacto del encargo).
_CI_1677 = {"total": "1677.00", "cuenta": "110201002", "asignacion": "CI-1"}
_CI_3677 = {"total": "3677.00", "cuenta": "110201002", "asignacion": "CI-1"}


class TestRegresionHistorica(_TmpMixin, unittest.TestCase):

    def test_A_sin_fila_facturas_anuladas_resultado_historico(self):
        """A. Cierre sin la fila (cierres anteriores a esta regla)."""
        resultado, asiento = _procesar(
            self.tmpdir,
            {"total_movimiento": "1677.00", "cobros_atc": "0.00", "ci": [_CI_1677]},
            {"total_movimiento": "0.00", "cobros_atc": "0.00"},
        )
        self.assertEqual(resultado["estado"], "OK")
        self.assertEqual(resultado["diferencia"], "0.00")
        self.assertEqual(resultado["componentes"]["facturas_anuladas"], "0.00")
        self.assertEqual(asiento["estado"], "OK")
        self.assertEqual(_partidas_por_origen(asiento, "FACTURA_ANULADA"), [])

    def test_B_facturas_anuladas_cero_resultado_historico(self):
        """B. Fila presente pero en 0.00: mismo comportamiento que A."""
        resultado, asiento = _procesar(
            self.tmpdir,
            {"total_movimiento": "1677.00", "cobros_atc": "0.00", "ci": [_CI_1677],
             "facturas_anuladas": "0.00"},
            {"total_movimiento": "0.00", "cobros_atc": "0.00"},
        )
        self.assertEqual(resultado["estado"], "OK")
        self.assertEqual(resultado["diferencia"], "0.00")
        self.assertEqual(resultado["componentes"]["facturas_anuladas"], "0.00")
        self.assertEqual(asiento["estado"], "OK")
        self.assertEqual(_partidas_por_origen(asiento, "FACTURA_ANULADA"), [])


class TestUnaFacturaAnulada(_TmpMixin, unittest.TestCase):

    def _procesar_una_anulada(self, numero=15806):
        return _procesar(
            self.tmpdir,
            {"total_movimiento": "2677.00", "cobros_atc": "0.00", "ci": [_CI_3677],
             "facturas_anuladas": "1000.00",
             "facturas_anuladas_detalle": [{"numero": numero, "importe": "1000.00"}]},
            {"total_movimiento": "0.00", "cobros_atc": "0.00"},
        )

    def test_C_importe_mayor_a_cero_entra_al_cuadre(self):
        """C. FACTURAS ANULADAS no toca el universo, pero SÍ explica
        recaudación: el cierre del ejemplo del encargo (2677/1000) cuadra."""
        resultado, asiento = self._procesar_una_anulada()

        self.assertEqual(resultado["universo_original"], "2677.00")
        self.assertEqual(resultado["universo_ajustado"], "2677.00")
        self.assertEqual(resultado["componentes"]["facturas_anuladas"], "1000.00")
        self.assertEqual(resultado["recaudacion_explicada"], "2677.00")
        self.assertEqual(resultado["diferencia"], "0.00")
        self.assertEqual(resultado["estado"], "OK")
        self.assertEqual(asiento["estado"], "OK")
        self.assertEqual(asiento["problemas"], [])

    def test_D_genera_haber_210103003(self):
        """D. Partida HABER en la cuenta CxP EMPRESAS, DEBE 0.00."""
        _, asiento = self._procesar_una_anulada()
        partidas = _partidas_por_origen(asiento, "FACTURA_ANULADA")
        self.assertEqual(len(partidas), 1)
        p = partidas[0]
        self.assertEqual(p["cuenta_mayor"], "210103003")
        self.assertEqual(p["haber"], "1000.00")
        self.assertEqual(p["cargo"], "0.00")
        self.assertEqual(p["texto_posicion"], "FACTURA ANULADA")

    def test_E_asignacion_exacta_f_numero_anulada(self):
        """E. 'F-<numero> ANULADA', con número entero (sin ".0")."""
        _, asiento = self._procesar_una_anulada(numero=15806)
        p = _partidas_por_origen(asiento, "FACTURA_ANULADA")[0]
        self.assertEqual(p["asignacion"], "F-15806 ANULADA")

    def test_E2_numero_como_float_en_excel_no_arrastra_punto_cero(self):
        """E (variante). Si Excel entrega el número como float (15806.0,
        típico de una celda numérica), la asignación sigue siendo
        'F-15806 ANULADA', nunca 'F-15806.0 ANULADA'."""
        _, asiento = self._procesar_una_anulada(numero=15806.0)
        p = _partidas_por_origen(asiento, "FACTURA_ANULADA")[0]
        self.assertEqual(p["asignacion"], "F-15806 ANULADA")

    def test_partidas_totales_cuadran(self):
        resultado, asiento = self._procesar_una_anulada()
        self.assertEqual(asiento["total_cargo"], asiento["total_haber"])
        self.assertEqual(asiento["diferencia"], "0.00")


class TestVariasFacturasAnuladas(_TmpMixin, unittest.TestCase):

    def test_varias_anuladas_generan_partidas_independientes(self):
        resultado, asiento = _procesar(
            self.tmpdir,
            {"total_movimiento": "2177.00", "cobros_atc": "0.00", "ci": [_CI_3677],
             "facturas_anuladas": "500.00",
             "facturas_anuladas_detalle": [{"numero": 15806, "importe": "500.00"}]},
            {"total_movimiento": "500.00", "cobros_atc": "0.00",
             "facturas_anuladas": "500.00",
             "facturas_anuladas_detalle": [{"numero": 15820, "importe": "500.00"}]},
        )

        self.assertEqual(resultado["estado"], "OK")
        self.assertEqual(resultado["componentes"]["facturas_anuladas"], "1000.00")
        self.assertEqual(asiento["estado"], "OK")

        partidas = _partidas_por_origen(asiento, "FACTURA_ANULADA")
        self.assertEqual(len(partidas), 2)
        asignaciones = sorted(p["asignacion"] for p in partidas)
        self.assertEqual(asignaciones, ["F-15806 ANULADA", "F-15820 ANULADA"])
        for p in partidas:
            self.assertEqual(p["cuenta_mayor"], "210103003")
            self.assertEqual(p["cargo"], "0.00")
        self.assertEqual(
            sum(Decimal(p["haber"]) for p in partidas), Decimal("1000.00")
        )


class TestFailClosed(_TmpMixin, unittest.TestCase):

    def test_suma_detalle_distinta_del_resumen_bloquea(self):
        with self.assertRaises(ValueError) as ctx:
            ruta = os.path.join(self.tmpdir, NOMBRE_CIERRE)
            crear_cierre(
                ruta,
                {"total_movimiento": "2677.00", "cobros_atc": "0.00", "ci": [_CI_1677],
                 "facturas_anuladas": "1000.00",
                 "facturas_anuladas_detalle": [{"numero": 15806, "importe": "900.00"}]},
                {"total_movimiento": "0.00", "cobros_atc": "0.00"},
            )
            io.leer_cierre(ruta)
        self.assertIn("FACTURAS ANULADAS", str(ctx.exception))

    def test_factura_sin_numero_bloquea(self):
        with self.assertRaises(ValueError) as ctx:
            ruta = os.path.join(self.tmpdir, NOMBRE_CIERRE)
            crear_cierre(
                ruta,
                {"total_movimiento": "2677.00", "cobros_atc": "0.00", "ci": [_CI_1677],
                 "facturas_anuladas": "1000.00",
                 "facturas_anuladas_detalle": [{"numero": None, "importe": "1000.00"}]},
                {"total_movimiento": "0.00", "cobros_atc": "0.00"},
            )
            io.leer_cierre(ruta)
        self.assertIn("sin número de factura", str(ctx.exception))

    def test_importe_de_detalle_menor_o_igual_a_cero_bloquea(self):
        with self.assertRaises(ValueError) as ctx:
            ruta = os.path.join(self.tmpdir, NOMBRE_CIERRE)
            crear_cierre(
                ruta,
                {"total_movimiento": "2677.00", "cobros_atc": "0.00", "ci": [_CI_1677],
                 "facturas_anuladas": "0.00",
                 "facturas_anuladas_detalle": [{"numero": 15806, "importe": "0.00"}]},
                {"total_movimiento": "0.00", "cobros_atc": "0.00"},
            )
            io.leer_cierre(ruta)
        self.assertIn("importe inválido", str(ctx.exception))

    def test_importe_total_negativo_bloquea(self):
        with self.assertRaises(ValueError) as ctx:
            ruta = os.path.join(self.tmpdir, NOMBRE_CIERRE)
            crear_cierre(
                ruta,
                {"total_movimiento": "2677.00", "cobros_atc": "0.00", "ci": [_CI_1677],
                 "facturas_anuladas": "-100.00"},
                {"total_movimiento": "0.00", "cobros_atc": "0.00"},
            )
            io.leer_cierre(ruta)
        self.assertIn("no puede ser negativo", str(ctx.exception))

    def test_factura_duplicada_en_el_detalle_bloquea(self):
        with self.assertRaises(ValueError) as ctx:
            ruta = os.path.join(self.tmpdir, NOMBRE_CIERRE)
            crear_cierre(
                ruta,
                {"total_movimiento": "2677.00", "cobros_atc": "0.00", "ci": [_CI_1677],
                 "facturas_anuladas": "1000.00",
                 "facturas_anuladas_detalle": [
                     {"numero": 15806, "importe": "500.00"},
                     {"numero": 15806, "importe": "500.00"},
                 ]},
                {"total_movimiento": "0.00", "cobros_atc": "0.00"},
            )
            io.leer_cierre(ruta)
        self.assertIn("duplicada", str(ctx.exception))

    def test_extraccion_fallida_ejecutar_v2_devuelve_indeterminado_nunca_inventa(self):
        """El motor nunca esconde el fallo detrás de un asiento inventado:
        ejecutar_v2 responde INDETERMINADO y construir_asiento NO_ASIENTO."""
        ruta_cierre = os.path.join(self.tmpdir, NOMBRE_CIERRE)
        ruta_maestro = os.path.join(self.tmpdir, "MAESTRO SEPTIEMBRE.xlsm")
        crear_cierre(
            ruta_cierre,
            {"total_movimiento": "2677.00", "cobros_atc": "0.00", "ci": [_CI_1677],
             "facturas_anuladas": "1000.00",
             "facturas_anuladas_detalle": [{"numero": 15806, "importe": "900.00"}]},
            {"total_movimiento": "0.00", "cobros_atc": "0.00"},
        )
        crear_maestro_unico(ruta_maestro, [], [])

        resultado = motor.ejecutar_v2(ruta_cierre, ruta_maestro, ruta_maestro)
        self.assertEqual(resultado["estado"], "INDETERMINADO")

        asiento = motor.construir_asiento(resultado)
        self.assertEqual(asiento["estado"], "NO_ASIENTO")
        self.assertEqual(asiento["partidas"], [])


class TestControl3ReconoceCxpEmpresas(unittest.TestCase):
    """F. Integración: CONTROL 3 (control_cxc_cxp.py, sin modificar) ya
    controla 210103003 por CUENTA+ASIGNACION — la partida FACTURA_ANULADA
    debe quedar visible ahí exactamente igual que cualquier otra CxP
    EMPRESAS."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmpdir = self._tmp.name
        self.addCleanup(self._tmp.cleanup)
        self.ruta_historico = os.path.join(self.tmpdir, "HISTORICO_CXC_CXP.csv")

    def test_partida_factura_anulada_es_cxp_empresas_abierta(self):
        ruta_global = os.path.join(self.tmpdir, "SAP_GLOBAL_TIQ_SEPTIEMBRE_2026.xlsx")
        _crear_global(ruta_global, [
            _partida("210103003", "F-15806 ANULADA", haber="1000.00", glosa="FACTURA ANULADA"),
        ])

        c3.ejecutar_control(
            ruta_global=ruta_global,
            ruta_historico=self.ruta_historico,
            ruta_salida_xlsx=os.path.join(self.tmpdir, "CONTROL.xlsx"),
            ruta_salida_json=os.path.join(self.tmpdir, "CONTROL.json"),
        )

        historico = c3.cargar_historico(self.ruta_historico)
        fila = historico[("210103003", "F-15806 ANULADA")]
        self.assertEqual(fila["tipo"], "CxP EMPRESAS")
        self.assertEqual(fila["saldo"], "1000.00")
        self.assertEqual(fila["estado"], "ABIERTO")


class TestAmericaSigueFuncionandoIgual(unittest.TestCase):
    """G. POSGRADO RESERVA de América, sin FACTURAS ANULADAS, produce
    exactamente el mismo asiento que antes de este BLOQUE 1 (regresión
    directa del escenario E de test_caja_america)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmpdir = self._tmp.name
        self.addCleanup(self._tmp.cleanup)

    def test_reserva_posgrado_america_sin_cambios(self):
        resultado, asiento = _procesar_america(
            self.tmpdir,
            {"total_movimiento": "1900.00", "cobros_atc": "2000.00",
             "posgrado_reserva": "100.00"},
            {"total_movimiento": "0.00", "cobros_atc": "0.00",
             "posgrado_reserva": "0.00"},
        )

        self.assertEqual(resultado["componentes"]["facturas_anuladas"], "0.00")
        self.assertEqual(resultado["componentes"]["reserva_posgrado"], "100.00")
        self.assertEqual(resultado["estado"], "OK")
        self.assertEqual(asiento["estado"], "OK")

        reservas = _partidas_por_origen_america(asiento, "RESERVA_POSGRADO")
        self.assertEqual(len(reservas), 1)
        self.assertEqual(reservas[0]["cuenta_mayor"], "210103003")
        self.assertEqual(reservas[0]["haber"], "100.00")
        self.assertEqual(reservas[0]["asignacion"], "POSTG-SEPT")
        self.assertEqual(_partidas_por_origen_america(asiento, "FACTURA_ANULADA"), [])


if __name__ == "__main__":
    unittest.main()
