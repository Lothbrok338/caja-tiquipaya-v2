#!/usr/bin/env bash
# start_n8n.sh — arranque reproducible de n8n para el POC de orquestacion
# (FASE B / TIQ · PROCESAR CIERRES PENDIENTES · POC).
#
# Este script NO es parte del motor contable: solo configura y arranca el
# proceso n8n self-hosted usado para orquestar run_batch.py en este
# Codespace. No toca Python, no toca datos, no se conecta a Drive.
set -euo pipefail

# n8n excluye "Execute Command" por defecto (NODES_EXCLUDE trae
# 'n8n-nodes-base.executeCommand' de fabrica). El workflow POC depende de
# ese nodo para invocar run_batch.py, asi que hay que habilitarlo aqui.
export NODES_EXCLUDE='[]'

# El nodo "Read/Write Files from Disk" del workflow POC solo puede acceder
# fuera de ~/.n8n-files (restriccion de seguridad por defecto de n8n) si
# se amplia este allowlist. Se agrega la carpeta de fixtures sinteticos
# del POC (fuera del repo, ver FASE B): ~/poc_n8n_tiquipaya.
export N8N_RESTRICT_FILE_ACCESS_TO="~/.n8n-files;${HOME}/poc_n8n_tiquipaya"

# N8N_EDITOR_BASE_URL corrige la URL publica usada por OAuth/UI: este
# Codespace se accede via la URL HTTPS de reenvio de puerto, no via
# localhost, y n8n necesita saberlo para construir el redirect_uri de
# OAuth2 (por ejemplo, para Google Drive) correctamente.
export N8N_EDITOR_BASE_URL="https://${CODESPACE_NAME}-5678.${GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN}"
# WEBHOOK_URL corrige las URLs publicas de Webhook/Form Trigger, que no
# heredan N8N_EDITOR_BASE_URL (se calculan por separado).
export WEBHOOK_URL="${N8N_EDITOR_BASE_URL}"

exec n8n start
