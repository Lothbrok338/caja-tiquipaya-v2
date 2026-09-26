"""Pruebas del flujo cloud: materializacion segura (nube_drive), MACROS ausente, salidas de resultados,
modo --manifiesto y validacion con el motor (aislada)."""
import base64
import datetime
import hashlib
import json
import os
import shutil
import sys
import tempfile
import unittest
import zipfile
import warnings

warnings.simplefilter("ignore")
sys.dont_write_bytecode = True
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import auditar as A  # noqa: E402
import nube_drive as N  # noqa: E402
import validar_motor as VM  # noqa: E402
import openpyxl  # noqa: E402
from test_controles import cierre, macros_xlsx  # noqa: E402

D = datetime.date


def volcar_como_conector(dirtemp, ruta_xlsm, drive_id, titulo):
    """Imita lo que hace el harness: guarda el resultado grande como JSON en <...>/tool-results/mcp-*.txt."""
    d = os.path.join(dirtemp, "tool-results")
    os.makedirs(d, exist_ok=True)
    with open(ruta_xlsm, "rb") as f:
        datos = f.read()
    p = os.path.join(d, "mcp-drive-download_file_content-%s.txt" % drive_id)
    with open(p, "w", encoding="utf-8") as f:
        json.dump({"content": base64.b64encode(datos).decode(), "id": drive_id, "mimeType": "x", "title": titulo}, f)
    return p, len(datos), hashlib.sha256(datos).hexdigest()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="test_nube_")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def ruta(self, *p):
        return os.path.join(self.tmp, *p)


