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
"""
import http.server
import os
import urllib.error
import urllib.request

os.chdir(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "n8n_frontend"))

N8N_ORIGIN = os.environ.get("TIQ_N8N_ORIGIN", "http://localhost:5678")
LISTEN_PORT = int(os.environ.get("PORT", "8090"))


class Handler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        # Sin esto, el navegador puede quedarse con una version vieja del
        # HTML/JS tras cada edicion (visto en vivo: el proxy ya servia el
        # archivo corregido, pero el navegador mostraba el cache).
        self.send_header("Cache-Control", "no-store, must-revalidate")
        super().end_headers()

    def do_GET(self):
        if self.path.startswith("/webhook/"):
            return self._proxy("GET")
        return super().do_GET()

    def do_POST(self):
        return self._proxy("POST")

    def _proxy(self, method):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else None
        req = urllib.request.Request(
            N8N_ORIGIN + self.path,
            data=body,
            method=method,
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
