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

        if self.path == "/rest/workflows-protegido":
            # Simula una ruta REAL de n8n que exige sesion propia (su
            # Cookie, nunca el Basic Auth del proxy publico -- ese ya
            # nunca llega hasta aca, se filtra en Handler._proxy_n8n).
            # El 401 y el body son deliberadamente DISTINTOS a los del
            # proxy (que siempre manda WWW-Authenticate: Basic) para
            # poder distinguir "me rechazo n8n" de "me rechazo el
            # proxy" desde el lado del test.
            if self.headers.get("Cookie") != "n8n-auth=sesion-valida":
                self.send_response(401)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"code": 401, "message": "Unauthorized (n8n)"}).encode("utf-8"))
                return
            self.send_response(200)
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


def test_n8n_admin_sin_basic_auth_del_proxy_igual_redirige(lanzar_proxy, fake_n8n):
    """FIX del prompt repetido: /n8n-admin NUNCA exige el Basic Auth del
    proxy publico (nunca dispara un 401/WWW-Authenticate) -- redirige a
    /home igual, sea cual sea el header Authorization que traiga (o no
    traiga) la request."""
    puerto_n8n, recibidas = fake_n8n
    proxy = lanzar_proxy(puerto_n8n)
    status, headers, _ = proxy.request("GET", "/n8n-admin")
    assert status == 302
    assert _header(headers, "Location") == ["/home"]
    assert not _header(headers, "WWW-Authenticate")
    assert recibidas == []


# ---------------------------------------------------------------------
# Rutas propias de n8n (/home, /rest/*, /credentials/*, ...): pasan tal
# cual, con cualquiera de los metodos que el editor necesita, y SIN
# exigir el Basic Auth del proxy publico (FIX del prompt repetido: la
# SPA de n8n dispara decenas de llamadas internas -- gatearlas con nuestro
# Basic Auth causaba prompts de usuario/clave una y otra vez). La
# seguridad de estas rutas queda a cargo exclusivo del login nativo de
# n8n (ver mas abajo "ruta protegida de n8n sin sesion").
# ---------------------------------------------------------------------

@pytest.mark.parametrize("ruta", [
    "/home", "/home/workflows", "/rest/login", "/rest/settings", "/rest/tags",
    "/credentials/nueva", "/signin", "/types/credentials.json",
])
def test_rutas_propias_de_n8n_llegan_sin_basic_auth_del_proxy(lanzar_proxy, fake_n8n, ruta):
    puerto_n8n, recibidas = fake_n8n
    proxy = lanzar_proxy(puerto_n8n)
    status, headers, data = proxy.request("GET", ruta)  # SIN Authorization
    assert status == 200
    assert not _header(headers, "WWW-Authenticate"), f"{ruta} no deberia pedir Basic Auth del proxy"
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


@pytest.mark.parametrize("archivo", ["/", "/v3_control_cierres.html", "/revision_correccion.html"])
def test_panel_cajas_gabo_sigue_protegido_con_basic_auth(lanzar_proxy, fake_n8n, archivo):
    """El fix acota el Basic Auth del proxy a las rutas de CAJAS GABO,
    pero NO lo elimina de ahi: '/', v3_control_cierres.html y
    revision_correccion.html siguen exigiendolo exactamente igual que
    antes (401 sin credenciales)."""
    puerto_n8n, _ = fake_n8n
    proxy = lanzar_proxy(puerto_n8n)
    status, headers, _ = proxy.request("GET", archivo)  # sin Authorization
    assert status == 401
    assert _header(headers, "WWW-Authenticate") == ['Basic realm="CAJAS GABO"']


# ---------------------------------------------------------------------
# Paginas de verificacion OAuth de Google (oauth-info.html, privacy.html):
# UNICAS excepciones publicas dentro de n8n_frontend/ -- Google las
# visita/audita sin ninguna credencial de CAJAS GABO.
# ---------------------------------------------------------------------

@pytest.mark.parametrize("archivo", ["/oauth-info.html", "/privacy.html"])
def test_paginas_oauth_publicas_responden_200_sin_auth(lanzar_proxy, fake_n8n, archivo):
    puerto_n8n, recibidas = fake_n8n
    proxy = lanzar_proxy(puerto_n8n)
    status, headers, cuerpo = proxy.request("GET", archivo)  # sin Authorization
    assert status == 200
    assert not _header(headers, "WWW-Authenticate")
    assert recibidas == [], "las paginas publicas nunca deben tocar n8n"
    assert b"CAJAS UNIVALLE" in cuerpo
    assert b"torricogabriel24@gmail.com" in cuerpo


def test_oauth_info_enlaza_a_privacy(lanzar_proxy, fake_n8n):
    puerto_n8n, _ = fake_n8n
    proxy = lanzar_proxy(puerto_n8n)
    _, _, cuerpo = proxy.request("GET", "/oauth-info.html")
    assert b"/privacy.html" in cuerpo


# ---------------------------------------------------------------------
# /webhook/* sigue usando el proxy angosto de siempre: mismo
# comportamiento (incluida la exigencia de Basic Auth), sin los headers
# nuevos (X-Forwarded-*, etc.)
# ---------------------------------------------------------------------

