"""tests_v3/test_frontend_auth.py — migración Railway 2026-09.

Verifica la autenticación HTTP Basic agregada a scripts/serve_v3_frontend.py
(el único proceso público de CAJAS GABO: sirve el frontend y proxifica
/webhook/* hacia n8n). Corre el script REAL como subproceso — la misma
invocación que usa scripts/railway_entrypoint.sh — contra un n8n falso en
memoria, para demostrar con requests HTTP reales que:

  - /healthz nunca requiere auth (con o sin credenciales configuradas);
  - todo lo demás exige HTTP Basic con TIQ_AUTH_USERNAME/TIQ_AUTH_PASSWORD;
  - sin credenciales configuradas (o incompletas), el proceso arranca
    pero falla CERRADO (503) en vez de quedar abierto;
  - una request no autenticada NUNCA llega al n8n real;
  - el header Authorization nunca se reenvía a n8n;
  - no queda ninguna credencial ni el header Authorization en los logs;
  - el comportamiento existente (proxy de query string, propagación de
    errores de n8n, Cache-Control) no cambia con auth correcta.

No toca motor_tiquipaya.py, pipeline_tiquipaya.py, workflows de n8n,
Drive/Postgres ni TIQ_BLOCK_OFFICIAL_PUBLISH.

Uso: python -m pytest tests_v3/test_frontend_auth.py -q
"""
import base64
import http.client
import http.server
import json
import os
import socket
import subprocess
import sys
import threading
import time

import pytest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(RAIZ, "scripts", "serve_v3_frontend.py")

USUARIO = "gabo_test"
CLAVE = "clave-super-secreta-test-123"


def _puerto_libre():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _basic_auth_header(usuario, clave):
    token = base64.b64encode(f"{usuario}:{clave}".encode("utf-8")).decode("ascii")
    return {"Authorization": f"Basic {token}"}


def _esperar_puerto(host, puerto, timeout=10):
    limite = time.time() + timeout
    while time.time() < limite:
        try:
            with socket.create_connection((host, puerto), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.05)
    return False


class _FakeN8NHandler(http.server.BaseHTTPRequestHandler):
    """n8n falso: registra cada request recibida (para probar que las no
    autenticadas nunca llegan hasta acá) y responde 200 con eco del path,
    salvo /webhook/no-existe que responde 404 (para probar que el proxy
    propaga errores de n8n igual que antes). /healthz/readiness (el probe
    de GestorN8N, ver test_n8n_lazy_lifecycle.py) responde 200 sin
    registrarse: no es una llamada funcional al webhook."""

    def _atender(self):
        if self.path == "/healthz/readiness":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status": "ok"}')
            return
        length = int(self.headers.get("Content-Length", 0) or 0)
        body = self.rfile.read(length) if length else b""
        self.server.recibidas.append({
            "method": self.command,
            "path": self.path,
            "headers": dict(self.headers.items()),
            "body": body,
        })
        if self.path == "/webhook/no-existe":
            self.send_response(404)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"error": "no encontrado en n8n falso"}')
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"ok": True, "recibido_en": self.path}).encode("utf-8"))

    def do_GET(self):
        self._atender()

    def do_POST(self):
        self._atender()

    def log_message(self, *args, **kwargs):
        pass  # silencia stderr del n8n falso en la salida de pytest


@pytest.fixture()
def fake_n8n():
    servidor = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _FakeN8NHandler)
    servidor.recibidas = []
    hilo = threading.Thread(target=servidor.serve_forever, daemon=True)
    hilo.start()
    puerto = servidor.server_address[1]
    try:
        yield f"http://127.0.0.1:{puerto}", servidor.recibidas
    finally:
        servidor.shutdown()
        servidor.server_close()


