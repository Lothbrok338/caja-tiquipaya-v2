import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient

from api_caja.main import app

CID = "corr-12345678"


class TestApiCaja(unittest.TestCase):
    def setUp(self):
        os.environ["API_KEYS"] = "clave-a,clave-b"
        os.environ.pop("CAJAS_HABILITADAS", None)
        self.c = TestClient(app)

    def _ping(self, key="clave-a", caja="Ayacucho", cid=CID):
        h = {"X-Correlation-Id": cid}
        if key is not None:
            h["X-API-Key"] = key
        return self.c.post("/v1/ping", json={"caja": caja}, headers=h)

    def test_health_sin_auth(self):
        r = self.c.get("/v1/health")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "ok")

    def test_ping_ok_devuelve_correlation_y_caja_normalizada(self):
        r = self._ping()
        self.assertEqual(r.status_code, 200)
        j = r.json()
        self.assertEqual((j["status"], j["caja"], j["correlation_id"]), ("ok", "AYACUCHO", CID))
        self.assertEqual(r.headers["x-correlation-id"], CID)

    def test_rotacion_segunda_clave(self):
        self.assertEqual(self._ping(key="clave-b").status_code, 200)

    def test_sin_clave_o_invalida_401(self):
        self.assertEqual(self._ping(key=None).status_code, 401)
        r = self._ping(key="mala")
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.json()["codigo"], "API_KEY_INVALIDA")

    def test_sin_api_keys_configuradas_falla_cerrada(self):
        os.environ.pop("API_KEYS")
        self.assertEqual(self._ping().status_code, 503)

    def test_caja_no_habilitada_422(self):
        r = self._ping(caja="TIQUIPAYA")
        self.assertEqual(r.status_code, 422)
        self.assertEqual(r.json()["codigo"], "CAJA_NO_HABILITADA")

    def test_correlation_invalido_se_reemplaza(self):
        r = self._ping(cid="x")
        self.assertEqual(r.status_code, 200)
        self.assertNotEqual(r.json()["correlation_id"], "x")


if __name__ == "__main__":
    unittest.main()
