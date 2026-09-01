"""
test_asiento.py — ETAPA 5: pruebas unitarias del asiento determinístico.

Usa fixtures mínimos construidos a partir de los valores YA conocidos de la
regresión real 19-08-2026 (ver HANDOFF_CODE_V2.md), sin abrir ningún Excel
ni subir datos contables reales al repositorio. No repite extracción ni
cruces: alimenta directamente construir_asiento() y validar_ci() con
estructuras equivalentes a las que produce el motor.

Uso: python -m unittest tests.test_asiento -v   (desde la raíz del repo)
"""

import os
import sys
import unittest
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import motor_tiquipaya as motor


# ---------------------------------------------------------------------------
# Fixture 19-08-2026 (valores de la regresión real ya validada)
# ---------------------------------------------------------------------------

FECHA_CIERRE = "2026-08-19"
SFC101_TOTAL = "137504.96"
SFC102_TOTAL = "144552.00"
VOUCHERS_TOTAL = Decimal("80805.00")
CI_TOTAL = Decimal("70368.96")
ATC_NETO = "130246.43"
ATC_COMISION = "636.57"

N_VOUCHERS = 4
N_CI = 49


def _repartir(total, n):
    """Divide `total` (Decimal) en `n` montos positivos que suman exacto,
    absorbiendo el resto de redondeo en el último elemento."""
    base = (total / n).quantize(Decimal("0.01"))
    montos = [base] * (n - 1)
    montos.append(total - base * (n - 1))
    return montos


def _fixture_vouchers():
    montos = _repartir(VOUCHERS_TOTAL, N_VOUCHERS)
    vouchers = []
    for i, monto in enumerate(montos):
        sfc = "SFC101" if i % 2 == 0 else "SFC102"
        vouchers.append({
            "sfc": sfc,
            "importe": motor.io.money_str(monto),
            "codigo_confirmado": f"VCH{i:04d}",
            "codigo_informado": f"VCH{i:04d}" if i != 0 else "VCHOOOO0",
            "fecha_bancaria": FECHA_CIERRE,
            "estado": "AUTOCORRECCION_0_O" if i == 0 else "MATCH_EXACTO",
        })
    return vouchers


def _fixture_ci():
    montos = _repartir(CI_TOTAL, N_CI)
    ci_list = []
    for i, monto in enumerate(montos):
        sfc = "SFC101" if i % 2 == 0 else "SFC102"
        ci_list.append({
            "sfc": sfc,
            "referencia": f"FAC-{i:04d}",
            "importe": motor.io.money_str(monto),
            "cuenta_contable": "210201005",
            "asignacion": f"CI{i:04d}",
        })
    return ci_list


def _resultado_v2_ok():
    detalle = {
        "sfc101_total": SFC101_TOTAL,
        "sfc102_total": SFC102_TOTAL,
        "vouchers_confirmados": _fixture_vouchers(),
        "ci_validas": _fixture_ci(),
        "atc_neto": {
            "importe": ATC_NETO,
            "codigo_confirmado": "ATC-19082026",
            "fecha_bancaria": FECHA_CIERRE,
        },
        "atc_comision": {"importe": ATC_COMISION},
        "dolares": "0.00",
    }
    return {
        "fecha": FECHA_CIERRE,
        "universo_original": "282056.96",
        "alquileres": "0.00",
        "universo_ajustado": "282056.96",
        "componentes": {
            "vouchers": "80805.00",
            "ci_operativas": "70368.96",
            "atc_bruto": "130883.00",
            "dolares": "0.00",
        },
        "recaudacion_explicada": "282056.96",
        "diferencia": "0.00",
        "excepciones_bloqueantes": 0,
        "estado": "OK",
        "detalle": detalle,
    }


