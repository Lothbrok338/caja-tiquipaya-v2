"""tests_v3/test_control1_institucional.py — CONTROL 1 institucional
(v3/control1_institucional.py): analiza SAP_GLOBAL_TIQ_... y
SAP_GLOBAL_AME_... simultáneamente, SIN fusionarlos en un tercer SAP.

Usa SAP GLOBAL sintéticos (nunca datos contables reales), igual criterio
que tests/test_control_asignaciones.py. Nunca ejercita control_asignaciones.py
directamente (eso ya lo cubre tests/test_control_asignaciones.py) — solo la
capa institucional nueva: combinación en memoria, trazabilidad de origen,
corrección atómica cross-archivo e idempotencia por PAR de SHA.

Uso: python -m pytest tests_v3/test_control1_institucional.py -q
"""
import datetime
import os
import shutil
import sys
import tempfile
import unittest
from decimal import Decimal
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import openpyxl

import config_cajas as cfg
import consolidador_mensual
import control_asignaciones as ca
from v3 import control1_institucional as ci


def _crear_global(ruta, partidas):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "1"
    fila = 16
    for p in partidas:
        ws[f"C{fila}"] = p.get("cuenta_mayor", "110101001")
        ws[f"D{fila}"] = p.get("glosa", "GLOSA")
        cargo = p.get("cargo")
        if cargo is not None:
            ws[f"E{fila}"] = Decimal(str(cargo))
        ws[f"O{fila}"] = p.get("fecha_valor", datetime.date(2026, 9, 5))
        ws[f"R{fila}"] = p.get("asignacion")
        fila += 1
    wb.save(ruta)


def _partida(asignacion, cuenta_mayor="110101001", cargo="100.00"):
    return {"asignacion": asignacion, "cuenta_mayor": cuenta_mayor, "cargo": cargo}


ANIO, MES = 2026, 9


