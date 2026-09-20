"""test_control_america_postg.py — Interacción CONTROL 1 / CONTROL 3 para
Caja América y la reserva de posgrado.

Son DOS controles distintos y no deben mezclarse:

  CONTROL 1 (control_asignaciones.py) detecta asignaciones DUPLICADAS. Las
  asignaciones estructurales (SFC101/SFC102/SFC107/SFC108) y las 12
  POSTG-<MES> se repiten por diseño, así que quedan fuera del detector.
  Excluirlas significa SOLO eso: no se borran del SAP ni se ignoran
  contablemente.

  CONTROL 3 (control_cxc_cxp.py) sigue la cuenta 210103003 (CxP EMPRESAS)
  y DEBE seguir acumulando POSTG-<MES> por CUENTA+ASIGNACION. Aquí se
  verifica explícitamente que esta tarea no se lo quitó.

Datos sintéticos, ningún dato contable real. Los fixtures se reutilizan de
las suites existentes de cada control (no se duplican ni se modifican).

Uso: python -m unittest tests.test_control_america_postg -v
"""

import datetime
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config_cajas as cfg  # noqa: E402
import control_asignaciones as ca  # noqa: E402
import control_cxc_cxp as c3  # noqa: E402

from tests.test_control_asignaciones import (  # noqa: E402
    _ControlAsignacionesTestBase,
    _crear_global as _crear_global_c1,
    _partida as _partida_c1,
)
from tests.test_control_cxc_cxp import (  # noqa: E402
    _Control3TestBase,
    _partida as _partida_c3,
)


CXP_EMPRESAS = "210103003"
POSTG_SEPT = "POSTG-SEPT"


# ---------------------------------------------------------------------------
# Contenido EXACTO de las exclusiones (allowlist, nunca un prefijo)
# ---------------------------------------------------------------------------

class TestContenidoDeLasExclusiones(unittest.TestCase):
    """Fija los literales. Si alguien cambiara el mapa de meses en
    config_cajas, CONTROL 1 dejaría de excluir en silencio: este test lo
    impide."""

    POSTG_ESPERADAS = {
        "POSTG-ENE", "POSTG-FEB", "POSTG-MAR", "POSTG-ABR",
        "POSTG-MAY", "POSTG-JUN", "POSTG-JUL", "POSTG-AGO",
        "POSTG-SEPT", "POSTG-OCT", "POSTG-NOV", "POSTG-DIC",
    }

    def test_las_12_postg_autorizadas(self):
        self.assertEqual(set(ca._ASIGNACIONES_POSTGRADO), self.POSTG_ESPERADAS)
        self.assertEqual(len(ca._ASIGNACIONES_POSTGRADO), 12)

    def test_septiembre_es_sept_no_sep(self):
        self.assertIn("POSTG-SEPT", ca._ASIGNACIONES_POSTGRADO)
        self.assertNotIn("POSTG-SEP", ca._ASIGNACIONES_POSTGRADO)

    def test_coincide_con_lo_que_genera_el_motor(self):
        """CONTROL 1 debe excluir EXACTAMENTE lo que el motor escribe."""
        for mes in range(1, 13):
            generada = cfg.asignacion_reserva_posgrado(f"2026-{mes:02d}-15")
            self.assertIn(generada, ca._ASIGNACIONES_EXCLUIDAS)

    def test_asignaciones_estructurales_de_ambas_cajas(self):
        self.assertEqual(set(ca._ASIGNACIONES_SFC),
                         {"SFC101", "SFC102", "SFC107", "SFC108"})

    def test_no_se_agrego_america_mes(self):
        """La comisión ATC ya está excluida POR CUENTA (110201008): no hace
        falta ninguna regla de asignación para ella."""
        for mes in ("SEP", "AGO", "ENE"):
            self.assertNotIn(f"AMERICA {mes}", ca._ASIGNACIONES_EXCLUIDAS)
        self.assertTrue(ca.es_excluida("AMERICA SEP", "110201008"))

    def test_typos_de_postg_no_estan_excluidos(self):
        for typo in ("POSTG-SET", "POSTG-SEP", "POSTGRADO-SEPT",
                     "POSTG-SEPTIEMBRE", "POSTG", "POSTG-", "postg-sept"):
            with self.subTest(typo=typo):
                self.assertFalse(ca.es_excluida(typo, "210103003"))

    def test_exclusiones_previas_intactas(self):
        for previa in ("SFC101", "SFC102", "TIQUIPAYA AGO", "TIQUIPAYA SEP"):
            self.assertIn(previa, ca._ASIGNACIONES_EXCLUIDAS)
        self.assertFalse(ca.es_excluida("FORTALEZA", "110101001"))
        self.assertTrue(ca.es_excluida("FORTALEZA", "110201008"))


