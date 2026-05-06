#!/usr/bin/env bash
# Verifies in-cluster networking by curling each backend from a one-shot pod.
# Distinguishes "service broken" from "pod broken" since it bypasses the
# port-forward path entirely.
set -u
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=_lib.sh
source "${SCRIPT_DIR}/_lib.sh"

FAIL_COUNT=0

run_curl() {
  local url="$1"; local label="$2"
  local out
  out=$(kc run "curl-$RANDOM" --rm -i --restart=Never --quiet \
    --image=curlimages/curl:8.5.0 -- \
    curl -s -o /dev/null -w '%{http_code}' --max-time 5 "$url" 2>/dev/null) || out="ERR"
  out="${out//[!0-9]/}"   # strip kubectl noise
  if [[ "$out" =~ ^2|3 ]]; then
    ok "$label → $out"
  else
    fail "$label → $out"
  fi
}

run_curl "http://web-service:5001/"                          "web"
run_curl "http://web-service:5001/metrics"                   "web /metrics"
run_curl "http://prometheus-service:9090/-/ready"            "prometheus"
run_curl "http://elasticsearch-service:9200/_cluster/health" "elasticsearch"
run_curl "http://jaeger-service:16686/"                      "jaeger UI"
run_curl "http://grafana-service:3000/api/health"            "grafana"

[[ "$FAIL_COUNT" -eq 0 ]] || exit 1
