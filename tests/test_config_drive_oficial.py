"""test_config_drive_oficial.py — Aislamiento de destinos Google Drive por
CAJA en la publicación oficial (config_drive_oficial.py), espejo Python del
nodo n8n "RESOLVER - Destinos Drive por caja" probado en
tests_v3/n8n_publicacion_oficial/test_logic_reference.js.

No toca Drive real, no crea carpetas, no modifica credenciales: solo
prueba la función de resolución/validación en memoria.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config_drive_oficial as cfgd  # noqa: E402

_TIQ_HISTORICOS = {
    "entrada": "1ntneoE3MI-25FyPXUymXEvIJmnaZWyJ1",
    "sap": "1mid4gUHnCmZbISlsAYMwWta3RudTSE13",
    "resultado": "16Z7Uhf-NgiZ6YuqWLnReaIozRIiOg5HO",
    "procesados": "1BkNC6lnonMM7YeWDKck-TM8WTyY2BJJP",
    "marker": "1i8wXRM-2yiH5N3SPOEd4eEqZnizCeCGu",
}


class TestResolverDestinosDrive(unittest.TestCase):

    def test_1_tiquipaya_resuelve_destinos_historicos(self):
        self.assertEqual(cfgd.resolver_destinos_drive("tiquipaya", entorno={}),
                          _TIQ_HISTORICOS)

    def test_1b_default_sin_caja_igual_a_tiquipaya(self):
        self.assertEqual(cfgd.resolver_destinos_drive(entorno={}), _TIQ_HISTORICOS)

    def test_2_america_resuelve_destinos_distintos_con_env_completo(self):
        entorno = {
            "DRIVE_ENTRADA_AME": "ame-entrada-1",
            "DRIVE_SAP_AME": "ame-sap-1",
            "DRIVE_RESULTADO_AME": "ame-resultado-1",
            "DRIVE_PROCESADOS_AME": "ame-procesados-1",
            "DRIVE_MARKER_AME": "ame-marker-1",
        }
        destinos_ame = cfgd.resolver_destinos_drive("america", entorno=entorno)
        destinos_tiq = cfgd.resolver_destinos_drive("tiquipaya", entorno={})
        for clave in cfgd.DESTINOS:
            self.assertNotEqual(destinos_ame[clave], destinos_tiq[clave])

    def test_3_america_no_puede_usar_destino_tiq_falla_cerrado(self):
        """Sin DRIVE_*_AME configuradas, América JAMAS hereda el folder de
        TIQUIPAYA: falla cerrado en vez de caer al default de otra caja."""
        with self.assertRaises(ValueError) as ctx:
            cfgd.resolver_destinos_drive("america", entorno={})
        self.assertIn("DRIVE_AME_PENDIENTE", str(ctx.exception))

    def test_3b_america_con_variables_parciales_tambien_falla_cerrado(self):
        entorno = {"DRIVE_ENTRADA_AME": "ame-entrada-1"}
        with self.assertRaises(ValueError):
            cfgd.resolver_destinos_drive("america", entorno=entorno)

    def test_4_tiquipaya_no_puede_usar_destino_ame(self):
        """Aunque el entorno traiga variables DRIVE_*_AME, TIQUIPAYA nunca
        las lee: sigue resolviendo (o su override _TIQ, o) su default."""
        entorno = {"DRIVE_ENTRADA_AME": "ame-entrada-1", "DRIVE_ENTRADA_TIQ": "override-tiq"}
        destinos = cfgd.resolver_destinos_drive("tiquipaya", entorno=entorno)
        self.assertEqual(destinos["entrada"], "override-tiq")
        self.assertNotEqual(destinos["entrada"], "ame-entrada-1")

    def test_caja_desconocida_falla_cerrado(self):
        with self.assertRaises(ValueError):
            cfgd.resolver_destinos_drive("brasil", entorno={})

    def test_override_tiq_via_env_no_rompe_default(self):
        entorno = {"DRIVE_SAP_TIQ": "sap-override"}
        destinos = cfgd.resolver_destinos_drive("tiquipaya", entorno=entorno)
        self.assertEqual(destinos["sap"], "sap-override")
        self.assertEqual(destinos["entrada"], _TIQ_HISTORICOS["entrada"])


class TestValidarPrefijoArchivo(unittest.TestCase):

    def test_5a_prefijo_tiq_publicandose_como_america_falla_cerrado(self):
        with self.assertRaises(ValueError) as ctx:
            cfgd.validar_prefijo_archivo("america", "SAP_TIQ_10-09-2026.xlsx")
        self.assertIn("PREFIJO_CAJA_NO_COINCIDE", str(ctx.exception))

    def test_5b_prefijo_ame_publicandose_como_tiquipaya_falla_cerrado(self):
        with self.assertRaises(ValueError) as ctx:
            cfgd.validar_prefijo_archivo("tiquipaya", "RESULTADO_AME_10-09-2026.json")
        self.assertIn("PREFIJO_CAJA_NO_COINCIDE", str(ctx.exception))

    def test_5c_variantes_de_prefijo_por_caja(self):
        for nombre in ("SAP_TIQ_10-09-2026.xlsx", "SAP_GLOBAL_TIQ_SEPTIEMBRE_2026.xlsx",
                       "RESULTADO_TIQ_10-09-2026.json"):
            with self.assertRaises(ValueError):
                cfgd.validar_prefijo_archivo("america", nombre)
        for nombre in ("SAP_AME_10-09-2026.xlsx", "SAP_GLOBAL_AME_SEPTIEMBRE_2026.xlsx",
                       "RESULTADO_AME_10-09-2026.json"):
            with self.assertRaises(ValueError):
                cfgd.validar_prefijo_archivo("tiquipaya", nombre)

    def test_prefijo_propio_no_lanza(self):
        cfgd.validar_prefijo_archivo("tiquipaya", "SAP_TIQ_10-09-2026.xlsx")
        cfgd.validar_prefijo_archivo("america", "SAP_AME_10-09-2026.xlsx")

    def test_nombre_sin_prefijo_reconocido_no_es_responsabilidad_de_este_validador(self):
        cfgd.validar_prefijo_archivo("tiquipaya", "CIERRE 10-09-2026.xlsm")
        cfgd.validar_prefijo_archivo("america", "CIERRE 10-09-2026.xlsm")

    def test_nombre_vacio_no_lanza(self):
        cfgd.validar_prefijo_archivo("tiquipaya", None)
        cfgd.validar_prefijo_archivo("america", "")


_MENSUAL_TIQ_HISTORICOS = {
    "controles": "1yZI_OCuYOAILg8E6uT-bAmkQtW-XB-qB",
    "global": "1KREzDpgptWRwuArA1qYco49rplOEeeNU",
    "control1": "1oOcwIgq_9uU9eRLV7z36zBjdBS-hBlRk",
    "control3": "15IYQDdpyBwrZTNS-qU8VZa47sVz1ziV_",
    "sap": "1mid4gUHnCmZbISlsAYMwWta3RudTSE13",
}


class TestResolverDestinosDriveMensual(unittest.TestCase):
    """Cierre MENSUAL (GLOBAL + CONTROL1 + CONTROL3) -- espejo Python de los
    nodos n8n "RESOLVER carpeta SAP oficial" / "RESOLVER control1 (periodo y
    carpetas)" / "RESOLVER control3 (periodo y carpetas)"."""

    def test_1_tiquipaya_resuelve_los_4_folder_ids_historicos_exactos(self):
        self.assertEqual(cfgd.resolver_destinos_drive_mensual("tiquipaya", entorno={}),
                          _MENSUAL_TIQ_HISTORICOS)

    def test_1b_default_sin_caja_igual_a_tiquipaya(self):
        self.assertEqual(cfgd.resolver_destinos_drive_mensual(entorno={}), _MENSUAL_TIQ_HISTORICOS)

    def test_2_sap_mensual_reutiliza_el_mismo_destino_sap_de_la_publicacion_diaria(self):
        entorno = {"DRIVE_SAP_TIQ": "sap-override-compartido"}
        mensual = cfgd.resolver_destinos_drive_mensual("tiquipaya", entorno=entorno)
        diario = cfgd.resolver_destinos_drive("tiquipaya", entorno=entorno)
        self.assertEqual(mensual["sap"], diario["sap"])
        self.assertEqual(mensual["sap"], "sap-override-compartido")

    def test_3_america_sin_variables_falla_cerrado_y_nunca_usa_ids_de_tiq(self):
        with self.assertRaises(ValueError) as ctx:
            cfgd.resolver_destinos_drive_mensual("america", entorno={})
        self.assertIn("DRIVE_AME_PENDIENTE", str(ctx.exception))

    def test_3b_america_con_los_4_destinos_pero_sin_sap_tambien_falla_cerrado(self):
        entorno = {
            "DRIVE_CONTROLES_AME": "ame-controles-1",
            "DRIVE_GLOBAL_AME": "ame-global-1",
            "DRIVE_CONTROL1_AME": "ame-control1-1",
            "DRIVE_CONTROL3_AME": "ame-control3-1",
        }
        with self.assertRaises(ValueError) as ctx:
            cfgd.resolver_destinos_drive_mensual("america", entorno=entorno)
        self.assertIn("DRIVE_AME_PENDIENTE", str(ctx.exception))
        self.assertIn("DRIVE_SAP_AME", str(ctx.exception))

    def test_4_america_con_las_5_variables_resuelve_distinto_de_tiq_y_nunca_hereda_tiq(self):
        entorno = {
            "DRIVE_CONTROLES_AME": "ame-controles-1",
            "DRIVE_GLOBAL_AME": "ame-global-1",
            "DRIVE_CONTROL1_AME": "ame-control1-1",
            "DRIVE_CONTROL3_AME": "ame-control3-1",
            "DRIVE_SAP_AME": "ame-sap-1",
        }
        destinos_ame = cfgd.resolver_destinos_drive_mensual("america", entorno=entorno)
        for clave, valor in destinos_ame.items():
            self.assertNotIn(valor, _MENSUAL_TIQ_HISTORICOS.values(),
                              f"AMERICA nunca debe heredar un folder ID de TIQUIPAYA (clave={clave})")
        self.assertEqual(destinos_ame, {
            "controles": "ame-controles-1", "global": "ame-global-1",
            "control1": "ame-control1-1", "control3": "ame-control3-1", "sap": "ame-sap-1",
        })

    def test_caja_desconocida_falla_cerrado(self):
        with self.assertRaises(ValueError):
            cfgd.resolver_destinos_drive_mensual("brasil", entorno={})


if __name__ == "__main__":
    unittest.main()
