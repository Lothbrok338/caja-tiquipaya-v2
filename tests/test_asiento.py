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
        # Sin ALQUILERES en el fixture base: HABER ajustado == total.
        "sfc101_haber": SFC101_TOTAL,
        "sfc102_haber": SFC102_TOTAL,
        "alquileres_sfc101": "0.00",
        "alquileres_sfc102": "0.00",
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

    def test_usd_mayor_a_cero_genera_partida_debe_caja_me(self):
        # CORRECCIÓN USD/DOLARES (post-ETAPA 8): ya no bloquea el asiento;
        # genera una partida DEBE 110101010 balanceando el HABER SFC101
        # con el mismo importe (aislado del cuadre real de ejecutar_v2,
        # que no se toca aquí).
        resultado = _resultado_v2_ok()
        resultado["detalle"]["dolares"] = "50.00"
        resultado["detalle"]["sfc101_haber"] = motor.io.money_str(
            Decimal(resultado["detalle"]["sfc101_haber"]) + Decimal("50.00")
        )
        asiento = motor.construir_asiento(resultado)
        self.assertEqual(asiento["estado"], "OK", asiento)
        self.assertNotEqual(asiento["estado"], "USD_CUENTA_PENDIENTE")

        usd = next(p for p in asiento["partidas"] if p["origen"] == "DOLARES")
        self.assertEqual(usd["cuenta_mayor"], "110101010")
        self.assertEqual(usd["cargo"], "50.00")
        self.assertEqual(usd["haber"], "0.00")
        self.assertEqual(usd["texto_posicion"], "RECAUDACION DOLARES")
        self.assertIsNone(usd["asignacion"])
        self.assertEqual(usd["fecha_valor"], resultado["fecha"])
        self.assertEqual(usd["sociedad"], "BO01")
        self.assertEqual(usd["centro_beneficio"], "10010101")

    def test_dolares_cero_no_genera_partida(self):
        resultado = _resultado_v2_ok()
        resultado["detalle"]["dolares"] = "0.00"
        asiento = motor.construir_asiento(resultado)
        self.assertEqual(asiento["estado"], "OK")
        self.assertNotEqual(asiento["estado"], "USD_CUENTA_PENDIENTE")
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


# ---------------------------------------------------------------------------
# ALQUILERES por SFC: HABER ajustado (correción obligatoria A)
# ---------------------------------------------------------------------------

def _resultado_v2_con_alquileres(alq_sfc101="0.00", alq_sfc102="0.00"):
    """Parte de _resultado_v2_ok() y simula que ALQUILERES ya estaba
    incluido en el TOTAL MOVIMIENTO crudo de cada SFC (como en un Excel
    real): se suma al total crudo y se resta al HABER ajustado, dejando
    el universo_ajustado y la recaudación explicada iguales al baseline
    (el alquiler nunca fue parte de CI_OPERATIVAS)."""
    resultado = _resultado_v2_ok()
    alq101 = Decimal(alq_sfc101)
    alq102 = Decimal(alq_sfc102)

    sfc101_total_crudo = Decimal(SFC101_TOTAL) + alq101
    sfc102_total_crudo = Decimal(SFC102_TOTAL) + alq102

    resultado["detalle"]["sfc101_total"] = motor.io.money_str(sfc101_total_crudo)
    resultado["detalle"]["sfc102_total"] = motor.io.money_str(sfc102_total_crudo)
    resultado["detalle"]["sfc101_haber"] = SFC101_TOTAL
    resultado["detalle"]["sfc102_haber"] = SFC102_TOTAL
    resultado["detalle"]["alquileres_sfc101"] = motor.io.money_str(alq101)
    resultado["detalle"]["alquileres_sfc102"] = motor.io.money_str(alq102)
    return resultado


