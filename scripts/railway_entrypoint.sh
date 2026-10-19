#!/usr/bin/env bash
# Entrypoint SONDA: registra EXACTAMENTE como llega el comando, luego aplica el
# mismo modo "ejecutar y salir" del entrypoint real.
set -euo pipefail
echo "PROBE_ENTRYPOINT argc=$# uid=$(id -u) user=$(id -un) pwd=$(pwd)"
i=0; for a in "$@"; do i=$((i+1)); echo "PROBE_ARG[$i]=<$a>"; done
echo "PROBE_TOOLS timeout=$(command -v timeout || echo NO) bash=$(command -v bash || echo NO)"
echo "PROBE_ENV RAILWAY_ENVIRONMENT_NAME=${RAILWAY_ENVIRONMENT_NAME:-<no>} PGHOST_set=${PGHOST:+si}"
if [ "$#" -gt 0 ]; then
  exec "$@"
fi
echo "PROBE_SERVE iniciando servidor /healthz en :${PORT}"
exec node -e 'require("http").createServer((q,r)=>{r.end("OK")}).listen(process.env.PORT)'