def test_webhook_sigue_exigiendo_basic_auth_del_proxy(lanzar_proxy, fake_n8n):
    puerto_n8n, recibidas = fake_n8n
    proxy = lanzar_proxy(puerto_n8n)
    status, headers, _ = proxy.request("GET", "/webhook/tiq-v3-dev/estado")  # sin Authorization
    assert status == 401
    assert _header(headers, "WWW-Authenticate") == ['Basic realm="CAJAS GABO"']
    assert recibidas == []


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


def test_websocket_sin_basic_auth_del_proxy_igual_llega_a_n8n(lanzar_proxy, fake_n8n):
    """FIX del prompt repetido: /rest/push (el canal de tiempo real del
    editor) ya NO exige el Basic Auth del proxy publico -- el handshake
    llega a n8n igual sin ningun header Authorization. Lo que protege
    esta ruta es la propia sesion de n8n (la Cookie que el navegador ya
    tenga, si la tiene) -- ver test_websocket_handshake_y_splice_de_bytes
    para el caso CON Cookie de sesion valida."""
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
            assert trozo, "la conexion se cerro antes de completar el handshake"
            buffer += trozo
        cabecera = buffer.partition(b"\r\n\r\n")[0]
        assert b" 101 " in cabecera.split(b"\r\n", 1)[0], cabecera
    finally:
        sock.close()
    recibida_ws = next(r for r in recibidas if r["method"] == "WS-UPGRADE")
    assert "Authorization" not in recibida_ws["headers"]


# ---------------------------------------------------------------------
# La pieza central del fix: una ruta de n8n que SI requiere sesion
# queda protegida por el 401 propio de n8n (nunca por el nuestro) --
# demuestra que "sin Basic Auth del proxy" no es "sin autenticacion",
# es "la autenticacion la hace n8n".
# ---------------------------------------------------------------------

def test_ruta_protegida_de_n8n_sin_sesion_queda_protegida_por_n8n_no_por_el_proxy(lanzar_proxy, fake_n8n):
    puerto_n8n, recibidas = fake_n8n
    proxy = lanzar_proxy(puerto_n8n)
    status, headers, data = proxy.request("GET", "/rest/workflows-protegido")  # sin Cookie, sin Authorization
    # Llega a n8n (nuestro proxy no la bloqueo) y es N8N quien la
    # rechaza -- nunca con el 401/WWW-Authenticate de nuestro proxy.
    assert status == 401
    assert not _header(headers, "WWW-Authenticate"), "un 401 con WWW-Authenticate Basic seria NUESTRO proxy, no n8n"
    assert json.loads(data) == {"code": 401, "message": "Unauthorized (n8n)"}
    assert len(recibidas) == 1
    assert recibidas[0]["path"] == "/rest/workflows-protegido"


def test_ruta_protegida_de_n8n_con_sesion_responde_ok(lanzar_proxy, fake_n8n):
    puerto_n8n, _ = fake_n8n
    proxy = lanzar_proxy(puerto_n8n)
    status, _, data = proxy.request(
        "GET", "/rest/workflows-protegido", headers={"Cookie": "n8n-auth=sesion-valida"}
    )
    assert status == 200
    assert json.loads(data)["ok"] is True


# ---------------------------------------------------------------------
# Verificacion puntual pedida sobre el commit 646c96d (sin rediseñar
# nada): X-Forwarded-* correctos y no spoofeables por el cliente, y el
# callback OAuth (/rest/oauth2-credential/callback) llega intacto a n8n
# sin quedar interceptado por ninguna ruta local, con Basic Auth como
# primera capa (nunca bypaseada, nunca "traga" la vuelta de Google).
# ---------------------------------------------------------------------

def test_x_forwarded_for_no_es_spoofeable_por_el_cliente(lanzar_proxy, fake_n8n):
    """Un cliente que ya manda su PROPIO X-Forwarded-For/Proto/Host
    (con cualquier capitalizacion) no debe poder colarlo hacia n8n: el
    proxy tiene que ganar siempre con la IP/host/proto REALES de esta
    conexion -- si no, N8N_PROXY_HOPS=1 confiaria en un valor que el
    cliente publico controla, no en el hop real (este proxy)."""
    puerto_n8n, recibidas = fake_n8n
    proxy = lanzar_proxy(puerto_n8n)
    headers = {
        **_basic_auth_header(USUARIO, CLAVE),
        "X-Forwarded-For": "6.6.6.6",
        "X-Forwarded-Proto": "http",
        "X-Forwarded-Host": "atacante.example.com",
    }
    status, _, _ = proxy.request("GET", "/home", headers=headers)
    assert status == 200
    recibida = recibidas[-1]["headers"]
    assert recibida.get("X-Forwarded-For") == "127.0.0.1", recibida.get("X-Forwarded-For")
    assert recibida.get("X-Forwarded-Proto") == "https", recibida.get("X-Forwarded-Proto")
    assert recibida.get("X-Forwarded-Host") != "atacante.example.com"
    # Un solo valor de cada uno llega a n8n -- nunca dos headers
    # colisionando (que dejaria a n8n eligiendo entre el real y el
    # spoofeado de forma ambigua).
    crudo = [(k, v) for k, v in recibida.items() if k.lower() == "x-forwarded-for"]
    assert len(crudo) <= 1, f"deberia llegar UN solo X-Forwarded-For, llegaron: {crudo}"


