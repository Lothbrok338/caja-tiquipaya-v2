#!/usr/bin/env python3
"""serve_v3_frontend.py — proxy temporal para la interfaz V3.

Sirve n8n_frontend/v3_control_cierres.html y reenvia /webhook/* a n8n
(por defecto localhost:5678), porque el HTML usa rutas RELATIVAS
(/webhook/tiq-v3-dev/*) y por lo tanto necesita compartir origen con n8n.
No contiene logica de negocio: solo sirve archivos estaticos y reenvia
bytes tal cual.

Portabilidad (migración Railway, 2026-09): el puerto y el origen de n8n
ahora se leen de variables de entorno (PORT / TIQ_N8N_ORIGIN) en vez de
estar fijos en el codigo. Railway inyecta PORT automaticamente para el
proceso publico del servicio; n8n sigue corriendo en el mismo contenedor
en localhost:5678 (ver scripts/start_n8n.sh), asi que TIQ_N8N_ORIGIN no
hace falta fijarla ahi. Sin ninguna de las dos variables, el
comportamiento es identico al de antes (8090 / localhost:5678).

Autenticacion (Railway pre-go-live, 2026-09): este proceso es el unico
punto de entrada publico de CAJAS GABO (frontend + proxy /webhook/* hacia
n8n), asi que la autenticacion HTTP Basic vive ACA, nunca en n8n. Las
credenciales salen exclusivamente de TIQ_AUTH_USERNAME/TIQ_AUTH_PASSWORD
(nunca hardcodeadas, nunca logueadas). Si no estan configuradas (ambas,
no vacias), el proceso FALLA CERRADO: /healthz sigue respondiendo 200
para que Railway no mate el contenedor, pero cualquier otra ruta responde
503 en vez de quedar abierta. Con credenciales configuradas, todo lo que
no sea /healthz exige Basic auth valido (comparacion en tiempo constante
via hmac.compare_digest) o responde 401 con WWW-Authenticate. El header
Authorization nunca se reenvia hacia n8n (_proxy ya solo reenviaba
Content-Type; ver seccion correspondiente).

n8n bajo demanda / Serverless Sleep (Railway, 2026-09): n8n ya NO arranca
al iniciar el contenedor (scripts/railway_entrypoint.sh ya no lo toca).
Mantenerlo siempre arriba le impedia a Railway (sleepApplication=true)
dormir el contenedor de verdad: n8n sostiene conexiones persistentes a
Postgres y el proceso quedaba usando ~0.54 GB de RAM sin uso real. Ahora
GestorN8N (mas abajo) arranca n8n (via scripts/start_n8n.sh) recien
cuando llega la primera request de /webhook/* autenticada, espera a que
este REALMENTE listo antes de reenviar, y lo apaga solo (SIGTERM limpio)
despues de TIQ_N8N_IDLE_TIMEOUT_SECONDS sin actividad de webhook -- nunca
mientras haya una request en curso. Si llega otro webhook despues de
apagarse, se vuelve a arrancar automaticamente. /healthz NUNCA toca
GestorN8N: responde 200 este n8n arriba o dormido. Nada de esto cambia
autenticacion, fail-closed, el no-reenvio de Authorization, ni ningun
workflow/regla de negocio.

Fix de carrera de readiness (Railway, 2026-09): el puerto 5678 abre ANTES
de que n8n termine de activar los workflows (evidencia real: puerto
escuchando ~13:46:57, workflows activos recien ~13:47:01-02) -- un simple
"socket abierto" no basta, el primer webhook llegaba antes de tiempo y
n8n respondia 404 (workflow todavia no registrado). GestorN8N ahora
considera a n8n listo UNICAMENTE cuando `GET {N8N_ORIGIN}/healthz/readiness`
responde HTTP 200 (endpoint propio de n8n para esto), reintentando cada
0.2s hasta TIQ_N8N_START_TIMEOUT_SECONDS. Sin sleep fijo.
"""
import base64
import hmac
import http.server
import os
import subprocess
import threading
import time
import urllib.error
import urllib.request

_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(_SCRIPTS_DIR)

os.chdir(os.path.join(RAIZ, "n8n_frontend"))

N8N_ORIGIN = os.environ.get("TIQ_N8N_ORIGIN", "http://localhost:5678")
LISTEN_PORT = int(os.environ.get("PORT", "8090"))

