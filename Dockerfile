# Dockerfile — imagen portable de Caja Tiquipaya V3 (n8n + Python en un
# solo contenedor), para el servicio sombra `cajas-gabo-shadow` en Railway
# y, si hiciera falta más adelante, para Contabo/OVH/Hetzner sin cambios.
#
# Reproduce en un contenedor la misma arquitectura que hoy corre en el
# Codespace (ver V3_OPEN_MONTH_STATE.md §1): n8n orquesta, invoca
# `python -m v3.dev_api` vía el nodo Execute Command, y
# scripts/serve_v3_frontend.py sirve el HTML y reenvía /webhook/* a n8n.
# Un solo servicio Railway, sin infraestructura extra.
#
# Base: node:22-bookworm-slim (Debian, con apt-get garantizado), NO la
# imagen oficial n8nio/n8n — su capa final (n8nio/base) es una Alpine
# deliberadamente sin apk ni compilador (hardening de tamaño/seguridad),
# así que no hay forma de instalarle Python encima. Se instala n8n via
# npm en su lugar: patrón estándar y soportado para self-hosting de n8n.
FROM node:22-bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
      python3 python3-pip build-essential \
    && rm -rf /var/lib/apt/lists/*

# n8n via npm (mismo paquete que publica n8nio/n8n internamente).
# Versión fijada: 2.35.7 es la que se validó realmente en este runtime
# (Task Runners para Code nodes, $env en vez de process.env — ver
# scripts/adapt_workflows_for_railway.py). "n8n" a secas dejaría que un
# redeploy futuro instale una versión distinta sin que nadie lo decida.
RUN npm install -g n8n@2.35.7

WORKDIR /app

COPY requirements.txt .
# --break-system-packages: Debian 12+ marca el Python del sistema como
# "externally managed" (PEP 668); no hay virtualenv de por medio en la
# imagen porque el mismo intérprete lo invoca n8n vía Execute Command.
RUN pip install --no-cache-dir --break-system-packages -r requirements.txt

COPY . .

RUN chmod +x scripts/start_n8n.sh scripts/railway_entrypoint.sh scripts/sync_workflows_railway.sh && \
    mkdir -p /app/.n8n && \
    chown -R node:node /app

# Rutas que los workflows adaptados (snapshots/railway-shadow/) usan como
# fallback si estas variables no están fijadas explícitamente en Railway.
ENV TIQ_REPO_ROOT=/app
ENV TIQ_PYTHON_BIN=/usr/bin/python3
ENV TIQ_BASE_DIR=/app/dev_workdir
ENV PYTHONPATH=/app
ENV N8N_USER_FOLDER=/app/.n8n
# Puerto público del servicio (el proxy del frontend); Railway inyecta
# PORT en runtime y lo sobrescribe — este valor es solo el default local.
ENV PORT=8090

USER node

EXPOSE 8090

ENTRYPOINT ["/app/scripts/railway_entrypoint.sh"]