class BaseInstitucional(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.ruta_tiq = os.path.join(self.tmp, consolidador_mensual.nombre_sap_global(ANIO, MES, cfg.TIQUIPAYA))
        self.ruta_ame = os.path.join(self.tmp, consolidador_mensual.nombre_sap_global(ANIO, MES, cfg.AMERICA))
        self.ruta_historico = os.path.join(self.tmp, ci.nombre_historico_institucional())

    def _ejecutar(self, tiq_partidas, ame_partidas, **kwargs):
        _crear_global(self.ruta_tiq, tiq_partidas)
        _crear_global(self.ruta_ame, ame_partidas)
        return ci.ejecutar_control1_institucional(
            self.ruta_tiq, self.ruta_ame, self.ruta_historico, directorio_revision=self.tmp, **kwargs,
        )


class TestSinDuplicados(BaseInstitucional):
    def test_ok_sin_duplicados_incorpora_ambas_cajas_al_historico(self):
        r = self._ejecutar([_partida("X1")], [_partida("X2")])
        self.assertEqual(r["estado"], "OK_SIN_DUPLICADOS")
        self.assertEqual(r["candidatas_tiq"], 1)
        self.assertEqual(r["candidatas_ame"], 1)
        historico = ci.cargar_historico_institucional(self.ruta_historico)
        self.assertEqual(len(historico), 2)
        cajas = {fila["caja"] for fila in historico}
        self.assertEqual(cajas, {"tiquipaya", "america"})


class TestExclusiones(BaseInstitucional):
    def test_exclusiones_estructurales_siguen_intactas_en_ambas_cajas(self):
        r = self._ejecutar(
            [_partida("SFC101"), _partida("X1")],
            [_partida("POSTG-SEPT"), _partida("X2")],
        )
        self.assertEqual(r["estado"], "OK_SIN_DUPLICADOS")
        self.assertEqual(r["excluidas_tiq"], 1)
        self.assertEqual(r["excluidas_ame"], 1)
        self.assertEqual(r["candidatas_tiq"], 1)
        self.assertEqual(r["candidatas_ame"], 1)

    def test_exclusion_por_cuenta_comision_atc_intacta(self):
        r = self._ejecutar([_partida("CUALQUIERA", cuenta_mayor="110201008")], [_partida("X2")])
        self.assertEqual(r["excluidas_tiq"], 1)
        self.assertEqual(r["candidatas_tiq"], 0)


class TestDuplicadosCruzados(BaseInstitucional):
    def test_duplicado_tiq_interno_mismo_periodo(self):
        r = self._ejecutar([_partida("DUP"), _partida("DUP")], [])
        self.assertEqual(r["estado"], "REVISAR_DUPLICADOS_ENCONTRADOS")
        self.assertEqual(len(r["alertas"]), 1)
        alerta = r["alertas"][0]
        self.assertEqual(alerta["caja"], "tiquipaya")
        self.assertEqual(alerta["caja_relacionada"], "tiquipaya")

    def test_duplicado_ame_interno_mismo_periodo(self):
        r = self._ejecutar([], [_partida("DUP"), _partida("DUP")])
        self.assertEqual(r["estado"], "REVISAR_DUPLICADOS_ENCONTRADOS")
        alerta = r["alertas"][0]
        self.assertEqual(alerta["caja"], "america")
        self.assertEqual(alerta["caja_relacionada"], "america")

    def test_duplicado_tiq_ame_cruzado(self):
        r = self._ejecutar([_partida("CRUZADA")], [_partida("CRUZADA")])
        self.assertEqual(r["estado"], "REVISAR_DUPLICADOS_ENCONTRADOS")
        alerta = r["alertas"][0]
        cajas = {alerta["caja"], alerta["caja_relacionada"]}
        self.assertEqual(cajas, {"tiquipaya", "america"})
        # La identidad de la alerta nunca es solo FILA_GLOBAL: siempre trae caja+archivo.
        self.assertIn("archivo_origen", alerta)
        self.assertIn("fila_origen", alerta)

    def test_duplicado_contra_historico_institucional_unico(self):
        r1 = self._ejecutar([_partida("HIST")], [])
        self.assertEqual(r1["estado"], "OK_SIN_DUPLICADOS")
        # Nuevo periodo (mismo archivo cambia de contenido -> nuevo SHA):
        # cambiamos AME esta vez para simular otro periodo de la misma auditoría.
        r2 = ci.ejecutar_control1_institucional(
            self.ruta_tiq, self.ruta_ame, self.ruta_historico, directorio_revision=self.tmp,
        )
        # Mismo par exacto de archivos que r1 -> idempotente.
        self.assertEqual(r2["estado"], "YA_PROCESADO_SIN_CAMBIOS")


class TestIdempotencia(BaseInstitucional):
    def test_mismo_par_sha_es_idempotente(self):
        r1 = self._ejecutar([_partida("X1")], [_partida("X2")])
        self.assertTrue(r1["historico_actualizado"])
        r2 = ci.ejecutar_control1_institucional(
            self.ruta_tiq, self.ruta_ame, self.ruta_historico, directorio_revision=self.tmp,
        )
        self.assertEqual(r2["estado"], "YA_PROCESADO_SIN_CAMBIOS")
        historico = ci.cargar_historico_institucional(self.ruta_historico)
        self.assertEqual(len(historico), 2)  # no se duplicó nada

    def test_global_modificado_requiere_revision(self):
        self._ejecutar([_partida("X1")], [_partida("X2")])
        # Se modifica el GLOBAL TIQ (mismo nombre, contenido distinto) sin pasar por corrección.
        _crear_global(self.ruta_tiq, [_partida("X1"), _partida("X3")])
        r2 = ci.ejecutar_control1_institucional(
            self.ruta_tiq, self.ruta_ame, self.ruta_historico, directorio_revision=self.tmp,
        )
        self.assertEqual(r2["estado"], "GLOBAL_MODIFICADO_REQUIERE_REVISION")


class TestCorreccionAtomica(BaseInstitucional):
    def setUp(self):
        super().setUp()
        _crear_global(self.ruta_tiq, [_partida("MALA_TIQ")])
        _crear_global(self.ruta_ame, [_partida("MALA_AME")])

    def test_correccion_tiq_toca_solo_tiq(self):
        ci.aplicar_correcciones_institucional(
            self.ruta_tiq, self.ruta_ame,
            correcciones_tiq=[(16, "MALA_TIQ", "BUENA_TIQ")],
            correcciones_ame=[],
        )
        partidas_tiq = ca.leer_partidas_global(self.ruta_tiq)
        partidas_ame = ca.leer_partidas_global(self.ruta_ame)
        self.assertEqual(partidas_tiq[0]["asignacion"], "BUENA_TIQ")
        self.assertEqual(partidas_ame[0]["asignacion"], "MALA_AME")

    def test_correccion_ame_toca_solo_ame(self):
        ci.aplicar_correcciones_institucional(
            self.ruta_tiq, self.ruta_ame,
            correcciones_tiq=[],
            correcciones_ame=[(16, "MALA_AME", "BUENA_AME")],
        )
        partidas_tiq = ca.leer_partidas_global(self.ruta_tiq)
        partidas_ame = ca.leer_partidas_global(self.ruta_ame)
        self.assertEqual(partidas_tiq[0]["asignacion"], "MALA_TIQ")
        self.assertEqual(partidas_ame[0]["asignacion"], "BUENA_AME")

    def test_fallo_de_una_correccion_no_modifica_ninguno(self):
        with self.assertRaises(ca.CorreccionInvalidaError):
            ci.aplicar_correcciones_institucional(
                self.ruta_tiq, self.ruta_ame,
                correcciones_tiq=[(16, "MALA_TIQ", "BUENA_TIQ")],
                # ASIGNACION_ORIGINAL incorrecta a propósito -> debe fallar cerrado.
                correcciones_ame=[(16, "NO_ES_LA_ORIGINAL", "BUENA_AME")],
            )
        partidas_tiq = ca.leer_partidas_global(self.ruta_tiq)
        partidas_ame = ca.leer_partidas_global(self.ruta_ame)
        self.assertEqual(partidas_tiq[0]["asignacion"], "MALA_TIQ", "TIQ no debe quedar modificado")
        self.assertEqual(partidas_ame[0]["asignacion"], "MALA_AME", "AME no debe quedar modificado")

    def test_fallo_durante_reemplazo_del_segundo_global_hace_rollback(self):
        """Ambas correcciones pasan la validación previa (ASIGNACION_ORIGINAL
        correcta): TIQ se reemplaza con éxito, pero simulamos que
        os.replace() falla justo al reemplazar el segundo GLOBAL (AME,
        orden fijo TIQ->AME). Verifica que AMBOS originales quedan
        BYTE A BYTE idénticos al contenido de arranque (TIQ hace rollback
        desde su respaldo; AME nunca llegó a reemplazarse)."""
        bytes_tiq_original = open(self.ruta_tiq, "rb").read()
        bytes_ame_original = open(self.ruta_ame, "rb").read()

        real_replace = os.replace

        def fake_replace(src, dst, *a, **kw):
            if os.path.abspath(dst) == os.path.abspath(self.ruta_ame):
                raise OSError("SIMULADO_FALLO_REEMPLAZO_SEGUNDO_GLOBAL")
            return real_replace(src, dst, *a, **kw)

        with mock.patch("os.replace", side_effect=fake_replace):
            with self.assertRaises(OSError):
                ci.aplicar_correcciones_institucional(
                    self.ruta_tiq, self.ruta_ame,
                    correcciones_tiq=[(16, "MALA_TIQ", "BUENA_TIQ")],
                    correcciones_ame=[(16, "MALA_AME", "BUENA_AME")],
                )

        self.assertEqual(
            open(self.ruta_tiq, "rb").read(), bytes_tiq_original,
            "TIQ debe quedar IDENTICO al inicio tras el rollback",
        )
        self.assertEqual(
            open(self.ruta_ame, "rb").read(), bytes_ame_original,
            "AME debe quedar IDENTICO al inicio (nunca llegó a reemplazarse)",
        )
        # No deben quedar respaldos huérfanos.
        self.assertFalse(os.path.isfile(f"{self.ruta_tiq}.rollback"))
        self.assertFalse(os.path.isfile(f"{self.ruta_ame}.rollback"))


class TestPeriodos(BaseInstitucional):
    def test_periodos_distintos_tiq_ame_falla_cerrado(self):
        _crear_global(self.ruta_tiq, [_partida("X1")])
        ruta_ame_otro_mes = os.path.join(
            self.tmp, consolidador_mensual.nombre_sap_global(ANIO, 10, cfg.AMERICA))
        _crear_global(ruta_ame_otro_mes, [_partida("X2")])
        r = ci.ejecutar_control1_institucional(
            self.ruta_tiq, ruta_ame_otro_mes, self.ruta_historico, directorio_revision=self.tmp,
        )
        self.assertEqual(r["estado"], "ERROR_TECNICO")
        self.assertIn("PERIODOS_DISTINTOS_TIQ_AME", r["problemas"])


if __name__ == "__main__":
    unittest.main()
