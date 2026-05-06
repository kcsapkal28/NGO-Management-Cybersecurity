#!/usr/bin/env bash
# Drive load against the web app and append P50/P95/P99 to results/load.csv.
# Uses 'hey' if available, else falls back to a parallel curl loop.
set -u
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=_lib.sh
source "${SCRIPT_DIR}/_lib.sh"

DURATION="${DURATION:-60s}"
RPS="${RPS:-50}"
TARGET_PATH="${TARGET_PATH:-/}"

read -r WEB_PORT WEB_PID < <(start_pf svc/web-service 5001)
trap 'kill $WEB_PID 2>/dev/null || true' EXIT
URL="http://127.0.0.1:${WEB_PORT}${TARGET_PATH}"
info "target: $URL  duration=$DURATION rps=$RPS"

RESULTS_DIR="${SCRIPT_DIR}/../results"
mkdir -p "$RESULTS_DIR"
CSV="${RESULTS_DIR}/load.csv"
[[ -f "$CSV" ]] || echo "ts,duration,rps,p50,p95,p99,total,errors" > "$CSV"

if command -v hey >/dev/null 2>&1; then
  info "using hey"
  out=$(hey -z "$DURATION" -q "$RPS" -c 10 "$URL")
  echo "$out"
  p50=$(echo "$out" | awk '/50%/ {print $NF; exit}')
  p95=$(echo "$out" | awk '/95%/ {print $NF; exit}')
  p99=$(echo "$out" | awk '/99%/ {print $NF; exit}')
  total=$(echo "$out" | awk '/Total:/ {print $2; exit}')
  errs=$(echo "$out" | awk '/Status code distribution/{flag=1;next} /Latency/{flag=0} flag && !/200/ {sum+=$NF} END{print sum+0}')
  echo "$(date -u +%FT%TZ),$DURATION,$RPS,$p50,$p95,$p99,$total,$errs" >> "$CSV"
  ok "appended results to $CSV"
else
  warn "'hey' not installed — falling back to seq curl. Install with: brew install hey  OR  go install github.com/rakyll/hey@latest"
  end=$(( $(date +%s) + 60 ))
  total=0; errors=0
  while [[ $(date +%s) -lt $end ]]; do
    code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 2 "$URL")
    [[ "$code" =~ ^2 ]] || errors=$((errors+1))
    total=$((total+1))
  done
  info "curl-loop done: $total reqs, $errors errors"
  echo "$(date -u +%FT%TZ),60s,?,?,?,?,$total,$errors" >> "$CSV"
fi
