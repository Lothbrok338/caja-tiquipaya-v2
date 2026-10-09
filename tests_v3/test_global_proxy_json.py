"""tests_v3/test_global_proxy_json.py — /webhook/tiq-v3-dev/global SIEMPRE
devuelve un objeto JSON al navegador.

n8n 2.35.7 (responseMode "responseNode") responde HTTP 200 con cuerpo
VACÍO cuando el workflow termina sin pasar por "RESPONDER global" (bug real
de GLOBAL AME, 2026-10-09: "Respuesta no-JSON del backend (HTTP 200)").
Corre scripts/serve_v3_frontend.py REAL como subproceso contra un n8n falso
y verifica que el proxy convierte cualquier respuesta no-JSON de /global en
el sobre de error del contrato, sin tocar el resto de rutas.

Uso: python -m pytest tests_v3/test_global_proxy_json.py -q
"""
import http.server
import json
import os
import sys
import threading
import urllib.parse

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_frontend_auth import CLAVE, USUARIO, _basic_auth_header, lanzar_proxy  # noqa: E402,F401

AUTH = {"TIQ_AUTH_USERNAME": USUARIO, "TIQ_AUTH_PASSWORD": CLAVE}

_RESPUESTAS = {
    # caso: (status, content-type, cuerpo)
    "vacio": (200, "application/json", b""),
    "texto": (200, "text/plain", b"Traceback (most recent call last): boom"),
    "html": (200, "text/html", b"<html><body>error</body></html>"),
    "lista": (200, "application/json", b"[1, 2]"),
    "error_n8n": (500, "application/json", b'{"message": "Error in workflow"}'),
    "ok": (200, "application/json", json.dumps({
        "resultado": "OK", "estado": "VALIDADO_PENDIENTE_PUBLICACION",
        "ruta_global_generado": "/x/SAP_GLOBAL_AME_SEPTIEMBRE_2026.xlsx",
    }).encode("utf-8")),
    "error_python": (200, "application/json", json.dumps({
        "resultado": "ERROR", "ok": False, "estado": "ERROR_REVISAR",
        "codigo": "GLOBAL_ERROR_TECNICO", "mensaje": "PERIODO_CERRADO_CONTROL1: x", "detalle": "RuntimeError: x",
    }).encode("utf-8")),
}


class _FakeN8N(http.server.BaseHTTPRequestHandler):
    def _atender(self):
        if self.path == "/healthz/readiness":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"status": "ok"}')
            return
        length = int(self.headers.get("Content-Length", 0) or 0)
        if length:
            self.rfile.read(length)
        caso = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query).get("caso", ["ok"])[0]
        status, ctype, cuerpo = _RESPUESTAS[caso]
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)

    do_GET = _atender
    do_POST = _atender

    def log_message(self, *args, **kwargs):
        pass


@pytest.fixture()
def n8n_falso():
    servidor = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _FakeN8N)
    hilo = threading.Thread(target=servidor.serve_forever, daemon=True)
    hilo.start()
    try:
        yield f"http://127.0.0.1:{servidor.server_address[1]}"
    finally:
        servidor.shutdown()
        servidor.server_close()


def _post_global(proxy, caso, ruta="/webhook/tiq-v3-dev/global"):
    headers = dict(_basic_auth_header(USUARIO, CLAVE))
    headers["Content-Type"] = "application/json"
    body = json.dumps({"anio": 2026, "mes": 9, "caja": "america", "modo": "official"})
    return proxy.request("POST", f"{ruta}?caso={caso}", headers=headers, body=body)


def _assert_sobre(data):
    r = json.loads(data.decode("utf-8"))
    assert r["resultado"] == "ERROR"
    assert r["ok"] is False
    assert r["estado"] == "ERROR_REVISAR"
    assert r["codigo"] == "GLOBAL_ERROR_TECNICO"
    assert r["mensaje"] and r["detalle"]
    assert "Traceback" not in data.decode("utf-8")
    assert "<html" not in data.decode("utf-8")
    return r


@pytest.mark.parametrize("caso", ["vacio", "texto", "html", "lista"])
def test_global_respuesta_no_json_se_convierte_en_sobre_json(lanzar_proxy, n8n_falso, caso):
    proxy = lanzar_proxy(AUTH, n8n_origin=n8n_falso)
    status, headers, data = _post_global(proxy, caso)
    assert status == 502
    assert headers.get("Content-Type", "").startswith("application/json")
    r = _assert_sobre(data)
    if caso == "vacio":
        assert "respuesta vacia" in r["detalle"]


def test_global_error_generico_de_n8n_se_convierte_en_sobre_json(lanzar_proxy, n8n_falso):
    proxy = lanzar_proxy(AUTH, n8n_origin=n8n_falso)
    status, _, data = _post_global(proxy, "error_n8n")
    assert status == 500
    r = _assert_sobre(data)
    assert "Error in workflow" in r["detalle"]


@pytest.mark.parametrize("caso", ["ok", "error_python"])
def test_global_json_valido_pasa_intacto(lanzar_proxy, n8n_falso, caso):
    proxy = lanzar_proxy(AUTH, n8n_origin=n8n_falso)
    status, _, data = _post_global(proxy, caso)
    assert status == 200
    assert data == _RESPUESTAS[caso][2]


def test_global_sin_n8n_disponible_devuelve_sobre_json(lanzar_proxy):
    proxy = lanzar_proxy(dict(AUTH, TIQ_N8N_START_TIMEOUT_SECONDS="1"), n8n_origin="http://127.0.0.1:9")
    status, _, data = _post_global(proxy, "ok")
    assert status in (502, 503)
    _assert_sobre(data)


def test_otras_rutas_no_cambian_de_comportamiento(lanzar_proxy, n8n_falso):
    proxy = lanzar_proxy(AUTH, n8n_origin=n8n_falso)
    status, _, data = _post_global(proxy, "vacio", ruta="/webhook/tiq-v3-dev/control1")
    assert status == 200
    assert data == b""
