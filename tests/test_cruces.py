"""test_cruces.py — pruebas unitarias de ETAPA 3 (cruzar_vouchers,
cruzar_atc) sobre fixtures de diccionario en memoria (sin Excel), igual que
test_asiento.py. No sube datos contables reales.

Uso: python -m unittest tests.test_cruces -v
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import motor_tiquipaya as motor
import excel_io as io


# ---------------------------------------------------------------------------
# 5-7. ATC — compatibilidad de fecha bancaria contra fecha de cierre
# ---------------------------------------------------------------------------

FECHA_CIERRE = "2026-08-19"


def _cierre_atc(bruto="130883.00"):
    mitad = str(round(float(bruto) / 2, 2))
    return {
        "fecha_cierre": FECHA_CIERRE,
        "sfc101": {"cobros_atc": mitad},
        "sfc102": {"cobros_atc": mitad},
    }


def _atc_idx(neto="130246.43", comision="636.57"):
    return {FECHA_CIERRE: {"neto": neto, "comision": comision}}


def _macros_por_importe(movs):
    """Arma un macros_idx completo (por_codigo + por_importe), como lo
    hace excel_io.leer_macros_bnb, a partir de una lista de movimientos
    {"codigo", "importe", "fecha"}."""
    por_codigo = {}
    por_importe = {}
    for m in movs:
        por_codigo.setdefault(io.normalize_codigo(m["codigo"]), []).append(m)
        por_importe.setdefault(m["importe"], []).append(m)
    return {"por_codigo": por_codigo, "por_importe": por_importe}


class TestAtcFechaCompatible(unittest.TestCase):
    def setUp(self):
        # bruto = neto + comision = 130246.43 + 636.57
        self.cierre = _cierre_atc("130883.00")
        self.atc_idx = _atc_idx()

    def test_candidato_anterior_a_cierre_no_hace_match(self):
        macros_idx = _macros_por_importe([
            {"codigo": "X1", "importe": "130246.43", "fecha": "2026-08-18"},
        ])
        resultado = motor.cruzar_atc(self.cierre, self.atc_idx, macros_idx)
        self.assertEqual(resultado["estado_match_macros"], "ATC_SIN_CANDIDATO")
        self.assertTrue(resultado["excepcion"])

    def test_candidato_posterior_unico_hace_match(self):
        macros_idx = _macros_por_importe([
            {"codigo": "X1", "importe": "130246.43", "fecha": "2026-08-20"},
        ])
        resultado = motor.cruzar_atc(self.cierre, self.atc_idx, macros_idx)
        self.assertEqual(resultado["estado_match_macros"], "ATC_MATCH_EXACTO")
        self.assertFalse(resultado["excepcion"])
        self.assertEqual(resultado["codigo_encontrado"], "X1")

    def test_candidato_mismo_dia_del_cierre_hace_match(self):
        macros_idx = _macros_por_importe([
            {"codigo": "X1", "importe": "130246.43", "fecha": FECHA_CIERRE},
        ])
        resultado = motor.cruzar_atc(self.cierre, self.atc_idx, macros_idx)
        self.assertEqual(resultado["estado_match_macros"], "ATC_MATCH_EXACTO")

    def test_multiples_candidatos_posteriores_es_multiple(self):
        macros_idx = _macros_por_importe([
            {"codigo": "X1", "importe": "130246.43", "fecha": "2026-08-20"},
            {"codigo": "X2", "importe": "130246.43", "fecha": "2026-08-21"},
        ])
        resultado = motor.cruzar_atc(self.cierre, self.atc_idx, macros_idx)
        self.assertEqual(resultado["estado_match_macros"], "ATC_MULTIPLE")
        self.assertTrue(resultado["excepcion"])

    def test_candidato_anterior_no_cuenta_aunque_sea_unico_en_el_mes(self):
        # Un solo candidato con ese importe en todo MACROS, pero anterior
        # al cierre: nunca debe elegirse solo por ser único.
        macros_idx = _macros_por_importe([
            {"codigo": "X1", "importe": "130246.43", "fecha": "2026-08-01"},
        ])
        resultado = motor.cruzar_atc(self.cierre, self.atc_idx, macros_idx)
        self.assertNotEqual(resultado["estado_match_macros"], "ATC_MATCH_EXACTO")
        self.assertEqual(resultado["estado_match_macros"], "ATC_SIN_CANDIDATO")


# ---------------------------------------------------------------------------
# 15-17. Vouchers — O<->P nunca autocorrección, 0<->O único/ambiguo
# ---------------------------------------------------------------------------

def _cierre_voucher(asignacion, importe, sfc="SFC101"):
    return {
        "sfc101": {"depositos": [{"sfc": sfc, "asignacion": asignacion, "importe": importe}]},
        "sfc102": {"depositos": []},
    }


class TestVouchersMatching(unittest.TestCase):
    def test_o_p_nunca_autocorreccion(self):
        # Código informado con "P", el macros trae "O" en la misma
        # posición: 1 solo carácter de diferencia, pero no es 0<->O.
        macros_idx = _macros_por_importe([
            {"codigo": "ABO123", "importe": "500.00", "fecha": FECHA_CIERRE},
        ])
        cierre = _cierre_voucher("ABP123", "500.00")
        resultado = motor.cruzar_vouchers(cierre, macros_idx)
        r = resultado["detalle"][0]
        self.assertEqual(r["estado"], "POSIBLE_TYPO")
        self.assertEqual(resultado["conteo"]["AUTOCORRECCION_0_O"], 0)

    def test_0_o_unico_es_autocorreccion(self):
        macros_idx = _macros_por_importe([
            {"codigo": "ABO123", "importe": "500.00", "fecha": FECHA_CIERRE},
        ])
        cierre = _cierre_voucher("AB0123", "500.00")
        resultado = motor.cruzar_vouchers(cierre, macros_idx)
        r = resultado["detalle"][0]
        self.assertEqual(r["estado"], "AUTOCORRECCION_0_O")
        self.assertEqual(r["codigo_encontrado"], "ABO123")

    def test_0_o_ambiguo_es_multiple(self):
        # Código informado "X0O1" (no existe tal cual en MACROS). Al
        # intercambiar 0<->O aparecen varias variantes; MACROS trae DOS de
        # ellas ("XOO1" y "X001") con el mismo importe: ambigüedad real,
        # no se autocorrige a ciegas.
        macros_idx = _macros_por_importe([
            {"codigo": "XOO1", "importe": "500.00", "fecha": FECHA_CIERRE},
            {"codigo": "X001", "importe": "500.00", "fecha": FECHA_CIERRE},
        ])
        cierre = _cierre_voucher("X0O1", "500.00")
        resultado = motor.cruzar_vouchers(cierre, macros_idx)
        r = resultado["detalle"][0]
        self.assertEqual(r["estado"], "MULTIPLE")


if __name__ == "__main__":
    unittest.main()