class TestAlquileresPorSFC(unittest.TestCase):
    """2-4. ALQUILERES excluido del asiento, HABER ajustado por SFC, el
    asiento sigue cuadrando y no aparece ninguna partida ALQUILERES."""

    def test_alquileres_sfc101(self):
        resultado = _resultado_v2_con_alquileres(alq_sfc101="1000.00")
        asiento = motor.construir_asiento(resultado)
        self.assertEqual(asiento["estado"], "OK")
        haber101 = next(p for p in asiento["partidas"] if p["origen"] == "UNIVERSO_SFC101")
        haber102 = next(p for p in asiento["partidas"] if p["origen"] == "UNIVERSO_SFC102")
        self.assertEqual(haber101["haber"], "137504.96")
        self.assertEqual(haber102["haber"], "144552.00")
        self.assertEqual(asiento["total_cargo"], asiento["total_haber"])
        self.assertEqual(asiento["diferencia"], "0.00")
        self.assertFalse(any(p["origen"] == "ALQUILERES" for p in asiento["partidas"]))

    def test_alquileres_sfc102(self):
        resultado = _resultado_v2_con_alquileres(alq_sfc102="2000.00")
        asiento = motor.construir_asiento(resultado)
        self.assertEqual(asiento["estado"], "OK")
        haber101 = next(p for p in asiento["partidas"] if p["origen"] == "UNIVERSO_SFC101")
        haber102 = next(p for p in asiento["partidas"] if p["origen"] == "UNIVERSO_SFC102")
        self.assertEqual(haber101["haber"], "137504.96")
        self.assertEqual(haber102["haber"], "144552.00")
        self.assertEqual(asiento["total_cargo"], asiento["total_haber"])
        self.assertFalse(any(p["origen"] == "ALQUILERES" for p in asiento["partidas"]))

    def test_alquileres_en_ambos_sfc(self):
        resultado = _resultado_v2_con_alquileres(alq_sfc101="500.00", alq_sfc102="700.00")
        asiento = motor.construir_asiento(resultado)
        self.assertEqual(asiento["estado"], "OK")
        haber101 = next(p for p in asiento["partidas"] if p["origen"] == "UNIVERSO_SFC101")
        haber102 = next(p for p in asiento["partidas"] if p["origen"] == "UNIVERSO_SFC102")
        self.assertEqual(haber101["haber"], "137504.96")
        self.assertEqual(haber102["haber"], "144552.00")
        self.assertEqual(asiento["total_cargo"], "282056.96")
        self.assertEqual(asiento["total_haber"], "282056.96")
        self.assertEqual(asiento["diferencia"], "0.00")
        self.assertFalse(any(p["origen"] == "ALQUILERES" for p in asiento["partidas"]))


class TestValidarCiAlquileresPorSFC(unittest.TestCase):
    """validar_ci debe exponer el importe de ALQUILERES separado por SFC,
    no solo el total global."""

    def test_alquileres_por_sfc_en_validar_ci(self):
        cierre = {
            "comunicaciones_internas": [
                {
                    "sfc": "SFC101", "referencia": "F-1", "importe": "100.00",
                    "cuenta_contable": "210201005", "asignacion": "CI0001",
                    "banco": "BNB", "alquileres": False,
                },
                {
                    "sfc": "SFC101", "referencia": "F-2", "importe": "300.00",
                    "cuenta_contable": None, "asignacion": None,
                    "banco": "ALQUILERES", "alquileres": True,
                },
                {
                    "sfc": "SFC102", "referencia": "F-3", "importe": "450.00",
                    "cuenta_contable": None, "asignacion": None,
                    "banco": "ALQUILERES", "alquileres": True,
                },
            ]
        }
        resultado = motor.validar_ci(cierre)
        self.assertEqual(resultado["alquileres_por_sfc"]["SFC101"], "300.00")
        self.assertEqual(resultado["alquileres_por_sfc"]["SFC102"], "450.00")
        self.assertEqual(resultado["alquileres_importe"], "750.00")


# ---------------------------------------------------------------------------
# CI: bloqueantes, importe negativo, fecha propia (G, H, 3.12-3.14)
# ---------------------------------------------------------------------------

