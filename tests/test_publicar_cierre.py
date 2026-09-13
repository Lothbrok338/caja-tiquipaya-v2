"""test_publicar_cierre.py — pruebas de publicar_cierre.py (CLI mínimo que
expone pipeline_tiquipaya.construir_marcador_procesado()).

No usa datos contables reales: el resultado_json de prueba es sintético.
No se conecta a Google Drive; solo verifica lectura/escritura de archivos
locales y el comportamiento de la compuerta de las 4 confirmaciones.

Uso: python -m unittest tests.test_publicar_cierre -v
"""

import ast
import inspect
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import publicar_cierre


def _resultado_json_valido(**overrides):
    base = {
        "fecha_cierre": "2026-09-01",
        "archivo_origen": "CIERRE 01-09-2026.xlsm",
        "sha256_origen": "HASH_SINTETICO_DE_PRUEBA_0001",
        "version_codigo": "TEST-VERSION",
        "estado_v2": "OK",
        "diferencia": "0.00",
        "diferencia_asiento": "0.00",
        "blockers": 0,
        "sap_archivo": "/ruta/sintetica/SAP_01-09-2026.xlsx",
    }
    base.update(overrides)
    return base


def _escribir_resultado_temporal(tmp_dir, contenido):
    ruta = os.path.join(tmp_dir, "RESULTADO_TIQ_01-09-2026.json")
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(contenido, f)
    return ruta


def _ejecutar_cli(argv):
    """Corre main(argv), captura stdout, y devuelve (codigo_salida, payload_json)."""
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        codigo = publicar_cierre.main(argv)
    payload = json.loads(buffer.getvalue())
    return codigo, payload


class TestCasoExitoso(unittest.TestCase):
    def test_las_4_confirmaciones_true_genera_marcador_local(self):
        with tempfile.TemporaryDirectory() as tmp:
            ruta_resultado = _escribir_resultado_temporal(tmp, _resultado_json_valido())
            ruta_marcador = os.path.join(tmp, "marcadores", "PROCESADO_test.json")

            codigo, payload = _ejecutar_cli([
                "--resultado", ruta_resultado,
                "--sap-publicado-por-usuario", "true",
                "--sap-verificado-en-drive", "true",
                "--resultado-publicado", "true",
                "--cierre-movido-a-procesados", "true",
                "--observaciones", "Prueba sintetica de publicar_cierre.py",
                "--salida-marcador", ruta_marcador,
            ])

            self.assertEqual(codigo, 0)
            self.assertEqual(payload["resultado"], "OK")
            self.assertEqual(payload["marcador_nombre"],
                              "PROCESADO_HASH_SINTETICO_DE_PRUEBA_0001.json")
            self.assertEqual(payload["hash_origen"], "HASH_SINTETICO_DE_PRUEBA_0001")
            self.assertTrue(os.path.isfile(ruta_marcador))

            with open(ruta_marcador, "r", encoding="utf-8") as f:
                contenido_en_disco = json.load(f)
            self.assertEqual(contenido_en_disco["Estado"], "PROCESADO")
            self.assertEqual(contenido_en_disco["HashOrigen"], "HASH_SINTETICO_DE_PRUEBA_0001")
            self.assertEqual(contenido_en_disco["Diferencia"], "0.00")
            self.assertEqual(contenido_en_disco["Blockers"], "0")
            self.assertEqual(contenido_en_disco["Observaciones"],
                              "Prueba sintetica de publicar_cierre.py")
            # El contenido debe ser exactamente el que ya construye
            # construir_registro_control(): no se reinterpreta nada aqui.
            self.assertEqual(contenido_en_disco, payload["contenido"])

    def test_archivo_sap_explicito_tiene_prioridad_sobre_resultado_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            ruta_resultado = _escribir_resultado_temporal(tmp, _resultado_json_valido())
            ruta_marcador = os.path.join(tmp, "PROCESADO_test.json")

            codigo, payload = _ejecutar_cli([
                "--resultado", ruta_resultado,
                "--sap-publicado-por-usuario", "true",
                "--sap-verificado-en-drive", "true",
                "--resultado-publicado", "true",
                "--cierre-movido-a-procesados", "true",
                "--archivo-sap", "SAP_RENOMBRADO_MANUALMENTE.xlsx",
                "--salida-marcador", ruta_marcador,
            ])

            self.assertEqual(codigo, 0)
            self.assertEqual(payload["contenido"]["ArchivoSAP"],
                              "SAP_RENOMBRADO_MANUALMENTE.xlsx")


