#!/usr/bin/env bash
# Uso: ./scripts/call_endpoint.sh [page_range]
# Lee ENDPOINT_ID y API_KEY desde .env.local en la raíz del proyecto.

set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if [[ -f "$ROOT/.env.local" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env.local"
  set +a
fi

: "${ENDPOINT_ID:?Falta ENDPOINT_ID en .env.local}"
: "${API_KEY:?Falta API_KEY en .env.local}"

PAGE_RANGE="${1:-0}"

JOB_ID=$(curl -sS -X POST "https://api.runpod.ai/v2/${ENDPOINT_ID}/run" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${API_KEY}" \
  -d "{\"input\":{\"pdf_url\":\"https://arxiv.org/pdf/2101.03961.pdf\",\"filename\":\"test.pdf\",\"output_format\":\"markdown\",\"page_range\":\"${PAGE_RANGE}\"}}" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")

echo "Job enviado: ${JOB_ID}"

for _ in $(seq 1 120); do
  RESP=$(curl -sS "https://api.runpod.ai/v2/${ENDPOINT_ID}/status/${JOB_ID}" \
    -H "Authorization: Bearer ${API_KEY}")
  STATUS=$(echo "$RESP" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status',''))")
  echo "Estado: ${STATUS}"
  if [[ "$STATUS" == "COMPLETED" || "$STATUS" == "FAILED" || "$STATUS" == "CANCELLED" || "$STATUS" == "TIMED_OUT" ]]; then
    echo "$RESP" | python3 -m json.tool
    exit 0
  fi
  sleep 10
done

echo "Tiempo de espera agotado. Consulta: curl https://api.runpod.ai/v2/${ENDPOINT_ID}/status/${JOB_ID} -H 'Authorization: Bearer ...'"
