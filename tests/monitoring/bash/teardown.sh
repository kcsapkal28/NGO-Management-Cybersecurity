#!/usr/bin/env bash
# Clean up test-generated data without touching the cluster.
# - Drops fluentd indices older than 1 day (keeps today's so dashboards keep data)
# - Wipes the local results/ directory of CSVs older than 30 days
set -u
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=_lib.sh
source "${SCRIPT_DIR}/_lib.sh"

read -r ES_PORT ES_PID < <(start_pf svc/elasticsearch-service 9200)
trap 'kill $ES_PID 2>/dev/null || true' EXIT

today=$(date -u +%Y.%m.%d)
info "deleting fluentd indices older than ${today}"
indices=$(curl -sf "http://127.0.0.1:${ES_PORT}/_cat/indices/fluentd-*?h=index" || true)
while IFS= read -r idx; do
  [[ -z "$idx" ]] && continue
  if [[ "$idx" < "fluentd-${today}" ]]; then
    info "deleting $idx"
    curl -sf -X DELETE "http://127.0.0.1:${ES_PORT}/${idx}" >/dev/null \
      && ok "deleted $idx" || warn "could not delete $idx"
  fi
done <<< "$indices"

info "trimming results/*.csv older than 30d"
find "${SCRIPT_DIR}/../results" -type f -name '*.csv' -mtime +30 -print -delete 2>/dev/null || true
ok "teardown complete"
