#!/usr/bin/env bash
# start_n8n.sh — arranque reproducible de n8n para el POC de orquestacion
# (FASE B / TIQ · PROCESAR CIERRES PENDIENTES · POC).
#
# Este script NO es parte del motor contable: solo configura y arranca el
# proceso n8n self-hosted usado para orquestar run_batch.py / v3.dev_api.
# No toca Python, no toca datos, no se conecta a Drive.
#
# Portabilidad (migración Railway, 2026-09): antes este script exigía
# CODESPACE_NAME + GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN de forma
# incondicional, así que solo podía arrancar dentro de un Codespace. Ahora
# detecta el entorno y elige la URL pública correcta; fuera de Codespaces
# y de Railway simplemente no fuerza ninguna URL pública (deja que n8n use
# sus valores por defecto). El soporte Codespaces original se conserva sin
# cambios de comportamiento.
set -euo pipefail

# n8n excluye "Execute Command" por defecto (NODES_EXCLUDE trae
# 'n8n-nodes-base.executeCommand' de fabrica). El backend V3 depende de
# ese nodo para invocar python -m v3.dev_api, asi que hay que habilitarlo aqui.
export NODES_EXCLUDE='[]'

# El nodo "Read/Write Files from Disk" del workflow POC solo puede acceder
# fuera de ~/.n8n-files (restriccion de seguridad por defecto de n8n) si
# se amplia este allowlist. Se agrega la carpeta de fixtures sinteticos
# del POC (fuera del repo, ver FASE B): ~/poc_n8n_tiquipaya. Inofensivo si
# esa carpeta no existe en el entorno actual (Railway).
export N8N_RESTRICT_FILE_ACCESS_TO="~/.n8n-files;${HOME}/poc_n8n_tiquipaya"

if [ -n "${CODESPACE_NAME:-}" ] && [ -n "${GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN:-}" ]; then
  # Codespaces: se accede via la URL HTTPS de reenvio de puerto, no via
  # localhost, y n8n necesita saberlo para construir el redirect_uri de
  # OAuth2 (por ejemplo, para Google Drive) correctamente.
  export N8N_EDITOR_BASE_URL="https://${CODESPACE_NAME}-5678.${GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN}"
  export N8N_WEBHOOK_URL="${N8N_EDITOR_BASE_URL}"
elif [ -n "${RAILWAY_PUBLIC_DOMAIN:-}" ]; then
  # Railway: RAILWAY_PUBLIC_DOMAIN la inyecta la plataforma automaticamente
  # cuando el servicio tiene un dominio generado. n8n corre solo en la red
  # interna del contenedor (scripts/serve_v3_frontend.py expone /webhook/*
  # bajo ese mismo dominio en $PORT). El editor queda privado via tunel SSH,
  # mientras que las URLs de Webhook/Form Trigger usan el dominio publico.
  export N8N_EDITOR_BASE_URL="${TIQ_N8N_EDITOR_BASE_URL:-http://localhost:5678}"
  export N8N_WEBHOOK_URL="https://${RAILWAY_PUBLIC_DOMAIN}"
elif [ -n "${N8N_EDITOR_BASE_URL:-}" ]; then
  # Compatibilidad con entornos existentes que todavia usan WEBHOOK_URL.
  export WEBHOOK_URL="${N8N_EDITOR_BASE_URL}"
fi

# Puerto interno de n8n: fijo en 5678 (nunca el $PORT publico de Railway),
# porque scripts/serve_v3_frontend.py asume este valor para reenviar
# /webhook/* -- ver N8N_ORIGIN en ese archivo.
export N8N_PORT="${N8N_INTERNAL_PORT:-5678}"

exec n8n start
