#!/usr/bin/env bash
# railway_entrypoint.sh — arranque del contenedor portable (Railway u otro
# host tipo Contabo/OVH/Hetzner) para el servicio cajas-gabo-shadow.
#
# Un solo contenedor corre n8n + el proxy/estatico del frontend V3, igual
# que hoy en Codespaces corren en la misma maquina (el backend V3 invoca
# `python -m v3.dev_api` via el nodo Execute Command de n8n, asi que ambos
# procesos deben compartir sistema de archivos y red local). n8n queda
# SOLO en localhost:5678 (nunca expuesto directo); el proceso publico del
# servicio es scripts/serve_v3_frontend.py, que sirve el HTML y reenvia
# /webhook/* a n8n. Esto reproduce exactamente la arquitectura descrita en
# V3_OPEN_MONTH_STATE.md, sin reescribir nada del motor.
set -euo pipefail

echo "[railway_entrypoint] TIQ_BLOCK_OFFICIAL_PUBLISH=${TIQ_BLOCK_OFFICIAL_PUBLISH:-<no fijada>}"
if [ "${TIQ_BLOCK_OFFICIAL_PUBLISH:-}" != "true" ]; then
  echo "[railway_entrypoint] ADVERTENCIA: TIQ_BLOCK_OFFICIAL_PUBLISH no es 'true'." >&2
  echo "[railway_entrypoint] Este entrypoint es para el servicio SHADOW/DEV; si esto no es" >&2
  echo "[railway_entrypoint] cajas-gabo-shadow, verifica las variables de entorno del servicio." >&2
fi

# n8n en background, en la red interna del contenedor unicamente.
bash /app/scripts/start_n8n.sh &
N8N_PID=$!

cleanup() {
  kill "$N8N_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

# Frontend + proxy /webhook/* en foreground: es el proceso principal del
# contenedor (Railway enruta $PORT hacia el). Si n8n aun no respondio la
# primera vez que alguien llama /webhook/*, el proxy devuelve el error de
# conexion tal cual (no reintenta, no oculta el fallo).
exec python3 /app/scripts/serve_v3_frontend.py
