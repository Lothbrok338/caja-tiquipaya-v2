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
#
# Serverless Sleep (Railway, 2026-09): n8n YA NO arranca aca al inicio del
# contenedor. Arrancaba siempre en background y quedaba con conexiones
# persistentes a Postgres, asi que aunque Railway tuviera
# sleepApplication=true el contenedor nunca bajaba de ~0.54 GB de RAM ni
# entraba realmente en sleep. Ahora serve_v3_frontend.py arranca n8n bajo
# demanda en el primer /webhook/* y lo apaga solo tras un periodo sin uso
# (ver GestorN8N / TIQ_N8N_IDLE_TIMEOUT_SECONDS en ese archivo) -- este
# script ya no lo toca en absoluto.
set -euo pipefail

echo "[railway_entrypoint] TIQ_BLOCK_OFFICIAL_PUBLISH=${TIQ_BLOCK_OFFICIAL_PUBLISH:-<no fijada>}"
if [ "${TIQ_BLOCK_OFFICIAL_PUBLISH:-}" != "true" ]; then
  echo "[railway_entrypoint] ADVERTENCIA: TIQ_BLOCK_OFFICIAL_PUBLISH no es 'true'." >&2
  echo "[railway_entrypoint] Este entrypoint es para el servicio SHADOW/DEV; si esto no es" >&2
  echo "[railway_entrypoint] cajas-gabo-shadow, verifica las variables de entorno del servicio." >&2
fi

# FIX: n8n fallaba antes de invocar Python porque ${TIQ_BASE_DIR}/tiq_v3_tmp
# (usado por los Code nodes de BACKEND para los archivos input/output del
# Execute Command) no existia todavia en un contenedor nuevo -- se crea
# aqui, antes de arrancar n8n, nunca dentro de un nodo del workflow.
mkdir -p "${TIQ_BASE_DIR:-/app/dev_workdir}/tiq_v3_tmp"

# FIX (bug real, bloque caja-america): el script que arranca n8n (ver
# scripts/) solo lo arranca con lo que YA esta guardado en su Postgres
# persistente -- nunca importa nada. El unico mecanismo previo para llevar un fix de
# snapshots/railway-shadow/*.json al n8n en ejecucion era MANUAL
# (scripts/import_workflows_railway.sh, "una sola vez por instancia
# nueva"), asi que un commit nuevo podia quedar en la imagen Docker sin
# que el workflow REAL en Postgres cambiara. sync_workflows_railway.sh
# cierra ese hueco en CADA boot, sin dejar ningun proceso n8n corriendo
# (son comandos CLI de una sola corrida, ver ese script) -- el modelo
# on-demand/sleep de GestorN8N (serve_v3_frontend.py) sigue intacto.
#
# FAIL CLOSED: si el sync falla, este entrypoint aborta ANTES de servir el
# frontend (set -euo pipefail ya activo arriba) -- nunca se expone una UI
# nueva contra workflows n8n desincronizados.
echo "[railway_entrypoint] Sincronizando workflows n8n con snapshots/railway-shadow ..."
bash /app/scripts/sync_workflows_railway.sh

# Frontend + proxy /webhook/* en foreground: es el UNICO proceso que este
# entrypoint arranca ahora, y es el proceso principal del contenedor
# (Railway enruta $PORT hacia el). n8n lo arranca y lo apaga el propio
# serve_v3_frontend.py bajo demanda -- ver GestorN8N ahi.
exec python3 /app/scripts/serve_v3_frontend.py
