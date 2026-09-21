#!/usr/bin/env bash
# sync_workflows_railway.sh — mantiene los 7 workflows n8n de
# snapshots/railway-shadow/ sincronizados con lo que hay persistido en el
# Postgres de esta instancia, en CADA arranque del contenedor (llamado
# desde railway_entrypoint.sh, ANTES de servir el frontend).
#
# Por qué existe: `n8n start` (scripts/start_n8n.sh) solo ARRANCA n8n con
# lo que ya está guardado en su Postgres persistente -- nunca importa
# nada. `scripts/import_workflows_railway.sh` (el único mecanismo previo)
# es explícitamente manual, "UNA sola vez por instancia nueva": ningún
# commit posterior a esa primera importación llegaba jamás al n8n en
# ejecución, así que un fix en snapshots/railway-shadow/*.json podía
# quedar en git y en la imagen Docker sin que el workflow REAL en
# Postgres cambiara un solo byte (bug real, bloque caja-america:
# aLs1f3GMqswbaENA seguía corriendo una versión sin el fix de caja-por-
# lote, a pesar de que el snapshot y la imagen desplegada sí lo traían).
#
# Este script cierra ese hueco de forma reproducible en cada boot, SIN
# reimportar ciegamente (evitar reimportar cuando no hace falta es tan
# importante como corregir cuando sí hace falta -- ver
# scripts/_compare_workflow.py para la comparación semántica exacta):
#
#   1. `n8n export:workflow --id=<id>` (comando CLI real, uno-a-uno,
#      arranca y termina n8n para ESE comando -- nunca dejar un proceso
#      n8n escuchando; el modelo on-demand/sleep de GestorN8N en
#      scripts/serve_v3_frontend.py no se toca).
#   2. Comparar SEMÁNTICAMENTE (name/nodes/connections/settings, nunca
#      versionId/activeVersionId/timestamps) contra el snapshot deseado.
#   3. Según la decisión (ABSENT/DIFFERENT/NEEDS_PUBLISH/SAME):
#        SAME           -> no tocar nada.
#        NEEDS_PUBLISH  -> el contenido YA es el deseado, pero la versión
#                          activa no es la última guardada: publicar
#                          (`n8n publish:workflow --id=<id>`, comando CLI
#                          real de n8n 2.35.7 que reemplaza al deprecado
#                          `update:workflow --active=<bool>`; el sync
#                          corre ANTES de arrancar el servidor n8n, así
#                          que no hace falta desactivar/reactivar para
#                          refrescar runtime).
#        DIFFERENT/ABSENT -> `n8n import:workflow --input=<snapshot>`
#                          (conserva el "id" original, ver comentario de
#                          import_workflows_railway.sh) + publicar igual
#                          que arriba.
#
# FAIL CLOSED: `set -euo pipefail` + cualquier comando n8n que falle
# aborta ESTE script con código != 0. railway_entrypoint.sh NO debe
# servir el frontend si este script falla (ver ese archivo): mejor un
# contenedor que no arranca a uno que sirve un frontend nuevo contra
# workflows viejos, que es exactamente el bug que este script existe
# para cerrar.
#
# NO toca credenciales (nunca se leen ni se comparan aquí -- ver
# scripts/_compare_workflow.py), NO borra workflows, NO corre SQL manual,
# NO duplica IDs (import:workflow siempre usa el "id" ya presente en el
# snapshot).
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SNAPSHOTS_DIR="${TIQ_WORKFLOWS_SNAPSHOTS_DIR:-$DIR/snapshots/railway-shadow}"
COMPARADOR="$DIR/scripts/_compare_workflow.py"
PYTHON_BIN="${TIQ_PYTHON_BIN:-python3}"

if [ ! -d "$SNAPSHOTS_DIR" ]; then
  echo "[workflow-sync] ERROR: no existe $SNAPSHOTS_DIR" >&2
  exit 1
fi

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

_leer_campo() {
  # $1 = archivo, $2 = campo top-level ("id" o "name")
  "$PYTHON_BIN" -c "import json,sys; print(json.load(open(sys.argv[1]))[sys.argv[2]])" "$1" "$2"
}

_publicar() {
  # `n8n publish:workflow` (n8n 2.35.7): publica la última versión
  # guardada del workflow. `update:workflow --active=<bool>` esta
  # deprecado; el sync corre ANTES de arrancar el servidor n8n, así que
  # no hace falta desactivar/reactivar para refrescar runtime.
  local id="$1"
  n8n publish:workflow --id="$id" >/dev/null
}

encontrados=0
for snapshot in "$SNAPSHOTS_DIR"/*.json; do
  [ -e "$snapshot" ] || continue
  encontrados=$((encontrados + 1))

  id="$(_leer_campo "$snapshot" id)"
  nombre="$(_leer_campo "$snapshot" name)"

  exportado="$TMP_DIR/${id}.json"
  if n8n export:workflow --id="$id" --output="$exportado" >"$TMP_DIR/${id}.export.log" 2>&1; then
    decision="$("$PYTHON_BIN" "$COMPARADOR" "$snapshot" "$exportado")"
  else
    decision="ABSENT"
  fi

  case "$decision" in
    SAME)
      echo "[workflow-sync] OK $id ($nombre)"
      ;;
    NEEDS_PUBLISH)
      _publicar "$id"
      echo "[workflow-sync] UPDATED $id ($nombre) -- publicado (el contenido ya coincidia)"
      ;;
    DIFFERENT|ABSENT)
      n8n import:workflow --input="$snapshot"
      _publicar "$id"
      if [ "$decision" = "ABSENT" ]; then
        echo "[workflow-sync] UPDATED $id ($nombre) -- no existia, importado y publicado"
      else
        echo "[workflow-sync] UPDATED $id ($nombre) -- contenido distinto, importado y publicado"
      fi
      ;;
    *)
      echo "[workflow-sync] ERROR $id ($nombre): decision desconocida '$decision'" >&2
      exit 1
      ;;
  esac
done

if [ "$encontrados" -eq 0 ]; then
  echo "[workflow-sync] ERROR: ningun snapshot *.json en $SNAPSHOTS_DIR" >&2
  exit 1
fi

echo "[workflow-sync] listo: $encontrados workflow(s) sincronizados"