# Override solo para tests (fake_n8n_starter en vez del script real, que
# arranca n8n de verdad y no existe en el sandbox de test). En produccion
# siempre es scripts/start_n8n.sh.
N8N_START_SCRIPT = os.environ.get("TIQ_N8N_START_SCRIPT", os.path.join(_SCRIPTS_DIR, "start_n8n.sh"))
N8N_IDLE_TIMEOUT_SECONDS = float(os.environ.get("TIQ_N8N_IDLE_TIMEOUT_SECONDS", "300"))
N8N_START_TIMEOUT_SECONDS = float(os.environ.get("TIQ_N8N_START_TIMEOUT_SECONDS", "60"))
N8N_REAPER_INTERVAL_SECONDS = float(os.environ.get("TIQ_N8N_REAPER_INTERVAL_SECONDS", "30"))


class GestorN8N:
    """Ciclo de vida de n8n bajo demanda: un solo lock protege arranque,
    conteo de requests activas y apagado, para que no se dupliquen
    procesos si varias requests de webhook coinciden mientras n8n esta
    levantando, y para que el reaper de inactividad nunca apague n8n con
    una request en curso."""

    def __init__(self, n8n_origin, start_script, cwd, idle_timeout, start_timeout, reaper_interval):
        self._readiness_url = n8n_origin.rstrip("/") + "/healthz/readiness"
        self._start_script = start_script
        self._cwd = cwd
        self._idle_timeout = idle_timeout
        self._start_timeout = start_timeout
        self._reaper_interval = reaper_interval
        self._lock = threading.Lock()
        self._proceso = None
        self._ultima_actividad = time.time()
        self._solicitudes_activas = 0
        hilo = threading.Thread(target=self._loop_reaper, daemon=True)
        hilo.start()

    def _listo(self):
        """True UNICAMENTE cuando /healthz/readiness responde HTTP 200.
        Que el puerto este abierto no alcanza: n8n lo abre antes de
        terminar de activar los workflows (carrera real vista en
        Railway), asi que un simple connect-and-close daba falsos
        positivos y el primer webhook llegaba antes de tiempo (404)."""
        try:
            with urllib.request.urlopen(self._readiness_url, timeout=1.0) as r:
                return r.status == 200
        except OSError:
            # Cubre tanto fallos de conexion (n8n todavia ni abrio el
            # puerto) como urllib.error.HTTPError por un status != 2xx
            # (p.ej. 503 mientras los workflows todavia se activan):
            # HTTPError y URLError son subclases de OSError.
            return False

    def preparar_para_webhook(self):
        """Llamar al inicio de cada request que se va a reenviar a n8n:
        marca actividad, arranca n8n si hace falta (sin duplicar proceso
        si ya esta arrancando/arriba) y bloquea hasta que este REALMENTE
        listo (ver _listo). Lanza TimeoutError si no levanta a tiempo.
        SIEMPRE debe ir seguido de liberar_despues_de_webhook() en un
        finally, haya o no lanzado."""
        with self._lock:
            self._solicitudes_activas += 1
            self._ultima_actividad = time.time()
            if self._proceso is not None and self._proceso.poll() is not None:
                self._proceso = None  # crasheo solo -- se puede reintentar
            if self._proceso is None and not self._listo():
                self._proceso = subprocess.Popen(["bash", self._start_script], cwd=self._cwd)
            limite = time.time() + self._start_timeout
            listo = False
            while time.time() < limite:
                if self._listo():
                    listo = True
                    break
                time.sleep(0.2)
        if not listo:
            raise TimeoutError(
                "n8n no quedo listo ({}) dentro de {}s".format(self._readiness_url, self._start_timeout)
            )

    def liberar_despues_de_webhook(self):
        with self._lock:
            self._solicitudes_activas = max(0, self._solicitudes_activas - 1)
            self._ultima_actividad = time.time()

    def _apagar_si_corresponde(self):
        with self._lock:
            if self._proceso is None or self._solicitudes_activas > 0:
                return
            if time.time() - self._ultima_actividad < self._idle_timeout:
                return
            proceso, self._proceso = self._proceso, None
        proceso.terminate()
        try:
            proceso.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proceso.kill()
            proceso.wait(timeout=5)

    def _loop_reaper(self):
        while True:
            time.sleep(self._reaper_interval)
            self._apagar_si_corresponde()


N8N_MANAGER = GestorN8N(
    N8N_ORIGIN, N8N_START_SCRIPT, RAIZ,
    N8N_IDLE_TIMEOUT_SECONDS, N8N_START_TIMEOUT_SECONDS, N8N_REAPER_INTERVAL_SECONDS,
)

