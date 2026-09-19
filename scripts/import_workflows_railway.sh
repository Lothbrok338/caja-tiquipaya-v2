#!/usr/bin/env bash
# import_workflows_railway.sh — importa los 7 workflows activos de V3 en la
# instancia de n8n que corre en el contenedor de cajas-gabo-shadow.
#
# Uso manual, UNA VEZ por instancia nueva de n8n (no forma parte del
# arranque automático — importar workflows con el mismo ID cada reinicio
# duplicaría o pisaría cambios hechos a mano en la UI de Railway). Correr
# dentro del contenedor, p. ej. via `railway ssh` o `railway run`:
#
#   bash scripts/import_workflows_railway.sh
#
# Usa `snapshots/railway-shadow/*.json` (copias con las rutas de Codespaces
# parametrizadas — ver scripts/adapt_workflows_for_railway.py), NUNCA
# snapshots/v3-final/ directamente, para que el backend funcione fuera de
# un Codespace sin tocar el snapshot fuente. Conserva los IDs de workflow
# originales (`n8n import:workflow` respeta el campo "id" del JSON).
#
# Después de importar: hace falta reconectar a mano la credencial de
# Google Drive (n8n nunca exporta el secreto — ver SNAPSHOT_MANIFEST.md)
# y activar cada workflow en la UI. Ninguno de los dos pasos es
# automatizable sin exponer credenciales, así que quedan manuales
# deliberadamente.
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/snapshots/railway-shadow"

if [ ! -d "$DIR" ]; then
  echo "No existe $DIR — corre primero: python3 scripts/adapt_workflows_for_railway.py" >&2
  exit 1
fi

for f in "$DIR"/*.json; do
  case "$(basename "$f")" in
    SOURCE_SNAPSHOT_MANIFEST.md) continue ;;
  esac
  echo "Importando $(basename "$f") ..."
  n8n import:workflow --input="$f"
done

echo
echo "Listo. Pendiente MANUAL en la UI de n8n (https://\${RAILWAY_PUBLIC_DOMAIN}):"
echo "  1. Reconectar la credencial 'Google Drive account' (OAuth2) en cada"
echo "     workflow que la usa (01 INGESTA, 06B, PREFLIGHT, 07C, 07D, 07E)."
echo "  2. Activar (toggle ON) los 7 workflows importados."
echo "  3. Confirmar TIQ_BLOCK_OFFICIAL_PUBLISH=true en las variables del"
echo "     servicio antes de cualquier prueba — ver DEPLOY_RAILWAY.md."