class TestConfirmacionesFaltantes(unittest.TestCase):
    """Si cualquiera de las 4 confirmaciones es false, debe fallar y NO
    debe escribirse ningun marcador (ni siquiera parcial)."""

    def _correr_con(self, tmp, **flags_bool):
        ruta_resultado = _escribir_resultado_temporal(tmp, _resultado_json_valido())
        ruta_marcador = os.path.join(tmp, "PROCESADO_no_deberia_existir.json")
        defaults = {
            "sap_publicado_por_usuario": True,
            "sap_verificado_en_drive": True,
            "resultado_publicado": True,
            "cierre_movido_a_procesados": True,
        }
        defaults.update(flags_bool)
        argv = ["--resultado", ruta_resultado]
        for nombre, valor in defaults.items():
            argv += [f"--{nombre.replace('_', '-')}", "true" if valor else "false"]
        argv += ["--salida-marcador", ruta_marcador]
        codigo, payload = _ejecutar_cli(argv)
        return codigo, payload, ruta_marcador

    def test_sap_no_publicado_por_usuario_falla(self):
        with tempfile.TemporaryDirectory() as tmp:
            codigo, payload, ruta_marcador = self._correr_con(
                tmp, sap_publicado_por_usuario=False)
            self.assertEqual(codigo, 2)
            self.assertEqual(payload["resultado"], "ERROR")
            self.assertEqual(payload["codigo"], "MARCADOR_NO_AUTORIZADO")
            self.assertIn("SAP_NO_PUBLICADO_POR_USUARIO", payload["faltantes"])
            self.assertFalse(os.path.isfile(ruta_marcador))

    def test_sap_no_verificado_en_drive_falla(self):
        with tempfile.TemporaryDirectory() as tmp:
            codigo, payload, ruta_marcador = self._correr_con(
                tmp, sap_verificado_en_drive=False)
            self.assertEqual(codigo, 2)
            self.assertIn("SAP_NO_VERIFICADO_EN_DRIVE", payload["faltantes"])
            self.assertFalse(os.path.isfile(ruta_marcador))

    def test_resultado_no_publicado_falla(self):
        with tempfile.TemporaryDirectory() as tmp:
            codigo, payload, ruta_marcador = self._correr_con(
                tmp, resultado_publicado=False)
            self.assertEqual(codigo, 2)
            self.assertIn("RESULTADO_NO_PUBLICADO", payload["faltantes"])
            self.assertFalse(os.path.isfile(ruta_marcador))

    def test_cierre_no_movido_a_procesados_falla(self):
        with tempfile.TemporaryDirectory() as tmp:
            codigo, payload, ruta_marcador = self._correr_con(
                tmp, cierre_movido_a_procesados=False)
            self.assertEqual(codigo, 2)
            self.assertIn("CIERRE_NO_MOVIDO_A_PROCESADOS", payload["faltantes"])
            self.assertFalse(os.path.isfile(ruta_marcador))

    def test_las_4_confirmaciones_false_reporta_las_4_faltantes(self):
        with tempfile.TemporaryDirectory() as tmp:
            codigo, payload, ruta_marcador = self._correr_con(
                tmp,
                sap_publicado_por_usuario=False,
                sap_verificado_en_drive=False,
                resultado_publicado=False,
                cierre_movido_a_procesados=False,
            )
            self.assertEqual(codigo, 2)
            self.assertEqual(len(payload["faltantes"]), 4)
            self.assertFalse(os.path.isfile(ruta_marcador))

    def test_argumento_booleano_requerido_ausente_falla(self):
        # argparse exige las 4 confirmaciones explicitas: omitir una debe
        # fallar (SystemExit) y no debe requerirse interpretar ningun
        # default implicito.
        with tempfile.TemporaryDirectory() as tmp:
            ruta_resultado = _escribir_resultado_temporal(tmp, _resultado_json_valido())
            ruta_marcador = os.path.join(tmp, "PROCESADO_no_deberia_existir.json")
            argv = [
                "--resultado", ruta_resultado,
                "--sap-publicado-por-usuario", "true",
                "--sap-verificado-en-drive", "true",
                "--resultado-publicado", "true",
                # falta --cierre-movido-a-procesados
                "--salida-marcador", ruta_marcador,
            ]
            with redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as ctx:
                publicar_cierre.main(argv)
            self.assertNotEqual(ctx.exception.code, 0)
            self.assertFalse(os.path.isfile(ruta_marcador))

    def test_valor_booleano_invalido_falla(self):
        with tempfile.TemporaryDirectory() as tmp:
            ruta_resultado = _escribir_resultado_temporal(tmp, _resultado_json_valido())
            ruta_marcador = os.path.join(tmp, "PROCESADO_no_deberia_existir.json")
            argv = [
                "--resultado", ruta_resultado,
                "--sap-publicado-por-usuario", "sí",  # invalido a proposito
                "--sap-verificado-en-drive", "true",
                "--resultado-publicado", "true",
                "--cierre-movido-a-procesados", "true",
                "--salida-marcador", ruta_marcador,
            ]
            with redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as ctx:
                publicar_cierre.main(argv)
            self.assertNotEqual(ctx.exception.code, 0)
            self.assertFalse(os.path.isfile(ruta_marcador))