class TestCiBloqueantes(unittest.TestCase):
    def test_ci_sin_cuenta_bloquea(self):
        cierre = {"comunicaciones_internas": [{
            "sfc": "SFC101", "referencia": "F-1", "importe": "100.00",
            "cuenta_contable": None, "asignacion": "CI0001",
            "banco": "BNB", "alquileres": False,
        }]}
        resultado = motor.validar_ci(cierre)
        self.assertEqual(len(resultado["bloqueantes"]), 1)
        self.assertEqual(resultado["bloqueantes"][0]["tipo"], "CI_CUENTA_FALTANTE")
        self.assertEqual(resultado["detalle_validas"], [])

    def test_ci_sin_asignacion_bloquea(self):
        cierre = {"comunicaciones_internas": [{
            "sfc": "SFC101", "referencia": "F-1", "importe": "100.00",
            "cuenta_contable": "210201005", "asignacion": None,
            "banco": "BNB", "alquileres": False,
        }]}
        resultado = motor.validar_ci(cierre)
        self.assertEqual(len(resultado["bloqueantes"]), 1)
        self.assertEqual(resultado["bloqueantes"][0]["tipo"], "CI_ASIGNACION_FALTANTE")
        self.assertEqual(resultado["detalle_validas"], [])

    def test_ci_importe_negativo_bloquea(self):
        cierre = {"comunicaciones_internas": [{
            "sfc": "SFC101", "referencia": "F-1", "importe": "-50.00",
            "cuenta_contable": "210201005", "asignacion": "CI0001",
            "banco": "BNB", "alquileres": False,
        }]}
        resultado = motor.validar_ci(cierre)
        self.assertEqual(len(resultado["bloqueantes"]), 1)
        self.assertEqual(resultado["bloqueantes"][0]["tipo"], "CI_IMPORTE_NEGATIVO")
        self.assertEqual(resultado["detalle_validas"], [])


def _resultado_v2_minimo_con_ci(ci_validas):
    """resultado_v2 mínimo, autocontenido y cuadrado (CARGO==HABER), para
    aislar el comportamiento de una sola CI sin arrastrar los totales del
    fixture completo 19-08-2026."""
    total_ci = sum((Decimal(ci["importe"]) for ci in ci_validas), Decimal("0"))
    detalle = {
        "sfc101_total": motor.io.money_str(total_ci),
        "sfc102_total": "0.00",
        "sfc101_haber": motor.io.money_str(total_ci),
        "sfc102_haber": "0.00",
        "alquileres_sfc101": "0.00",
        "alquileres_sfc102": "0.00",
        "vouchers_confirmados": [],
        "ci_validas": ci_validas,
        "atc_neto": {"importe": "0.00", "codigo_confirmado": "X", "fecha_bancaria": None},
        "atc_comision": {"importe": "0.00"},
        "dolares": "0.00",
    }
    return {
        "fecha": "2026-08-19",
        "estado": "OK",
        "excepciones_bloqueantes": 0,
        "diferencia": "0.00",
        "detalle": detalle,
    }


class TestCiFechaPropia(unittest.TestCase):
    """10-11. Fecha propia de CI: se preserva y se propaga como
    fecha_valor; si no existe, ETAPA 8 usa como fallback la fecha del
    cierre (nunca queda vacía), sin que eso reemplace una fecha real
    cuando sí existe."""

    def test_fecha_ci_preservada_hasta_la_partida(self):
        cierre = {"comunicaciones_internas": [{
            "sfc": "SFC101", "referencia": "F-1", "importe": "100.00",
            "cuenta_contable": "210201005", "asignacion": "CI0001",
            "banco": "BNB", "alquileres": False, "fecha_ci": "2026-08-15",
        }]}
        validado = motor.validar_ci(cierre)
        self.assertEqual(validado["detalle_validas"][0]["fecha_ci"], "2026-08-15")

        resultado = _resultado_v2_minimo_con_ci(validado["detalle_validas"])
        asiento = motor.construir_asiento(resultado)
        self.assertEqual(asiento["estado"], "OK")
        ci_partida = next(p for p in asiento["partidas"] if p["origen"] == "CI")
        self.assertEqual(ci_partida["fecha_valor"], "2026-08-15")

    def test_sin_fecha_propia_fecha_valor_usa_fallback_fecha_cierre(self):
        cierre = {"comunicaciones_internas": [{
            "sfc": "SFC101", "referencia": "F-1", "importe": "100.00",
            "cuenta_contable": "210201005", "asignacion": "CI0001",
            "banco": "BNB", "alquileres": False,
            # sin clave "fecha_ci": simula una hoja sin esa columna
        }]}
        validado = motor.validar_ci(cierre)
        self.assertIsNone(validado["detalle_validas"][0]["fecha_ci"])

        resultado = _resultado_v2_minimo_con_ci(validado["detalle_validas"])
        asiento = motor.construir_asiento(resultado)
        self.assertEqual(asiento["estado"], "OK")
        ci_partida = next(p for p in asiento["partidas"] if p["origen"] == "CI")
        # ETAPA 8: sin fecha real propia, fallback = fecha del cierre.
        self.assertEqual(ci_partida["fecha_valor"], resultado["fecha"])


