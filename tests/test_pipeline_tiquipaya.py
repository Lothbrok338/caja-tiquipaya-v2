"""
test_pipeline_tiquipaya.py — ETAPA 7: pruebas de pipeline_tiquipaya.py
(control de procesamiento, idempotencia por SHA256, trazabilidad
estructurada y preparación de publicación).

Usa exclusivamente fixtures SINTÉTICOS (tests/xlsx_fixtures.py) y los
mismos datos base que tests/test_regresion_sintetica.py /
tests/test_atc_preconciliado.py. No sube ningún archivo real ni datos
contables reales. No reimplementa ninguna regla de ETAPAS 1-6: solo
ejercita la orquestación de ETAPA 7 sobre resultados reales de
motor_tiquipaya/sap_writer.

Uso: python -m unittest tests.test_pipeline_tiquipaya -v
"""

import csv
import json
import os
import sys
import tempfile
import unittest
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pipeline_tiquipaya as pipeline
from tests import xlsx_fixtures as fx
from tests.xlsx_fixtures import crear_plantilla_sap
from tests.test_regresion_sintetica import (
    FECHA_CIERRE, NOMBRE_CIERRE, _baseline_sfc101, _baseline_sfc102,
)
from tests.test_atc_preconciliado import (
    _macros_filas_solo_vouchers, _fila_neto, _fila_comision,
)


def _metadata_cabecera():
    return {
        "tipo_asiento": "SA",
        "fecha_registro": FECHA_CIERRE,
        "fecha_contabilizacion": FECHA_CIERRE,
        "mes": "08",
        "texto_cabecera": "CAJA TIQUIPAYA 19-08-2026",
        "referencia": "TIQ-19082026",
    }


VERSION_CODIGO = "3fae592"