class _ProxyProceso:
    def __init__(self, puerto, proceso):
        self.puerto = puerto
        self.proceso = proceso

    def request(self, method, path, headers=None, body=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.puerto, timeout=5)
        try:
            conn.request(method, path, body=body, headers=headers or {})
            resp = conn.getresponse()
            data = resp.read()
            return resp.status, dict(resp.getheaders()), data
        finally:
            conn.close()

    def terminar_y_leer_salida(self):
        """Termina el proceso y devuelve TODO lo que escribió a
        stdout/stderr (redirigidos juntos), para poder verificar que
        nunca se logueó una credencial ni el header Authorization."""
        if self.proceso.poll() is None:
            self.proceso.terminate()
        try:
            salida, _ = self.proceso.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            self.proceso.kill()
            salida, _ = self.proceso.communicate(timeout=5)
        return salida or ""


@pytest.fixture()
def lanzar_proxy():
    procesos = []

    def _lanzar(env_extra=None, n8n_origin=None):
        puerto = _puerto_libre()
        env = dict(os.environ)
        env.pop("TIQ_AUTH_USERNAME", None)
        env.pop("TIQ_AUTH_PASSWORD", None)
        env["PORT"] = str(puerto)
        if n8n_origin:
            env["TIQ_N8N_ORIGIN"] = n8n_origin
        env.update(env_extra or {})
        proceso = subprocess.Popen(
            [sys.executable, SCRIPT], cwd=RAIZ, env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
        procesos.append(proceso)
        if not _esperar_puerto("127.0.0.1", puerto):
            proceso.kill()
            raise AssertionError("serve_v3_frontend.py no abrió el puerto a tiempo")
        return _ProxyProceso(puerto, proceso)

    yield _lanzar

    for p in procesos:
        if p.poll() is None:
            p.terminate()
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()


# ---------------------------------------------------------------------
# 1) /healthz nunca requiere auth
# ---------------------------------------------------------------------

def test_healthz_sin_auth_y_sin_credenciales_configuradas(lanzar_proxy):
    proxy = lanzar_proxy({})
    status, _, body = proxy.request("GET", "/healthz")
    assert status == 200
    assert body == b"OK"


def test_healthz_sin_auth_con_credenciales_configuradas(lanzar_proxy):
    proxy = lanzar_proxy({"TIQ_AUTH_USERNAME": USUARIO, "TIQ_AUTH_PASSWORD": CLAVE})
    status, _, body = proxy.request("GET", "/healthz")
    assert status == 200
    assert body == b"OK"


# ---------------------------------------------------------------------
# 2-3-4) GET / sin auth / con credenciales incorrectas / correctas
# ---------------------------------------------------------------------

def test_raiz_sin_auth_devuelve_401(lanzar_proxy):
    proxy = lanzar_proxy({"TIQ_AUTH_USERNAME": USUARIO, "TIQ_AUTH_PASSWORD": CLAVE})
    status, headers, _ = proxy.request("GET", "/")
    assert status == 401
    assert headers.get("WWW-Authenticate") == 'Basic realm="CAJAS GABO"'


def test_raiz_credenciales_incorrectas_401(lanzar_proxy):
    proxy = lanzar_proxy({"TIQ_AUTH_USERNAME": USUARIO, "TIQ_AUTH_PASSWORD": CLAVE})
    status, headers, _ = proxy.request(
        "GET", "/", headers=_basic_auth_header(USUARIO, "clave-incorrecta")
    )
    assert status == 401
    assert headers.get("WWW-Authenticate") == 'Basic realm="CAJAS GABO"'


@pytest.mark.parametrize("ruta", ["/", "/?utm_source=chatgpt.com", "/?foo=bar&x=1"])
def test_raiz_credenciales_correctas_redirige_302_a_v3_control_cierres(lanzar_proxy, ruta):
    proxy = lanzar_proxy({"TIQ_AUTH_USERNAME": USUARIO, "TIQ_AUTH_PASSWORD": CLAVE})
    status, headers, _ = proxy.request("GET", ruta, headers=_basic_auth_header(USUARIO, CLAVE))
    assert status == 302
    assert headers.get("Location") == "/v3_control_cierres.html"


def test_v3_control_cierres_html_acceso_directo_autenticado_200(lanzar_proxy):
    proxy = lanzar_proxy({"TIQ_AUTH_USERNAME": USUARIO, "TIQ_AUTH_PASSWORD": CLAVE})
    status, _, _ = proxy.request(
        "GET", "/v3_control_cierres.html", headers=_basic_auth_header(USUARIO, CLAVE)
    )
    assert status == 200


# ---------------------------------------------------------------------
# 5-6) GET/POST /webhook/* sin auth NUNCA llegan a n8n
# ---------------------------------------------------------------------

def test_webhook_get_sin_auth_no_llega_a_n8n(lanzar_proxy, fake_n8n):
    origen, recibidas = fake_n8n
    proxy = lanzar_proxy({"TIQ_AUTH_USERNAME": USUARIO, "TIQ_AUTH_PASSWORD": CLAVE}, n8n_origin=origen)
    status, _, _ = proxy.request("GET", "/webhook/tiq-v3-dev/estado")
    assert status == 401
    assert recibidas == []


def test_webhook_post_sin_auth_no_llega_a_n8n(lanzar_proxy, fake_n8n):
    origen, recibidas = fake_n8n
    proxy = lanzar_proxy({"TIQ_AUTH_USERNAME": USUARIO, "TIQ_AUTH_PASSWORD": CLAVE}, n8n_origin=origen)
    status, _, _ = proxy.request(
        "POST", "/webhook/tiq-v3-dev/procesar",
        headers={"Content-Type": "application/json"}, body=b'{"lote_id": "L1"}',
    )
    assert status == 401
    assert recibidas == []


# ---------------------------------------------------------------------
# 7-8) POST autenticado sí proxifica, y Authorization nunca se reenvía
# ---------------------------------------------------------------------

def test_webhook_post_autenticado_proxifica_y_no_reenvia_authorization(lanzar_proxy, fake_n8n):
    origen, recibidas = fake_n8n
    proxy = lanzar_proxy({"TIQ_AUTH_USERNAME": USUARIO, "TIQ_AUTH_PASSWORD": CLAVE}, n8n_origin=origen)
    cuerpo = b'{"lote_id": "L1"}'
    headers = {"Content-Type": "application/json"}
    headers.update(_basic_auth_header(USUARIO, CLAVE))

    status, _, data = proxy.request("POST", "/webhook/tiq-v3-dev/procesar", headers=headers, body=cuerpo)

    assert status == 200
    assert json.loads(data)["recibido_en"] == "/webhook/tiq-v3-dev/procesar"
    assert len(recibidas) == 1
    recibida = recibidas[0]
    assert recibida["method"] == "POST"
    assert recibida["path"] == "/webhook/tiq-v3-dev/procesar"
    assert recibida["body"] == cuerpo
    assert "Authorization" not in recibida["headers"]
    assert not any(k.lower() == "authorization" for k in recibida["headers"])


def test_webhook_get_autenticado_proxifica_y_no_reenvia_authorization(lanzar_proxy, fake_n8n):
    origen, recibidas = fake_n8n
    proxy = lanzar_proxy({"TIQ_AUTH_USERNAME": USUARIO, "TIQ_AUTH_PASSWORD": CLAVE}, n8n_origin=origen)
    status, _, _ = proxy.request(
        "GET", "/webhook/tiq-v3-dev/estado", headers=_basic_auth_header(USUARIO, CLAVE)
    )
    assert status == 200
    assert len(recibidas) == 1
    assert not any(k.lower() == "authorization" for k in recibidas[0]["headers"])


# ---------------------------------------------------------------------
# 9) sin variables de auth (o incompletas) -> fail closed (503), nunca abierto
# ---------------------------------------------------------------------

def test_fail_closed_sin_variables_de_auth(lanzar_proxy, fake_n8n):
    origen, recibidas = fake_n8n
    proxy = lanzar_proxy({}, n8n_origin=origen)  # ni USERNAME ni PASSWORD

    status_raiz, _, _ = proxy.request("GET", "/")
    status_get, _, _ = proxy.request("GET", "/webhook/tiq-v3-dev/estado")
    status_post, _, _ = proxy.request(
        "POST", "/webhook/tiq-v3-dev/procesar",
        headers={"Content-Type": "application/json"}, body=b"{}",
    )
    # Ni siquiera un intento de Basic auth "convincente" abre nada:
    # AUTH_CONFIGURED=False bloquea cualquier combinación.
    status_con_intento, _, _ = proxy.request(
        "GET", "/", headers=_basic_auth_header("cualquiera", "cualquiera")
    )

    assert status_raiz == 503
    assert status_get == 503
    assert status_post == 503
    assert status_con_intento == 503
    assert recibidas == []  # nunca llegó a n8n

    status_healthz, _, body = proxy.request("GET", "/healthz")
    assert status_healthz == 200
    assert body == b"OK"


def test_fail_closed_con_solo_username(lanzar_proxy):
    proxy = lanzar_proxy({"TIQ_AUTH_USERNAME": USUARIO})  # sin PASSWORD
    status, _, _ = proxy.request("GET", "/")
    assert status == 503


def test_fail_closed_con_solo_password(lanzar_proxy):
    proxy = lanzar_proxy({"TIQ_AUTH_PASSWORD": CLAVE})  # sin USERNAME
    status, _, _ = proxy.request("GET", "/")
    assert status == 503


def test_fail_closed_con_password_vacia(lanzar_proxy):
    proxy = lanzar_proxy({"TIQ_AUTH_USERNAME": USUARIO, "TIQ_AUTH_PASSWORD": ""})
    status, _, _ = proxy.request("GET", "/")
    assert status == 503


# ---------------------------------------------------------------------
# No se loguean credenciales ni Authorization
# ---------------------------------------------------------------------

def test_no_se_registran_credenciales_ni_authorization_en_logs(lanzar_proxy):
    proxy = lanzar_proxy({"TIQ_AUTH_USERNAME": USUARIO, "TIQ_AUTH_PASSWORD": CLAVE})
    proxy.request("GET", "/")  # 401 sin auth
    proxy.request("GET", "/", headers=_basic_auth_header(USUARIO, "mala-clave"))  # 401
    proxy.request("GET", "/", headers=_basic_auth_header(USUARIO, CLAVE))  # 302

    salida = proxy.terminar_y_leer_salida()

    assert CLAVE not in salida
    assert USUARIO not in salida
    token = base64.b64encode(f"{USUARIO}:{CLAVE}".encode("utf-8")).decode("ascii")
    assert token not in salida
    assert "Authorization" not in salida


# ---------------------------------------------------------------------
# 10) comportamiento existente del proxy no se rompe con auth correcta
# ---------------------------------------------------------------------

def test_comportamiento_existente_query_string_se_reenvia(lanzar_proxy, fake_n8n):
    origen, recibidas = fake_n8n
    proxy = lanzar_proxy({"TIQ_AUTH_USERNAME": USUARIO, "TIQ_AUTH_PASSWORD": CLAVE}, n8n_origin=origen)
    status, _, _ = proxy.request(
        "GET", "/webhook/tiq-v3-dev/estado?x=1", headers=_basic_auth_header(USUARIO, CLAVE)
    )
    assert status == 200
    assert recibidas[0]["path"] == "/webhook/tiq-v3-dev/estado?x=1"


def test_comportamiento_existente_error_de_n8n_se_propaga(lanzar_proxy, fake_n8n):
    origen, _ = fake_n8n
    proxy = lanzar_proxy({"TIQ_AUTH_USERNAME": USUARIO, "TIQ_AUTH_PASSWORD": CLAVE}, n8n_origin=origen)
    status, _, data = proxy.request(
        "GET", "/webhook/no-existe", headers=_basic_auth_header(USUARIO, CLAVE)
    )
    assert status == 404
    assert b"no encontrado en n8n falso" in data


def test_comportamiento_existente_cache_control_se_mantiene(lanzar_proxy):
    proxy = lanzar_proxy({"TIQ_AUTH_USERNAME": USUARIO, "TIQ_AUTH_PASSWORD": CLAVE})
    _, headers, _ = proxy.request("GET", "/", headers=_basic_auth_header(USUARIO, CLAVE))
    assert headers.get("Cache-Control") == "no-store, must-revalidate"
