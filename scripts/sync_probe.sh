#!/usr/bin/env bash
# Imita la FORMA del sync real (8 pasos, falla cerrado) sin tocar nada:
# solo imprime. PROBE_FAIL_AT=N hace fallar el paso N. PROBE_PG_HOST/PORT
# (opcional) prueba alcance TCP por red privada hacia un Postgres DESECHABLE
# de ESTE proyecto de sonda -- jamas el de CAJAS GABO.
set -euo pipefail
echo "PROBE_SYNC inicio $(date -u +%T)"
if [ -n "${PROBE_PG_HOST:-}" ]; then
  if timeout 10 bash -c "</dev/tcp/${PROBE_PG_HOST}/${PROBE_PG_PORT:-5432}"; then echo "PROBE_PG alcanzable"; else echo "PROBE_PG NO alcanzable" >&2; exit 4; fi
fi
for n in 1 2 3 4 5 6 7 8; do
  if [ "${PROBE_FAIL_AT:-0}" = "$n" ]; then echo "PROBE_SYNC paso $n FALLA" >&2; exit 3; fi
  echo "PROBE_SYNC paso $n aplicado (simulado)"
done
echo "PROBE_SYNC listo: 8 paso(s)"
