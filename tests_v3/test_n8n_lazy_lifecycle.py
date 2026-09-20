"""tests_v3/test_n8n_lazy_lifecycle.py — migración Railway 2026-09.

Verifica el arranque/apagado bajo demanda de n8n (GestorN8N, en
scripts/serve_v3_frontend.py), agregado para que Railway
`sleepApplication` pueda dormir de verdad el contenedor cuando CAJAS
GABO no se usa: antes n8n arrancaba siempre al iniciar el contenedor y
sostenía conexiones persistentes a Postgres sin importar el tráfico
(~0.54 GB de RAM en uso incluso sin actividad).

Corre el script REAL como subproceso (mismo patrón que
tests_v3/test_frontend_auth.py) contra un "n8n falso" que, a diferencia
de ese archivo, NO está arriba de entrada: arranca recién cuando
GestorN8N ejecuta el script de arranque configurado vía
TIQ_N8N_START_SCRIPT (un starter falso que simula la latencia real de
boot de n8n), para poder probar que el proxy efectivamente ESPERA antes
de reenviar.

No repite las pruebas de autenticación/fail-closed/redirect de
test_frontend_auth.py (esa lógica no cambió); se enfoca en:
  - n8n no arranca al iniciar el proxy ni con /healthz;
  - una request sin auth nunca arranca n8n;
  - el primer webhook autenticado arranca n8n y espera a que esté listo;
  - Authorization sigue sin reenviarse con el nuevo flujo;
  - tras inactividad, n8n se apaga solo, y un webhook posterior lo
    vuelve a arrancar automáticamente;
  - una request activa nunca deja que el reaper de inactividad apague
    n8n a mitad de camino;
  - si el arranque de n8n nunca responde a tiempo, el proxy falla con
    503 (nunca cuelga, nunca miente con un 200);
  - readiness REAL vía GET /healthz/readiness (no solo puerto abierto):
    el n8n falso puede abrir el puerto de inmediato y responder 503 en
    /healthz/readiness durante un intervalo configurable antes de pasar
    a 200 (misma carrera vista en Railway: puerto listo ~13:46:57,
    workflows activos recién ~13:47:01-02) — se verifica que el webhook
    original NO se reenvía hasta después de ese 200, y que los probes de
    /healthz/readiness nunca se cuentan como llamadas al webhook.

Uso: python -m pytest tests_v3/test_n8n_lazy_lifecycle.py -q
"""
import base64
import http.client
import json
import os
import socket
import stat
import subprocess
import sys
import time

import pytest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(RAIZ, "scripts", "serve_v3_frontend.py")

USUARIO = "gabo_test"
CLAVE = "clave-super-secreta-test-123"

# n8n falso: arranca cuando alguien lo ejecuta (nunca antes), registra
# cada request en un archivo JSONL (proceso aparte, no puede compartir
# memoria con el test) y puede demorar artificialmente una ruta puntual
# vía FAKE_N8N_DELAY_PATHS, para probar que una request lenta en curso
# no deja que el reaper de inactividad apague n8n a mitad de camino.
#
# /healthz/readiness simula la carrera real de Railway: el puerto abre
# de inmediato (como en la vida real) pero /healthz/readiness responde
# 503 hasta que pasan FAKE_N8N_READINESS_DELAY segundos desde que ESTE
# proceso arrancó (no desde el boot del starter) -- recién ahí pasa a
# 200. Nunca se registra en LOG: un probe de readiness no es una
# llamada funcional al webhook.
_FAKE_N8N_SERVER_PY = r'''
import http.server
import json
import os
import time

PUERTO = int(os.environ["FAKE_N8N_PORT"])
LOG = os.environ["FAKE_N8N_LOG"]
DELAY_PATHS = json.loads(os.environ.get("FAKE_N8N_DELAY_PATHS", "{}"))
READINESS_DELAY = float(os.environ.get("FAKE_N8N_READINESS_DELAY", "0"))
_INICIO = time.time()


class Handler(http.server.BaseHTTPRequestHandler):
    def _readiness(self):
        listo = (time.time() - _INICIO) >= READINESS_DELAY
        self.send_response(200 if listo else 503)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"status": "ok"}' if listo else b'{"status": "not ready"}')

    def _atender(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        body = self.rfile.read(length) if length else b""
        demora = DELAY_PATHS.get(self.path)
        if demora:
            time.sleep(demora)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "method": self.command,
                "path": self.path,
                "headers": dict(self.headers.items()),
                "body": body.decode("utf-8", "replace"),
            }) + "\n")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"ok": True, "path": self.path}).encode("utf-8"))

    def do_GET(self):
        if self.path == "/healthz/readiness":
            return self._readiness()
        self._atender()

    def do_POST(self):
        self._atender()

    def log_message(self, *args, **kwargs):
        pass


http.server.HTTPServer(("127.0.0.1", PUERTO), Handler).serve_forever()
'''

