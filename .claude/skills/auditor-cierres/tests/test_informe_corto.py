"""Pruebas de los tres reportes cortos y de su clasificacion estructurada."""
import datetime
import os
import shutil
import sys
import tempfile
import unittest
from decimal import Decimal

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))

import informe_corto as ic  # noqa: E402

D = datetime.date


def hall(tipo, caja="america", fecha=D(2026, 9, 3), resultado="REVISAR", sfc="SFC107", fila="F3", **datos):
    d = {"tipo": tipo}
    d.update(datos)
    # El texto es deliberadamente inutil: el informe corto no debe interpretarlo.
    return {"fecha": fecha, "caja": caja, "sfc": sfc, "control": 5, "resultado": resultado,
            "hallazgo": "TEXTO QUE NO DEBE PARSEARSE: MACROS 99/99/9999", "accion": "IGNORAR", "fila": fila, "datos": d}


def c5_probable(aplicado=False, fecha="09/04/2026", hasta="28/09/2026"):
    return hall("c5", motivo="SIN_VOUCHER_EN_MACROS", deposito="Depósito 1", celda="F3", valor_actual=fecha,
                fecha_en_cierre=fecha, importe="9527.50", asignacion="3P91155531", aplicado=aplicado,
                candidatos={"veredicto": "CANDIDATO PROBABLE", "macros_hasta": hasta,
                            "declarado": {"importe": "9527.50", "fecha": fecha, "asignacion": "3P91155531"},
                            "candidatos": [{"fecha": "04/09/2026", "importe": "9527.50", "asignacion": "3P94114380"}]})


class TestClasificacion(unittest.TestCase):
    def modelo(self, hallazgos, alquileres=None):
        cierres = [{"caja": "america", "fecha": D(2026, 9, 3)}, {"caja": "tiquipaya", "fecha": D(2026, 9, 23)}]
        return ic.construir_modelo(datetime.datetime(2026, 9, 26, 12), cierres, hallazgos, alquileres or [],
                                   [r"C:\tmp\MACROS SEPTIEMBRE.xlsm"])

    def test_america_03_prioriza_asignacion_y_no_muestra_fecha_autocorregible(self):
        m = self.modelo([c5_probable()])
        self.assertEqual(len(m["acciones"]), 1)
        a = m["acciones"][0]
        self.assertIn("asignación/voucher 3P91155531", a["mal"])
        self.assertEqual(a["candidato"]["asignacion"], "3P94114380")
        self.assertNotIn("09/04/2026", a["mal"] + a["hacer"] + a["gabo"])

    def test_fecha_normalizada_automaticamente_no_llega_a_caja(self):
        m = self.modelo([c5_probable(aplicado=True)])
        self.assertEqual(m["acciones"], [])

    def test_fecha_imposible_si_llega_a_caja_con_el_valor(self):
        h = hall("c5", motivo="TEXTO_FECHA_INEXISTENTE_EN_CALENDARIO", deposito="Depósito 1", celda="F3",
                 valor_actual="05/0/2026", aplicado=False)
        a = self.modelo([h])["acciones"][0]
        self.assertIn("05/0/2026", a["mal"])
        self.assertIn("no puede resolverse automáticamente", a["mal"])

    def test_registros_bancarios_sin_cobertura_no_se_envian_a_caja(self):
        h = c5_probable(fecha="30/09/2026", hasta="20/09/2026")
        m = self.modelo([h])
        self.assertEqual(m["acciones"], [])
        self.assertEqual(m["pendientes"], {("america", D(2026, 9, 3))})

    def test_bloqueo_del_motor_solo_por_cobertura_no_se_envia_a_caja(self):
        h = hall("motor_observaciones", sfc=None, fila=None, codigo_bloqueo="MACROS_NO_CUBRE_FECHA_DEPOSITO",
                 fecha_maxima_macros="2026-09-20", fecha_requerida_deposito="2026-09-23", observaciones=[])
        m = self.modelo([h])
        self.assertEqual(m["acciones"], [])
        self.assertEqual(len(m["pendientes"]), 1)

    def test_sin_archivo_bancario_el_sin_voucher_no_se_convierte_en_error_de_caja(self):
        falta = hall("c5_sin_macros", sfc=None, fila=None, ilegible=False)
        sin_voucher = c5_probable()
        sin_voucher["datos"]["candidatos"] = None
        m = self.modelo([falta, sin_voucher])
        self.assertEqual(m["acciones"], [])
        self.assertEqual(len(m["pendientes"]), 1)

    def test_alquileres_en_asignacion_conserva_exencion_y_activa_solo_nota_de_motor(self):
        alq = [{"caja": "tiquipaya", "fecha": D(2026, 9, 23), "sfc": "SFC102", "fila": 2,
                "importe": Decimal("1560"), "fecha_del_cierre": False, "marcado_en": "asignacion"}]
        m = self.modelo([], alq)
        self.assertEqual(m["acciones"], [])
        self.assertTrue(m["nota_motor_alquileres"])
        self.assertEqual(next(iter(m["alquileres"]))[3], "asignacion")

    def test_no_parsea_la_frase_del_hallazgo(self):
        h = hall("c4_formato_asignacion", banco="BNB MN", asignacion="123456", esperado="código alfanumérico")
        a = self.modelo([h])["acciones"][0]
        self.assertIn("123456", a["mal"])
        self.assertNotIn("99/99/9999", a["mal"] + a["hacer"] + a["gabo"])


class TestPDF(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="test_ic_")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_genera_los_tres_pdf_y_oculta_macros_en_los_de_caja(self):
        cierres = [{"caja": "america", "fecha": D(2026, 9, 3)}, {"caja": "tiquipaya", "fecha": D(2026, 9, 23)}]
        imposible = hall("c5", motivo="TEXTO_FECHA_INEXISTENTE_EN_CALENDARIO", deposito="Depósito 1", celda="F3",
                          valor_actual="05/0/2026", aplicado=False)
        out = ic.generar(self.tmp, datetime.datetime(2026, 9, 26, 12), cierres, [c5_probable(), imposible], [],
                         [r"C:\tmp\MACROS SEPTIEMBRE.xlsm"])
        self.assertEqual(sorted(os.path.basename(out[k]) for k in
                                ("resumen_gabo", "para_caja_america", "para_caja_tiquipaya")),
                         ["PARA_CAJA_AMERICA.pdf", "PARA_CAJA_TIQUIPAYA.pdf", "RESUMEN_GABO.pdf"])
        from pypdf import PdfReader
        for clave in ("para_caja_america", "para_caja_tiquipaya"):
            texto = "\n".join(p.extract_text() or "" for p in PdfReader(out[clave]).pages)
            self.assertNotIn("MACROS", texto.upper())
        america = "\n".join(p.extract_text() or "" for p in PdfReader(out["para_caja_america"]).pages)
        self.assertIn("05/0/2026", america)
        self.assertNotIn("09/04/2026", america)


if __name__ == "__main__":
    unittest.main()
