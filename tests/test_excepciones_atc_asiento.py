"""test_excepciones_atc_asiento.py — FASE 3 (gap corregido, aprobado
2026-09-12): las excepciones ATC de ETAPA 5 (ATC_NETO_CUENTA_INVALIDA /
ATC_COMISION_CUENTA_INVALIDA), que ya existían como códigos sueltos dentro
de asiento["problemas"] (_validar_partidas, sin cambios), ahora también se
exponen en excepciones[] con el mismo schema de FASE 1
(motor_tiquipaya._excepciones_atc_asiento), para que el módulo de
corrección (correcciones_tiquipaya.py, ya aprobado) pueda localizarlas.

No prueba reglas nuevas de bloqueo/validación/cuentas/asiento: cada caso
confirma primero que _validar_partidas() clasifica exactamente igual que
antes (mismo "problemas", mismo "estado", mismas partidas vacías si
corresponde), y solo después verifica que el detalle estructurado nuevo
(excepciones[]) aparece cuando corresponde y queda vacío cuando no.

Uso: python -m unittest tests.test_excepciones_atc_asiento -v
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import correcciones_tiquipaya as correcciones
import motor_tiquipaya as motor
import pipeline_tiquipaya as pipeline
from tests.test_asiento import _resultado_v2_ok, FECHA_CIERRE


def _resultado_v2_atc_preconciliado(cuenta_neto="110103012", cuenta_comision="110201008",
                                     asignacion_neto="3P02891953",
                                     asignacion_comision="TIQUIPAYA AGO"):
    """Mismo fixture base de test_asiento.py (regresión 19-08-2026), pero
    con atc_neto/atc_comision en forma PRECONCILIADA (con cuenta_contable/
    asignación propias) en vez de la forma LEGADA — solo el modo
    PRECONCILIADO puede producir ATC_NETO_CUENTA_INVALIDA/
    ATC_COMISION_CUENTA_INVALIDA (en LEGADO, construir_asiento() siempre
    usa la cuenta fija por fallback, sin exponer nunca una cuenta propia)."""
    resultado = _resultado_v2_ok()
    resultado["detalle"]["atc_neto"] = {
        "importe": resultado["detalle"]["atc_neto"]["importe"],
        "codigo_confirmado": asignacion_neto,
        "fecha_bancaria": None,
        "cuenta_contable": cuenta_neto,
        "texto_detalle": "ATC COCHABAMBA",
    }
    resultado["detalle"]["atc_comision"] = {
        "importe": resultado["detalle"]["atc_comision"]["importe"],
        "asignacion": asignacion_comision,
        "cuenta_contable": cuenta_comision,
        "texto_detalle": "COMISION ATC",
    }
    return resultado


class TestClasificacionSinCambios(unittest.TestCase):
    """Control: la corrección del gap NO debe alterar en absoluto el
    comportamiento de bloqueo/validación ya existente."""

    def test_cuentas_validas_sigue_dando_ok_sin_excepciones(self):
        resultado_v2 = _resultado_v2_atc_preconciliado()
        asiento = motor.construir_asiento(resultado_v2)
        self.assertEqual(asiento["estado"], "OK")
        self.assertEqual(asiento["problemas"], [])
        self.assertGreater(asiento["cantidad_partidas"], 0)

    def test_cuenta_neto_invalida_sigue_bloqueando_exactamente_igual(self):
        resultado_v2 = _resultado_v2_atc_preconciliado(cuenta_neto="999999999")
        asiento = motor.construir_asiento(resultado_v2)
        # Mismo comportamiento de SIEMPRE: estado ERROR, partidas vacías,
        # el código de problema sigue estando en "problemas".
        self.assertEqual(asiento["estado"], "ERROR")
        self.assertEqual(asiento["partidas"], [])
        self.assertEqual(asiento["cantidad_partidas"], 0)
        self.assertIn("ATC_NETO_CUENTA_INVALIDA", asiento["problemas"])

    def test_cuenta_comision_invalida_sigue_bloqueando_exactamente_igual(self):
        resultado_v2 = _resultado_v2_atc_preconciliado(cuenta_comision="888888888")
        asiento = motor.construir_asiento(resultado_v2)
        self.assertEqual(asiento["estado"], "ERROR")
        self.assertEqual(asiento["partidas"], [])
        self.assertIn("ATC_COMISION_CUENTA_INVALIDA", asiento["problemas"])


class TestExcepcionAtcAsientoEstructurada(unittest.TestCase):
    """Ahora la excepción ATC de ETAPA 5 queda visible estructuradamente
    (categoria/tipo/campos actuales/motivo_legible), no solo como un
    código suelto en asiento["problemas"]."""

    def test_cuenta_neto_invalida_expone_excepcion_atc(self):
        resultado_v2 = _resultado_v2_atc_preconciliado(cuenta_neto="999999999")
        asiento = motor.construir_asiento(resultado_v2)

        self.assertEqual(len(asiento["excepciones"]), 1)
        exc = asiento["excepciones"][0]
        self.assertEqual(exc["categoria"], "ATC")
        self.assertEqual(exc["tipo"], "ATC_NETO_CUENTA_INVALIDA")
        self.assertEqual(exc["neto_cuenta_contable"], "999999999")
        self.assertEqual(exc["neto_asignacion"], "3P02891953")
        self.assertEqual(exc["comision_cuenta_contable"], "110201008")
        self.assertEqual(exc["comision_asignacion"], "TIQUIPAYA AGO")
        self.assertTrue(exc["motivo_legible"])

    def test_cuenta_comision_invalida_expone_excepcion_atc(self):
        resultado_v2 = _resultado_v2_atc_preconciliado(cuenta_comision="888888888")
        asiento = motor.construir_asiento(resultado_v2)

        self.assertEqual(len(asiento["excepciones"]), 1)
        exc = asiento["excepciones"][0]
        self.assertEqual(exc["categoria"], "ATC")
        self.assertEqual(exc["tipo"], "ATC_COMISION_CUENTA_INVALIDA")
        self.assertEqual(exc["comision_cuenta_contable"], "888888888")
        self.assertEqual(exc["neto_cuenta_contable"], "110103012")  # disponible aunque no sea la causa

    def test_ambas_cuentas_invalidas_expone_las_dos_excepciones(self):
        resultado_v2 = _resultado_v2_atc_preconciliado(
            cuenta_neto="999999999", cuenta_comision="888888888"
        )
        asiento = motor.construir_asiento(resultado_v2)

        self.assertEqual(len(asiento["excepciones"]), 2)
        tipos = {exc["tipo"] for exc in asiento["excepciones"]}
        self.assertEqual(tipos, {"ATC_NETO_CUENTA_INVALIDA", "ATC_COMISION_CUENTA_INVALIDA"})

    def test_cuentas_validas_no_genera_excepciones(self):
        resultado_v2 = _resultado_v2_atc_preconciliado()
        asiento = motor.construir_asiento(resultado_v2)
        self.assertEqual(asiento["excepciones"], [])

    def test_no_asiento_conserva_excepciones_vacio(self):
        # Precondición no cumplida (estado != OK): NO_ASIENTO, sin cambios,
        # y "excepciones" sigue presente como lista vacía (nunca ausente).
        resultado_v2 = _resultado_v2_atc_preconciliado()
        resultado_v2["estado"] = "DIFERENCIA"
        asiento = motor.construir_asiento(resultado_v2)
        self.assertEqual(asiento["estado"], "NO_ASIENTO")
        self.assertEqual(asiento["excepciones"], [])


class TestPropagacionResultadoJson(unittest.TestCase):
    """La excepción ATC de ETAPA 5 llega hasta RESULTADO_TIQ (resultado_json)
    exactamente igual que las de ETAPA 3/4 (FASE 1), sin alterar "blockers"
    (que sigue siendo EXCLUSIVAMENTE resultado_v2["excepciones_bloqueantes"],
    sin cambios de cálculo/bloqueo)."""

    def test_resultado_json_incluye_excepcion_atc_de_asiento(self):
        resultado_v2 = _resultado_v2_atc_preconciliado(cuenta_neto="999999999")
        asiento = motor.construir_asiento(resultado_v2)

        resultado_json = pipeline._construir_resultado_json(
            fecha_cierre=resultado_v2["fecha"],
            archivo_origen="CIERRE 19-08-2026.xlsm",
            hash_origen="0" * 64,
            version_codigo="TEST-VERSION",
            resultado_v2=resultado_v2,
            asiento=asiento,
            sap_resumen=None,
            ruta_sap_salida=None,
            warnings_extra=[],
        )

        # Bloqueo/conteo SIN cambios: sigue en 0 (la excepción ATC de
        # ETAPA 5 nunca contaba en excepciones_bloqueantes, ni antes ni
        # ahora).
        self.assertEqual(resultado_json["blockers"], 0)
        self.assertEqual(resultado_json["asiento_estado"], "ERROR")

        excepciones = resultado_json["excepciones"]
        self.assertEqual(len(excepciones), 1)
        self.assertEqual(excepciones[0]["categoria"], "ATC")
        self.assertEqual(excepciones[0]["tipo"], "ATC_NETO_CUENTA_INVALIDA")

    def test_resultado_json_combina_excepciones_v2_y_asiento(self):
        # Si ADEMÁS hubiera una excepción de ETAPA 3/4 (aquí simulada
        # directamente, ya que resultado_v2["estado"] tendría que ser
        # distinto de OK para eso — se simula solo el campo excepciones[]
        # de origen v2 para probar que ambas fuentes se combinan sin
        # pisarse), ambas conviven en la misma lista.
        resultado_v2 = _resultado_v2_atc_preconciliado(cuenta_neto="999999999")
        resultado_v2["excepciones"] = [{
            "categoria": "COMUNICACION_INTERNA", "tipo": "CI_CUENTA_FALTANTE",
            "sfc": "SFC101", "factura": "F-1",
        }]
        asiento = motor.construir_asiento(resultado_v2)

        resultado_json = pipeline._construir_resultado_json(
            fecha_cierre=resultado_v2["fecha"], archivo_origen="x", hash_origen="0" * 64,
            version_codigo="TEST", resultado_v2=resultado_v2, asiento=asiento,
            sap_resumen=None, ruta_sap_salida=None, warnings_extra=[],
        )
        categorias = [e["categoria"] for e in resultado_json["excepciones"]]
        self.assertEqual(categorias, ["COMUNICACION_INTERNA", "ATC"])


class TestCorreccionLocalizaExcepcionExpuesta(unittest.TestCase):
    """La corrección autorizada existente (correcciones_tiquipaya.py, ya
    aprobada — sin cambios) puede localizar y aplicar EXACTAMENTE la
    excepción que este gap-fix ahora expone."""

    def test_correccion_existente_localiza_y_aplica_la_excepcion(self):
        resultado_v2 = _resultado_v2_atc_preconciliado(cuenta_neto="999999999")
        asiento = motor.construir_asiento(resultado_v2)
        exc = asiento["excepciones"][0]

        # La categoría y el campo a corregir de la excepción expuesta ya
        # están dentro del universo autorizado por FASE 3 Parte B, sin
        # ningún cambio en correcciones_tiquipaya.py.
        self.assertEqual(exc["categoria"], correcciones.CATEGORIA_ATC)
        self.assertIn("neto_cuenta_contable", correcciones.CAMPOS_CORREGIBLES[correcciones.CATEGORIA_ATC])

        atc_idx = {
            "modo": "PRECONCILIADO",
            "por_fecha": {
                FECHA_CIERRE: {
                    "neto": {"monto": "130246.43", "cuenta_contable": exc["neto_cuenta_contable"],
                             "detalle": "ATC COCHABAMBA", "asignacion": exc["neto_asignacion"]},
                    "comision": {"monto": "636.57", "cuenta_contable": exc["comision_cuenta_contable"],
                                 "detalle": "COMISION ATC", "asignacion": exc["comision_asignacion"]},
                }
            },
        }
        correccion = {
            "fecha_cierre": FECHA_CIERRE, "sha256_origen": "0" * 64,
            "categoria": exc["categoria"], "tipo": exc["tipo"],
            "identificadores": {}, "campo_corregido": "neto_cuenta_contable",
            "valor_original": exc["neto_cuenta_contable"], "valor_autorizado": "110103012",
            "motivo": "Cuenta ATC NETO mal digitada en la hoja ATC TIQUIPAYA",
            "usuario_auditor": "gabriel.torrico", "fecha_hora": "2026-09-12T14:05:00-04:00",
        }
        correccion["version_correccion"] = correcciones.calcular_version_correccion(correccion)

        # No lanza: el schema/versión de la corrección son válidos.
        correcciones.validar_schema_correccion(correccion)

        cierre_vacio = {"comunicaciones_internas": [], "sfc101": {"depositos": []}, "sfc102": {"depositos": []}}
        macros_vacio = {"por_codigo": {}, "por_importe": {}}
        _, atc_corregido = correcciones.aplicar_correccion_en_memoria(
            cierre_vacio, macros_vacio, atc_idx, correccion
        )

        self.assertEqual(
            atc_corregido["por_fecha"][FECHA_CIERRE]["neto"]["cuenta_contable"], "110103012"
        )
        # El atc_idx original nunca se muta.
        self.assertEqual(
            atc_idx["por_fecha"][FECHA_CIERRE]["neto"]["cuenta_contable"], "999999999"
        )


if __name__ == "__main__":
    unittest.main()
