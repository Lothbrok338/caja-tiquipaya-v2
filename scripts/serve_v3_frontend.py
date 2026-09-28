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

Autenticacion (Railway pre-go-live, 2026-09; ACOTADA a CAJAS GABO desde
el fix post-editor de mas abajo): este proceso es el unico punto de
entrada publico de CAJAS GABO (frontend + proxy /webhook/* hacia n8n),
asi que la autenticacion HTTP Basic vive ACA, nunca en n8n -- pero SOLO
para lo que es de CAJAS GABO: `/`, los archivos estaticos de
n8n_frontend/ y `/webhook/*`. Las credenciales salen exclusivamente de
TIQ_AUTH_USERNAME/TIQ_AUTH_PASSWORD (nunca hardcodeadas, nunca
logueadas). Si no estan configuradas (ambas, no vacias), esas rutas
FALLAN CERRADAS: /healthz sigue respondiendo 200 para que Railway no
mate el contenedor, pero cualquier otra ruta de CAJAS GABO responde 503
en vez de quedar abierta. Con credenciales configuradas, esas rutas
exigen Basic auth valido (comparacion en tiempo constante via
hmac.compare_digest) o responden 401 con WWW-Authenticate. El header
Authorization nunca se reenvia hacia n8n (_proxy ya solo reenviaba
Content-Type; ver seccion correspondiente).

FIX (bug real, post-exposicion del editor n8n): las rutas propias de
n8n (`/n8n-admin`, `/home*`, `/signin*`, `/rest/*`, `/credentials/*`,
`/workflow/*`, `/types/*`, assets, el callback OAuth, el WebSocket de
`/rest/push`, etc. -- ver Handler._proxy_n8n/_proxy_websocket_n8n) NO
pasan por _autenticar(): la SPA de n8n dispara decenas de llamadas
internas por segundo, y el Basic Auth del proxy delante de TODAS ellas
generaba prompts de usuario/clave repetidos (el navegador no
reautentica esas llamadas de forma consistente). Esas rutas quedan
protegidas EXCLUSIVAMENTE por el login nativo de n8n (su propia cookie
de sesion) -- nunca sin autenticacion alguna, solo con otra
autenticacion (la de n8n), independiente de si TIQ_AUTH_USERNAME/
TIQ_AUTH_PASSWORD estan configuradas o no.

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

Acceso admin al editor n8n en el mismo dominio (2026-09): antes el unico
acceso al editor era un tunel SSH -- dificultaba tareas administrativas
normales (p.ej. reconectar credenciales OAuth de Google Drive). Se evaluo
exponerlo bajo un SUBPATH (/n8n/*) y se descarto: n8n usa N8N_PATH para
eso, pero hay un issue abierto y sin resolver en el propio n8n
(github.com/n8n-io/n8n/issues/19635) que documenta que la mayoria de sus
endpoints IGNORAN ese basePath -- redirects de la UI y el callback OAuth
quedarian rotos de forma impredecible. En vez de eso, n8n sigue creyendo
que vive en la RAIZ (nunca se toca N8N_PATH): `/n8n-admin` es solo un
redirect (302) a `/home` (la pantalla inicial real de n8n), y CUALQUIER
otra ruta que no sea un archivo estatico local de n8n_frontend/ ni
`/webhook/*` se reenvia tal cual hacia n8n en su raiz real (ver
Handler._proxy_n8n) -- `/rest/*`, `/home*`, `/workflow/*`,
`/credentials/*`, `/executions/*`, `/signin`, `/assets/*`, etc., todo
sin reescribir nada, porque hoy n8n_frontend/ solo tiene dos .html
sueltos (sin heredar ningun nombre de ruta propio de n8n). Esto es un
DENYLIST (reservamos lo nuestro, todo lo demas es de n8n), no un
allowlist de rutas de n8n: mas robusto ante rutas nuevas que agregue
una version futura de n8n (aunque la imagen fija n8n@2.35.7).

A diferencia de `_proxy` (solo GET/POST de /webhook/*, solo reenvia
Content-Type, pensado para webhooks sin sesion), `_proxy_n8n` es un
proxy completo: reenvia todos los metodos que el editor necesita (GET/
POST/PUT/PATCH/DELETE/OPTIONS), TODOS los headers salvo
Authorization/Host/Content-Length/Connection/Transfer-Encoding/
Accept-Encoding (Cookie y Set-Cookie SI viajan en ambos sentidos -- el
login propio de n8n depende de eso), agrega X-Forwarded-Proto/Host/For
(n8n necesita N8N_PROXY_HOPS=1 para confiar en ellos, ver
scripts/start_n8n.sh) y transmite el cuerpo de la respuesta en bloques
(Transfer-Encoding: chunked si n8n no da Content-Length) en vez de
bufferizarlo entero.

El canal de tiempo real del editor (`/rest/push`) usa WebSocket real
(RFC 6455), nunca Server-Sent Events -- se evaluo N8N_PUSH_BACKEND=sse
como atajo (evita implementar el upgrade) y se descarto a pedido
explicito: hay reportes de bugs de validacion de origen con SSE en n8n
2.x. El soporte de WebSocket es un PASS-THROUGH crudo a nivel de
sockets (Handler._proxy_websocket_n8n): reenvia el handshake HTTP de
upgrade, relee la respuesta de n8n, y si es 101 Switching Protocols
copia bytes sin interpretar en ambos sentidos entre el socket del
navegador y un socket nuevo hacia n8n hasta que cualquiera cierre --
nunca hace falta entender el framing/masking de WebSocket (eso lo
manejan el navegador y n8n en cada punta). Por eso el servidor pasa de
HTTPServer a ThreadingHTTPServer mas abajo: una conexion WebSocket (o
cualquier respuesta larga) queda abierta minutos u horas, y con el
servidor de un solo hilo de antes eso hubiera bloqueado TODO el proceso
-- incluido /webhook/* en produccion -- mientras el editor estuviera
abierto.

Todo esto reutiliza GestorN8N sin cambiarlo: tanto _proxy_n8n como el
pass-through de WebSocket llaman preparar_para_webhook()/
liberar_despues_de_webhook() igual que _proxy, asi que abrir el editor
tambien despierta n8n bajo demanda, y una sesion de editor abierta (o
cualquier request al editor en curso) sigue contando como actividad
para el apagado por inactividad -- el mecanismo de sleep/on-demand no
cambia en absoluto.
"""
import base64
import hmac
import http.server
import os
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(_SCRIPTS_DIR)

os.chdir(os.path.join(RAIZ, "n8n_frontend"))

N8N_ORIGIN = os.environ.get("TIQ_N8N_ORIGIN", "http://localhost:5678")
LISTEN_PORT = int(os.environ.get("PORT", "8090"))

# Acceso admin al editor n8n (2026-09): _N8N_HOST/_N8N_PORT son el mismo
# origen que N8N_ORIGIN, ya separados, para poder abrir un socket TCP
# crudo hacia n8n en el pass-through de WebSocket (ver
# Handler._proxy_websocket_n8n) -- ahi no se puede usar urllib (solo
# entiende HTTP normal, no el handshake de upgrade).
_N8N_URL = urllib.parse.urlsplit(N8N_ORIGIN)
N8N_HOST = _N8N_URL.hostname or "localhost"
N8N_PORT = _N8N_URL.port or (443 if _N8N_URL.scheme == "https" else 80)


class _SinRedirect(urllib.request.HTTPRedirectHandler):
    """Neutraliza el seguimiento automatico de 3xx de urlopen() -- solo
    para el proxy del editor n8n (Handler._proxy_n8n). n8n emite sus
    propios redirects (login, /home, etc.) que tienen que llegar
    intactos al navegador, nunca resueltos en silencio por este proxy."""

    def redirect_request(self, *args, **kwargs):
        return None


_OPENER_SIN_REDIRECT = urllib.request.build_opener(_SinRedirect)

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
        """Gate de autenticacion Basic para las rutas de CAJAS GABO
        (/, archivos estaticos, /webhook/*) -- NUNCA para las rutas
        propias del editor n8n, que llaman directo a _proxy_n8n /
        _proxy_websocket_n8n sin pasar por aca (ver docstring del
        modulo). Si ya respondio (503 sin credenciales configuradas, o
        401 sin Basic auth valido), devuelve False y el llamador debe
        retornar sin hacer nada mas."""
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
        # FIX (bug real post-exposicion del editor): el Basic Auth del
        # proxy publico SOLO gatea lo que es de CAJAS GABO (/,
        # /webhook/*, archivos estaticos de n8n_frontend/) -- nunca las
        # rutas propias de n8n. Antes _autenticar() corria para TODO, y
        # la SPA de n8n dispara decenas de llamadas internas (/rest/*,
        # /types/*, etc.) que el navegador no siempre reautentica de
        # forma consistente con Basic Auth -> prompts repetidos de
        # usuario/clave. La seguridad de /n8n-admin, /home*, /rest/*,
        # /credentials/*, /workflow/*, /signin*, el callback OAuth, etc.
        # queda exclusivamente a cargo del login nativo de n8n (su
        # propia cookie de sesion) -- nunca sin autenticacion alguna,
        # solo con OTRA autenticacion, la de n8n mismo.
        if self.path.startswith("/webhook/"):
            if not self._autenticar():
                return
            return self._proxy("GET")
        if self.path.partition("?")[0] == "/":
            if not self._autenticar():
                return
            # Evita el listado de directorio ("Directory listing for /") de
            # SimpleHTTPRequestHandler: no hay index.html en n8n_frontend/,
            # asi que la raiz redirige a la interfaz real de CAJAS GABO.
            self.send_response(302)
            self.send_header("Location", "/v3_control_cierres.html")
            self.end_headers()
            return
        if os.path.isfile(self.translate_path(self.path)):
            if not self._autenticar():
                return
            # Archivo REAL en n8n_frontend/ (v3_control_cierres.html,
            # revision_correccion.html, o cualquier estatico futuro):
            # comportamiento identico a hoy, sin pasar por n8n.
            return super().do_GET()
        # A partir de aca: SOLO rutas propias del editor n8n. Ningun
        # _autenticar() -- ver comentario arriba.
        if self.path.partition("?")[0].rstrip("/") == "/n8n-admin":
            # Solo un atajo/redirect -- nunca se proxifica el literal
            # "/n8n-admin" -- ver docstring del modulo. /home SI cae en
            # el pass-through generico de mas abajo, como cualquier otra
            # ruta propia de n8n.
            self.send_response(302)
            self.send_header("Location", "/home")
            self.end_headers()
            return
        if self._es_upgrade_websocket():
            return self._proxy_websocket_n8n()
        return self._proxy_n8n("GET")

    def do_POST(self):
        if self.path.startswith("/webhook/"):
            if not self._autenticar():
                return
            return self._proxy("POST")
        # Ruta propia de n8n (p.ej. /rest/login, /rest/workflows, el
        # propio /rest/oauth2-credential/callback si Google llegara a
        # usar POST): sin Basic Auth del proxy, ver do_GET.
        return self._proxy_n8n("POST")

    def do_PUT(self):
        # /webhook/* nunca usa PUT (los nodos WEBHOOK del workflow real
        # solo configuran GET/POST) -- esto es siempre una ruta de n8n.
        return self._proxy_n8n("PUT")

    def do_PATCH(self):
        return self._proxy_n8n("PATCH")

    def do_DELETE(self):
        return self._proxy_n8n("DELETE")

    def do_OPTIONS(self):
        return self._proxy_n8n("OPTIONS")

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

    # -----------------------------------------------------------------
    # Acceso admin al editor n8n (ver docstring del modulo). Todo lo que
    # llega aca ya paso _autenticar() y no coincide con ningun archivo
    # estatico local ni con /webhook/* -- es una ruta propia de n8n
    # (/rest/*, /home*, /workflow/*, /credentials/*, /signin, /assets/*,
    # etc.), reenviada tal cual a su raiz real.
    # -----------------------------------------------------------------

    _HEADERS_NO_REENVIAR_A_N8N = {
        "authorization",  # secreto del proxy publico; nunca es de n8n
        "host",  # lo recalcula urllib para N8N_ORIGIN
        "content-length",  # lo recalcula la libreria HTTP segun el body
        "connection",  # framing propio de cada conexion, no se reenvia
        "transfer-encoding",  # idem; el body ya llega decodificado
        "accept-encoding",  # evita tener que des/re-comprimir al relaywear
    }

    def _es_upgrade_websocket(self):
        conexion = self.headers.get("Connection", "")
        upgrade = self.headers.get("Upgrade", "")
        return "upgrade" in conexion.lower() and upgrade.lower() == "websocket"

    def _proxy_n8n(self, method):
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
            length = int(self.headers.get("Content-Length", 0) or 0)
            body = self.rfile.read(length) if length else None
            headers = {
                k: v for k, v in self.headers.items()
                if k.lower() not in self._HEADERS_NO_REENVIAR_A_N8N
            }
            headers["X-Forwarded-Proto"] = "https"
            headers["X-Forwarded-Host"] = self.headers.get("Host", "")
            headers["X-Forwarded-For"] = self.client_address[0]
            req = urllib.request.Request(N8N_ORIGIN + self.path, data=body, method=method, headers=headers)
            try:
                # urlopen() normal SIGUE redirects 3xx solo -- inaceptable
                # aca: el editor de n8n depende de que su propio Location
                # (login, /home, etc.) llegue intacto al navegador, no que
                # este proxy lo "resuelva" en silencio. _OPENER_SIN_REDIRECT
                # (mas abajo) lo desactiva; un 3xx entonces llega como
                # HTTPError, igual que cualquier otro status no-2xx.
                with _OPENER_SIN_REDIRECT.open(req) as r:
                    self._reenviar_respuesta_n8n(r.status, r.headers, r)
            except urllib.error.HTTPError as e:
                self._reenviar_respuesta_n8n(e.code, e.headers, e)
        finally:
            N8N_MANAGER.liberar_despues_de_webhook()

    def _reenviar_respuesta_n8n(self, status, headers_origen, cuerpo):
        """Reenvia la respuesta de n8n con TODOS sus headers (incluido
        cada Set-Cookie por separado -- headers_origen.items() nunca los
        colapsa) salvo Connection/Transfer-Encoding (los recalculamos
        nosotros). El body se transmite en bloques en vez de
        bufferizarlo entero: si n8n dio Content-Length se reenvia tal
        cual y se copian exactamente esos bytes; si no (chunked del lado
        de n8n, ya decodificado por http.client al leerlo), la respuesta
        se re-emite con Transfer-Encoding: chunked propio."""
        self.send_response(status)
        content_length = headers_origen.get("Content-Length")
        for k, v in headers_origen.items():
            if k.lower() in ("connection", "transfer-encoding"):
                continue
            self.send_header(k, v)
        if content_length is None:
            self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        if content_length is None:
            while True:
                bloque = cuerpo.read(65536)
                if not bloque:
                    break
                self.wfile.write(("%x\r\n" % len(bloque)).encode("ascii"))
                self.wfile.write(bloque)
                self.wfile.write(b"\r\n")
            self.wfile.write(b"0\r\n\r\n")
        else:
            restante = int(content_length)
            while restante > 0:
                bloque = cuerpo.read(min(65536, restante))
                if not bloque:
                    break
                self.wfile.write(bloque)
                restante -= len(bloque)

    def _proxy_websocket_n8n(self):
        try:
            N8N_MANAGER.preparar_para_webhook()
        except TimeoutError:
            self.send_response(503)
            self.end_headers()
            return
        try:
            self._splice_websocket_a_n8n()
        finally:
            N8N_MANAGER.liberar_despues_de_webhook()

    def _splice_websocket_a_n8n(self):
        """Pass-through crudo a nivel de sockets para /rest/push (canal
        de tiempo real del editor): reenvia el handshake HTTP de upgrade
        tal cual (Cookie incluido -- n8n exige sesion valida ahi), relee
        la respuesta de n8n, y si es 101 Switching Protocols copia bytes
        SIN interpretar en ambos sentidos hasta que cualquiera de los
        dos lados cierre. No hace falta entender el framing/masking de
        WebSocket (RFC 6455): eso lo manejan el navegador y n8n en cada
        punta, no este proxy.

        LIMITACION ACEPTADA (deliberada, no oculta): no se drenan bytes
        que el navegador ya hubiera mandado ANTES del 101 -- un cliente
        WebSocket conforme al RFC (el unico real aca: la UI de n8n)
        nunca hace eso, siempre espera el 101 antes de mandar el primer
        frame."""
        encabezados = [
            (k, v) for k, v in self.headers.items()
            if k.lower() not in ("host", "authorization")
        ]
        encabezados.append(("Host", "{}:{}".format(N8N_HOST, N8N_PORT)))
        encabezados.append(("X-Forwarded-Proto", "https"))
        encabezados.append(("X-Forwarded-Host", self.headers.get("Host", "")))
        encabezados.append(("X-Forwarded-For", self.client_address[0]))

        peticion = "{} {} HTTP/1.1\r\n".format(self.command, self.path)
        peticion += "".join("{}: {}\r\n".format(k, v) for k, v in encabezados)
        peticion += "\r\n"

        try:
            sock_n8n = socket.create_connection((N8N_HOST, N8N_PORT), timeout=10)
        except OSError:
            self.send_response(502)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"Bad Gateway: no se pudo conectar a n8n")
            return

        try:
            sock_n8n.sendall(peticion.encode("iso-8859-1"))

            # Lee la respuesta de n8n en un unico recv() acotado y ubica
            # a mano el fin de cabeceras (\r\n\r\n) -- en vez de
            # socket.makefile() -- para no perder bytes: n8n puede
            # empezar a mandar frames WebSocket pegados al 101 mismo, y
            # un lector bufferizado los dejaria atrapados en un buffer
            # que despues se descarta al pasar a recv() crudo.
            buffer_n8n = b""
            while b"\r\n\r\n" not in buffer_n8n and len(buffer_n8n) <= 65536:
                trozo = sock_n8n.recv(65536)
                if not trozo:
                    break
                buffer_n8n += trozo
            cabecera, separador, resto = buffer_n8n.partition(b"\r\n\r\n")
            if not separador:
                self.send_response(502)
                self.end_headers()
                return
            self.wfile.write(cabecera + b"\r\n\r\n")
            es_101 = cabecera.startswith(b"HTTP/1.1 101") or cabecera.startswith(b"HTTP/1.0 101")
            if not es_101:
                return

            # A partir de aca la conexion queda hijacked para WebSocket:
            # nunca mas se interpreta como HTTP normal en este socket.
            self.close_connection = True
            sock_cliente = self.connection
            if resto:
                sock_cliente.sendall(resto)

            hilo = threading.Thread(target=self._bombear, args=(sock_n8n, sock_cliente), daemon=True)
            hilo.start()
            self._bombear(sock_cliente, sock_n8n)
            hilo.join(timeout=5)
        finally:
            try:
                sock_n8n.close()
            except OSError:
                pass

    @staticmethod
    def _bombear(origen, destino):
        """Copia bytes crudos de `origen` a `destino` hasta que `origen`
        cierre o falle; al terminar, medio-cierra `destino` del lado de
        escritura para que la otra punta tambien vea el fin del stream."""
        try:
            while True:
                datos = origen.recv(65536)
                if not datos:
                    break
                destino.sendall(datos)
        except OSError:
            pass
        finally:
            try:
                destino.shutdown(socket.SHUT_WR)
            except OSError:
                pass


if __name__ == "__main__":
    # ThreadingHTTPServer (antes HTTPServer, de un solo hilo): necesario
    # desde que existe el editor n8n en este mismo proceso -- una sesion
    # de WebSocket (/rest/push) o cualquier request larga hacia n8n
    # queda abierta minutos u horas, y con un solo hilo eso hubiera
    # bloqueado TODO el proceso, incluido /webhook/* en produccion,
    # mientras el editor estuviera abierto. GestorN8N ya usa su propio
    # Lock pensado para esto (ver docstring del modulo), asi que no hace
    # falta ningun otro cambio de concurrencia.
    http.server.ThreadingHTTPServer(("0.0.0.0", LISTEN_PORT), Handler).serve_forever()
