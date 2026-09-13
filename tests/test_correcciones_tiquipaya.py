"""test_correcciones_tiquipaya.py — FASE 3, Parte B (HANDOFF_CODE_V2.md
sección 16): validación/aplicación en memoria de correcciones autorizadas
por el auditor (correcciones_tiquipaya.py), reproceso
(pipeline_tiquipaya.procesar_cierre_con_correccion) y el CLI
aplicar_correccion.py.

Usa exclusivamente fixtures SINTÉTICOS (tests/xlsx_fixtures.py) y los mismos
datos base que tests/test_regresion_sintetica.py / tests/test_pipeline_tiquipaya.py
/ tests/test_excepciones.py. No sube ningún archivo real ni datos contables
reales. No reimplementa ninguna regla de motor_tiquipaya.py/excel_io.py: solo
ejercita la capa de corrección + reproceso sobre resultados reales del motor.

Uso: python -m unittest tests.test_correcciones_tiquipaya -v
"""

import io as stdlib_io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import aplicar_correccion
import correcciones_tiquipaya as correcciones
import pipeline_tiquipaya as pipeline
from tests import xlsx_fixtures as fx
from tests.xlsx_fixtures import crear_plantilla_sap
from tests.test_regresion_sintetica import (
    FECHA_CIERRE, NOMBRE_CIERRE, _baseline_sfc101, _baseline_sfc102,
)
from tests.test_atc_preconciliado import (
    _macros_filas_solo_vouchers, _fila_neto, _fila_comision,
)


VERSION_CODIGO = "3fae592"


def _metadata_cabecera():
    return {
        "tipo_asiento": "SA",
        "fecha_registro": FECHA_CIERRE,
        "fecha_contabilizacion": FECHA_CIERRE,
        "mes": "08",
        "texto_cabecera": "CAJA TIQUIPAYA 19-08-2026",
        "referencia": "TIQ-19082026",
    }


def _construir_correccion(categoria, tipo, identificadores, campo_corregido,
                           valor_original, valor_autorizado, sha256_origen, fecha_cierre,
                           usuario_auditor="gabriel.torrico", motivo="Corrección de prueba",
                           fecha_hora="2026-09-12T14:05:00-04:00"):
    correccion = {
        "fecha_cierre": fecha_cierre,
        "sha256_origen": sha256_origen,
        "categoria": categoria,
        "tipo": tipo,
        "identificadores": identificadores,
        "campo_corregido": campo_corregido,
        "valor_original": valor_original,
        "valor_autorizado": valor_autorizado,
        "motivo": motivo,
        "usuario_auditor": usuario_auditor,
        "fecha_hora": fecha_hora,
    }
    correccion["version_correccion"] = correcciones.calcular_version_correccion(correccion)
    return correccion


def _ejecutar_cli(argv):
    """Corre aplicar_correccion.main(argv), captura stdout, y devuelve
    (codigo_salida, payload_json). Mismo patrón que tests/test_publicar_cierre.py."""
    buffer = stdlib_io.StringIO()
    with redirect_stdout(buffer):
        codigo = aplicar_correccion.main(argv)
    payload = json.loads(buffer.getvalue())
    return codigo, payload


