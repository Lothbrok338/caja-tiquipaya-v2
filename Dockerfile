# Dockerfile — imagen portable de Caja Tiquipaya V3 (n8n + Python en un
# solo contenedor), para el servicio sombra `cajas-gabo-shadow` en Railway
# y, si hiciera falta más adelante, para Contabo/OVH/Hetzner sin cambios.
#
# Reproduce en un contenedor la misma arquitectura que hoy corre en el
# Codespace (ver V3_OPEN_MONTH_STATE.md §1): n8n orquesta, invoca
# `python -m v3.dev_api` vía el nodo Execute Command, y
# scripts/serve_v3_frontend.py sirve el HTML y reenvía /webhook/* a n8n.
# Un solo servicio Railway, sin infraestructura extra.
FROM n8nio/n8n:latest

USER root

# Python 3 + pip. openpyxl/pytest son las únicas dependencias reales del
# motor y los tests — ver requirements.txt. La imagen base de n8n cambió
# de Alpine a Debian en algún momento entre versiones (sin apk); se
# detecta el gestor de paquetes disponible en vez de asumir uno fijo,
# para no romperse otra vez si vuelve a cambiar.
RUN if command -v apt-get >/dev/null 2>&1; then \
      apt-get update && apt-get install -y --no-install-recommends python3 python3-pip && \
      rm -rf /var/lib/apt/lists/*; \
    elif command -v apk >/dev/null 2>&1; then \
      apk add --no-cache python3 py3-pip; \
    else \
      echo "Ni apt-get ni apk disponibles en la imagen base" >&2 && exit 1; \
    fi

WORKDIR /app

COPY requirements.txt .
# --break-system-packages: Alpine marca el Python del sistema como
# "externally managed" (PEP 668); no hay virtualenv de por medio en la
# imagen porque el mismo intérprete lo invoca n8n vía Execute Command.
RUN pip install --no-cache-dir --break-system-packages -r requirements.txt

COPY . .

RUN chmod +x scripts/start_n8n.sh scripts/railway_entrypoint.sh && \
    chown -R node:node /app

# Rutas que los workflows adaptados (snapshots/railway-shadow/) usan como
# fallback si estas variables no están fijadas explícitamente en Railway.
ENV TIQ_REPO_ROOT=/app
ENV TIQ_PYTHON_BIN=/usr/bin/python3
ENV TIQ_BASE_DIR=/app/dev_workdir
ENV PYTHONPATH=/app
# Puerto público del servicio (el proxy del frontend); Railway inyecta
# PORT en runtime y lo sobrescribe — este valor es solo el default local.
ENV PORT=8090

USER node

EXPOSE 8090

ENTRYPOINT ["/app/scripts/railway_entrypoint.sh"]