class TestMaterializacion(Base):
    def setUp(self):
        super().setUp()
        self.orig = self.ruta("CIERRE 23-09-2026.xlsm")
        cierre(self.orig, deposito=(100, "23/09/26", "ZZ"))
        self.sesion = N.iniciar(self.ruta("base"))["sesion"]

    def registrar(self, **kw):
        p, n, h = volcar_como_conector(self.tmp, self.orig, "ID1", "CIERRE 23-09-2026.xlsm")
        args = dict(sesion=self.sesion, rol="cierre", drive_id="ID1", nombre="CIERRE 23-09-2026.xlsm", tam_drive=n,
                    json_fuente=p, caja="america")
        args.update(kw)
        return N.registrar(**args), p, n, h

    def test_registra_binario_identico_y_borra_la_fuente(self):
        r, p, n, h = self.registrar()
        destino = os.path.join(self.sesion, "AMERICA", "CIERRE 23-09-2026.xlsm")
        with open(destino, "rb") as f:
            self.assertEqual(hashlib.sha256(f.read()).hexdigest(), h)      # bit a bit
        self.assertEqual((r["bytes"], r["fuente_borrada"]), (n, True))
        self.assertFalse(os.path.exists(p))                                # el JSON con base64 se elimina
        m = json.load(open(os.path.join(self.sesion, "manifiesto.json"), encoding="utf-8"))
        self.assertEqual((m["cierres"][0]["caja"], m["cierres"][0]["fecha"]), ("america", "2026-09-23"))

    def test_tamano_distinto_al_de_drive_se_rechaza_y_no_deja_archivo(self):
        p, n, _ = volcar_como_conector(self.tmp, self.orig, "ID1", "CIERRE 23-09-2026.xlsm")
        with self.assertRaisesRegex(N.ErrorNube, "TAMANO_NO_COINCIDE"):
            N.registrar(self.sesion, "cierre", "ID1", "CIERRE 23-09-2026.xlsm", n + 1, p, "america")
        self.assertFalse(os.path.exists(os.path.join(self.sesion, "AMERICA", "CIERRE 23-09-2026.xlsm")))

    def test_id_o_titulo_distintos_se_rechazan(self):
        p, n, _ = volcar_como_conector(self.tmp, self.orig, "ID1", "CIERRE 23-09-2026.xlsm")
        with self.assertRaisesRegex(N.ErrorNube, "ID_NO_COINCIDE"):
            N.registrar(self.sesion, "cierre", "OTRO", "CIERRE 23-09-2026.xlsm", n, p, "america")
        with self.assertRaisesRegex(N.ErrorNube, "TITULO_NO_COINCIDE"):
            N.registrar(self.sesion, "cierre", "ID1", "CIERRE 24-09-2026.xlsm", n, p, "america")

    def test_no_zip_se_rechaza(self):
        d = os.path.join(self.tmp, "tool-results")
        os.makedirs(d, exist_ok=True)
        p = os.path.join(d, "mcp-x.txt")
        datos = b"esto no es un xlsm"
        json.dump({"content": base64.b64encode(datos).decode(), "id": "ID1", "title": "CIERRE 23-09-2026.xlsm"}, open(p, "w"))
        with self.assertRaises(Exception):
            N.registrar(self.sesion, "cierre", "ID1", "CIERRE 23-09-2026.xlsm", len(datos), p, "america")
        self.assertFalse(os.path.exists(os.path.join(self.sesion, "AMERICA", "CIERRE 23-09-2026.xlsm")))

    def test_base64_corrupto_y_fuente_sin_contenido(self):
        d = os.path.join(self.tmp, "tool-results")
        os.makedirs(d, exist_ok=True)
        p = os.path.join(d, "mcp-y.txt")
        json.dump({"content": "@@@@", "id": "ID1", "title": "CIERRE 23-09-2026.xlsm"}, open(p, "w"))
        with self.assertRaisesRegex(N.ErrorNube, "BASE64_INVALIDO"):
            N.registrar(self.sesion, "cierre", "ID1", "CIERRE 23-09-2026.xlsm", 4, p, "america")
        json.dump({"error": "x"}, open(p, "w"))
        with self.assertRaisesRegex(N.ErrorNube, "FUENTE_SIN_CONTENIDO"):
            N.registrar(self.sesion, "cierre", "ID1", "CIERRE 23-09-2026.xlsm", 4, p, "america")

    def test_duplicado_nombre_invalido_y_caja_requerida(self):
        self.registrar()
        with self.assertRaisesRegex(N.ErrorNube, "DUPLICADO"):
            self.registrar()
        with self.assertRaisesRegex(N.ErrorNube, "NOMBRE_CIERRE_INVALIDO"):
            self.registrar(nombre="cierre.xlsm")
        with self.assertRaisesRegex(N.ErrorNube, "CAJA_REQUERIDA"):
            self.registrar(caja=None)

    def test_la_fuente_fuera_de_tool_results_no_se_borra(self):
        p = self.ruta("mi_fuente.json")
        _, n, _ = volcar_como_conector(self.tmp, self.orig, "ID1", "CIERRE 23-09-2026.xlsm")
        shutil.copy(os.path.join(self.tmp, "tool-results", "mcp-drive-download_file_content-ID1.txt"), p)
        r = N.registrar(self.sesion, "cierre", "ID1", "CIERRE 23-09-2026.xlsm", n, p, "america")
        self.assertFalse(r["fuente_borrada"])
        self.assertTrue(os.path.exists(p))

    def test_limpiar_borra_solo_sesiones_propias(self):
        self.registrar()
        r = N.limpiar(self.sesion)
        self.assertTrue(r["ok"])
        self.assertFalse(os.path.exists(self.sesion))
        ajena = self.ruta("carpeta_ajena")
        os.makedirs(ajena)
        with self.assertRaisesRegex(N.ErrorNube, "SESION_INVALIDA"):
            N.limpiar(ajena)
        self.assertTrue(os.path.exists(ajena))

    def test_macros_se_guarda_en_su_carpeta(self):
        mac = self.ruta("MACROS SEPTIEMBRE.xlsm")
        macros_xlsx(mac, [(D(2026, 9, 10), "AB1", 100)])
        p, n, _ = volcar_como_conector(self.tmp, mac, "M1", "MACROS SEPTIEMBRE.xlsm")
        N.registrar(self.sesion, "macros", "M1", "MACROS SEPTIEMBRE.xlsm", n, p)
        self.assertTrue(os.path.isfile(os.path.join(self.sesion, "MACROS", "MACROS SEPTIEMBRE.xlsm")))