# ---------------------------------------------------------------------------
# A-G — CONTROL 1
# ---------------------------------------------------------------------------

class TestControl1America(_ControlAsignacionesTestBase):

    def _partida_america(self, asignacion, cuenta_mayor="110101003"):
        return _partida_c1(asignacion, cuenta_mayor=cuenta_mayor,
                           glosa="RECAUDACION CAJA AMERICA")

    def test_A_sfc107_repetido_no_alerta(self):
        resumen = self._ejecutar([self._partida_america("SFC107")] * 3)
        self.assertEqual(resumen["estado"], "OK_SIN_DUPLICADOS")
        self.assertEqual(resumen["asignaciones_excluidas"], 3)
        self.assertEqual(resumen["asignaciones_evaluadas"], 0)
        self.assertEqual(resumen["cantidad_hallazgos"], 0)

    def test_B_sfc108_repetido_no_alerta(self):
        resumen = self._ejecutar([self._partida_america("SFC108")] * 3)
        self.assertEqual(resumen["estado"], "OK_SIN_DUPLICADOS")
        self.assertEqual(resumen["asignaciones_excluidas"], 3)
        self.assertEqual(resumen["cantidad_hallazgos"], 0)

    def test_C_postg_sept_repetido_en_el_mismo_global_no_alerta(self):
        """La reserva se acumula todo el mes bajo la misma asignación."""
        partidas = [
            _partida_c1(POSTG_SEPT, cuenta_mayor=CXP_EMPRESAS, cargo=None,
                        haber="100.00", glosa="RESERVA POSGRADO",
                        fecha_valor=datetime.date(2026, 9, 1)),
            _partida_c1(POSTG_SEPT, cuenta_mayor=CXP_EMPRESAS, cargo=None,
                        haber="50.00", glosa="RESERVA POSGRADO",
                        fecha_valor=datetime.date(2026, 9, 5)),
            _partida_c1(POSTG_SEPT, cuenta_mayor=CXP_EMPRESAS, cargo=None,
                        haber="200.00", glosa="RESERVA POSGRADO",
                        fecha_valor=datetime.date(2026, 9, 12)),
        ]
        resumen = self._ejecutar(
            partidas, ruta_global=self._ruta_global(self.NOMBRE_GLOBAL_SEPTIEMBRE)
        )
        self.assertEqual(resumen["estado"], "OK_SIN_DUPLICADOS")
        self.assertEqual(resumen["asignaciones_excluidas"], 3)
        self.assertEqual(resumen["cantidad_hallazgos"], 0)
        self.assertEqual(resumen["asignaciones_duplicadas"], [])

    def test_D_postg_sept_en_otro_periodo_no_alerta(self):
        """Reaparecer en un GLOBAL posterior tampoco alerta, y nunca entra
        al histórico de CONTROL 1."""
        fila = _partida_c1(POSTG_SEPT, cuenta_mayor=CXP_EMPRESAS, cargo=None,
                           haber="100.00", glosa="RESERVA POSGRADO")
        r1 = self._ejecutar([fila], ruta_global=self._ruta_global(
            self.NOMBRE_GLOBAL_AGOSTO))
        r2 = self._ejecutar([fila], ruta_global=self._ruta_global(
            self.NOMBRE_GLOBAL_SEPTIEMBRE))

        self.assertEqual(r1["estado"], "OK_SIN_DUPLICADOS")
        self.assertEqual(r2["estado"], "OK_SIN_DUPLICADOS")
        self.assertEqual(r2["cantidad_hallazgos"], 0)

        historico = ca.cargar_historico(self.ruta_historico)
        self.assertNotIn(POSTG_SEPT, [f["asignacion"] for f in historico])

    def test_D2_postg_sept_ya_presente_en_el_historico_no_alerta(self):
        """Caso real de un GLOBAL procesado ANTES de esta corrección: la
        asignación quedó en el histórico. Volver a verla no debe alertar."""
        ca.guardar_historico(self.ruta_historico, [{
            "asignacion": POSTG_SEPT,
            "fecha_valor": "2026-09-01",
            "cuenta_mayor": CXP_EMPRESAS,
            "glosa": "RESERVA POSGRADO",
            "monto": "100.00",
            "archivo_global": "SAP_GLOBAL_TIQ_AGOSTO_2026.xlsx",
            "fila_sap": "16",
            "sha256_archivo": "a" * 64,
            "fecha_incorporacion": "2026-09-30T00:00:00",
        }])

        resumen = self._ejecutar(
            [_partida_c1(POSTG_SEPT, cuenta_mayor=CXP_EMPRESAS, cargo=None,
                         haber="50.00", glosa="RESERVA POSGRADO")],
            ruta_global=self._ruta_global(self.NOMBRE_GLOBAL_SEPTIEMBRE),
        )
        self.assertEqual(resumen["estado"], "OK_SIN_DUPLICADOS")
        self.assertEqual(resumen["cantidad_hallazgos"], 0)
        self.assertEqual(resumen["alertas_contra_historico"], 0)

    def test_E_asignacion_normal_repetida_sigue_alertando(self):
        resumen = self._ejecutar([
            self._partida_america("3P66536982"),
            self._partida_america("3P66536982"),
        ])
        self.assertEqual(resumen["estado"], "REVISAR_DUPLICADOS_ENCONTRADOS")
        self.assertEqual(resumen["asignaciones_duplicadas"], ["3P66536982"])
        # Se cuenta UNA ALERTA POR OCURRENCIA del GLOBAL (así se arma el
        # Excel de revisión), no una por par: dos filas -> 2.
        self.assertEqual(resumen["alertas_mismo_mes"], 2)
        self.assertEqual(resumen["asignaciones_excluidas"], 0)

    def test_F_asignacion_normal_contra_historico_sigue_alertando(self):
        # Importes distintos a propósito: dos GLOBAL byte-idénticos
        # compartirían SHA-256 y el segundo se saltaría por idempotencia.
        self._ejecutar([_partida_c1("3P66536982", cuenta_mayor="110101003",
                                    cargo="100.00")],
                       ruta_global=self._ruta_global(self.NOMBRE_GLOBAL_AGOSTO))
        resumen = self._ejecutar(
            [_partida_c1("3P66536982", cuenta_mayor="110101003",
                         cargo="250.00")],
            ruta_global=self._ruta_global(self.NOMBRE_GLOBAL_SEPTIEMBRE),
        )
        self.assertEqual(resumen["estado"], "REVISAR_DUPLICADOS_ENCONTRADOS")
        self.assertEqual(resumen["alertas_contra_historico"], 1)
        self.assertEqual(resumen["asignaciones_duplicadas"], ["3P66536982"])

    def test_G_typo_postg_set_sigue_alertando(self):
        """El riesgo que una regla por prefijo habría ocultado."""
        resumen = self._ejecutar([
            _partida_c1("POSTG-SET", cuenta_mayor=CXP_EMPRESAS, cargo=None,
                        haber="100.00", glosa="RESERVA POSGRADO"),
            _partida_c1("POSTG-SET", cuenta_mayor=CXP_EMPRESAS, cargo=None,
                        haber="50.00", glosa="RESERVA POSGRADO"),
        ])
        self.assertEqual(resumen["estado"], "REVISAR_DUPLICADOS_ENCONTRADOS")
        self.assertEqual(resumen["asignaciones_duplicadas"], ["POSTG-SET"])
        self.assertEqual(resumen["alertas_mismo_mes"], 2)  # una por ocurrencia
        self.assertEqual(resumen["asignaciones_excluidas"], 0)

    def test_G2_otros_typos_de_postg_siguen_alertando(self):
        for typo in ("POSTGRADO-SEPT", "POSTG-SEPTIEMBRE", "POSTG-SEP"):
            with self.subTest(typo=typo):
                self.setUp()  # histórico limpio por cada variante
                resumen = self._ejecutar([
                    _partida_c1(typo, cuenta_mayor=CXP_EMPRESAS, cargo=None,
                                haber="100.00", glosa="RESERVA POSGRADO"),
                    _partida_c1(typo, cuenta_mayor=CXP_EMPRESAS, cargo=None,
                                haber="50.00", glosa="RESERVA POSGRADO"),
                ])
                self.assertEqual(resumen["estado"], "REVISAR_DUPLICADOS_ENCONTRADOS")
                self.assertEqual(resumen["asignaciones_duplicadas"], [typo])

    def test_sfc_y_postg_conviven_con_duplicados_reales(self):
        """Un GLOBAL mixto: lo estructural se excluye y el duplicado real
        se sigue detectando en la misma corrida."""
        resumen = self._ejecutar([
            self._partida_america("SFC107"),
            self._partida_america("SFC107"),
            self._partida_america("SFC108"),
            _partida_c1(POSTG_SEPT, cuenta_mayor=CXP_EMPRESAS, cargo=None,
                        haber="100.00", glosa="RESERVA POSGRADO"),
            _partida_c1(POSTG_SEPT, cuenta_mayor=CXP_EMPRESAS, cargo=None,
                        haber="200.00", glosa="RESERVA POSGRADO"),
            self._partida_america("3P66536982"),
            self._partida_america("3P66536982"),
        ])
        self.assertEqual(resumen["estado"], "REVISAR_DUPLICADOS_ENCONTRADOS")
        self.assertEqual(resumen["asignaciones_excluidas"], 5)
        self.assertEqual(resumen["asignaciones_evaluadas"], 2)
        self.assertEqual(resumen["asignaciones_duplicadas"], ["3P66536982"])


