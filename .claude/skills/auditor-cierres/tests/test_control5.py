"""Pruebas del Control 5 (unittest, sin dependencias extra).

Ejecutar:  python -m unittest discover -s tests -v   (desde la carpeta auditor-cierres)

Los .xlsm de prueba son SINTETICOS (openpyxl solo para CREAR fixtures nuevos
en una carpeta temporal; el Auditor nunca guarda con openpyxl).
Ademas hay una prueba opcional contra copias reales locales si existen.
"""
import datetime
import os
import sys
import tempfile
import unittest
import warnings
import zipfile

warnings.simplefilter("ignore")
sys.dont_write_bytecode = True
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))

import openpyxl  # noqa: E402

import control5_fecha_deposito as c5  # noqa: E402
import macros_vouchers as mv  # noqa: E402
import xlsm_xml as X  # noqa: E402

D = datetime.date
VBA = b"VBA-BINARIO-FALSO-\x00\x01\x02" * 50


def hacer_cierre(ruta, depositos, sfc=("SFC101", "SFC102"), extra_sfc2=None):
    """depositos: lista de (importe, fecha, codigo) para la 1a hoja SFC.
    `fecha` puede ser date, str, None o '=formula'. Crea un .xlsm con un
    vbaProject.bin falso para comprobar que se conserva byte a byte."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sfc[0]
    ws2 = wb.create_sheet(sfc[1])
    for w in (ws, ws2):
        w["A1"] = "FECHA DE CAJA"
        w["D2"], w["E2"], w["F2"], w["G2"], w["H2"] = "COMPOSICIÓN DE DEPOSITOS", "IMPORTE Bs", "FECHA DE DEPOSITO", "ASIGNACION", "BANCO"
    for i, (imp, fecha, cod) in enumerate(depositos):
        r = 3 + i
        ws.cell(r, 4, "DEPOSITO %d" % (i + 1))
        if imp is not None:
            ws.cell(r, 5, imp)
        c = ws.cell(r, 6, fecha)
        if isinstance(fecha, datetime.date):
            c.number_format = "dd/mm/yyyy"
        elif isinstance(fecha, str) and not fecha.startswith("="):
            c.number_format = "@"
        if cod is not None:
            ws.cell(r, 7, cod)
    ws.cell(3 + len(depositos) + 1, 5, "=SUBTOTAL(109,E3:E8)")  # fila sin etiqueta: debe ignorarse
    for i, (imp, fecha, cod) in enumerate(extra_sfc2 or []):
        r = 3 + i
        ws2.cell(r, 4, "DEPOSITO %d" % (i + 1))
        ws2.cell(r, 5, imp)
        ws2.cell(r, 6, fecha).number_format = "dd/mm/yyyy"
        ws2.cell(r, 7, cod)
    tmp = ruta + ".x.xlsx"
    wb.save(tmp)
    with zipfile.ZipFile(tmp) as zi, zipfile.ZipFile(ruta, "w", zipfile.ZIP_DEFLATED) as zo:
        for info in zi.infolist():
            zo.writestr(info.filename, zi.read(info.filename))
        zo.writestr("xl/vbaProject.bin", VBA)
    os.remove(tmp)


def idx(*items):
    """items: (codigo, importe, fecha|None) -> indice como el de MACROS."""
    out = {}
    for cod, imp, f in items:
        out.setdefault((cod, imp), []).append(f)
    return out


class Base(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.d = self._t.name
        self.addCleanup(self._t.cleanup)

    def ruta(self, n):
        return os.path.join(self.d, n)

    def analizar(self, depositos, indice, caja="tiquipaya", fecha_cierre=D(2026, 9, 15), **kw):
        r = self.ruta("c.xlsm")
        hacer_cierre(r, depositos, **kw)
        return r, c5.analizar(r, indice, caja, fecha_cierre=fecha_cierre)

    def una(self, depositos, indice):
        _, inf = self.analizar(depositos, indice)
        self.assertEqual(len(inf["filas"]), len(depositos))
        return inf["filas"][0]


class TestClasificacion(Base):
    def test_fecha_igual_a_voucher_es_correcta(self):
        f = self.una([(100, D(2026, 9, 15), "AB1")], idx(("AB1", "100.00", D(2026, 9, 15))))
        self.assertEqual((f["clase"], f["accion"]), (c5.CORRECTA, "NINGUNA"))

    def test_inversion_ddmm_se_normaliza(self):
        # almacenada 09/10/2026 (9 de octubre), voucher 10/09/2026
        f = self.una([(100, D(2026, 10, 9), "AB1")], idx(("AB1", "100.00", D(2026, 9, 10))))
        self.assertEqual(f["clase"], c5.NORMALIZAR_INVERSION)
        self.assertEqual(f["fecha_nueva"], D(2026, 9, 10))

    def test_inversion_sin_voucher_no_se_corrige(self):
        f = self.una([(100, D(2026, 10, 9), "AB1")], {})
        self.assertEqual((f["clase"], f["motivo"]), (c5.REQUIERE_REVISION, "SIN_VOUCHER_EN_MACROS"))
        self.assertEqual(f["tipo_revision"], c5.NO_VERIFICABLE)

    def test_fecha_distinta_a_voucher_y_a_su_inversion_es_conflicto(self):
        f = self.una([(100, D(2026, 10, 9), "AB1")], idx(("AB1", "100.00", D(2026, 9, 20))))
        self.assertEqual((f["clase"], f["tipo_revision"]), (c5.REQUIERE_REVISION, c5.CONFLICTO))

    def test_dia_mayor_a_12_no_es_invertible(self):
        # 15/09/2026 no tiene inversion posible (mes 15 no existe); voucher 05/09/2026 => conflicto
        f = self.una([(100, D(2026, 9, 15), "AB1")], idx(("AB1", "100.00", D(2026, 9, 5))))
        self.assertEqual((f["clase"], f["tipo_revision"]), (c5.REQUIERE_REVISION, c5.CONFLICTO))

    def test_dia_igual_a_mes_no_se_invierte(self):
        f = self.una([(100, D(2026, 9, 9), "AB1")], idx(("AB1", "100.00", D(2026, 9, 12))))
        self.assertEqual(f["clase"], c5.REQUIERE_REVISION)

    def test_texto_ddmmyyyy_igual_a_voucher_se_convierte(self):
        f = self.una([(100, "15/09/2026", "AB1")], idx(("AB1", "100.00", D(2026, 9, 15))))
        self.assertEqual((f["clase"], f["accion"]), (c5.CONVERTIR_TEXTO, "CONVERTIR"))

    def test_texto_formatos_no_admitidos(self):
        v = idx(("AB1", "100.00", D(2026, 9, 15)))
        for txt in ("05/0/2026", "15-09-2026", " 15/09/2026", "15/09/2026 ", "2026-09-15", "hola", "31/02/2026", "15.09.2026", "15/09/202", "15/09/20266", "5//2026", "/9/2026", "15/09"):
            f = self.una([(100, txt, "AB1")], v)
            self.assertEqual(f["clase"], c5.REQUIERE_REVISION, txt)
            self.assertEqual(f["accion"], "NINGUNA", txt)

    def test_formas_de_texto_admitidas_se_convierten(self):
        casos = {D(2026, 9, 15): ("15/09/2026", "15/9/2026", "15/09/26", "15/9/26"),
                 D(2026, 9, 5): ("5/9/2026", "05/9/2026", "5/09/2026", "05/09/2026", "5/9/26", "05/09/26")}
        for fecha, textos in casos.items():
            for txt in textos:
                f = self.una([(100, txt, "AB1")], idx(("AB1", "100.00", fecha)))
                self.assertEqual((f["clase"], f["accion"], f["fecha_nueva"]), (c5.CONVERTIR_TEXTO, "CONVERTIR", fecha), txt)

    def test_anio_de_2_digitos_solo_contra_el_anio_del_cierre(self):
        v = idx(("AB1", "100.00", D(2025, 9, 15)))
        f = self.una([(100, "15/09/25", "AB1")], v)   # cierre 2026: 25 no coincide, aunque el voucher diga 2025
        self.assertEqual((f["clase"], f["accion"], f["motivo"]), (c5.REQUIERE_REVISION, "NINGUNA", "TEXTO_ANIO_2_DIGITOS_NO_COINCIDE_CON_ANIO_DEL_CIERRE"))
        _, inf = self.analizar([(100, "15/09/26", "AB1")], idx(("AB1", "100.00", D(2026, 9, 15))), fecha_cierre=None)
        self.assertEqual(inf["filas"][0]["motivo"], "TEXTO_ANIO_2_DIGITOS_NO_COINCIDE_CON_ANIO_DEL_CIERRE")
        _, inf = self.analizar([(100, "15/09/26", "AB1")], idx(("AB1", "100.00", D(2026, 9, 15))), fecha_cierre=D(2026, 1, 3))
        self.assertEqual(inf["filas"][0]["clase"], c5.CONVERTIR_TEXTO)   # solo importa el anio del cierre

    def test_texto_estructuralmente_invalido_o_inexistente_queda_manual(self):
        v = idx(("AB1", "100.00", D(2026, 9, 5)), ("AB1", "100.01", D(2026, 9, 5)))
        for txt in ("05/0/2026", "0/9/26", "32/01/2026", "15/13/26", "31/02/26", "29/02/2026", "00/09/2026"):
            f = self.una([(100, txt, "AB1")], v)
            self.assertEqual((f["clase"], f["accion"]), (c5.REQUIERE_REVISION, "NINGUNA"), txt)

    def test_texto_de_2_digitos_exige_voucher_unico_e_igual(self):
        f = self.una([(100, "15/09/26", "AB1")], idx(("AB1", "100.00", D(2026, 9, 20))))
        self.assertEqual((f["clase"], f["motivo"]), (c5.REQUIERE_REVISION, "TEXTO_DISTINTO_A_VOUCHER"))
        v = idx(("AB1", "100.00", D(2026, 9, 15)), ("AB1", "100.00", D(2026, 9, 15)))
        f = self.una([(100, "15/09/26", "AB1")], v)
        self.assertTrue(f["motivo"].startswith("VOUCHER_NO_UNICO"))

    def test_sin_voucher_normaliza_sin_cambiar_dia_mes_ni_anio(self):
        # sin voucher en MACROS (o MACROS sin cobertura): cualquier dia, solo formato
        casos = {"23/09/26": D(2026, 9, 23), "24/09/26": D(2026, 9, 24), "5/9/2026": D(2026, 9, 5),
                 "31/12/2026": D(2026, 12, 31), "1/1/26": D(2026, 1, 1), "05/10/26": D(2026, 10, 5)}
        for txt, esperado in casos.items():
            f = self.una([(100, txt, "SIN-VOUCHER")], {})
            self.assertEqual((f["clase"], f["fecha_nueva"]), (c5.CONVERTIR_TEXTO_SIN_VOUCHER, esperado), txt)
            self.assertEqual(f["valor_actual"], "texto %r" % txt)

    def test_sin_voucher_y_sin_asignacion_tambien_normaliza_formato(self):
        f = self.una([(100, "23/09/26", None)], idx(("AB1", "100.00", D(2026, 9, 23))))
        self.assertEqual(f["clase"], c5.CONVERTIR_TEXTO_SIN_VOUCHER)

    def test_sin_voucher_lo_invalido_o_ambiguo_sigue_manual(self):
        for txt in ("05/0/2026", "31/02/2026", "29/02/2026", "15/09/25", "15-09-2026", "23/09/2", "hola", "15/13/26"):
            f = self.una([(100, txt, "SIN-VOUCHER")], {})
            self.assertEqual((f["clase"], f["accion"]), (c5.REQUIERE_REVISION, "NINGUNA"), txt)

    def test_sin_voucher_no_corrige_valores_solo_formato(self):
        # fecha Excel real sin voucher: no se toca (ni siquiera una posible inversion)
        f = self.una([(100, D(2026, 10, 9), "SIN-VOUCHER")], {})
        self.assertEqual((f["clase"], f["accion"], f["motivo"]), (c5.REQUIERE_REVISION, "NINGUNA", "SIN_VOUCHER_EN_MACROS"))

    def test_voucher_no_unico_no_es_voucher_no_encontrado(self):
        v = idx(("AB1", "100.00", D(2026, 9, 23)), ("AB1", "100.00", D(2026, 9, 23)))
        f = self.una([(100, "23/09/26", "AB1")], v)
        self.assertEqual((f["clase"], f["accion"]), (c5.REQUIERE_REVISION, "NINGUNA"))
        f = self.una([(100, "23/09/26", "AB1")], idx(("AB1", "100.00", None)))
        self.assertEqual(f["motivo"], "VOUCHER_SIN_FECHA_VALIDA")

    def test_con_voucher_sigue_la_logica_de_contraste(self):
        f = self.una([(100, "23/09/26", "AB1")], idx(("AB1", "100.00", D(2026, 9, 23))))
        self.assertEqual(f["clase"], c5.CONVERTIR_TEXTO)        # contrastado con MACROS
        f = self.una([(100, "23/09/26", "AB1")], idx(("AB1", "100.00", D(2026, 9, 26))))
        self.assertEqual((f["clase"], f["motivo"]), (c5.REQUIERE_REVISION, "TEXTO_DISTINTO_A_VOUCHER"))

    def test_texto_con_voucher_de_otra_fecha_es_revision(self):
        f = self.una([(100, "15/09/2026", "AB1")], idx(("AB1", "100.00", D(2026, 9, 20))))
        self.assertEqual((f["clase"], f["motivo"]), (c5.REQUIERE_REVISION, "TEXTO_DISTINTO_A_VOUCHER"))

    def test_texto_invertido_respecto_al_voucher_no_se_corrige(self):
        # texto '09/10/2026' vs voucher 10/09/2026: el swap solo aplica a fechas Excel
        f = self.una([(100, "09/10/2026", "AB1")], idx(("AB1", "100.00", D(2026, 9, 10))))
        self.assertEqual(f["clase"], c5.REQUIERE_REVISION)

    def test_texto_sin_voucher_se_normaliza_solo_el_formato(self):
        f = self.una([(100, "15/09/2026", "AB1")], {})
        self.assertEqual((f["clase"], f["accion"], f["fecha_nueva"], f["motivo"]),
                         (c5.CONVERTIR_TEXTO_SIN_VOUCHER, "CONVERTIR", D(2026, 9, 15), "FECHA_NORMALIZADA_SIN_VOUCHER_MACROS"))

    def test_fecha_vacia_se_avisa_no_se_completa(self):
        f = self.una([(100, None, "AB1")], idx(("AB1", "100.00", D(2026, 9, 15))))
        self.assertEqual((f["clase"], f["accion"]), (c5.VACIA, "NINGUNA"))

    def test_formula_no_se_toca(self):
        f = self.una([(100, "=DATE(2026,9,15)", "AB1")], idx(("AB1", "100.00", D(2026, 9, 15))))
        self.assertEqual((f["clase"], f["motivo"]), (c5.REQUIERE_REVISION, "CELDA_CON_FORMULA_NO_SE_MODIFICA"))

    def test_voucher_no_unico(self):
        v = idx(("AB1", "100.00", D(2026, 9, 15)), ("AB1", "100.00", D(2026, 9, 15)))
        f = self.una([(100, D(2026, 9, 15), "AB1")], v)
        self.assertEqual(f["clase"], c5.REQUIERE_REVISION)
        self.assertTrue(f["motivo"].startswith("VOUCHER_NO_UNICO"))

    def test_mismo_codigo_otro_importe_no_es_voucher(self):
        f = self.una([(100, D(2026, 10, 9), "AB1")], idx(("AB1", "100.01", D(2026, 9, 10))))
        self.assertEqual(f["motivo"], "SIN_VOUCHER_EN_MACROS")

    def test_voucher_sin_fecha_valida(self):
        f = self.una([(100, D(2026, 10, 9), "AB1")], idx(("AB1", "100.00", None)))
        self.assertEqual(f["motivo"], "VOUCHER_SIN_FECHA_VALIDA")

    def test_asignacion_vacia(self):
        f = self.una([(100, D(2026, 10, 9), None)], idx(("AB1", "100.00", D(2026, 9, 10))))
        self.assertEqual(f["motivo"], "ASIGNACION_VACIA_SIN_VOUCHER")

    def test_solo_filas_con_importe(self):
        _, inf = self.analizar([(None, D(2026, 10, 9), "AB1"), (0, D(2026, 10, 9), "AB1")], {})
        self.assertEqual(inf["filas"], [])

    def test_codigo_normalizado(self):
        f = self.una([(100, D(2026, 9, 15), " ab 1 ")], idx(("AB1", "100.00", D(2026, 9, 15))))
        self.assertEqual(f["clase"], c5.CORRECTA)

    def test_america_usa_sfc107_sfc108(self):
        r = self.ruta("a.xlsm")
        hacer_cierre(r, [(100, D(2026, 10, 9), "AB1")], sfc=("SFC107", "SFC108"))
        inf = c5.analizar(r, idx(("AB1", "100.00", D(2026, 9, 10))), "america")
        self.assertEqual(inf["filas"][0]["clase"], c5.NORMALIZAR_INVERSION)
        inf2 = c5.analizar(r, idx(("AB1", "100.00", D(2026, 9, 10))), "tiquipaya")
        self.assertEqual({h["motivo"] for h in inf2["hojas_con_problema"]}, {"HOJA_NO_ENCONTRADA"})

    def test_caja_desconocida_falla_cerrado(self):
        r = self.ruta("c.xlsm")
        hacer_cierre(r, [(100, D(2026, 9, 15), "AB1")])
        with self.assertRaises(ValueError):
            c5.analizar(r, {}, "otra")


class TestEscrituraXml(Base):
    def _aplicar(self, depositos, indice, **kw):
        r, inf = self.analizar(depositos, indice, **kw)
        out = self.ruta("salida.xlsm")
        res = c5.aplicar(r, out, inf)
        return r, out, inf, res

    def test_inversion_solo_cambia_la_celda_y_conserva_estilo(self):
        r, out, inf, res = self._aplicar(
            [(100, D(2026, 10, 9), "AB1"), (200, D(2026, 9, 9), "AB2")],
            idx(("AB1", "100.00", D(2026, 9, 10)), ("AB2", "200.00", D(2026, 9, 9))))
        self.assertTrue(res["escrito"])
        self.assertEqual(res["partes_modificadas"], ["xl/worksheets/sheet1.xml"])
        with zipfile.ZipFile(r) as a, zipfile.ZipFile(out) as b:
            self.assertEqual(a.read("xl/vbaProject.bin"), b.read("xl/vbaProject.bin"))
            self.assertEqual(a.read("xl/styles.xml"), b.read("xl/styles.xml"))
            self.assertEqual([i.filename for i in a.infolist()], [i.filename for i in b.infolist()])
        wb = openpyxl.load_workbook(out)
        self.assertEqual(wb["SFC101"]["F3"].value, datetime.datetime(2026, 9, 10))
        self.assertEqual(wb["SFC101"]["F3"].number_format, "dd/mm/yyyy")
        self.assertEqual(wb["SFC101"]["F4"].value, datetime.datetime(2026, 9, 9))

    def test_texto_a_fecha_agrega_estilo_de_fecha_solo_al_final(self):
        r, out, inf, res = self._aplicar([(100, "15/09/2026", "AB1")], idx(("AB1", "100.00", D(2026, 9, 15))))
        self.assertEqual(sorted(res["partes_modificadas"]), ["xl/styles.xml", "xl/worksheets/sheet1.xml"])
        self.assertIn("agrega xf", res["estilo"])
        wb = openpyxl.load_workbook(out)
        self.assertEqual(wb["SFC101"]["F3"].value, datetime.datetime(2026, 9, 15))
        self.assertTrue(wb["SFC101"]["F3"].is_date)
        # estilos previos intactos: prefijo identico
        with zipfile.ZipFile(r) as a, zipfile.ZipFile(out) as b:
            xa = X._xf_lista(a.read("xl/styles.xml").decode())[1]
            xb = X._xf_lista(b.read("xl/styles.xml").decode())[1]
            self.assertEqual(xb[:len(xa)], xa)
            self.assertEqual(len(xb), len(xa) + 1)

    def test_texto_dd_mm_yy_se_guarda_como_fecha_excel_real(self):
        r, inf = self.analizar([(100, "15/09/26", "AB1")], idx(("AB1", "100.00", D(2026, 9, 15))))
        out = self.ruta("salida.xlsm")
        res = c5.aplicar(r, out, inf)
        self.assertEqual(res["cambios"][0]["xml_despues"].count("<v>46280</v>"), 1)
        self.assertNotIn("t=", res["cambios"][0]["xml_despues"])       # numero, no texto
        wb = openpyxl.load_workbook(out)
        self.assertEqual(wb["SFC101"]["F3"].value, datetime.datetime(2026, 9, 15))
        self.assertTrue(wb["SFC101"]["F3"].is_date)
        prob, nuevo = c5.reanalizar_y_comparar(out, idx(("AB1", "100.00", D(2026, 9, 15))), "tiquipaya", inf, fecha_cierre=D(2026, 9, 15))
        self.assertEqual((prob, nuevo["plan"], nuevo["resumen"]), ([], [], {c5.CORRECTA: 1}))

    def test_sin_voucher_se_guarda_fecha_real_y_segunda_pasada_no_escribe(self):
        r, inf = self.analizar([(100, "24/09/26", "SIN-VOUCHER")], {})
        out = self.ruta("salida.xlsm")
        res = c5.aplicar(r, out, inf)
        self.assertTrue(res["escrito"])
        wb = openpyxl.load_workbook(out)
        self.assertEqual(wb["SFC101"]["F3"].value, datetime.datetime(2026, 9, 24))
        self.assertTrue(wb["SFC101"]["F3"].is_date)
        prob, nuevo = c5.reanalizar_y_comparar(out, {}, "tiquipaya", inf, fecha_cierre=D(2026, 9, 15))
        self.assertEqual((prob, nuevo["plan"]), ([], []))                     # nada mas que normalizar
        res2 = c5.aplicar(out, self.ruta("otra.xlsm"), nuevo)
        self.assertFalse(res2["escrito"])
        with zipfile.ZipFile(r) as a, zipfile.ZipFile(out) as b:
            self.assertEqual(a.read("xl/vbaProject.bin"), b.read("xl/vbaProject.bin"))

    def test_dos_textos_comparten_un_solo_xf_nuevo(self):
        r, out, inf, res = self._aplicar(
            [(100, "15/09/2026", "AB1"), (200, "16/09/2026", "AB2")],
            idx(("AB1", "100.00", D(2026, 9, 15)), ("AB2", "200.00", D(2026, 9, 16))))
        with zipfile.ZipFile(r) as a, zipfile.ZipFile(out) as b:
            n0 = len(X._xf_lista(a.read("xl/styles.xml").decode())[1])
            n1 = len(X._xf_lista(b.read("xl/styles.xml").decode())[1])
        self.assertEqual(n1, n0 + 1)

    def test_sin_plan_no_escribe(self):
        r, inf = self.analizar([(100, D(2026, 9, 15), "AB1")], idx(("AB1", "100.00", D(2026, 9, 15))))
        out = self.ruta("nada.xlsm")
        res = c5.aplicar(r, out, inf)
        self.assertFalse(res["escrito"])
        self.assertFalse(os.path.exists(out))

    def test_idempotencia_segunda_pasada_sin_cambios(self):
        v = idx(("AB1", "100.00", D(2026, 9, 10)), ("AB2", "200.00", D(2026, 9, 15)))
        r, out, inf, res = self._aplicar([(100, D(2026, 10, 9), "AB1"), (200, "15/09/2026", "AB2")], v)
        problemas, nuevo = c5.reanalizar_y_comparar(out, v, "tiquipaya", inf)
        self.assertEqual(problemas, [])
        self.assertEqual(nuevo["plan"], [])
        self.assertEqual(nuevo["resumen"], {c5.CORRECTA: 2})

    def test_filas_en_revision_no_se_modifican_al_aplicar(self):
        r, out, inf, res = self._aplicar(
            [(100, D(2026, 10, 9), "AB1"), (200, D(2026, 10, 9), "SINVOUCHER")],
            idx(("AB1", "100.00", D(2026, 9, 10))))
        wb = openpyxl.load_workbook(out)
        self.assertEqual(wb["SFC101"]["F3"].value, datetime.datetime(2026, 9, 10))
        self.assertEqual(wb["SFC101"]["F4"].value, datetime.datetime(2026, 10, 9))

    def test_no_sobrescribe_la_entrada(self):
        r, inf = self.analizar([(100, D(2026, 10, 9), "AB1")], idx(("AB1", "100.00", D(2026, 9, 10))))
        with self.assertRaises(X.ErrorXlsm):
            c5.aplicar(r, r, inf)

    def test_parche_rechaza_formula(self):
        xml = '<sheetData><c r="F3" s="1"><f>1+1</f><v>2</v></c></sheetData>'
        with self.assertRaises(X.ErrorXlsm):
            X.parche_celda(xml, "F3", 46275)

    def test_parche_no_confunde_f3_con_f30(self):
        xml = '<r><c r="F30" s="2"><v>1</v></c><c r="F3" s="1"><v>2</v></c></r>'
        nuevo, antes, despues = X.parche_celda(xml, "F3", 46275)
        self.assertEqual(antes, '<c r="F3" s="1"><v>2</v></c>')
        self.assertIn('<c r="F30" s="2"><v>1</v></c>', nuevo)

    def test_parche_celda_autocerrada(self):
        nuevo, antes, despues = X.parche_celda('<r><c r="F3" s="4"/></r>', "F3", 5)
        self.assertEqual(despues, '<c r="F3" s="4"><v>5</v></c>')


class TestMacros(Base):
    def test_lee_macros_y_descarta_encabezados_repetidos(self):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = mv.HOJA_MACROS
        ws.append(["Fecha", "Código de Asignación", "Créditos"])
        ws.append([datetime.datetime(2026, 9, 10), "AB1", 100])
        ws.append(["Fecha", "Código de Asignación", "Créditos"])   # encabezado repetido
        ws.append(["15/09/2026", "ab 2", 50.5])
        ws.append([datetime.datetime(2026, 9, 11), "AB1", 100])   # duplicado -> no unico
        ws.append([datetime.datetime(2026, 9, 12), None, 10])
        ws.append([datetime.datetime(2026, 9, 12), "ZZ", None])
        ws.append(["fecha rara", "AB3", 7])
        p = self.ruta("m.xlsx")
        wb.save(p)
        r = mv.leer_indice_macros(p)["indice"]
        self.assertEqual(len(r[("AB1", "100.00")]), 2)
        self.assertEqual(r[("AB2", "50.50")], [D(2026, 9, 15)])
        self.assertEqual(r[("AB3", "7.00")], [None])
        self.assertNotIn(("ZZ", "0.00"), r)


class TestToleranciaUnDia(Base):
    """Tolerancia +-1 dia CALENDARIO contra el voucher unico y valido de MACROS."""

    V = D(2026, 9, 15)

    def real(self, fecha):
        return self.una([(100, fecha, "AB1")], idx(("AB1", "100.00", self.V)))

    def texto(self, txt):
        return self.una([(100, txt, "AB1")], idx(("AB1", "100.00", self.V)))

    # ---- fecha Excel real ---------------------------------------------------
    def test_real_igualdad_exacta_correcta_sin_hallazgo(self):
        f = self.real(D(2026, 9, 15))
        self.assertEqual((f["clase"], f["accion"]), (c5.CORRECTA, "NINGUNA"))

    def test_real_menos_1_dia_es_aceptable_sin_cambiar_nada(self):
        f = self.real(D(2026, 9, 14))
        self.assertEqual((f["clase"], f["accion"], f["motivo"], f["fecha_nueva"]),
                         (c5.DENTRO_TOLERANCIA, "NINGUNA", "FECHA_DENTRO_TOLERANCIA_MACROS_1_DIA", None))
        self.assertEqual((f["fecha_cierre"], f["fecha_macros"]), ("14/09/2026", "15/09/2026"))

    def test_real_mas_1_dia_es_aceptable_sin_cambiar_nada(self):
        f = self.real(D(2026, 9, 16))
        self.assertEqual((f["clase"], f["accion"], f["fecha_nueva"]), (c5.DENTRO_TOLERANCIA, "NINGUNA", None))
        self.assertEqual((f["fecha_cierre"], f["fecha_macros"]), ("16/09/2026", "15/09/2026"))

    def test_real_menos_2_dias_es_revision_sin_corregir(self):
        f = self.real(D(2026, 9, 13))
        self.assertEqual((f["clase"], f["accion"], f["tipo_revision"]), (c5.REQUIERE_REVISION, "NINGUNA", c5.CONFLICTO))

    def test_real_mas_2_dias_es_revision_sin_corregir(self):
        f = self.real(D(2026, 9, 17))
        self.assertEqual((f["clase"], f["accion"], f["tipo_revision"]), (c5.REQUIERE_REVISION, "NINGUNA", c5.CONFLICTO))

    def test_tolerancia_cruza_fin_de_mes_y_de_anio(self):
        v = idx(("AB1", "100.00", D(2026, 10, 1)))
        self.assertEqual(self.una([(100, D(2026, 9, 30), "AB1")], v)["clase"], c5.DENTRO_TOLERANCIA)
        v = idx(("AB1", "100.00", D(2027, 1, 1)))
        self.assertEqual(self.una([(100, D(2026, 12, 31), "AB1")], v)["clase"], c5.DENTRO_TOLERANCIA)
        self.assertEqual(self.una([(100, D(2026, 12, 30), "AB1")], v)["clase"], c5.REQUIERE_REVISION)

    def test_tolerancia_es_por_dias_calendario_no_por_horas(self):
        # 15/09 23:59 vs voucher 15/09: mismo dia calendario aunque haya horas
        wb_dias = X.fecha_a_serial(D(2026, 9, 15))
        r = self.ruta("h.xlsm")
        hacer_cierre(r, [(100, D(2026, 9, 15), "AB1")])
        # reescribe la celda F3 con serial fraccionario: 16/09 00:30 => dia calendario 16 => +1
        with zipfile.ZipFile(r) as z:
            xml = z.read("xl/worksheets/sheet1.xml").decode()
        import re as _re
        m = _re.search(r'<c r="F3"([^>]*?)>.*?</c>', xml, _re.S)
        nuevo = '<c r="F3"%s><v>%s</v></c>' % (m.group(1), wb_dias + 1 + 0.02)
        X.reescribir_zip(r, self.ruta("h2.xlsm"), {"xl/worksheets/sheet1.xml": (xml[:m.start()] + nuevo + xml[m.end():]).encode()})
        inf = c5.analizar(self.ruta("h2.xlsm"), idx(("AB1", "100.00", D(2026, 9, 15))), "tiquipaya", fecha_cierre=D(2026, 9, 15))
        f = inf["filas"][0]
        self.assertEqual((f["clase"], f["accion"], f["fecha_cierre"]), (c5.DENTRO_TOLERANCIA, "NINGUNA", "16/09/2026"))
        # +2 dias calendario con solo 1 dia y algo de horas: sigue siendo revision
        nuevo = '<c r="F3"%s><v>%s</v></c>' % (m.group(1), wb_dias + 2 + 0.5)
        X.reescribir_zip(r, self.ruta("h3.xlsm"), {"xl/worksheets/sheet1.xml": (xml[:m.start()] + nuevo + xml[m.end():]).encode()})
        f = c5.analizar(self.ruta("h3.xlsm"), idx(("AB1", "100.00", D(2026, 9, 15))), "tiquipaya", fecha_cierre=D(2026, 9, 15))["filas"][0]
        self.assertEqual((f["clase"], f["accion"]), (c5.REQUIERE_REVISION, "NINGUNA"))

    def test_la_inversion_ddmm_sigue_normalizandose(self):
        # 09/10 vs voucher 10/09 (diferencia grande): regla de inversion previa, intacta
        f = self.una([(100, D(2026, 10, 9), "AB1")], idx(("AB1", "100.00", D(2026, 9, 10))))
        self.assertEqual((f["clase"], f["fecha_nueva"]), (c5.NORMALIZAR_INVERSION, D(2026, 9, 10)))

    # ---- texto -------------------------------------------------------------
    def test_texto_igualdad_exacta_se_convierte(self):
        f = self.texto("15/09/2026")
        self.assertEqual((f["clase"], f["fecha_nueva"]), (c5.CONVERTIR_TEXTO, self.V))

    def test_texto_menos_1_dia_se_convierte_conservando_el_valor(self):
        f = self.texto("14/09/2026")
        self.assertEqual((f["clase"], f["accion"], f["fecha_nueva"], f["motivo"]),
                         (c5.CONVERTIR_TEXTO_TOLERANCIA, "CONVERTIR", D(2026, 9, 14), "FECHA_DENTRO_TOLERANCIA_MACROS_1_DIA"))
        self.assertEqual((f["fecha_cierre"], f["fecha_macros"]), ("14/09/2026", "15/09/2026"))

    def test_texto_mas_1_dia_se_convierte_conservando_el_valor_y_2_digitos(self):
        for txt, esperado in (("16/09/2026", D(2026, 9, 16)), ("16/09/26", D(2026, 9, 16)), ("16/9/26", D(2026, 9, 16))):
            f = self.texto(txt)
            self.assertEqual((f["clase"], f["fecha_nueva"]), (c5.CONVERTIR_TEXTO_TOLERANCIA, esperado), txt)

    def test_texto_a_2_dias_no_se_corrige(self):
        for txt in ("13/09/2026", "17/09/2026", "17/09/26", "13/09/26"):
            f = self.texto(txt)
            self.assertEqual((f["clase"], f["accion"], f["motivo"]), (c5.REQUIERE_REVISION, "NINGUNA", "TEXTO_DISTINTO_A_VOUCHER"), txt)

    def test_texto_tolerancia_se_guarda_fecha_real_con_el_mismo_valor(self):
        r, inf = self.analizar([(100, "14/09/26", "AB1")], idx(("AB1", "100.00", self.V)))
        out = self.ruta("salida.xlsm")
        res = c5.aplicar(r, out, inf)
        self.assertTrue(res["escrito"])
        wb = openpyxl.load_workbook(out)
        self.assertEqual(wb["SFC101"]["F3"].value, datetime.datetime(2026, 9, 14))   # NO 15/09
        self.assertTrue(wb["SFC101"]["F3"].is_date)
        prob, nuevo = c5.reanalizar_y_comparar(out, idx(("AB1", "100.00", self.V)), "tiquipaya", inf, fecha_cierre=D(2026, 9, 15))
        self.assertEqual((prob, nuevo["plan"], nuevo["resumen"]), ([], [], {c5.DENTRO_TOLERANCIA: 1}))

    def test_real_dentro_de_tolerancia_no_genera_plan_ni_escritura(self):
        r, inf = self.analizar([(100, D(2026, 9, 14), "AB1")], idx(("AB1", "100.00", self.V)))
        self.assertEqual(inf["plan"], [])
        self.assertFalse(c5.aplicar(r, self.ruta("x.xlsm"), inf)["escrito"])

    # ---- sin voucher / duplicado / invalido ----------------------------------
    def test_voucher_inexistente_mantiene_regla_sin_voucher(self):
        f = self.una([(100, "14/09/26", "AB1")], {})
        self.assertEqual((f["clase"], f["fecha_nueva"], f["motivo"]),
                         (c5.CONVERTIR_TEXTO_SIN_VOUCHER, D(2026, 9, 14), "FECHA_NORMALIZADA_SIN_VOUCHER_MACROS"))
        f = self.una([(100, D(2026, 9, 14), "AB1")], {})
        self.assertEqual((f["clase"], f["accion"]), (c5.REQUIERE_REVISION, "NINGUNA"))

    def test_voucher_duplicado_es_revision_manual_aunque_este_a_1_dia(self):
        v = idx(("AB1", "100.00", self.V), ("AB1", "100.00", D(2026, 9, 14)))
        for valor in (D(2026, 9, 14), "14/09/26", D(2026, 9, 15)):
            f = self.una([(100, valor, "AB1")], v)
            self.assertEqual((f["clase"], f["accion"]), (c5.REQUIERE_REVISION, "NINGUNA"), valor)
            self.assertTrue(f["motivo"].startswith("VOUCHER_NO_UNICO"))

    def test_voucher_con_fecha_invalida_es_revision_manual(self):
        f = self.una([(100, "14/09/26", "AB1")], idx(("AB1", "100.00", None)))
        self.assertEqual((f["clase"], f["motivo"]), (c5.REQUIERE_REVISION, "VOUCHER_SIN_FECHA_VALIDA"))

    def test_fecha_invalida_o_imposible_no_se_toca_con_o_sin_voucher(self):
        con = idx(("AB1", "100.00", self.V))
        for txt in ("05/0/2026", "31/02/2026", "15/13/26", "15/09/25"):
            for indice in (con, {}):
                f = self.una([(100, txt, "AB1")], indice)
                self.assertEqual((f["clase"], f["accion"]), (c5.REQUIERE_REVISION, "NINGUNA"), (txt, bool(indice)))


REAL = r"C:\Users\PC\Desktop\prueba_auditor"


@unittest.skipUnless(os.path.exists(os.path.join(REAL, "ORIGINAL_INTACTO_referencia.xlsm")), "copias reales locales no disponibles")
class TestCopiaReal(Base):
    def test_cierre_09_09_2026_tiquipaya(self):
        cierre = os.path.join(REAL, "ORIGINAL_INTACTO_referencia.xlsm")
        ev = mv.leer_indice_macros(os.path.join(REAL, "MACROS SEPTIEMBRE.xlsm"))
        inf = c5.analizar(cierre, ev["indice"], "tiquipaya")
        self.assertEqual(inf["resumen"], {c5.CORRECTA: 2, c5.NORMALIZAR_INVERSION: 1})
        out = self.ruta("real.xlsm")
        res = c5.aplicar(cierre, out, inf)
        self.assertEqual(res["partes_modificadas"], ["xl/worksheets/sheet1.xml"])
        self.assertEqual(res["cambios"][0]["xml_despues"], '<c r="F4" s="15"><v>46275</v></c>')
        with zipfile.ZipFile(cierre) as a, zipfile.ZipFile(out) as b:
            self.assertEqual(a.read("xl/vbaProject.bin"), b.read("xl/vbaProject.bin"))
        prob, nuevo = c5.reanalizar_y_comparar(out, ev["indice"], "tiquipaya", inf)
        self.assertEqual((prob, nuevo["plan"]), ([], []))


if __name__ == "__main__":
    unittest.main()