def test_x_forwarded_host_refleja_el_host_real_del_request(lanzar_proxy, fake_n8n):
    puerto_n8n, recibidas = fake_n8n
    proxy = lanzar_proxy(puerto_n8n)
    headers = {**_basic_auth_header(USUARIO, CLAVE), "Host": "cajas-gabo-shadow-production.up.railway.app"}
    proxy.request("GET", "/home", headers=headers)
    assert recibidas[-1]["headers"].get("X-Forwarded-Host") == "cajas-gabo-shadow-production.up.railway.app"


def test_callback_oauth_sin_basic_auth_del_proxy_llega_a_n8n(lanzar_proxy, fake_n8n):
    """FIX del prompt repetido / requisito de OAuth: Google NO puede
    devolver la clave del proxy -- el callback tiene que llegar a n8n
    SIN el Basic Auth de CAJAS GABO, exactamente el caso real de cuando
    el navegador vuelve de Google. n8n es quien valida code/state."""
    puerto_n8n, recibidas = fake_n8n
    proxy = lanzar_proxy(puerto_n8n)
    status, headers, data = proxy.request(
        "GET", "/rest/oauth2-credential/callback?code=AUTH_CODE_DE_GOOGLE&state=xyz"
    )
    assert status == 200
    assert not _header(headers, "WWW-Authenticate")
    assert len(recibidas) == 1
    assert recibidas[0]["path"] == "/rest/oauth2-credential/callback?code=AUTH_CODE_DE_GOOGLE&state=xyz"
    assert "Authorization" not in recibidas[0]["headers"]


def test_callback_oauth_con_auth_llega_intacto_a_n8n_con_forwarded_correctos(lanzar_proxy, fake_n8n):
    """Caso real: el navegador YA tiene Basic Auth cacheado para este
    origen (se autentico para llegar a /n8n-admin -> /home -> conectar
    la credencial antes de ir a Google), asi que la vuelta desde Google
    la reenvia el propio navegador con las MISMAS credenciales Basic
    Auth -- comportamiento estandar de todo navegador para requests
    subsiguientes al mismo origen/realm. El callback debe llegar a n8n
    con el path/query EXACTOS que mando Google, sin que /webhook/*,
    /n8n-admin ni el chequeo de archivo estatico lo intercepten, y con
    X-Forwarded-Proto/Host/For correctos (para que n8n valide bien el
    redirect_uri con N8N_PROXY_HOPS=1)."""
    puerto_n8n, recibidas = fake_n8n
    proxy = lanzar_proxy(puerto_n8n)
    headers = {
        **_basic_auth_header(USUARIO, CLAVE),
        "Host": "cajas-gabo-shadow-production.up.railway.app",
        "Cookie": "n8n-auth=sesion-admin-ya-logueada",
    }
    ruta = "/rest/oauth2-credential/callback?code=AUTH_CODE_DE_GOOGLE&state=xyz"
    status, _, data = proxy.request("GET", ruta, headers=headers)

    assert status == 200
    assert json.loads(data)["recibido_en"] == ruta, "el query string (code/state) debe llegar intacto"
    assert len(recibidas) == 1, "ninguna otra ruta interfirio en el camino"
    recibida = recibidas[0]
    assert recibida["path"] == ruta
    assert recibida["method"] == "GET"
    assert "Authorization" not in recibida["headers"], "el Basic Auth del proxy nunca debe llegar a n8n"
    assert recibida["headers"].get("Cookie") == "n8n-auth=sesion-admin-ya-logueada"
    assert recibida["headers"].get("X-Forwarded-Proto") == "https"
    assert recibida["headers"].get("X-Forwarded-Host") == "cajas-gabo-shadow-production.up.railway.app"
    assert recibida["headers"].get("X-Forwarded-For") == "127.0.0.1"


def test_callback_oauth_no_coincide_con_ninguna_ruta_local_reservada(lanzar_proxy, fake_n8n):
    """Confirma explicitamente que /rest/oauth2-credential/callback no
    es ni /, ni /webhook/*, ni /n8n-admin, ni un archivo de
    n8n_frontend/ -- cae SIEMPRE en el pass-through generico hacia n8n
    (_proxy_n8n), nunca se sirve localmente ni se redirige."""
    puerto_n8n, _ = fake_n8n
    proxy = lanzar_proxy(puerto_n8n)
    status, headers, _ = proxy.request(
        "GET", "/rest/oauth2-credential/callback?code=X&state=Y",
        headers=_basic_auth_header(USUARIO, CLAVE),
    )
    assert status == 200  # nunca 302 (no es /, no es /n8n-admin)
    assert not _header(headers, "Location")