class TestSinMacrosYResultados(Base):
    def test_sin_macros_igual_normaliza_formato_de_texto_valido(self):
        r = self.ruta("CIERRE 23-09-2026.xlsm")
        cierre(r, deposito=(100, "23/09/26", "AB1"))
        out = A.auditar([("tiquipaya", r)], [], salida_dir=self.ruta("salida"), reporte_dir=self.ruta("rep"), hoy=D(2026, 9, 26))
        self.assertEqual(out["fechas_normalizadas"], 1)
        self.assertEqual(out["normalizadas_sin_voucher_macros"], 1)
        self.assertIn("no se indicó el archivo MACROS", " ".join(out["hallazgos"]))
        self.assertTrue(os.path.exists(os.path.join(self.ruta("salida"), "TIQUIPAYA", "CIERRE 23-09-2026.xlsm")))

    def test_macros_ilegible_tampoco_impide_normalizar(self):
        r = self.ruta("CIERRE 23-09-2026.xlsm")
        cierre(r, deposito=(100, "23/09/26", "AB1"))
        malo = self.ruta("MACROS SEPTIEMBRE.xlsm")
        open(malo, "wb").write(b"no zip")
        out = A.auditar([("tiquipaya", r)], [malo], salida_dir=self.ruta("salida"), reporte_dir=self.ruta("rep"), hoy=D(2026, 9, 26))
        self.assertEqual(out["fechas_normalizadas"], 1)
        self.assertIn("no se pudo leer MACROS", " ".join(out["hallazgos"]))

    def test_salida_estandar_zip_completo_y_solo_cuatro_entregables_en_la_carpeta(self):
        r = self.ruta("CIERRE 23-09-2026.xlsm")
        cierre(r, deposito=(100, "23/09/26", "AB1"))
        rep = self.ruta("rep")
        out = A.auditar([("tiquipaya", r)], [], salida_dir=os.path.join(rep, "CIERRES_NORMALIZADOS"), reporte_dir=rep,
                        hoy=D(2026, 9, 26), origen={"cierres": [], "macros": []})
        a = out["archivos"]
        self.assertEqual(sorted(os.listdir(rep)), ["AUDITORIA_CIERRES_RESULTADOS.zip", "PARA_CAJA_AMERICA.pdf",
                                                    "PARA_CAJA_TIQUIPAYA.pdf", "RESUMEN_GABO.pdf"])
        self.assertEqual(a["pdf"], os.path.abspath(os.path.join(rep, "RESUMEN_GABO.pdf")))
        for clave in ("resumen_gabo", "para_caja_america", "para_caja_tiquipaya"):
            with open(a[clave], "rb") as f:
                self.assertTrue(f.read(4).startswith(b"%PDF"))
        with zipfile.ZipFile(a["zip"]) as z:
            self.assertIsNone(z.testzip())
            self.assertEqual(sorted(z.namelist()), sorted([
                "INFORME_AUDITORIA_CIERRES.pdf", "INFORME_AUDITORIA_CIERRES.docx", "DETALLE_TECNICO_AUDITORIA.xlsx",
                "RESULTADOS_AUDITORIA.json", "HALLAZGOS_AUDITORIA.csv", "RECURSOS_USADOS.txt",
                "CIERRES_NORMALIZADOS/TIQUIPAYA/CIERRE 23-09-2026.xlsm"]))
            self.assertEqual(sorted(z.namelist()), sorted(a["contenido_zip"]))
            det = json.loads(z.read("RESULTADOS_AUDITORIA.json").decode("utf-8"))
            self.assertFalse(det["originales_drive_modificados"])
            self.assertEqual(det["resumen"]["revisados"], 1)
            self.assertTrue(z.read("HALLAZGOS_AUDITORIA.csv").decode("utf-8-sig").startswith("FECHA,CAJA,SFC,RESULTADO"))
            self.assertTrue(z.read("INFORME_AUDITORIA_CIERRES.pdf").startswith(b"%PDF"))
            self.assertTrue(z.read("INFORME_AUDITORIA_CIERRES.docx").startswith(b"PK"))
            # la copia normalizada del ZIP es un libro valido con la fecha ya normalizada
            copia = self.ruta("copia.xlsm")
            open(copia, "wb").write(z.read("CIERRES_NORMALIZADOS/TIQUIPAYA/CIERRE 23-09-2026.xlsm"))
        self.assertEqual(openpyxl.load_workbook(copia)["SFC101"]["F3"].value, datetime.datetime(2026, 9, 23))

    def test_recursos_usados_solo_metricas_verificables(self):
        r = self.ruta("CIERRE 23-09-2026.xlsm")
        cierre(r, deposito=(100, "23/09/26", "AB1"))
        out = A.auditar([("tiquipaya", r)], [], reporte_dir=self.ruta("rep"), hoy=D(2026, 9, 26),
                        origen={"cierres": [{"nombre": "x"}], "macros": [], "sesion_creada": "2026-09-26T10:00:00"})
        with zipfile.ZipFile(out["archivos"]["zip"]) as z:
            t = z.read("RECURSOS_USADOS.txt").decode("utf-8")
        for esperado in ("Duracion del proceso (reloj)", "Tiempo de CPU del proceso Python", "Pico de memoria residente",
                         "Cierres auditados: 1 (TIQUIPAYA: 1)", "Bytes de cierres leidos : %d" % os.path.getsize(r),
                         "NO medido por la skill", "Tokens/contexto del asistente", "Desde iniciar la sesion temporal",
                         "1 cierre(s) + 0 MACROS"):
            self.assertIn(esperado, t)

    def test_ni_la_skill_ni_su_config_contienen_destino_de_publicacion_en_drive(self):
        raiz = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
        cfg = json.load(open(os.path.join(raiz, "config_nube.json"), encoding="utf-8"))
        self.assertEqual(sorted(cfg), ["carpetas_prohibidas", "descripcion", "entradas", "macros", "motor_cajas_gabo", "version"])
        for nombre in os.listdir(os.path.join(raiz, "scripts")):
            if nombre.endswith(".py"):
                src = open(os.path.join(raiz, "scripts", nombre), encoding="utf-8").read()
                self.assertNotIn("create_file", src, nombre)
                self.assertNotIn("googleapiclient", src, nombre)