class TestConstruirAsientoRegresion190826(unittest.TestCase):
    """Regresión contable 19-08-2026 con fixture derivado del baseline."""

    def setUp(self):
        self.resultado_v2 = _resultado_v2_ok()
        self.asiento = motor.construir_asiento(self.resultado_v2)

    def test_estado_ok(self):
        self.assertEqual(self.asiento["estado"], "OK")
        self.assertEqual(self.asiento["problemas"], [])

    def test_totales_cuadran(self):
        self.assertEqual(self.asiento["total_cargo"], "282056.96")
        self.assertEqual(self.asiento["total_haber"], "282056.96")
        self.assertEqual(self.asiento["diferencia"], "0.00")

    def test_cantidad_de_partidas(self):
        # 4 vouchers + 49 CI + 1 ATC neto + 1 ATC comisión + 2 HABER = 57
        self.assertEqual(self.asiento["cantidad_partidas"], 57)
        self.assertEqual(len(self.asiento["partidas"]), 57)

    def test_dos_partidas_haber_normales(self):
        haber = [p for p in self.asiento["partidas"]
                 if p["origen"] in ("UNIVERSO_SFC101", "UNIVERSO_SFC102")]
        self.assertEqual(len(haber), 2)
        for p in haber:
            self.assertEqual(p["cuenta_mayor"], "110101001")
            self.assertEqual(p["cargo"], "0.00")

    def test_cuentas_por_origen(self):
        for p in self.asiento["partidas"]:
            if p["origen"] == "VOUCHER":
                self.assertEqual(p["cuenta_mayor"], "110103012")
            elif p["origen"] == "ATC_NETO":
                self.assertEqual(p["cuenta_mayor"], "110103012")
            elif p["origen"] == "ATC_COMISION":
                self.assertEqual(p["cuenta_mayor"], "110201008")

    def test_asignacion_comision_respeta_18_caracteres(self):
        comision = next(p for p in self.asiento["partidas"] if p["origen"] == "ATC_COMISION")
        self.assertEqual(comision["asignacion"], "TIQUIPAYA AGO")
        self.assertLessEqual(len(comision["asignacion"]), 18)

    def test_trazabilidad_autocorreccion_0_o(self):
        self.assertEqual(len(self.asiento["correcciones_aplicadas"]), 1)
        corr = self.asiento["correcciones_aplicadas"][0]
        self.assertEqual(corr["tipo"], "AUTOCORRECCION_0_O")
        self.assertEqual(corr["codigo_informado"], "VCHOOOO0")
        voucher_partida = next(
            p for p in self.asiento["partidas"]
            if p["origen"] == "VOUCHER" and p["codigo_informado_original"] is not None
        )
        self.assertEqual(voucher_partida["codigo_informado_original"], "VCHOOOO0")

    def test_ningun_cargo_haber_simultaneo_ni_negativo(self):
        for p in self.asiento["partidas"]:
            cargo = Decimal(p["cargo"])
            haber = Decimal(p["haber"])
            self.assertFalse(cargo > 0 and haber > 0)
            self.assertGreaterEqual(cargo, 0)
            self.assertGreaterEqual(haber, 0)

    def test_todas_las_ci_tienen_cuenta_y_asignacion(self):
        for p in self.asiento["partidas"]:
            if p["origen"] == "CI":
                self.assertTrue(p["cuenta_mayor"])
                self.assertTrue(p["asignacion"])


class TestPrecondicionesBloqueo(unittest.TestCase):
    """No debe construirse asiento si el cierre no está limpio."""

    def test_no_asiento_si_estado_no_ok(self):
        resultado = _resultado_v2_ok()
        resultado["estado"] = "BLOQUEADO_EXCEPCION"
        resultado["excepciones_bloqueantes"] = 2
        asiento = motor.construir_asiento(resultado)
        self.assertEqual(asiento["estado"], "NO_ASIENTO")
        self.assertEqual(asiento["partidas"], [])

    def test_no_asiento_si_diferencia_no_es_cero(self):
        resultado = _resultado_v2_ok()
        resultado["diferencia"] = "0.01"
        asiento = motor.construir_asiento(resultado)
        self.assertEqual(asiento["estado"], "NO_ASIENTO")

    def test_no_asiento_si_falta_detalle(self):
        resultado = _resultado_v2_ok()
        resultado["detalle"] = None
        asiento = motor.construir_asiento(resultado)
        self.assertEqual(asiento["estado"], "NO_ASIENTO")

    def test_usd_cuenta_pendiente_si_dolares_mayor_a_cero(self):
        resultado = _resultado_v2_ok()
        resultado["detalle"]["dolares"] = "50.00"
        asiento = motor.construir_asiento(resultado)
        self.assertEqual(asiento["estado"], "USD_CUENTA_PENDIENTE")
        self.assertEqual(asiento["partidas"], [])

    def test_dolares_cero_no_genera_partida(self):
        resultado = _resultado_v2_ok()
        resultado["detalle"]["dolares"] = "0.00"
        asiento = motor.construir_asiento(resultado)
        self.assertEqual(asiento["estado"], "OK")
        for p in asiento["partidas"]:
            self.assertNotEqual(p["origen"], "DOLARES")


class TestValidarCiExcluyeAlquileres(unittest.TestCase):
    """ALQUILERES nunca debe aparecer entre las CI válidas expuestas para
    el asiento (excluidas por validar_ci, ETAPA 3/4, ya vigente)."""

    def test_alquileres_no_esta_en_detalle_validas(self):
        cierre = {
            "comunicaciones_internas": [
                {
                    "sfc": "SFC101", "referencia": "F-1", "importe": "100.00",
                    "cuenta_contable": "210201005", "asignacion": "CI0001",
                    "banco": "BNB", "alquileres": False,
                },
                {
                    "sfc": "SFC101", "referencia": "F-2", "importe": "500.00",
                    "cuenta_contable": None, "asignacion": None,
                    "banco": "ALQUILERES", "alquileres": True,
                },
            ]
        }
        resultado = motor.validar_ci(cierre)
        self.assertEqual(resultado["alquileres_cantidad"], 1)
        self.assertEqual(len(resultado["detalle_validas"]), 1)
        self.assertEqual(resultado["detalle_validas"][0]["referencia"], "F-1")


if __name__ == "__main__":
    unittest.main()