# ---------------------------------------------------------------------------
# Corrección PRE-SAP — ATC BRUTO = 0.00 (ATC_NO_APLICA): el asiento debe
# construirse igual, sin las 2 líneas ATC_NETO/ATC_COMISION, siempre que
# el resto del cierre esté OK. Nunca debe convertirse en NO_ASIENTO solo
# porque el día no tuvo cobros con tarjeta.
# ---------------------------------------------------------------------------

def _resultado_v2_sin_atc():
    """resultado_v2 mínimo y cuadrado (CARGO==HABER) con ATC BRUTO=0.00:
    sin atc_neto/atc_comision y atc_aplica=False (ATC_NO_APLICA)."""
    detalle = {
        "sfc101_total": "1000.00",
        "sfc102_total": "0.00",
        "sfc101_haber": "1000.00",
        "sfc102_haber": "0.00",
        "alquileres_sfc101": "0.00",
        "alquileres_sfc102": "0.00",
        "vouchers_confirmados": [{
            "sfc": "SFC101", "importe": "1000.00", "codigo_confirmado": "VCH1",
            "codigo_informado": "VCH1", "fecha_bancaria": "2026-08-08",
            "estado": "MATCH_EXACTO",
        }],
        "ci_validas": [],
        "atc_neto": None,
        "atc_comision": None,
        "atc_aplica": False,
        "atc_estado": "ATC_NO_APLICA",
        "dolares": "0.00",
    }
    return {
        "fecha": "2026-08-08",
        "estado": "OK",
        "excepciones_bloqueantes": 0,
        "diferencia": "0.00",
        "detalle": detalle,
    }


class TestAtcNoAplicaEnAsiento(unittest.TestCase):
    def test_C_asiento_ok_sin_partida_atc_neto(self):
        resultado = _resultado_v2_sin_atc()
        asiento = motor.construir_asiento(resultado)
        self.assertNotEqual(asiento["estado"], "NO_ASIENTO")
        self.assertEqual(asiento["estado"], "OK")
        self.assertFalse(any(p["origen"] == "ATC_NETO" for p in asiento["partidas"]))

    def test_D_asiento_ok_sin_partida_atc_comision(self):
        resultado = _resultado_v2_sin_atc()
        asiento = motor.construir_asiento(resultado)
        self.assertEqual(asiento["estado"], "OK")
        self.assertFalse(any(p["origen"] == "ATC_COMISION" for p in asiento["partidas"]))

    def test_asiento_cuadra_con_las_demas_partidas(self):
        resultado = _resultado_v2_sin_atc()
        asiento = motor.construir_asiento(resultado)
        self.assertEqual(asiento["problemas"], [])
        self.assertEqual(asiento["cantidad_partidas"], 3)  # 2 HABER + 1 VOUCHER
        self.assertEqual(asiento["total_cargo"], asiento["total_haber"])
        self.assertEqual(asiento["diferencia"], "0.00")

    def test_atc_aplica_ausente_conserva_comportamiento_anterior(self):
        # Compatibilidad: si detalle no trae "atc_aplica" (fixtures/código
        # anterior a esta corrección), el default es True y atc_neto/
        # atc_comision ausentes siguen dando NO_ASIENTO como antes.
        resultado = _resultado_v2_sin_atc()
        del resultado["detalle"]["atc_aplica"]
        asiento = motor.construir_asiento(resultado)
        self.assertEqual(asiento["estado"], "NO_ASIENTO")


# ---------------------------------------------------------------------------
# Asiento inválido: ERROR -> partidas vacías (corrección obligatoria E)
# ---------------------------------------------------------------------------

class TestAsientoInvalidoLimpiaPartidas(unittest.TestCase):
    def test_importe_negativo_en_voucher_bloquea_y_limpia_partidas(self):
        resultado = _resultado_v2_ok()
        resultado["detalle"]["vouchers_confirmados"][0]["importe"] = "-100.00"
        asiento = motor.construir_asiento(resultado)
        self.assertEqual(asiento["estado"], "ERROR")
        self.assertEqual(asiento["partidas"], [])
        self.assertEqual(asiento["cantidad_partidas"], 0)
        self.assertTrue(any(p.startswith("IMPORTE_NEGATIVO") for p in asiento["problemas"]))


if __name__ == "__main__":
    unittest.main()