class _BaseCorreccion(unittest.TestCase):
    """Arma un escenario sintético completo (cierre + maestro único +
    plantilla SAP) en un directorio temporal, más los directorios de
    resultados/salidas/controles que usa el CLI aplicar_correccion.py."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = self._tmp.name

        self.ruta_cierre = os.path.join(self.tmp, NOMBRE_CIERRE)
        self.ruta_maestro = os.path.join(self.tmp, "MACROS AGOSTO 2026.xlsm")
        self.ruta_plantilla = os.path.join(self.tmp, "plantilla_sap.xlsx")
        self.ruta_sap_original = os.path.join(self.tmp, "SAP_19-08-2026.xlsx")
        self.ruta_resultado_original = os.path.join(self.tmp, "RESULTADO_TIQ_19-08-2026.json")

        self.resultados_dir = os.path.join(self.tmp, "resultados")
        self.salidas_dir = os.path.join(self.tmp, "salidas")
        self.controles_dir = os.path.join(self.tmp, "controles")
        os.makedirs(self.resultados_dir, exist_ok=True)
        os.makedirs(self.salidas_dir, exist_ok=True)

        crear_plantilla_sap(self.ruta_plantilla)
        fx.crear_maestro_unico(
            self.ruta_maestro,
            macros_filas=_macros_filas_solo_vouchers(),
            atc_filas=[_fila_neto(), _fila_comision()],
        )

    def _crear_cierre(self, sfc101, sfc102):
        fx.crear_cierre(self.ruta_cierre, sfc101, sfc102)

    def _hash_cierre(self):
        return correcciones.calcular_sha256_archivo(self.ruta_cierre)

    def _procesar_original(self):
        return pipeline.procesar_cierre_completo(
            ruta_cierre=self.ruta_cierre,
            ruta_maestro=self.ruta_maestro,
            ruta_plantilla_sap=self.ruta_plantilla,
            ruta_sap_salida=self.ruta_sap_original,
            metadata_cabecera=_metadata_cabecera(),
            version_codigo=VERSION_CODIGO,
            ruta_resultado=self.ruta_resultado_original,
        )

    def _reprocesar(self, correccion, ruta_sap_salida=None, ruta_resultado=None, ya_publicado=False):
        ruta_sap_salida = ruta_sap_salida or os.path.join(self.tmp, "REPROCESOS", "SAP_reproceso.xlsx")
        os.makedirs(os.path.dirname(ruta_sap_salida), exist_ok=True)
        return pipeline.procesar_cierre_con_correccion(
            ruta_cierre=self.ruta_cierre,
            ruta_maestro=self.ruta_maestro,
            ruta_plantilla_sap=self.ruta_plantilla,
            ruta_sap_salida=ruta_sap_salida,
            metadata_cabecera=_metadata_cabecera(),
            version_codigo=VERSION_CODIGO,
            correccion=correccion,
            ruta_resultado=ruta_resultado or os.path.join(self.tmp, "REPROCESOS", "RESULTADO_reproceso.json"),
            ya_publicado=ya_publicado,
        )

    def _argv_cli(self, ruta_correccion):
        return [
            "--resultado", self.ruta_resultado_original,
            "--correccion", ruta_correccion,
            "--cierre", self.ruta_cierre,
            "--maestro", self.ruta_maestro,
            "--plantilla-sap", self.ruta_plantilla,
            "--resultados-dir", self.resultados_dir,
            "--salidas-dir", self.salidas_dir,
            "--controles-dir", self.controles_dir,
        ]

    def _escribir_correccion(self, correccion, nombre="correccion.json"):
        ruta = os.path.join(self.tmp, nombre)
        with open(ruta, "w", encoding="utf-8") as f:
            json.dump(correccion, f)
        return ruta


# ---------------------------------------------------------------------------
# 1. Comunicación Interna — cuenta_contable
# ---------------------------------------------------------------------------

class TestCorreccionCiCuenta(_BaseCorreccion):
    def test_corrige_cuenta_contable_y_reprocesa_a_ok(self):
        sfc101 = _baseline_sfc101()
        sfc101["ci"][0]["cuenta"] = None
        self._crear_cierre(sfc101, _baseline_sfc102())

        hash_antes = self._hash_cierre()
        original = self._procesar_original()
        self.assertIn(original["estado"], (pipeline.ESTADO_BLOQUEADO, pipeline.ESTADO_ERROR))
        excepciones = original["resultado_json"]["excepciones"]
        self.assertEqual(len(excepciones), 1)
        exc = excepciones[0]
        self.assertEqual(exc["categoria"], "COMUNICACION_INTERNA")
        self.assertEqual(exc["tipo"], "CI_CUENTA_FALTANTE")
        self.assertIsNone(exc["cuenta_contable"])

        correccion = _construir_correccion(
            categoria=exc["categoria"], tipo=exc["tipo"],
            identificadores={"sfc": exc["sfc"], "factura": exc["factura"]},
            campo_corregido="cuenta_contable",
            valor_original=exc["cuenta_contable"],
            valor_autorizado="210201005",
            sha256_origen=original["hash_origen"], fecha_cierre=FECHA_CIERRE,
        )

        reproceso = self._reprocesar(correccion)
        self.assertEqual(reproceso["estado"], pipeline.ESTADO_VALIDADO_PENDIENTE)
        self.assertTrue(reproceso["publicacion_autorizada"])
        self.assertEqual(reproceso["resultado_json"]["diferencia"], "0.00")
        self.assertEqual(reproceso["version_correccion"], correccion["version_correccion"])
        self.assertEqual(reproceso["resultado_json"]["correccion_aplicada"]["campo_corregido"],
                          "cuenta_contable")

        # El .xlsm original NUNCA se abre en modo escritura ni se modifica.
        self.assertEqual(self._hash_cierre(), hash_antes)
        self.assertFalse(os.path.isfile(self.ruta_sap_original))


# ---------------------------------------------------------------------------
# 2. Comunicación Interna — asignacion
# ---------------------------------------------------------------------------

class TestCorreccionCiAsignacion(_BaseCorreccion):
    def test_corrige_asignacion_y_reprocesa_a_ok(self):
        sfc101 = _baseline_sfc101()
        sfc101["ci"][0]["asignacion"] = None
        self._crear_cierre(sfc101, _baseline_sfc102())

        hash_antes = self._hash_cierre()
        original = self._procesar_original()
        exc = original["resultado_json"]["excepciones"][0]
        self.assertEqual(exc["tipo"], "CI_ASIGNACION_FALTANTE")
        self.assertIsNone(exc["asignacion"])

        correccion = _construir_correccion(
            categoria=exc["categoria"], tipo=exc["tipo"],
            identificadores={"sfc": exc["sfc"], "factura": exc["factura"]},
            campo_corregido="asignacion",
            valor_original=exc["asignacion"],
            valor_autorizado="CI0001",
            sha256_origen=original["hash_origen"], fecha_cierre=FECHA_CIERRE,
        )

        reproceso = self._reprocesar(correccion)
        self.assertEqual(reproceso["estado"], pipeline.ESTADO_VALIDADO_PENDIENTE)
        self.assertEqual(self._hash_cierre(), hash_antes)


# ---------------------------------------------------------------------------
# 3. Voucher — codigo_informado eligiendo un candidato válido (POSIBLE_TYPO)
# ---------------------------------------------------------------------------

class TestCorreccionVoucherCandidato(_BaseCorreccion):
    def test_corrige_codigo_informado_con_candidato_valido(self):
        sfc101 = _baseline_sfc101()
        # "VCH1092" difiere de "VCH1002" (el código real en MACROS para el
        # mismo importe) por UN caracter que no es un swap 0<->O: cae en
        # POSIBLE_TYPO con exactamente un candidato, nunca en
        # AUTOCORRECCION_0_O (que se resolvería solo, sin excepción).
        sfc101["depositos"][1]["asignacion"] = "VCH1092"
        self._crear_cierre(sfc101, _baseline_sfc102())

        hash_antes = self._hash_cierre()
        original = self._procesar_original()
        exc = original["resultado_json"]["excepciones"][0]
        self.assertEqual(exc["categoria"], "VOUCHER")
        self.assertEqual(exc["tipo"], "POSIBLE_TYPO")
        self.assertEqual(exc["cantidad_candidatos"], 1)
        candidato = exc["candidatos"][0]["codigo"]
        self.assertEqual(candidato, "VCH1002")

        correccion = _construir_correccion(
            categoria=exc["categoria"], tipo=exc["tipo"],
            identificadores={"sfc": exc["sfc"], "codigo_informado": exc["codigo_informado"]},
            campo_corregido="codigo_informado",
            valor_original=exc["codigo_informado"],
            valor_autorizado=candidato,
            sha256_origen=original["hash_origen"], fecha_cierre=FECHA_CIERRE,
        )

        reproceso = self._reprocesar(correccion)
        self.assertEqual(reproceso["estado"], pipeline.ESTADO_VALIDADO_PENDIENTE)
        self.assertTrue(reproceso["publicacion_autorizada"])
        self.assertEqual(self._hash_cierre(), hash_antes)


# ---------------------------------------------------------------------------
# 4. Voucher — código informado LIBRE (sin candidatos) es rechazado
# ---------------------------------------------------------------------------

class TestCorreccionVoucherSinCandidatos(_BaseCorreccion):
    def test_codigo_libre_sin_candidatos_es_rechazado(self):
        sfc101 = _baseline_sfc101()
        sfc101["depositos"][1]["asignacion"] = "VCH-INEXISTENTE"
        self._crear_cierre(sfc101, _baseline_sfc102())

        original = self._procesar_original()
        exc = original["resultado_json"]["excepciones"][0]
        self.assertEqual(exc["tipo"], "NO_ENCONTRADO")
        self.assertEqual(exc["candidatos"], [])

        correccion = _construir_correccion(
            categoria=exc["categoria"], tipo=exc["tipo"],
            identificadores={"sfc": exc["sfc"], "codigo_informado": exc["codigo_informado"]},
            campo_corregido="codigo_informado",
            valor_original=exc["codigo_informado"],
            valor_autorizado="VCH1002",  # libre: el motor NUNCA lo propuso como candidato
            sha256_origen=original["hash_origen"], fecha_cierre=FECHA_CIERRE,
        )

        with self.assertRaises(ValueError) as ctx:
            self._reprocesar(correccion)
        self.assertIn("CORRECCION_SIN_CANDIDATOS", str(ctx.exception))


# ---------------------------------------------------------------------------
# 5. ATC — neto/comisión cuenta_contable/asignacion (modo PRECONCILIADO)
# ---------------------------------------------------------------------------

class TestCorreccionAtc(unittest.TestCase):
    """Cobertura unitaria directa de correcciones_tiquipaya sobre atc_idx,
    sin pasar por un .xlsm completo (más rápido y más preciso para probar
    la localización/aplicación en sí)."""

    def _atc_idx(self):
        return {
            "modo": "PRECONCILIADO",
            "por_fecha": {
                FECHA_CIERRE: {
                    "neto": {"monto": "130246.43", "cuenta_contable": "110103012",
                             "detalle": "ATC COCHABAMBA", "asignacion": "3P02891953"},
                    "comision": {"monto": "636.57", "cuenta_contable": "110201008",
                                 "detalle": "COMISION ATC", "asignacion": "TIQUIPAYA AGO"},
                }
            },
        }

    def _cierre_vacio(self):
        return {"comunicaciones_internas": [], "sfc101": {"depositos": []}, "sfc102": {"depositos": []}}

    def _macros_vacio(self):
        return {"por_codigo": {}, "por_importe": {}}

    def _correccion(self, campo, valor_original, valor_autorizado, sha="0" * 64):
        correccion = {
            "fecha_cierre": FECHA_CIERRE, "sha256_origen": sha,
            "categoria": "ATC", "tipo": "ATC_ASIGNACION_REVISAR",
            "identificadores": {}, "campo_corregido": campo,
            "valor_original": valor_original, "valor_autorizado": valor_autorizado,
            "motivo": "prueba", "usuario_auditor": "gabriel.torrico",
            "fecha_hora": "2026-09-12T14:05:00-04:00",
        }
        correccion["version_correccion"] = correcciones.calcular_version_correccion(correccion)
        return correccion

    def test_corrige_neto_asignacion_en_memoria(self):
        atc_idx = self._atc_idx()
        correccion = self._correccion("neto_asignacion", "3P02891953", "3P99999999")

        _, atc_corregido = correcciones.aplicar_correccion_en_memoria(
            self._cierre_vacio(), self._macros_vacio(), atc_idx, correccion
        )

        self.assertEqual(atc_corregido["por_fecha"][FECHA_CIERRE]["neto"]["asignacion"], "3P99999999")
        # Nunca muta el atc_idx original recibido.
        self.assertEqual(atc_idx["por_fecha"][FECHA_CIERRE]["neto"]["asignacion"], "3P02891953")

    def test_rechaza_modo_legado(self):
        atc_idx = {"modo": "LEGADO", "por_fecha": {}}
        correccion = self._correccion("neto_asignacion", "X", "Y")

        with self.assertRaises(ValueError) as ctx:
            correcciones.aplicar_correccion_en_memoria(
                self._cierre_vacio(), self._macros_vacio(), atc_idx, correccion
            )
        self.assertIn("CORRECCION_ATC_MODO_NO_CORREGIBLE", str(ctx.exception))


class TestCorreccionAtcEndToEnd(_BaseCorreccion):
    """Escenario realista de bloqueo: una cuenta ATC_NETO inválida en la
    hoja 'ATC TIQUIPAYA' hace que ETAPA 5 (construir_asiento) rechace el
    asiento (ATC_NETO_CUENTA_INVALIDA) aunque ETAPA 3/4 (v2) queden OK sin
    excepciones — corregir neto_cuenta_contable restaura el asiento válido."""

    def test_corrige_neto_cuenta_contable_invalida_y_reprocesa_a_ok(self):
        fx.crear_maestro_unico(
            self.ruta_maestro,
            macros_filas=_macros_filas_solo_vouchers(),
            atc_filas=[_fila_neto(cuenta="999999999"), _fila_comision()],
        )
        self._crear_cierre(_baseline_sfc101(), _baseline_sfc102())

        hash_antes = self._hash_cierre()
        original = self._procesar_original()
        self.assertEqual(original["resultado_v2"]["estado"], "OK")
        self.assertEqual(original["resultado_v2"]["excepciones"], [])
        self.assertEqual(original["asiento"]["estado"], "ERROR")
        self.assertIn("ATC_NETO_CUENTA_INVALIDA", original["asiento"]["problemas"])
        self.assertEqual(original["estado"], pipeline.ESTADO_ERROR)

        # Gap corregido (aprobado 2026-09-12): el problema de ETAPA 5 ahora
        # SÍ queda visible en RESULTADO_TIQ como excepcion estructurada,
        # sin que "blockers" (exclusivo de ETAPA 3/4) se vea afectado.
        self.assertEqual(original["resultado_json"]["blockers"], 0)
        excepciones = original["resultado_json"]["excepciones"]
        self.assertEqual(len(excepciones), 1)
        self.assertEqual(excepciones[0]["categoria"], "ATC")
        self.assertEqual(excepciones[0]["tipo"], "ATC_NETO_CUENTA_INVALIDA")
        self.assertEqual(excepciones[0]["neto_cuenta_contable"], "999999999")

        correccion = _construir_correccion(
            categoria="ATC", tipo="ATC_NETO_CUENTA_INVALIDA", identificadores={},
            campo_corregido="neto_cuenta_contable",
            valor_original="999999999", valor_autorizado="110103012",
            sha256_origen=original["hash_origen"], fecha_cierre=FECHA_CIERRE,
        )

        reproceso = self._reprocesar(correccion)
        self.assertEqual(reproceso["estado"], pipeline.ESTADO_VALIDADO_PENDIENTE)
        self.assertEqual(self._hash_cierre(), hash_antes)


# ---------------------------------------------------------------------------
# 6. SHA256 incorrecto (corrección huérfana)
# ---------------------------------------------------------------------------

class TestCorreccionShaIncorrecto(_BaseCorreccion):
    def test_sha_distinto_es_rechazado(self):
        sfc101 = _baseline_sfc101()
        sfc101["ci"][0]["cuenta"] = None
        self._crear_cierre(sfc101, _baseline_sfc102())
        original = self._procesar_original()
        exc = original["resultado_json"]["excepciones"][0]

        correccion = _construir_correccion(
            categoria=exc["categoria"], tipo=exc["tipo"],
            identificadores={"sfc": exc["sfc"], "factura": exc["factura"]},
            campo_corregido="cuenta_contable", valor_original=None,
            valor_autorizado="210201005",
            sha256_origen="0" * 64,  # deliberadamente incorrecto
            fecha_cierre=FECHA_CIERRE,
        )

        with self.assertRaises(ValueError) as ctx:
            self._reprocesar(correccion)
        self.assertIn("CORRECCION_HUERFANA", str(ctx.exception))


# ---------------------------------------------------------------------------
# 7. Cierre ya publicado (marcador PROCESADO_<hash>.json existente)
# ---------------------------------------------------------------------------

class TestCorreccionCierreYaPublicado(_BaseCorreccion):
    def _correccion_base(self, original):
        exc = original["resultado_json"]["excepciones"][0]
        return _construir_correccion(
            categoria=exc["categoria"], tipo=exc["tipo"],
            identificadores={"sfc": exc["sfc"], "factura": exc["factura"]},
            campo_corregido="cuenta_contable", valor_original=None,
            valor_autorizado="210201005",
            sha256_origen=original["hash_origen"], fecha_cierre=FECHA_CIERRE,
        )

    def test_pipeline_rechaza_si_ya_publicado(self):
        sfc101 = _baseline_sfc101()
        sfc101["ci"][0]["cuenta"] = None
        self._crear_cierre(sfc101, _baseline_sfc102())
        original = self._procesar_original()
        correccion = self._correccion_base(original)

        with self.assertRaises(ValueError) as ctx:
            self._reprocesar(correccion, ya_publicado=True)
        self.assertIn("CIERRE_YA_PUBLICADO_NO_CORREGIBLE", str(ctx.exception))

    def test_cli_rechaza_si_existe_marcador_procesado(self):
        sfc101 = _baseline_sfc101()
        sfc101["ci"][0]["cuenta"] = None
        self._crear_cierre(sfc101, _baseline_sfc102())
        original = self._procesar_original()
        correccion = self._correccion_base(original)
        ruta_correccion = self._escribir_correccion(correccion)

        marcadores_dir = os.path.join(self.controles_dir, "MARCADORES_PROCESAMIENTO")
        os.makedirs(marcadores_dir, exist_ok=True)
        with open(os.path.join(marcadores_dir, f"PROCESADO_{original['hash_origen']}.json"),
                  "w", encoding="utf-8") as f:
            json.dump({"HashOrigen": original["hash_origen"], "Estado": "PROCESADO"}, f)

        codigo, payload = _ejecutar_cli(self._argv_cli(ruta_correccion))
        self.assertNotEqual(codigo, 0)
        self.assertEqual(payload["codigo"], "CIERRE_YA_PUBLICADO_NO_CORREGIBLE")


# ---------------------------------------------------------------------------
# 8-9. Idempotencia por CLI: misma corrección dos veces / corrección
# distinta sobre el mismo original
# ---------------------------------------------------------------------------

class TestCliIdempotenciaYCorreccionesDistintas(_BaseCorreccion):
    def _preparar(self):
        sfc101 = _baseline_sfc101()
        sfc101["ci"][0]["cuenta"] = None
        self._crear_cierre(sfc101, _baseline_sfc102())
        original = self._procesar_original()
        exc = original["resultado_json"]["excepciones"][0]
        return original, exc

    def test_misma_correccion_dos_veces_es_idempotente(self):
        original, exc = self._preparar()
        correccion = _construir_correccion(
            categoria=exc["categoria"], tipo=exc["tipo"],
            identificadores={"sfc": exc["sfc"], "factura": exc["factura"]},
            campo_corregido="cuenta_contable", valor_original=None,
            valor_autorizado="210201005",
            sha256_origen=original["hash_origen"], fecha_cierre=FECHA_CIERRE,
        )
        ruta_correccion = self._escribir_correccion(correccion)

        codigo1, payload1 = _ejecutar_cli(self._argv_cli(ruta_correccion))
        self.assertEqual(codigo1, 0)
        self.assertEqual(payload1["estado"], "LISTO_PARA_PUBLICAR")
        ruta_sap = payload1["ruta_sap_reproceso"]
        self.assertTrue(os.path.isfile(ruta_sap))
        mtime_sap = os.path.getmtime(ruta_sap)

        codigo2, payload2 = _ejecutar_cli(self._argv_cli(ruta_correccion))
        self.assertEqual(codigo2, 0)
        self.assertEqual(payload2["estado"], "YA_APLICADA")
        self.assertEqual(payload2["version_correccion"], payload1["version_correccion"])
        self.assertEqual(payload2["ruta_resultado_reproceso"], payload1["ruta_resultado_reproceso"])
        # La segunda corrida NUNCA vuelve a invocar el motor/SAP: el archivo
        # SAP del reproceso no se regenera.
        self.assertEqual(os.path.getmtime(ruta_sap), mtime_sap)

    def test_correccion_distinta_sobre_mismo_original_no_colisiona(self):
        original, exc = self._preparar()
        correccion_a = _construir_correccion(
            categoria=exc["categoria"], tipo=exc["tipo"],
            identificadores={"sfc": exc["sfc"], "factura": exc["factura"]},
            campo_corregido="cuenta_contable", valor_original=None,
            valor_autorizado="210201005",
            sha256_origen=original["hash_origen"], fecha_cierre=FECHA_CIERRE,
        )
        ruta_correccion_a = self._escribir_correccion(correccion_a, "correccion_a.json")
        codigo_a, payload_a = _ejecutar_cli(self._argv_cli(ruta_correccion_a))
        self.assertEqual(codigo_a, 0)

        # Corrección DISTINTA (otro valor_autorizado) sobre el MISMO .xlsm
        # original (mismo sha256_origen): debe producir su propio reproceso,
        # con su propio version_correccion, sin pisar el anterior.
        correccion_b = _construir_correccion(
            categoria=exc["categoria"], tipo=exc["tipo"],
            identificadores={"sfc": exc["sfc"], "factura": exc["factura"]},
            campo_corregido="cuenta_contable", valor_original=None,
            valor_autorizado="210299999",
            sha256_origen=original["hash_origen"], fecha_cierre=FECHA_CIERRE,
        )
        ruta_correccion_b = self._escribir_correccion(correccion_b, "correccion_b.json")
        codigo_b, payload_b = _ejecutar_cli(self._argv_cli(ruta_correccion_b))
        self.assertEqual(codigo_b, 0)

        self.assertNotEqual(payload_b["version_correccion"], payload_a["version_correccion"])
        self.assertNotEqual(payload_b["ruta_resultado_reproceso"], payload_a["ruta_resultado_reproceso"])
        self.assertTrue(os.path.isfile(payload_a["ruta_resultado_reproceso"]))
        self.assertTrue(os.path.isfile(payload_b["ruta_resultado_reproceso"]))

        with open(payload_a["ruta_resultado_reproceso"], "r", encoding="utf-8") as f:
            resultado_a_en_disco = json.load(f)
        with open(payload_b["ruta_resultado_reproceso"], "r", encoding="utf-8") as f:
            resultado_b_en_disco = json.load(f)
        self.assertEqual(resultado_a_en_disco["correccion_aplicada"]["valor_autorizado"], "210201005")
        self.assertEqual(resultado_b_en_disco["correccion_aplicada"]["valor_autorizado"], "210299999")


# ---------------------------------------------------------------------------
# 10. El .xlsm original nunca cambia (verificación explícita)
# ---------------------------------------------------------------------------

class TestXlsmOriginalNuncaCambia(_BaseCorreccion):
    def test_xlsm_no_cambia_tras_validar_aplicar_y_reprocesar(self):
        sfc101 = _baseline_sfc101()
        sfc101["ci"][0]["cuenta"] = None
        self._crear_cierre(sfc101, _baseline_sfc102())

        hash_antes = self._hash_cierre()
        mtime_antes = os.path.getmtime(self.ruta_cierre)

        original = self._procesar_original()
        exc = original["resultado_json"]["excepciones"][0]
        correccion = _construir_correccion(
            categoria=exc["categoria"], tipo=exc["tipo"],
            identificadores={"sfc": exc["sfc"], "factura": exc["factura"]},
            campo_corregido="cuenta_contable", valor_original=None,
            valor_autorizado="210201005",
            sha256_origen=original["hash_origen"], fecha_cierre=FECHA_CIERRE,
        )
        ruta_correccion = self._escribir_correccion(correccion)

        # Aplicado por CLI (dos veces, ejercitando la idempotencia) y
        # directo por pipeline.procesar_cierre_con_correccion(): en NINGÚN
        # caso el .xlsm original se abre en modo escritura.
        codigo1, _ = _ejecutar_cli(self._argv_cli(ruta_correccion))
        self.assertEqual(codigo1, 0)
        codigo2, _ = _ejecutar_cli(self._argv_cli(ruta_correccion))
        self.assertEqual(codigo2, 0)
        self._reprocesar(correccion)

        self.assertEqual(self._hash_cierre(), hash_antes)
        self.assertEqual(os.path.getmtime(self.ruta_cierre), mtime_antes)


# ---------------------------------------------------------------------------
# Extra — schema: importes nunca corregibles, version_correccion no se
# puede alterar tras calcularse.
# ---------------------------------------------------------------------------

class TestSchemaGuardarrailes(unittest.TestCase):
    def test_importe_no_es_corregible(self):
        correccion = _construir_correccion(
            categoria="COMUNICACION_INTERNA", tipo="CI_IMPORTE_NEGATIVO",
            identificadores={"sfc": "SFC101", "factura": "F-1"},
            campo_corregido="importe", valor_original="-50.00", valor_autorizado="50.00",
            sha256_origen="0" * 64, fecha_cierre=FECHA_CIERRE,
        )
        with self.assertRaises(ValueError) as ctx:
            correcciones.validar_schema_correccion(correccion)
        self.assertIn("CORRECCION_CAMPO_NO_CORREGIBLE", str(ctx.exception))

    def test_version_correccion_alterada_es_rechazada(self):
        correccion = _construir_correccion(
            categoria="COMUNICACION_INTERNA", tipo="CI_CUENTA_FALTANTE",
            identificadores={"sfc": "SFC101", "factura": "F-1"},
            campo_corregido="cuenta_contable", valor_original=None, valor_autorizado="210201005",
            sha256_origen="0" * 64, fecha_cierre=FECHA_CIERRE,
        )
        correccion["version_correccion"] = "0" * 64  # manipulada tras calcularse

        with self.assertRaises(ValueError) as ctx:
            correcciones.validar_schema_correccion(correccion)
        self.assertIn("CORRECCION_VERSION_INCONSISTENTE", str(ctx.exception))


# ---------------------------------------------------------------------------
# --correccion-sin-version — FASE 3 Parte A: n8n arma los campos de la
# corrección pero NUNCA calcula version_correccion (evita duplicar ese hash
# en JavaScript); Python lo calcula con la MISMA función que ya valida
# --correccion.
# ---------------------------------------------------------------------------

class TestCliCorreccionSinVersion(_BaseCorreccion):
    def test_correccion_sin_version_calcula_el_mismo_hash_que_calcular_version_correccion(self):
        sfc101 = _baseline_sfc101()
        sfc101["ci"][0]["cuenta"] = None
        self._crear_cierre(sfc101, _baseline_sfc102())
        original = self._procesar_original()
        exc = original["resultado_json"]["excepciones"][0]

        # JSON "crudo": todos los campos de la corrección MENOS version_correccion.
        correccion_sin_version = {
            "fecha_cierre": FECHA_CIERRE,
            "sha256_origen": original["hash_origen"],
            "categoria": exc["categoria"], "tipo": exc["tipo"],
            "identificadores": {"sfc": exc["sfc"], "factura": exc["factura"]},
            "campo_corregido": "cuenta_contable",
            "valor_original": exc["cuenta_contable"], "valor_autorizado": "210201005",
            "motivo": "prueba", "usuario_auditor": "gabriel.torrico",
            "fecha_hora": "2026-09-12T14:05:00-04:00",
        }
        ruta_sin_version = self._escribir_correccion(correccion_sin_version, "correccion_sin_version.json")

        version_esperada = correcciones.calcular_version_correccion(correccion_sin_version)

        argv = self._argv_cli(ruta_sin_version)
        # Reemplaza --correccion por --correccion-sin-version en el mismo argv.
        idx = argv.index("--correccion")
        argv[idx] = "--correccion-sin-version"

        codigo, payload = _ejecutar_cli(argv)
        self.assertEqual(codigo, 0)
        self.assertEqual(payload["estado"], "LISTO_PARA_PUBLICAR")
        self.assertEqual(payload["version_correccion"], version_esperada)

    def test_correccion_y_correccion_sin_version_son_mutuamente_excluyentes(self):
        with self.assertRaises(SystemExit):
            _ejecutar_cli([
                "--resultado", self.ruta_resultado_original,
                "--correccion", "a.json", "--correccion-sin-version", "b.json",
                "--cierre", self.ruta_cierre, "--maestro", self.ruta_maestro,
                "--plantilla-sap", self.ruta_plantilla,
                "--resultados-dir", self.resultados_dir, "--salidas-dir", self.salidas_dir,
            ])


if __name__ == "__main__":
    unittest.main()