# ---------------------------------------------------------------------------
# CONTROL 3 — regresión: POSTG debe seguir acumulándose
# ---------------------------------------------------------------------------

class TestControl3AcumulaPostg(_Control3TestBase):

    def test_universo_de_cuentas_conserva_210103003(self):
        self.assertIn(CXP_EMPRESAS, c3._CUENTAS_CONTROL)

    def test_control3_no_conoce_exclusiones_de_asignacion(self):
        """CONTROL 3 no importa ni replica las exclusiones de CONTROL 1:
        son controles independientes."""
        import inspect
        fuente = inspect.getsource(c3)
        self.assertNotIn("POSTG", fuente)
        self.assertNotIn("es_excluida", fuente)

    def test_acumula_100_50_200_y_queda_abierto(self):
        """100 + 50 + 200 = 350 -> SALDO 350, ABIERTO."""
        resumen, _ = self._ejecutar(
            [
                _partida_c3(CXP_EMPRESAS, POSTG_SEPT, haber="100.00"),
                _partida_c3(CXP_EMPRESAS, POSTG_SEPT, haber="50.00"),
                _partida_c3(CXP_EMPRESAS, POSTG_SEPT, haber="200.00"),
            ],
            nombre_global="SAP_GLOBAL_TIQ_SEPTIEMBRE_2026.xlsx",
        )
        self.assertEqual(resumen["estado"], "OK")

        fila = self._historico()[(CXP_EMPRESAS, POSTG_SEPT)]
        self.assertEqual(fila["debe_acumulado"], "0.00")
        self.assertEqual(fila["haber_acumulado"], "350.00")
        self.assertEqual(fila["saldo"], "350.00")
        self.assertEqual(fila["estado"], "ABIERTO")

    def test_cierre_posterior_con_debe_350_queda_cerrado(self):
        """Y al compensarse después: SALDO 0, CERRADO."""
        self._ejecutar(
            [
                _partida_c3(CXP_EMPRESAS, POSTG_SEPT, haber="100.00"),
                _partida_c3(CXP_EMPRESAS, POSTG_SEPT, haber="50.00"),
                _partida_c3(CXP_EMPRESAS, POSTG_SEPT, haber="200.00"),
            ],
            nombre_global="SAP_GLOBAL_TIQ_SEPTIEMBRE_2026.xlsx",
        )
        self._ejecutar(
            [_partida_c3(CXP_EMPRESAS, POSTG_SEPT, debe="350.00")],
            nombre_global="SAP_GLOBAL_TIQ_OCTUBRE_2026.xlsx",
        )

        fila = self._historico()[(CXP_EMPRESAS, POSTG_SEPT)]
        self.assertEqual(fila["debe_acumulado"], "350.00")
        self.assertEqual(fila["haber_acumulado"], "350.00")
        self.assertEqual(fila["saldo"], "0.00")
        self.assertEqual(fila["estado"], "CERRADO")

    def test_llave_cuenta_mas_asignacion_sigue_separando_entidades(self):
        """POSTG-SEPT y POSTG-OCT son entidades distintas, no se mezclan."""
        self._ejecutar(
            [
                _partida_c3(CXP_EMPRESAS, POSTG_SEPT, haber="350.00"),
                _partida_c3(CXP_EMPRESAS, "POSTG-OCT", haber="120.00"),
            ],
            nombre_global="SAP_GLOBAL_TIQ_SEPTIEMBRE_2026.xlsx",
        )
        historico = self._historico()
        self.assertEqual(historico[(CXP_EMPRESAS, POSTG_SEPT)]["saldo"], "350.00")
        self.assertEqual(historico[(CXP_EMPRESAS, "POSTG-OCT")]["saldo"], "120.00")

    def test_cuenta_110101003_de_america_no_entra_a_control3(self):
        """Las líneas normales de América (SFC107/SFC108) no son CxC/CxP:
        su cuenta no pertenece al universo controlado."""
        self.assertNotIn("110101003", c3._CUENTAS_CONTROL)
        self._ejecutar(
            [
                _partida_c3("110101003", "SFC107", haber="1900.00"),
                _partida_c3("110101003", "SFC108", haber="500.00"),
            ],
            nombre_global="SAP_GLOBAL_TIQ_SEPTIEMBRE_2026.xlsx",
        )
        self.assertEqual(self._historico(), {})


if __name__ == "__main__":
    unittest.main()