AUTH_USERNAME = os.environ.get("TIQ_AUTH_USERNAME", "")
AUTH_PASSWORD = os.environ.get("TIQ_AUTH_PASSWORD", "")
AUTH_CONFIGURED = bool(AUTH_USERNAME) and bool(AUTH_PASSWORD)

if not AUTH_CONFIGURED:
    print(
        "[serve_v3_frontend] ADVERTENCIA: TIQ_AUTH_USERNAME/TIQ_AUTH_PASSWORD no estan "
        "configuradas (o alguna esta vacia). Todas las rutas salvo /healthz responderan "
        "503 hasta que ambas variables esten configuradas (fail closed).",
        flush=True,
    )


def _credenciales_validas(header_authorization):
    """True si `header_authorization` trae credenciales HTTP Basic que
    coinciden con TIQ_AUTH_USERNAME/TIQ_AUTH_PASSWORD. Comparacion en
    tiempo constante (hmac.compare_digest) para no filtrar por timing
    cuanto de la clave es correcto. Nunca loguea el header ni su
    contenido decodificado."""
    if not AUTH_CONFIGURED or not header_authorization:
        return False
    esquema, _, credenciales_b64 = header_authorization.partition(" ")
    if esquema != "Basic" or not credenciales_b64:
        return False
    try:
        decodificado = base64.b64decode(credenciales_b64, validate=True).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return False
    usuario, separador, clave = decodificado.partition(":")
    if not separador:
        return False
    usuario_ok = hmac.compare_digest(usuario.encode("utf-8"), AUTH_USERNAME.encode("utf-8"))
    clave_ok = hmac.compare_digest(clave.encode("utf-8"), AUTH_PASSWORD.encode("utf-8"))
    return usuario_ok and clave_ok


class Handler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        # Sin esto, el navegador puede quedarse con una version vieja del
        # HTML/JS tras cada edicion (visto en vivo: el proxy ya servia el
        # archivo corregido, pero el navegador mostraba el cache).
        self.send_header("Cache-Control", "no-store, must-revalidate")
        super().end_headers()

    def _autenticar(self):
        """Gate de autenticacion para toda ruta salvo /healthz. Si ya
        respondio (503 sin credenciales configuradas, o 401 sin
        Basic auth valido), devuelve False y el llamador debe retornar
        sin hacer nada mas."""
        if not AUTH_CONFIGURED:
            self.send_response(503)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"Service Unavailable: authentication not configured")
            return False
        if _credenciales_validas(self.headers.get("Authorization")):
            return True
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="CAJAS GABO"')
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"Unauthorized")
        return False

    def do_GET(self):
        if self.path == "/healthz":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"OK")
            return
        if not self._autenticar():
            return
        if self.path == "/":
            # Evita el listado de directorio ("Directory listing for /") de
            # SimpleHTTPRequestHandler: no hay index.html en n8n_frontend/,
            # asi que la raiz redirige a la interfaz real de CAJAS GABO.
            self.send_response(302)
            self.send_header("Location", "/v3_control_cierres.html")
            self.end_headers()
            return
        if self.path.startswith("/webhook/"):
            return self._proxy("GET")
        return super().do_GET()

    def do_POST(self):
        if not self._autenticar():
            return
        return self._proxy("POST")

    def _proxy(self, method):
        try:
            N8N_MANAGER.preparar_para_webhook()
        except TimeoutError:
            self.send_response(503)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"Service Unavailable: n8n no arranco a tiempo")
            N8N_MANAGER.liberar_despues_de_webhook()
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length) if length else None
            req = urllib.request.Request(
                N8N_ORIGIN + self.path,
                data=body,
                method=method,
                # Deliberado: solo se reenvia Content-Type. Authorization
                # (y cualquier otro header del cliente publico) nunca llega
                # a n8n -- n8n no necesita saber nada de la autenticacion
                # del proxy publico.
                headers={"Content-Type": self.headers.get("Content-Type", "application/json")},
            )
            try:
                with urllib.request.urlopen(req) as r:
                    self.send_response(r.status)
                    self.send_header("Content-Type", r.headers.get("Content-Type", "application/json"))
                    self.end_headers()
                    self.wfile.write(r.read())
            except urllib.error.HTTPError as e:
                self.send_response(e.code)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(e.read())
        finally:
            N8N_MANAGER.liberar_despues_de_webhook()


if __name__ == "__main__":
    http.server.HTTPServer(("0.0.0.0", LISTEN_PORT), Handler).serve_forever()
