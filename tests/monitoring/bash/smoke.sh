#!/usr/bin/env bash
# Fast (~30s) post-deploy sanity check. Returns non-zero on first failure.
set -u
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=_lib.sh
source "${SCRIPT_DIR}/_lib.sh"

FAIL_COUNT=0

info "namespace: ${NS}"

info "checking required deployments are Available"
for d in web grafana prometheus jaeger elasticsearch; do
  kind=$(kc get deployment "$d" -o name 2>/dev/null || \
         kc get statefulset "$d" -o name 2>/dev/null || echo "")
  if [[ -z "$kind" ]]; then
    fail "$d: workload not found"
    continue
  fi
  ready=$(kc get "$kind" -o jsonpath='{.status.readyReplicas}' 2>/dev/null)
  desired=$(kc get "$kind" -o jsonpath='{.status.replicas}' 2>/dev/null)
  if [[ "$ready" == "$desired" && -n "$ready" && "$ready" != "0" ]]; then
    ok "$d ($ready/$desired ready)"
  else
    fail "$d: $ready/$desired ready"
  fi
done

info "checking fluentd DaemonSet"
ds_ready=$(kc get ds fluentd -o jsonpath='{.status.numberReady}' 2>/dev/null)
ds_want=$(kc get ds fluentd -o jsonpath='{.status.desiredNumberScheduled}' 2>/dev/null)
if [[ "$ds_ready" == "$ds_want" && -n "$ds_ready" && "$ds_ready" != "0" ]]; then
  ok "fluentd ($ds_ready/$ds_want ready)"
else
  fail "fluentd: $ds_ready/$ds_want ready"
fi

info "checking app /metrics responds"
read -r WEB_PORT WEB_PID < <(start_pf svc/web-service 5001)
trap 'kill $WEB_PID 2>/dev/null || true' EXIT
if curl -sf -o /dev/null --max-time 5 "http://127.0.0.1:${WEB_PORT}/metrics"; then
  ok "web /metrics 200"
else
  fail "web /metrics did not respond"
fi

info "checking Prometheus targets"
read -r PROM_PORT PROM_PID < <(start_pf svc/prometheus-service 9090)
trap 'kill $WEB_PID $PROM_PID 2>/dev/null || true' EXIT
up_count=$(curl -sf --max-time 5 \
  "http://127.0.0.1:${PROM_PORT}/api/v1/query?query=up" \
  | python3 -c 'import json,sys;d=json.load(sys.stdin);print(sum(1 for r in d["data"]["result"] if r["value"][1]=="1"))' \
  2>/dev/null || echo "0")
if [[ "${up_count:-0}" -gt 0 ]]; then
  ok "Prometheus: ${up_count} targets up"
else
  fail "Prometheus: no targets up"
fi

info "checking Elasticsearch cluster health"
read -r ES_PORT ES_PID < <(start_pf svc/elasticsearch-service 9200)
trap 'kill $WEB_PID $PROM_PID $ES_PID 2>/dev/null || true' EXIT
es_status=$(curl -sf --max-time 5 "http://127.0.0.1:${ES_PORT}/_cluster/health" \
  | python3 -c 'import json,sys;print(json.load(sys.stdin)["status"])' 2>/dev/null || echo "unreachable")
case "$es_status" in
  green|yellow) ok "Elasticsearch: $es_status" ;;
  *)            fail "Elasticsearch: $es_status" ;;
esac

info "checking Jaeger UI"
read -r JG_PORT JG_PID < <(start_pf svc/jaeger-service 16686)
trap 'kill $WEB_PID $PROM_PID $ES_PID $JG_PID 2>/dev/null || true' EXIT
if curl -sf -o /dev/null --max-time 5 "http://127.0.0.1:${JG_PORT}/"; then
  ok "Jaeger UI 200"
else
  fail "Jaeger UI did not respond"
fi

echo
if [[ "$FAIL_COUNT" -eq 0 ]]; then
  echo "$(c_green 'SMOKE OK')"
  exit 0
fi
echo "$(c_red SMOKE FAILED): $FAIL_COUNT check(s) failed"
exit 1
