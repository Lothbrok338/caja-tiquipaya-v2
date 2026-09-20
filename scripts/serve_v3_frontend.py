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
"""
import base64
import hmac
import http.server
import os
import urllib.error
import urllib.request

os.chdir(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "n8n_frontend"))

N8N_ORIGIN = os.environ.get("TIQ_N8N_ORIGIN", "http://localhost:5678")
LISTEN_PORT = int(os.environ.get("PORT", "8090"))

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
        if self.path.startswith("/webhook/"):
            return self._proxy("GET")
        return super().do_GET()

    def do_POST(self):
        if not self._autenticar():
            return
        return self._proxy("POST")

    def _proxy(self, method):
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


if __name__ == "__main__":
    http.server.HTTPServer(("0.0.0.0", LISTEN_PORT), Handler).serve_forever()