class TestResultadoInvalido(unittest.TestCase):
    def test_resultado_inexistente_falla_sin_crear_marcador(self):
        with tempfile.TemporaryDirectory() as tmp:
            ruta_marcador = os.path.join(tmp, "PROCESADO_no_deberia_existir.json")
            codigo, payload = _ejecutar_cli([
                "--resultado", os.path.join(tmp, "NO_EXISTE.json"),
                "--sap-publicado-por-usuario", "true",
                "--sap-verificado-en-drive", "true",
                "--resultado-publicado", "true",
                "--cierre-movido-a-procesados", "true",
                "--salida-marcador", ruta_marcador,
            ])
            self.assertEqual(codigo, 2)
            self.assertEqual(payload["codigo"], "RESULTADO_NO_LEGIBLE")
            self.assertFalse(os.path.isfile(ruta_marcador))

    def test_resultado_sin_hash_origen_falla_sin_crear_marcador(self):
        with tempfile.TemporaryDirectory() as tmp:
            resultado_incompleto = _resultado_json_valido()
            del resultado_incompleto["sha256_origen"]
            ruta_resultado = _escribir_resultado_temporal(tmp, resultado_incompleto)
            ruta_marcador = os.path.join(tmp, "PROCESADO_no_deberia_existir.json")

            codigo, payload = _ejecutar_cli([
                "--resultado", ruta_resultado,
                "--sap-publicado-por-usuario", "true",
                "--sap-verificado-en-drive", "true",
                "--resultado-publicado", "true",
                "--cierre-movido-a-procesados", "true",
                "--salida-marcador", ruta_marcador,
            ])
            self.assertEqual(codigo, 2)
            self.assertEqual(payload["codigo"], "RESULTADO_INCOMPLETO")
            self.assertFalse(os.path.isfile(ruta_marcador))


class TestSinDependenciaGoogleDrive(unittest.TestCase):
    def test_no_importa_ningun_cliente_de_google_ni_drive(self):
        codigo_fuente = inspect.getsource(publicar_cierre)
        for modulo in ("googleapiclient", "google.oauth2", "pydrive", "google.auth",
                       "requests", "httplib2", "urllib"):
            self.assertNotIn(f"import {modulo}", codigo_fuente)
        self.assertNotIn("drive.googleapis.com", codigo_fuente)
        self.assertNotIn("googleapiclient", sys.modules)

    def test_publicar_cierre_solo_importa_modulos_estandar_y_locales(self):
        permitidos = {"argparse", "json", "os", "sys", "pipeline_tiquipaya"}
        arbol = ast.parse(inspect.getsource(publicar_cierre))
        importados = set()
        for nodo in ast.walk(arbol):
            if isinstance(nodo, ast.Import):
                importados.update(alias.name.split(".")[0] for alias in nodo.names)
            elif isinstance(nodo, ast.ImportFrom) and nodo.module:
                importados.add(nodo.module.split(".")[0])
        self.assertTrue(importados.issubset(permitidos), importados - permitidos)


if __name__ == "__main__":
    unittest.main()