_FAKE_N8N_STARTER_SH = """#!/usr/bin/env bash
set -euo pipefail
sleep "${FAKE_N8N_BOOT_DELAY:-0.3}"
exec python3 "${FAKE_N8N_SERVER_PY}"
"""


def _puerto_libre():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _basic_auth_header(usuario, clave):
    token = base64.b64encode(f"{usuario}:{clave}".encode("utf-8")).decode("ascii")
    return {"Authorization": f"Basic {token}"}


def _esperar(condicion, timeout=10, intervalo=0.05):
    limite = time.time() + timeout
    while time.time() < limite:
        if condicion():
            return True
        time.sleep(intervalo)
    return False


def _puerto_abierto(host, puerto):
    try:
        with socket.create_connection((host, puerto), timeout=0.3):
            return True
    except OSError:
        return False


def _leer_log(ruta):
    if not os.path.exists(ruta):
        return []
    with open(ruta, encoding="utf-8") as f:
        return [json.loads(linea) for linea in f if linea.strip()]


def _estado_readiness(host, puerto):
    """GET directo (sin pasar por el proxy) a /healthz/readiness, para
    verificar el fixture en sí mismo. None si todavía no hay nadie
    escuchando en ese puerto."""
    conn = http.client.HTTPConnection(host, puerto, timeout=1)
    try:
        conn.request("GET", "/healthz/readiness")
        resp = conn.getresponse()
        resp.read()
        return resp.status
    except OSError:
        return None
    finally:
        conn.close()


@pytest.fixture()
def fake_n8n_fixtures(tmp_path):
    """Escribe el n8n falso (arranca bajo demanda; NO está corriendo al
    crear la fixture) y devuelve sus rutas + el puerto que usará."""
    server_py = tmp_path / "fake_n8n_server.py"
    server_py.write_text(_FAKE_N8N_SERVER_PY, encoding="utf-8")

    starter_sh = tmp_path / "fake_n8n_starter.sh"
    starter_sh.write_text(_FAKE_N8N_STARTER_SH, encoding="utf-8")
    starter_sh.chmod(starter_sh.stat().st_mode | stat.S_IEXEC)

    log = tmp_path / "fake_n8n_log.jsonl"
    return {
        "server_py": str(server_py),
        "starter_sh": str(starter_sh),
        "log": str(log),
        "puerto": _puerto_libre(),
    }


class _ProxyProceso:
    def __init__(self, puerto, proceso):
        self.puerto = puerto
        self.proceso = proceso

    def request(self, method, path, headers=None, body=None, timeout=10):
        conn = http.client.HTTPConnection("127.0.0.1", self.puerto, timeout=timeout)
        try:
            conn.request(method, path, body=body, headers=headers or {})
            resp = conn.getresponse()
            data = resp.read()
            return resp.status, dict(resp.getheaders()), data
        finally:
            conn.close()


