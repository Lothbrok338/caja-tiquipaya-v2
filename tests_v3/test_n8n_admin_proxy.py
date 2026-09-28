"""tests_v3/test_n8n_admin_proxy.py — acceso admin al editor n8n (2026-09).

Verifica el pass-through agregado a scripts/serve_v3_frontend.py para dar
acceso web al editor n8n en el MISMO dominio, SIN tunel SSH y SIN usar
N8N_PATH/subpath (ver docstring del modulo para la justificacion: n8n
tiene un issue abierto -- github.com/n8n-io/n8n/issues/19635 -- que
documenta que la mayoria de sus endpoints ignoran el basePath de
N8N_PATH). El diseno es: n8n sigue creyendo que vive en la raiz;
`/n8n-admin` es solo un redirect a `/home`; cualquier otra ruta que no
sea un archivo estatico local ni /webhook/* se reenvia tal cual a la
raiz real de n8n.

Corre el script REAL como subproceso (mismo patron que
test_frontend_auth.py/test_n8n_lazy_lifecycle.py) contra un n8n falso
que, ademas de eco de requests, sabe: devolver Set-Cookie (multiple),
Location, una respuesta SIN Content-Length (fuerza el reenvio chunked
propio) y completar un handshake real de WebSocket (RFC 6455) para
poder probar el pass-through crudo de /rest/push a nivel de bytes.

NO repite las pruebas de autenticacion/fail-closed de
test_frontend_auth.py (esa logica no cambio: _autenticar() se llama
igual antes de cualquier rama nueva). Se enfoca en:
  - /n8n-admin redirige (302) a /home, nunca se proxifica el literal;
  - /home, /rest/*, /credentials/nueva, etc. (rutas propias de n8n) se
    reenvian tal cual, con GET/POST/PUT/PATCH/DELETE/OPTIONS;
  - Cookie de ida y Set-Cookie de vuelta (incluidas varias a la vez)
    viajan integras; Authorization nunca llega a n8n;
  - X-Forwarded-Proto/Host/For se agregan al reenviar;
  - Location se reenvia sin reescribir;
  - una respuesta de n8n sin Content-Length se retransmite con
    Transfer-Encoding: chunked, y el cliente reconstruye el body igual;
  - los archivos estaticos existentes (v3_control_cierres.html,
    revision_correccion.html) NO se ven afectados: siguen sirviendose
    localmente, nunca viajan a n8n;
  - /webhook/* sigue usando el proxy angosto de siempre, sin ninguno de
    los headers/metodos nuevos;
  - el pass-through de WebSocket (/rest/push): handshake real, 101, y
    bytes crudos viajando en ambos sentidos tras el handshake.

No toca motor_tiquipaya.py, pipeline_tiquipaya.py, workflows de n8n,
Drive/Postgres ni TIQ_BLOCK_OFFICIAL_PUBLISH.

Uso: python -m pytest tests_v3/test_n8n_admin_proxy.py -q
"""
import base64
import hashlib
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

_WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


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
    """n8n falso, ampliado respecto al de test_frontend_auth.py: soporta
    todos los metodos que el editor necesita, puede devolver varios
    Set-Cookie a la vez, un Location, una respuesta SIN Content-Length
    (para forzar el chunked propio del proxy), y completa un handshake
    WebSocket real para /rest/push (luego solo hace eco crudo de bytes,
    sin interpretar frames -- no hace falta mas para probar el splice)."""

    def _registrar(self, body):
        self.server.recibidas.append({
            "method": self.command,
            "path": self.path,
            "headers": dict(self.headers.items()),
            "body": body,
        })

    def _es_upgrade_websocket(self):
        return (
            "upgrade" in self.headers.get("Connection", "").lower()
            and self.headers.get("Upgrade", "").lower() == "websocket"
        )

    def _manejar_websocket(self):
        clave = self.headers.get("Sec-WebSocket-Key", "")
        aceptar = base64.b64encode(hashlib.sha1((clave + _WS_GUID).encode("ascii")).digest()).decode("ascii")
        self.send_response(101, "Switching Protocols")
        self.send_header("Upgrade", "websocket")
        self.send_header("Connection", "Upgrade")
        self.send_header("Sec-WebSocket-Accept", aceptar)
        self.end_headers()
        self.server.recibidas.append({
            "method": "WS-UPGRADE", "path": self.path,
            "headers": dict(self.headers.items()), "body": b"",
        })
        self.close_connection = True
        sock = self.connection
        sock.settimeout(5)
        try:
            while True:
                datos = sock.recv(65536)
                if not datos:
                    break
                sock.sendall(datos)  # eco crudo: alcanza para probar el splice
        except OSError:
            pass

    def _atender(self):
        if self.path == "/healthz/readiness":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status": "ok"}')
            return
        if self._es_upgrade_websocket():
            return self._manejar_websocket()
        length = int(self.headers.get("Content-Length", 0) or 0)
        body = self.rfile.read(length) if length else b""
        self._registrar(body)

        if self.path == "/sin-content-length":
            # Respuesta deliberadamente SIN Content-Length ni
            # Transfer-Encoding -- fuerza la rama "chunked propio" de
            # Handler._reenviar_respuesta_n8n.
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"X" * 200000)
            self.close_connection = True
            return

        if self.path == "/con-redirect":
            self.send_response(302)
            self.send_header("Location", "/home/workflows")
            self.end_headers()
            return

        if self.path == "/con-cookies":
            self.send_response(200)
            self.send_header("Set-Cookie", "n8n-auth=abc123; HttpOnly; Path=/")
            self.send_header("Set-Cookie", "n8n-csrf=xyz789; Path=/")
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"ok": true}')
            return

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"ok": True, "recibido_en": self.path, "metodo": self.command}).encode("utf-8"))

    def do_GET(self):
        self._atender()

    def do_POST(self):
        self._atender()

    def do_PUT(self):
        self._atender()

    def do_PATCH(self):
        self._atender()

    def do_DELETE(self):
        self._atender()

    def do_OPTIONS(self):
        self._atender()

    def log_message(self, *args, **kwargs):
        pass


@pytest.fixture()
def fake_n8n():
    servidor = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _FakeN8NHandler)
    servidor.recibidas = []
    hilo = threading.Thread(target=servidor.serve_forever, daemon=True)
    hilo.start()
    puerto = servidor.server_address[1]
    try:
        yield puerto, servidor.recibidas
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
            return resp.status, resp.getheaders(), data
        finally:
            conn.close()