class _BasePipeline(unittest.TestCase):
    """Arma un escenario sintético completo (cierre + maestro único +
    plantilla SAP) en un directorio temporal, reutilizable por las
    subclases OK/ERROR."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = self._tmp.name

        self.ruta_cierre = os.path.join(self.tmp, NOMBRE_CIERRE)
        self.ruta_maestro = os.path.join(self.tmp, "MACROS AGOSTO 2026.xlsm")
        self.ruta_plantilla = os.path.join(self.tmp, "plantilla_sap.xlsx")
        self.ruta_sap_salida = os.path.join(self.tmp, "SAP_19-08-2026.xlsx")
        self.ruta_control = os.path.join(self.tmp, "CONTROL_PROCESAMIENTO.csv")
        self.ruta_resultado = os.path.join(self.tmp, "RESULTADO_TIQ_19-08-2026.json")

        fx.crear_cierre(self.ruta_cierre, _baseline_sfc101(), _baseline_sfc102())
        fx.crear_maestro_unico(
            self.ruta_maestro,
            macros_filas=_macros_filas_solo_vouchers(),
            atc_filas=[_fila_neto(), _fila_comision()],
        )
        crear_plantilla_sap(self.ruta_plantilla)

    def _procesar(self, **overrides):
        kwargs = dict(
            ruta_cierre=self.ruta_cierre,
            ruta_maestro=self.ruta_maestro,
            ruta_plantilla_sap=self.ruta_plantilla,
            ruta_sap_salida=self.ruta_sap_salida,
            metadata_cabecera=_metadata_cabecera(),
            version_codigo=VERSION_CODIGO,
            ruta_control=self.ruta_control,
            ruta_resultado=self.ruta_resultado,
        )
        kwargs.update(overrides)
        return pipeline.procesar_cierre_completo(**kwargs)


# ---------------------------------------------------------------------------
# 1. SHA256
# ---------------------------------------------------------------------------

class TestSha256(_BasePipeline):
    def test_sha256_calculado_correctamente(self):
        import hashlib
        esperado = hashlib.sha256()
        with open(self.ruta_cierre, "rb") as f:
            esperado.update(f.read())
        self.assertEqual(pipeline.calcular_sha256(self.ruta_cierre), esperado.hexdigest())


# ---------------------------------------------------------------------------
# 2-5. Idempotencia
# ---------------------------------------------------------------------------

class TestIdempotencia(_BasePipeline):
    def test_control_inexistente_procesa(self):
        self.assertFalse(os.path.isfile(self.ruta_control))
        resultado = self._procesar()
        self.assertEqual(resultado["estado"], pipeline.ESTADO_VALIDADO_PENDIENTE)
        self.assertIsNotNone(resultado["resultado_v2"])

    def test_hash_ya_procesado_devuelve_ya_procesado(self):
        primero = self._procesar()
        pipeline.registrar_procesado(self.ruta_control, primero["resultado_json"])

        segundo = self._procesar()
        self.assertEqual(segundo["estado"], pipeline.ESTADO_YA_PROCESADO)

    def test_ya_procesado_no_ejecuta_motor(self):
        primero = self._procesar()
        pipeline.registrar_procesado(self.ruta_control, primero["resultado_json"])

        segundo = self._procesar()
        self.assertIsNone(segundo["resultado_v2"])
        self.assertIsNone(segundo["asiento"])

    def test_ya_procesado_no_genera_sap(self):
        primero = self._procesar()
        pipeline.registrar_procesado(self.ruta_control, primero["resultado_json"])

        # Si se reprocesara, generar_y_validar_sap fallaría al intentar
        # sobrescribir un archivo SAP ya existente sobre una plantilla
        # ya usada; en cambio no debe siquiera intentarlo.
        mtime_antes = os.path.getmtime(self.ruta_sap_salida)
        segundo = self._procesar()
        self.assertIsNone(segundo["sap"])
        self.assertEqual(os.path.getmtime(self.ruta_sap_salida), mtime_antes)


# ---------------------------------------------------------------------------
# 6. Mismo nombre, hash distinto
# ---------------------------------------------------------------------------

class TestMismoNombreHashDistinto(_BasePipeline):
    def test_mismo_nombre_hash_distinto_permite_y_advierte(self):
        # Fila previa en control con el MISMO nombre de archivo pero un
        # hash distinto (simula una versión anterior del mismo cierre).
        pipeline._escribir_control(self.ruta_control, [{
            "FechaCierre": FECHA_CIERRE,
            "ArchivoOrigen": os.path.basename(self.ruta_cierre),
            "HashOrigen": "0" * 64,
            "Estado": "PROCESADO",
            "FechaProcesamiento": "2026-08-01 00:00:00",
            "VersionCodigo": "otra-version",
            "Resultado": "OK",
            "Diferencia": "0.00",
            "Blockers": "0",
            "ArchivoSAP": "",
            "Observaciones": "",
        }])

        resultado = self._procesar()
        self.assertEqual(resultado["estado"], pipeline.ESTADO_VALIDADO_PENDIENTE)
        self.assertIn(pipeline.WARNING_MISMO_NOMBRE_HASH_DISTINTO, resultado["warnings"])
        self.assertIn(
            pipeline.WARNING_MISMO_NOMBRE_HASH_DISTINTO,
            resultado["resultado_json"]["advertencias"],
        )


# ---------------------------------------------------------------------------
# 7-11. Estados según validez del cierre
# ---------------------------------------------------------------------------

class TestEstadosSegunValidez(_BasePipeline):
    def test_cierre_ok_da_validado_pendiente_publicacion(self):
        resultado = self._procesar()
        self.assertEqual(resultado["estado"], pipeline.ESTADO_VALIDADO_PENDIENTE)
        self.assertTrue(resultado["publicacion_autorizada"])
        self.assertTrue(os.path.isfile(self.ruta_sap_salida))

    def test_cierre_con_blocker_no_autoriza_publicacion(self):
        # SFC101 sin depósitos que crucen con MACROS: el voucher informado
        # nunca aparece en MACROS -> EXCEPCION_NO_ENCONTRADO (bloqueante).
        sfc101 = _baseline_sfc101()
        sfc101["depositos"][0]["asignacion"] = "VCH-INEXISTENTE"
        fx.crear_cierre(self.ruta_cierre, sfc101, _baseline_sfc102())

        resultado = self._procesar()
        self.assertFalse(resultado["publicacion_autorizada"])
        self.assertEqual(resultado["acciones_requeridas"], [])
        self.assertIn(resultado["estado"], (pipeline.ESTADO_BLOQUEADO, pipeline.ESTADO_ERROR))
        self.assertFalse(os.path.isfile(self.ruta_sap_salida))

    def test_diferencia_distinta_de_cero_no_autoriza_publicacion(self):
        sfc101 = _baseline_sfc101()
        sfc101["total_movimiento"] = "999999.99"  # rompe el cuadre
        fx.crear_cierre(self.ruta_cierre, sfc101, _baseline_sfc102())

        resultado = self._procesar()
        self.assertFalse(resultado["publicacion_autorizada"])
        self.assertEqual(resultado["acciones_requeridas"], [])
        self.assertFalse(os.path.isfile(self.ruta_sap_salida))

    def test_asiento_error_no_autoriza_publicacion(self):
        # CI válida en monto pero sin cuenta contable -> ETAPA 5 bloquea
        # el asiento (CI_SIN_CUENTA_O_ASIGNACION) aunque V2 quede OK.
        sfc101 = _baseline_sfc101()
        sfc101["ci"][0]["cuenta"] = None
        fx.crear_cierre(self.ruta_cierre, sfc101, _baseline_sfc102())

        resultado = self._procesar()
        resultado_v2 = resultado["resultado_v2"]
        if resultado_v2 is not None and resultado_v2.get("estado") == "OK":
            self.assertEqual(resultado["asiento"]["estado"], "ERROR")
        self.assertFalse(resultado["publicacion_autorizada"])
        self.assertFalse(os.path.isfile(self.ruta_sap_salida))

    def test_sap_invalido_no_autoriza_publicacion(self):
        # Plantilla SAP sin la hoja "1": generar_sap falla en
        # precondiciones y nunca llega a escribir un SAP válido.
        ruta_plantilla_invalida = os.path.join(self.tmp, "plantilla_invalida.xlsx")
        import openpyxl
        wb = openpyxl.Workbook()
        wb.active.title = "OTRA_HOJA"
        wb.save(ruta_plantilla_invalida)

        resultado = self._procesar(ruta_plantilla_sap=ruta_plantilla_invalida)
        self.assertFalse(resultado["publicacion_autorizada"])
        self.assertEqual(resultado["estado"], pipeline.ESTADO_ERROR)
        self.assertEqual(resultado["resultado_json"]["sap_estado"], "ERROR")


# ---------------------------------------------------------------------------
# 12-14. JSON de resultado
# ---------------------------------------------------------------------------

class TestResultadoJson(_BasePipeline):
    def test_json_resultado_estable(self):
        resultado = self._procesar()
        with open(self.ruta_resultado, "r", encoding="utf-8") as f:
            leido = json.load(f)
        self.assertEqual(leido, resultado["resultado_json"])
        self.assertEqual(leido["fecha_cierre"], FECHA_CIERRE)
        self.assertEqual(leido["sha256_origen"], resultado["hash_origen"])
        self.assertEqual(leido["version_codigo"], VERSION_CODIGO)

    def test_decimal_serializado_a_dos_decimales(self):
        resultado = self._procesar()
        j = resultado["resultado_json"]
        for campo in ("universo_original", "alquileres", "universo_ajustado",
                      "total_vouchers", "total_ci", "atc_bruto", "atc_neto",
                      "atc_comision", "usd", "cargo", "haber",
                      "diferencia_asiento", "diferencia"):
            valor = j[campo]
            self.assertIsInstance(valor, str, f"{campo} no es string: {valor!r}")
            self.assertEqual(Decimal(valor), Decimal(valor).quantize(Decimal("0.01")))
            self.assertRegex(valor, r"^-?\d+\.\d{2}$")

    def test_json_no_incluye_detalle_personal_de_ci(self):
        resultado = self._procesar()
        serializado = json.dumps(resultado["resultado_json"], ensure_ascii=False)
        # Ninguna referencia/factura/glosa de CI individual debe aparecer:
        # solo cantidad_ci/total_ci agregados.
        for token in ("FAC-0001", "FAC-0002", "glosa", "referencia", "PAGO PROVEEDOR"):
            self.assertNotIn(token, serializado)
        self.assertIn("cantidad_ci", resultado["resultado_json"])
        self.assertIn("total_ci", resultado["resultado_json"])
        self.assertNotIn("ci_validas", resultado["resultado_json"])
        self.assertNotIn("detalle", resultado["resultado_json"])


# ---------------------------------------------------------------------------
# 15. Manifiesto de publicación
# ---------------------------------------------------------------------------

class TestManifiestoPublicacion(_BasePipeline):
    def test_manifiesto_usa_anio_mes_correctos(self):
        resultado = self._procesar()
        acciones = resultado["acciones_requeridas"]
        self.assertEqual(len(acciones), 4)
        for accion in acciones:
            if accion["accion"] == "ACTUALIZAR_CONTROL":
                continue
            self.assertIn("2026", accion["destino"])
            self.assertIn("2026-08", accion["destino"])
        tipos = {a["accion"] for a in acciones}
        self.assertEqual(
            tipos,
            {"SUBIR_SAP", "SUBIR_RESULTADO", "ACTUALIZAR_CONTROL", "MOVER_CIERRE"},
        )


# ---------------------------------------------------------------------------
# 16-18. registrar_procesado
# ---------------------------------------------------------------------------

class TestRegistrarProcesado(_BasePipeline):
    def test_registrar_procesado_crea_control(self):
        self.assertFalse(os.path.isfile(self.ruta_control))
        resultado = self._procesar()
        registro = pipeline.registrar_procesado(self.ruta_control, resultado["resultado_json"])
        self.assertEqual(registro["estado"], "PROCESADO")
        self.assertTrue(os.path.isfile(self.ruta_control))

        with open(self.ruta_control, "r", encoding="utf-8", newline="") as f:
            filas = list(csv.DictReader(f))
        self.assertEqual(len(filas), 1)
        self.assertEqual(filas[0]["Estado"], "PROCESADO")
        self.assertEqual(filas[0]["HashOrigen"], resultado["hash_origen"])

    def test_registrar_procesado_no_duplica_mismo_sha(self):
        resultado = self._procesar()
        pipeline.registrar_procesado(self.ruta_control, resultado["resultado_json"])
        segundo_registro = pipeline.registrar_procesado(self.ruta_control, resultado["resultado_json"])
        self.assertEqual(segundo_registro["estado"], pipeline.ESTADO_YA_PROCESADO)

        with open(self.ruta_control, "r", encoding="utf-8", newline="") as f:
            filas = list(csv.DictReader(f))
        self.assertEqual(len(filas), 1)

    def test_procesado_solo_tras_confirmacion_explicita(self):
        resultado = self._procesar()
        self.assertEqual(resultado["estado"], pipeline.ESTADO_VALIDADO_PENDIENTE)
        self.assertFalse(os.path.isfile(self.ruta_control))  # pipeline no escribe control

        pipeline.registrar_procesado(self.ruta_control, resultado["resultado_json"])
        filas = pipeline._leer_control(self.ruta_control)
        self.assertEqual(filas[0]["Estado"], "PROCESADO")


# ---------------------------------------------------------------------------
# 19. UTF-8
# ---------------------------------------------------------------------------

class TestControlUtf8(_BasePipeline):
    def test_control_utf8(self):
        resultado = self._procesar()
        pipeline.registrar_procesado(
            self.ruta_control, resultado["resultado_json"],
            observaciones="cierre ñandú - año 2026 áéíóú",
        )
        with open(self.ruta_control, "r", encoding="utf-8", newline="") as f:
            contenido = f.read()
        self.assertIn("ñandú", contenido)
        self.assertIn("áéíóú", contenido)


if __name__ == "__main__":
    unittest.main()
