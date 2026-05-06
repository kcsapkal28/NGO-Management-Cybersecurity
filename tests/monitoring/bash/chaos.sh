#!/usr/bin/env bash
# Restart each monitored workload one at a time and re-run smoke after each.
# Verifies the system recovers gracefully from pod churn.
set -u
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=_lib.sh
source "${SCRIPT_DIR}/_lib.sh"

WORKLOADS=(
  "deployment/web"
  "statefulset/grafana"
  "statefulset/prometheus"
  "deployment/jaeger"
  "statefulset/elasticsearch"
  "daemonset/fluentd"
)

FAIL_COUNT=0
for w in "${WORKLOADS[@]}"; do
  info "restarting $w"
  kc rollout restart "$w" || { fail "$w: rollout restart failed"; continue; }
  if kc rollout status "$w" --timeout=180s; then
    ok "$w: rollout completed"
  else
    fail "$w: rollout did not complete in 180s"
    continue
  fi
  info "running smoke after restarting $w"
  if "${SCRIPT_DIR}/smoke.sh"; then
    ok "smoke OK after $w restart"
  else
    fail "smoke FAILED after $w restart"
  fi
  echo "----"
done

[[ "$FAIL_COUNT" -eq 0 ]] || exit 1