class TestManifiestoYMotor(Base):
    def test_modo_manifiesto_extremo_a_extremo(self):
        sesion = N.iniciar(self.ruta("base"))["sesion"]
        orig = self.ruta("CIERRE 23-09-2026.xlsm")
        cierre(orig, deposito=(100, "23/09/26", "AB1"))
        p, n, _ = volcar_como_conector(self.tmp, orig, "C1", "CIERRE 23-09-2026.xlsm")
        N.registrar(sesion, "cierre", "C1", "CIERRE 23-09-2026.xlsm", n, p, "tiquipaya")
        h_orig = hashlib.sha256(open(orig, "rb").read()).hexdigest()
        rep = self.ruta("resultados")
        import io
        import contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            codigo = A.main(["--manifiesto", os.path.join(sesion, "manifiesto.json"), "--reporte-dir", rep, "--sin-motor"])
        self.assertEqual(codigo, 0)
        out = json.loads(buf.getvalue())
        self.assertEqual(out["cierres"]["revisados"], 1)
        self.assertEqual(out["fechas_normalizadas"], 1)
        self.assertEqual(sorted(os.listdir(rep)), ["AUDITORIA_CIERRES_RESULTADOS.zip", "PARA_CAJA_AMERICA.pdf",
                                                    "PARA_CAJA_TIQUIPAYA.pdf", "RESUMEN_GABO.pdf"])
        with zipfile.ZipFile(out["archivos"]["zip"]) as z:
            self.assertIn("CIERRES_NORMALIZADOS/TIQUIPAYA/CIERRE 23-09-2026.xlsm", z.namelist())
            self.assertIn("RECURSOS_USADOS.txt", z.namelist())
            det = json.loads(z.read("RESULTADOS_AUDITORIA.json").decode("utf-8"))
        self.assertEqual(det["origen"]["cierres"][0]["drive_id"], "C1")
        self.assertEqual(hashlib.sha256(open(orig, "rb").read()).hexdigest(), h_orig)
        # limpieza: la sesion temporal desaparece pero los resultados persisten
        self.assertTrue(N.limpiar(sesion)["ok"])
        self.assertFalse(os.path.exists(sesion))
        self.assertTrue(os.path.isfile(out["archivos"]["pdf"]))
        self.assertTrue(os.path.isfile(out["archivos"]["zip"]))

    def test_motor_no_disponible_no_detiene_la_auditoria(self):
        r = self.ruta("CIERRE 23-09-2026.xlsm")
        cierre(r, deposito=(100, "23/09/26", "AB1"))
        out = A.auditar([("tiquipaya", r)], [], reporte_dir=self.ruta("rep"), hoy=D(2026, 9, 26), validar_motor=True,
                        motor_dir=self.ruta("no_existe"))
        self.assertFalse(out["motor_cajas_gabo"]["disponible"])
        self.assertIn("MOTOR_NO_ENCONTRADO", out["motor_cajas_gabo"]["motivo"])
        self.assertEqual(out["cierres"]["revisados"], 1)

    def _auditar_capturando_lo_que_recibe_el_motor(self, r, rep, con_copias=True):
        """Corre auditar con el motor real y registra el sha256 EXACTO del archivo que se le entrega al motor."""
        vistos = []
        original = A._validar_motor

        def espia(grupos, macros, motor_dir=None):
            for caja, ruta in grupos:
                vistos.append((ruta, hashlib.sha256(open(ruta, "rb").read()).hexdigest()))
            return original(grupos, macros, motor_dir)

        A._validar_motor = espia
        try:
            out = A.auditar([("tiquipaya", r)], [], salida_dir=os.path.join(rep, "CIERRES_NORMALIZADOS") if con_copias else None,
                            reporte_dir=rep, hoy=D(2026, 9, 26), validar_motor=True)
        finally:
            A._validar_motor = original
        return out, vistos

    def test_motor_valida_la_copia_post_auditoria_y_no_el_original(self):
        """23/09/26 -> el auditor la normaliza -> el motor recibe 23/09/2026 -> el motor YA NO falla por formato
        -> el informe no trae una falsa discrepancia de lectura."""
        if VM.localizar() is None:
            self.skipTest("motor CAJAS GABO no disponible en este equipo")
        r = self.ruta("CIERRE 23-09-2026.xlsm")
        cierre(r, deposito=(100, "23/09/26", "AB1"))
        # Precondicion (el defecto que existia): sobre el ORIGINAL el motor falla por el formato de la fecha.
        base = VM.validar([{"caja": "tiquipaya", "ruta": r, "fecha": "2026-09-23", "maestro": None}])["items"][0]
        self.assertEqual(base["lectura_motor"], "ERROR")
        self.assertIn("23/09/26", base["error"])

        rep = self.ruta("rep")
        out, vistos = self._auditar_capturando_lo_que_recibe_el_motor(r, rep)
        with zipfile.ZipFile(out["archivos"]["zip"]) as z:
            det = json.loads(z.read("RESULTADOS_AUDITORIA.json").decode("utf-8"))
            copia = z.read("CIERRES_NORMALIZADOS/TIQUIPAYA/CIERRE 23-09-2026.xlsm")
            informe_zip = z.read("DETALLE_TECNICO_AUDITORIA.xlsx")
        # 1) el auditor normalizo la fecha en la copia
        self.assertEqual(out["fechas_normalizadas"], 1)
        # 2) el motor recibio EXACTAMENTE el archivo que se entrega como cierre normalizado (no el original)
        self.assertEqual(len(vistos), 1)
        self.assertEqual(vistos[0][1], hashlib.sha256(copia).hexdigest())
        self.assertNotEqual(vistos[0][1], hashlib.sha256(open(r, "rb").read()).hexdigest())
        self.assertNotEqual(os.path.abspath(vistos[0][0]), os.path.abspath(r))
        # 3) el motor leyo 23/09/2026 y ya no falla por formato
        item = det["motor_cajas_gabo"]["items"][0]
        self.assertEqual(item["archivo_validado"], "copia_normalizada")
        self.assertEqual(item["lectura_motor"], "OK")
        self.assertIsNone(item["error"])
        self.assertEqual(item["fechas_deposito_motor"], ["2026-09-23"])
        # 4) ninguna falsa discrepancia de lectura en resultados ni en el informe
        motor_h = [h for h in det["hallazgos"] if h["control"] == 7]
        self.assertFalse([h for h in motor_h if "no pudo leer" in h["hallazgo"] or "discrepancia" in h["hallazgo"]])
        self.assertFalse([h for h in out["hallazgos"] if "no pudo leer" in h or "discrepancia" in h])
        informe = self.ruta("informe_zip.xlsx")
        open(informe, "wb").write(informe_zip)
        hoja = openpyxl.load_workbook(informe)["Validacion motor"]
        fila = [c.value for c in hoja[2]]
        self.assertEqual((fila[3], fila[8], fila[9]), ("OK", "Copia normalizada (la que se entrega)", "2026-09-23"))

    def test_cierre_sin_cambios_se_valida_su_copia_temporal_equivalente(self):
        if VM.localizar() is None:
            self.skipTest("motor CAJAS GABO no disponible en este equipo")
        r = self.ruta("CIERRE 23-09-2026.xlsm")
        cierre(r, deposito=(100, D(2026, 9, 23), "AB1"))          # fecha ya valida: el auditor no cambia nada
        out, vistos = self._auditar_capturando_lo_que_recibe_el_motor(r, self.ruta("rep"))
        self.assertEqual(out["fechas_normalizadas"], 0)
        self.assertEqual(vistos[0][1], hashlib.sha256(open(r, "rb").read()).hexdigest())   # el mismo archivo materializado
        with zipfile.ZipFile(out["archivos"]["zip"]) as z:
            item = json.loads(z.read("RESULTADOS_AUDITORIA.json").decode("utf-8"))["motor_cajas_gabo"]["items"][0]
        self.assertEqual((item["archivo_validado"], item["lectura_motor"]), ("original_sin_cambios", "OK"))

    def test_sin_copia_generada_el_motor_valida_el_original_y_se_explica(self):
        if VM.localizar() is None:
            self.skipTest("motor CAJAS GABO no disponible en este equipo")
        r = self.ruta("CIERRE 23-09-2026.xlsm")
        cierre(r, deposito=(100, "23/09/26", "AB1"))
        out, _ = self._auditar_capturando_lo_que_recibe_el_motor(r, self.ruta("rep"), con_copias=False)
        with zipfile.ZipFile(out["archivos"]["zip"]) as z:
            item = json.loads(z.read("RESULTADOS_AUDITORIA.json").decode("utf-8"))["motor_cajas_gabo"]["items"][0]
        self.assertEqual(item["archivo_validado"], "original_con_cambios_pendientes")
        self.assertIn("no se generó la copia normalizada", " ".join(out["hallazgos"]))

    def test_macros_por_mes_del_cierre(self):
        m = ["C:/x/MACROS AGOSTO.xlsm", "C:/x/MACROS SEPTIEMBRE.xlsm"]
        self.assertTrue(A._macros_de_cierre(m, D(2026, 9, 5)).endswith("SEPTIEMBRE.xlsm"))
        self.assertTrue(A._macros_de_cierre(m, D(2026, 8, 5)).endswith("AGOSTO.xlsm"))
        self.assertIsNone(A._macros_de_cierre(m, D(2026, 10, 5)))
        self.assertTrue(A._macros_de_cierre(m[:1], D(2026, 10, 5)).endswith("AGOSTO.xlsm"))


if __name__ == "__main__":
    unittest.main()
