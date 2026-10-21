import hashlib
import json
import os
import re
import sys
import tempfile
import unittest
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "powerautomate"))

import build_zip  # noqa: E402
from flows.flow00_smoke import FLOW  # noqa: E402


def _sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


class TestZip(unittest.TestCase):
    def _build(self, d):
        build_zip.main(["--version", "9.9.9", "--out", d])
        return [os.path.join(d, f) for f in sorted(os.listdir(d))]

    def test_build_reproducible(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            ra, rb = self._build(a), self._build(b)
            self.assertEqual([_sha(x) for x in ra], [_sha(x) for x in rb])

    def test_contenido_valido_y_sin_secretos(self):
        with tempfile.TemporaryDirectory() as d:
            for ruta in self._build(d):
                with zipfile.ZipFile(ruta) as z:
                    self.assertIsNone(z.testzip())
                    for n in z.namelist():
                        self.assertNotIn("\\", n)
                        txt = z.read(n).decode("utf-8")
                        if n.endswith(".json"):
                            json.loads(txt)
                        self.assertFalse(re.search(r"(?i)api[_-]?key\s*[\"']?\s*[:=]\s*[\"'][^\"'@]{6,}", txt), n)

    def test_legacy_estructura(self):
        with tempfile.TemporaryDirectory() as d:
            ruta = [r for r in self._build(d) if r.endswith("_legacy.zip")][0]
            with zipfile.ZipFile(ruta) as z:
                m = json.loads(z.read("manifest.json"))
                (fid, res), = m["resources"].items()
                self.assertEqual(res["type"], "Microsoft.Flow/flows")
                dj = json.loads(z.read(f"Microsoft.Flow/flows/{fid}/definition.json"))
                self.assertEqual(dj["name"], fid)
                self.assertIn("HTTP_ping", dj["properties"]["definition"]["actions"])
                self.assertEqual(dj["properties"]["connectionReferences"], {})

    def test_validador_detecta_referencia_rota(self):
        d = FLOW["definition"]("legacy")
        d["actions"]["Parse_JSON"]["inputs"]["content"] = "@body('NoExiste')"
        with self.assertRaises(ValueError):
            build_zip.validar_definicion(d, "x")

    def test_validador_detecta_runafter_roto(self):
        d = FLOW["definition"]("legacy")
        d["actions"]["Parse_JSON"]["runAfter"] = {"Fantasma": ["Succeeded"]}
        with self.assertRaises(ValueError):
            build_zip.validar_definicion(d, "x")

    def test_validador_detecta_parametro_no_declarado(self):
        d = FLOW["definition"]("legacy")
        d["actions"]["HTTP_ping"]["inputs"]["uri"] = "@parameters('Otro')"
        with self.assertRaises(ValueError):
            build_zip.validar_definicion(d, "x")


if __name__ == "__main__":
    unittest.main()