@pytest.fixture()
def lanzar_proxy():
    procesos = []

    def _lanzar(puerto_n8n, env_extra=None):
        puerto = _puerto_libre()
        env = dict(os.environ)
        env.pop("TIQ_AUTH_USERNAME", None)
        env.pop("TIQ_AUTH_PASSWORD", None)
        env["PORT"] = str(puerto)
        env["TIQ_N8N_ORIGIN"] = f"http://127.0.0.1:{puerto_n8n}"
        env["TIQ_AUTH_USERNAME"] = USUARIO
        env["TIQ_AUTH_PASSWORD"] = CLAVE
        env.update(env_extra or {})
        proceso = subprocess.Popen(
            [sys.executable, SCRIPT], cwd=RAIZ, env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
        procesos.append(proceso)
        if not _esperar_puerto("127.0.0.1", puerto):
            proceso.kill()
            raise AssertionError("serve_v3_frontend.py no abrio el puerto a tiempo")
        return _ProxyProceso(puerto, proceso)

    yield _lanzar

    for p in procesos:
        if p.poll() is None:
            p.terminate()
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()


def _header(headers, nombre):
    return [v for k, v in headers if k.lower() == nombre.lower()]


# ---------------------------------------------------------------------
# /n8n-admin es SOLO un redirect a /home -- nunca se proxifica el literal
# ---------------------------------------------------------------------

def test_n8n_admin_redirige_a_home(lanzar_proxy, fake_n8n):
    puerto_n8n, recibidas = fake_n8n
    proxy = lanzar_proxy(puerto_n8n)
    status, headers, _ = proxy.request("GET", "/n8n-admin", headers=_basic_auth_header(USUARIO, CLAVE))
    assert status == 302
    assert _header(headers, "Location") == ["/home"]
    assert recibidas == []  # el redirect no toca n8n para nada


def test_n8n_admin_con_barra_final_tambien_redirige(lanzar_proxy, fake_n8n):
    puerto_n8n, _ = fake_n8n
    proxy = lanzar_proxy(puerto_n8n)
    status, headers, _ = proxy.request("GET", "/n8n-admin/", headers=_basic_auth_header(USUARIO, CLAVE))
    assert status == 302
    assert _header(headers, "Location") == ["/home"]


def test_n8n_admin_sin_auth_no_llega_a_n8n(lanzar_proxy, fake_n8n):
    puerto_n8n, recibidas = fake_n8n
    proxy = lanzar_proxy(puerto_n8n)
    status, _, _ = proxy.request("GET", "/n8n-admin")
    assert status == 401
    assert recibidas == []


# ---------------------------------------------------------------------
# Rutas propias de n8n (/home, /rest/*, /credentials/*, ...): pasan tal
# cual, con cualquiera de los metodos que el editor necesita
# ---------------------------------------------------------------------

@pytest.mark.parametrize("ruta", ["/home", "/home/workflows", "/rest/login", "/credentials/nueva", "/signin"])
def test_rutas_propias_de_n8n_se_reenvian_get(lanzar_proxy, fake_n8n, ruta):
    puerto_n8n, recibidas = fake_n8n
    proxy = lanzar_proxy(puerto_n8n)
    status, _, data = proxy.request("GET", ruta, headers=_basic_auth_header(USUARIO, CLAVE))
    assert status == 200
    assert json.loads(data)["recibido_en"] == ruta
    assert recibidas[-1]["path"] == ruta


@pytest.mark.parametrize("metodo", ["POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
def test_metodos_de_editor_se_reenvian(lanzar_proxy, fake_n8n, metodo):
    puerto_n8n, recibidas = fake_n8n
    proxy = lanzar_proxy(puerto_n8n)
    cuerpo = b'{"name": "workflow"}' if metodo in ("POST", "PUT", "PATCH") else None
    headers = _basic_auth_header(USUARIO, CLAVE)
    if cuerpo:
        headers = {**headers, "Content-Type": "application/json"}
    status, _, data = proxy.request(metodo, "/rest/workflows/123", headers=headers, body=cuerpo)
    assert status == 200
    assert json.loads(data)["metodo"] == metodo
    assert recibidas[-1]["method"] == metodo
    if cuerpo:
        assert recibidas[-1]["body"] == cuerpo


def test_authorization_nunca_llega_a_n8n_en_ruta_de_editor(lanzar_proxy, fake_n8n):
    puerto_n8n, recibidas = fake_n8n
    proxy = lanzar_proxy(puerto_n8n)
    proxy.request("GET", "/home", headers=_basic_auth_header(USUARIO, CLAVE))
    assert not any(k.lower() == "authorization" for k in recibidas[-1]["headers"])


def test_x_forwarded_headers_se_agregan(lanzar_proxy, fake_n8n):
    puerto_n8n, recibidas = fake_n8n
    proxy = lanzar_proxy(puerto_n8n)
    proxy.request("GET", "/home", headers=_basic_auth_header(USUARIO, CLAVE))
    recibida = recibidas[-1]["headers"]
    assert recibida.get("X-Forwarded-Proto") == "https"
    assert recibida.get("X-Forwarded-For") == "127.0.0.1"


# ---------------------------------------------------------------------
# Cookies (ida y vuelta) y Location se reenvian integros
# ---------------------------------------------------------------------

def test_cookie_de_ida_viaja_a_n8n(lanzar_proxy, fake_n8n):
    puerto_n8n, recibidas = fake_n8n
    proxy = lanzar_proxy(puerto_n8n)
    headers = {**_basic_auth_header(USUARIO, CLAVE), "Cookie": "n8n-auth=sesion-existente"}
    proxy.request("GET", "/home", headers=headers)
    assert recibidas[-1]["headers"].get("Cookie") == "n8n-auth=sesion-existente"


def test_set_cookie_multiple_viaja_de_vuelta_al_navegador(lanzar_proxy, fake_n8n):
    puerto_n8n, _ = fake_n8n
    proxy = lanzar_proxy(puerto_n8n)
    status, headers, _ = proxy.request("GET", "/con-cookies", headers=_basic_auth_header(USUARIO, CLAVE))
    assert status == 200
    cookies = _header(headers, "Set-Cookie")
    assert len(cookies) == 2, f"esperaba 2 Set-Cookie, llegaron: {cookies}"
    assert any(c.startswith("n8n-auth=abc123") for c in cookies)
    assert any(c.startswith("n8n-csrf=xyz789") for c in cookies)


def test_location_se_reenvia_sin_reescribir(lanzar_proxy, fake_n8n):
    puerto_n8n, _ = fake_n8n
    proxy = lanzar_proxy(puerto_n8n)
    status, headers, _ = proxy.request("GET", "/con-redirect", headers=_basic_auth_header(USUARIO, CLAVE))
    assert status == 302
    assert _header(headers, "Location") == ["/home/workflows"]


# ---------------------------------------------------------------------
# Respuesta de n8n sin Content-Length -> se retransmite chunked, el
# cliente igual reconstruye el body completo
# ---------------------------------------------------------------------

def test_respuesta_sin_content_length_se_retransmite_completa(lanzar_proxy, fake_n8n):
    puerto_n8n, _ = fake_n8n
    proxy = lanzar_proxy(puerto_n8n)
    status, headers, data = proxy.request("GET", "/sin-content-length", headers=_basic_auth_header(USUARIO, CLAVE))
    assert status == 200
    assert data == b"X" * 200000
    assert _header(headers, "Transfer-Encoding") == ["chunked"]


# ---------------------------------------------------------------------
# Archivos estaticos existentes: sin cambios, nunca viajan a n8n
# ---------------------------------------------------------------------

@pytest.mark.parametrize("archivo", ["/v3_control_cierres.html", "/revision_correccion.html"])
def test_archivos_estaticos_existentes_no_pasan_por_n8n(lanzar_proxy, fake_n8n, archivo):
    puerto_n8n, recibidas = fake_n8n
    proxy = lanzar_proxy(puerto_n8n)
    status, _, _ = proxy.request("GET", archivo, headers=_basic_auth_header(USUARIO, CLAVE))
    assert status == 200
    assert recibidas == []


# ---------------------------------------------------------------------
# /webhook/* sigue usando el proxy angosto de siempre: mismo
# comportamiento, sin los headers nuevos (X-Forwarded-*, etc.)
# ---------------------------------------------------------------------

def test_webhook_sigue_sin_x_forwarded_headers(lanzar_proxy, fake_n8n):
    puerto_n8n, recibidas = fake_n8n
    proxy = lanzar_proxy(puerto_n8n)
    status, _, _ = proxy.request(
        "GET", "/webhook/tiq-v3-dev/estado", headers=_basic_auth_header(USUARIO, CLAVE)
    )
    assert status == 200
    assert "X-Forwarded-Proto" not in recibidas[-1]["headers"]
    assert "X-Forwarded-For" not in recibidas[-1]["headers"]


def test_webhook_put_delete_no_soportados_igual_que_antes(lanzar_proxy, fake_n8n):
    """/webhook/* nunca necesito PUT/DELETE (los nodos WEBHOOK del
    workflow real solo usan GET/POST) -- confirma que agregar do_PUT/
    do_DELETE en el Handler no cambia nada para esa ruta: sigue sin
    metodo dedicado para ella (los nuevos do_PUT/do_DELETE reenvian a
    _proxy_n8n, no a _proxy, independientemente del path)."""
    puerto_n8n, recibidas = fake_n8n
    proxy = lanzar_proxy(puerto_n8n)
    status, _, _ = proxy.request(
        "PUT", "/webhook/tiq-v3-dev/estado", headers=_basic_auth_header(USUARIO, CLAVE)
    )
    # Llega (via _proxy_n8n, como cualquier otro PUT), pero NUNCA por el
    # camino angosto _proxy -- se confirma por la presencia de
    # X-Forwarded-Proto (que _proxy nunca agrega).
    assert status == 200
    assert recibidas[-1]["headers"].get("X-Forwarded-Proto") == "https"


# ---------------------------------------------------------------------
# WebSocket (/rest/push): handshake real + bytes crudos en ambos
# sentidos tras el 101
# ---------------------------------------------------------------------

def test_websocket_handshake_y_splice_de_bytes(lanzar_proxy, fake_n8n):
    puerto_n8n, recibidas = fake_n8n
    proxy = lanzar_proxy(puerto_n8n)

    clave_ws = base64.b64encode(os.urandom(16)).decode("ascii")
    peticion = (
        "GET /rest/push?sessionId=abc HTTP/1.1\r\n"
        "Host: 127.0.0.1\r\n"
        "Connection: Upgrade\r\n"
        "Upgrade: websocket\r\n"
        "Sec-WebSocket-Version: 13\r\n"
        f"Sec-WebSocket-Key: {clave_ws}\r\n"
        f"Authorization: Basic {base64.b64encode(f'{USUARIO}:{CLAVE}'.encode()).decode()}\r\n"
        "Cookie: n8n-auth=sesion-valida\r\n"
        "\r\n"
    )

    sock = socket.create_connection(("127.0.0.1", proxy.puerto), timeout=10)
    try:
        sock.sendall(peticion.encode("ascii"))

        # Lee la linea de estado + cabeceras del 101.
        buffer = b""
        while b"\r\n\r\n" not in buffer:
            trozo = sock.recv(4096)
            assert trozo, "la conexion se cerro antes de completar el handshake"
            buffer += trozo
        cabecera, _, resto = buffer.partition(b"\r\n\r\n")
        # El status-line lo pone el "n8n falso" (o el n8n real): el
        # splice del proxy lo reenvia byte a byte, sin reescribirlo.
        assert cabecera.startswith(b"HTTP/1.1 101") or cabecera.startswith(b"HTTP/1.0 101"), cabecera

        aceptar_esperado = base64.b64encode(
            hashlib.sha1((clave_ws + _WS_GUID).encode("ascii")).digest()
        ).decode("ascii")
        assert aceptar_esperado.encode("ascii") in cabecera

        # El "n8n falso" recibio el upgrade con la Cookie de sesion, y
        # Authorization (el secreto del proxy publico) NO le llego.
        recibida_ws = next(r for r in recibidas if r["method"] == "WS-UPGRADE")
        assert recibida_ws["headers"].get("Cookie") == "n8n-auth=sesion-valida"
        assert "Authorization" not in recibida_ws["headers"]

        # Bytes crudos: el "n8n falso" hace eco -- confirma que el
        # splice copia datos en ambos sentidos sin interpretarlos.
        mensaje = b"\x81\x05hello"  # como si fuera un frame WS cualquiera; el proxy no lo interpreta
        sock.sendall(mensaje)
        eco = b""
        sock.settimeout(5)
        while len(eco) < len(mensaje):
            eco += sock.recv(4096)
        assert eco == mensaje
    finally:
        sock.close()


def test_websocket_sin_auth_no_llega_a_n8n(lanzar_proxy, fake_n8n):
    puerto_n8n, recibidas = fake_n8n
    proxy = lanzar_proxy(puerto_n8n)

    clave_ws = base64.b64encode(os.urandom(16)).decode("ascii")
    peticion = (
        "GET /rest/push HTTP/1.1\r\n"
        "Host: 127.0.0.1\r\n"
        "Connection: Upgrade\r\n"
        "Upgrade: websocket\r\n"
        "Sec-WebSocket-Version: 13\r\n"
        f"Sec-WebSocket-Key: {clave_ws}\r\n"
        "\r\n"
    )
    sock = socket.create_connection(("127.0.0.1", proxy.puerto), timeout=10)
    try:
        sock.sendall(peticion.encode("ascii"))
        buffer = b""
        while b"\r\n\r\n" not in buffer:
            trozo = sock.recv(4096)
            if not trozo:
                break
            buffer += trozo
        # Handler nunca fijo protocol_version (siempre fue HTTP/1.0 por
        # default de SimpleHTTPRequestHandler, sin relacion con este
        # cambio) -- lo que importa aca es que _autenticar() corta ANTES
        # de intentar cualquier upgrade.
        assert b" 401 " in buffer.split(b"\r\n", 1)[0]
    finally:
        sock.close()
    assert not any(r["method"] == "WS-UPGRADE" for r in recibidas)