@pytest.fixture()
def lanzar_proxy():
    procesos = []

    def _lanzar(env_extra=None, fake_n8n=None, boot_delay="0.3", idle_timeout="300",
                start_timeout="10", reaper_interval="30", delay_paths=None, readiness_delay="0"):
        puerto = _puerto_libre()
        env = dict(os.environ)
        env.pop("TIQ_AUTH_USERNAME", None)
        env.pop("TIQ_AUTH_PASSWORD", None)
        env["PORT"] = str(puerto)
        env["TIQ_N8N_IDLE_TIMEOUT_SECONDS"] = str(idle_timeout)
        env["TIQ_N8N_START_TIMEOUT_SECONDS"] = str(start_timeout)
        env["TIQ_N8N_REAPER_INTERVAL_SECONDS"] = str(reaper_interval)
        if fake_n8n:
            env["TIQ_N8N_ORIGIN"] = f"http://127.0.0.1:{fake_n8n['puerto']}"
            env["TIQ_N8N_START_SCRIPT"] = fake_n8n["starter_sh"]
            env["FAKE_N8N_PORT"] = str(fake_n8n["puerto"])
            env["FAKE_N8N_LOG"] = fake_n8n["log"]
            env["FAKE_N8N_SERVER_PY"] = fake_n8n["server_py"]
            env["FAKE_N8N_BOOT_DELAY"] = str(boot_delay)
            env["FAKE_N8N_READINESS_DELAY"] = str(readiness_delay)
            if delay_paths:
                env["FAKE_N8N_DELAY_PATHS"] = json.dumps(delay_paths)
        env.update(env_extra or {})
        proceso = subprocess.Popen(
            [sys.executable, SCRIPT], cwd=RAIZ, env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
        procesos.append(proceso)
        if not _esperar(lambda: _puerto_abierto("127.0.0.1", puerto), timeout=10):
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
# n8n NO arranca solo (ni al iniciar el proxy, ni con /healthz, ni sin auth)
# ---------------------------------------------------------------------

def test_n8n_no_arranca_al_iniciar_el_proxy(lanzar_proxy, fake_n8n_fixtures):
    lanzar_proxy({"TIQ_AUTH_USERNAME": USUARIO, "TIQ_AUTH_PASSWORD": CLAVE}, fake_n8n=fake_n8n_fixtures)
    time.sleep(0.5)  # tiempo de sobra para que arrancara si el fix no funcionara
    assert not _puerto_abierto("127.0.0.1", fake_n8n_fixtures["puerto"])
    assert _leer_log(fake_n8n_fixtures["log"]) == []


def test_healthz_nunca_arranca_n8n(lanzar_proxy, fake_n8n_fixtures):
    proxy = lanzar_proxy({"TIQ_AUTH_USERNAME": USUARIO, "TIQ_AUTH_PASSWORD": CLAVE}, fake_n8n=fake_n8n_fixtures)
    for _ in range(3):
        status, _, body = proxy.request("GET", "/healthz")
        assert status == 200
        assert body == b"OK"
    assert not _puerto_abierto("127.0.0.1", fake_n8n_fixtures["puerto"])
    assert _leer_log(fake_n8n_fixtures["log"]) == []


def test_webhook_sin_auth_no_arranca_n8n(lanzar_proxy, fake_n8n_fixtures):
    proxy = lanzar_proxy({"TIQ_AUTH_USERNAME": USUARIO, "TIQ_AUTH_PASSWORD": CLAVE}, fake_n8n=fake_n8n_fixtures)
    status, _, _ = proxy.request("GET", "/webhook/tiq-v3-dev/estado")
    assert status == 401
    assert not _puerto_abierto("127.0.0.1", fake_n8n_fixtures["puerto"])
    assert _leer_log(fake_n8n_fixtures["log"]) == []


# ---------------------------------------------------------------------
# Primer webhook autenticado arranca n8n y ESPERA a que esté listo
# ---------------------------------------------------------------------

def test_primer_webhook_arranca_n8n_y_espera_que_este_listo(lanzar_proxy, fake_n8n_fixtures):
    proxy = lanzar_proxy(
        {"TIQ_AUTH_USERNAME": USUARIO, "TIQ_AUTH_PASSWORD": CLAVE},
        fake_n8n=fake_n8n_fixtures, boot_delay="1.0",
    )
    assert not _puerto_abierto("127.0.0.1", fake_n8n_fixtures["puerto"])  # todavía dormido

    status, _, data = proxy.request(
        "GET", "/webhook/tiq-v3-dev/estado", headers=_basic_auth_header(USUARIO, CLAVE), timeout=15,
    )

    assert status == 200
    assert json.loads(data)["path"] == "/webhook/tiq-v3-dev/estado"
    registros = _leer_log(fake_n8n_fixtures["log"])
    assert len(registros) == 1
    assert not any(k.lower() == "authorization" for k in registros[0]["headers"])


# ---------------------------------------------------------------------
# Apagado por inactividad + reinicio automático
# ---------------------------------------------------------------------

def test_n8n_se_apaga_tras_inactividad_y_vuelve_a_arrancar(lanzar_proxy, fake_n8n_fixtures):
    proxy = lanzar_proxy(
        {"TIQ_AUTH_USERNAME": USUARIO, "TIQ_AUTH_PASSWORD": CLAVE},
        fake_n8n=fake_n8n_fixtures, boot_delay="0.2",
        idle_timeout="1", reaper_interval="0.3",
    )

    status, _, _ = proxy.request("GET", "/webhook/tiq-v3-dev/estado", headers=_basic_auth_header(USUARIO, CLAVE))
    assert status == 200
    assert _puerto_abierto("127.0.0.1", fake_n8n_fixtures["puerto"])

    apagado = _esperar(lambda: not _puerto_abierto("127.0.0.1", fake_n8n_fixtures["puerto"]), timeout=10)
    assert apagado, "n8n debería haberse apagado solo tras el período de inactividad"

    status2, _, _ = proxy.request("GET", "/webhook/tiq-v3-dev/estado", headers=_basic_auth_header(USUARIO, CLAVE))
    assert status2 == 200
    assert len(_leer_log(fake_n8n_fixtures["log"])) == 2


def test_no_apaga_n8n_con_solicitud_activa(lanzar_proxy, fake_n8n_fixtures):
    proxy = lanzar_proxy(
        {"TIQ_AUTH_USERNAME": USUARIO, "TIQ_AUTH_PASSWORD": CLAVE},
        fake_n8n=fake_n8n_fixtures, boot_delay="0.1",
        idle_timeout="0.5", reaper_interval="0.2",
        delay_paths={"/webhook/lento": 2.0},
    )
    # El reaper corre cada 0.2s con idle_timeout=0.5s: si no respetara la
    # request activa, mataría a n8n bastante antes de que responda a los
    # 2s. Si esto sigue devolviendo 200, la solicitud activa lo protegió.
    status, _, data = proxy.request(
        "GET", "/webhook/lento", headers=_basic_auth_header(USUARIO, CLAVE), timeout=10,
    )
    assert status == 200
    assert json.loads(data)["path"] == "/webhook/lento"


# ---------------------------------------------------------------------
# Arranque que nunca responde -> 503, nunca cuelga ni miente
# ---------------------------------------------------------------------

def test_arranque_fallido_responde_503(lanzar_proxy, tmp_path):
    starter_roto = tmp_path / "starter_roto.sh"
    starter_roto.write_text("#!/usr/bin/env bash\nsleep 5\n", encoding="utf-8")
    starter_roto.chmod(starter_roto.stat().st_mode | stat.S_IEXEC)
    puerto_nunca_escucha = _puerto_libre()

    proxy = lanzar_proxy(
        {
            "TIQ_AUTH_USERNAME": USUARIO, "TIQ_AUTH_PASSWORD": CLAVE,
            "TIQ_N8N_ORIGIN": f"http://127.0.0.1:{puerto_nunca_escucha}",
            "TIQ_N8N_START_SCRIPT": str(starter_roto),
        },
        start_timeout="1",
    )

    status, _, body = proxy.request(
        "GET", "/webhook/x", headers=_basic_auth_header(USUARIO, CLAVE), timeout=10,
    )
    assert status == 503
    assert b"n8n" in body


# ---------------------------------------------------------------------
# Readiness REAL (GET /healthz/readiness), no solo puerto abierto
# ---------------------------------------------------------------------

def test_fake_n8n_readiness_pasa_de_503_a_200(fake_n8n_fixtures):
    """Sanity check del fixture en sí mismo (sin pasar por el proxy):
    1) puerto abierto, 2) /healthz/readiness responde 503 durante el
    intervalo configurado, 3) luego 200, y los probes nunca quedan en
    el log de requests (no son llamadas funcionales al webhook)."""
    puerto = fake_n8n_fixtures["puerto"]
    env = dict(os.environ)
    env["FAKE_N8N_PORT"] = str(puerto)
    env["FAKE_N8N_LOG"] = fake_n8n_fixtures["log"]
    env["FAKE_N8N_READINESS_DELAY"] = "1.0"
    proceso = subprocess.Popen(
        [sys.executable, fake_n8n_fixtures["server_py"]], env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        assert _esperar(lambda: _puerto_abierto("127.0.0.1", puerto), timeout=5), "el puerto debe abrir enseguida"

        # 2) recién abierto, /healthz/readiness todavía debe dar 503.
        assert _estado_readiness("127.0.0.1", puerto) == 503

        # 3) después del intervalo configurado, pasa a 200.
        listo = _esperar(lambda: _estado_readiness("127.0.0.1", puerto) == 200, timeout=5)
        assert listo, "/healthz/readiness debería haber pasado a 200"

        assert _leer_log(fake_n8n_fixtures["log"]) == [], "los probes de readiness no deben registrarse"
    finally:
        proceso.terminate()
        try:
            proceso.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proceso.kill()


def test_espera_readiness_real_no_solo_puerto_abierto(lanzar_proxy, fake_n8n_fixtures):
    """4) El webhook original NO se reenvía hasta que /healthz/readiness
    da 200: con el puerto abierto casi de inmediato (boot_delay chico)
    pero readiness recién a 1.5s, la request tiene que tardar al menos
    ese tiempo -- y el único request logueado debe ser el webhook real,
    nunca un probe de readiness."""
    proxy = lanzar_proxy(
        {"TIQ_AUTH_USERNAME": USUARIO, "TIQ_AUTH_PASSWORD": CLAVE},
        fake_n8n=fake_n8n_fixtures, boot_delay="0.1", readiness_delay="1.5",
    )

    inicio = time.time()
    status, _, data = proxy.request(
        "GET", "/webhook/tiq-v3-dev/estado", headers=_basic_auth_header(USUARIO, CLAVE), timeout=15,
    )
    duracion = time.time() - inicio

    assert status == 200
    assert json.loads(data)["path"] == "/webhook/tiq-v3-dev/estado"
    assert duracion >= 1.0, f"volvió en {duracion:.2f}s -- no parece haber esperado readiness real, no solo el puerto"

    registros = _leer_log(fake_n8n_fixtures["log"])
    assert len(registros) == 1, "los probes de /healthz/readiness no deben contarse como llamadas al webhook"
    assert registros[0]["path"] == "/webhook/tiq-v3-dev/estado"
