#!/usr/bin/env bash
# Drives ~3 minutes of varied, realistic traffic so every Grafana panel,
# Jaeger search, and ES log query has something interesting to show before
# you take screenshots.
#
# Usage:
#   export ADMIN_EMAIL=you@example.com
#   export ADMIN_PASSWORD='...'
#   bash docs/screenshots/demo-driver.sh
#
# What you should see while it runs:
#   • Grafana → App Overview: request rate climbs, 5xx % spikes briefly,
#     P95 latency bump from db-slow, donation funnel ramps up.
#   • Grafana → Infrastructure: ES indexing rate spikes during log-storm,
#     pod-restart counter ticks if you panic enough times.
#   • Grafana → Logs & Traces: ERROR/WARNING counters rise, log-by-pod
#     piechart populates, recent traces panel fills.
#   • Jaeger UI: trace-deep depth=8 produces a nicely-nested span tree.

set -u

NS="${NGO_NAMESPACE:-default}"

if [[ -z "${ADMIN_EMAIL:-}" || -z "${ADMIN_PASSWORD:-}" ]]; then
  echo "ERROR: export ADMIN_EMAIL and ADMIN_PASSWORD before running" >&2
  echo "       (the user must already exist; promote with: kubectl exec deploy/web -- flask promote-admin <email>)" >&2
  exit 1
fi

# --- Port-forward web app -----------------------------------------------
echo "==> port-forward web-service:5001 → 15001"
kubectl -n "$NS" port-forward svc/web-service 15001:5001 >/tmp/demo-pf.log 2>&1 &
PF_PID=$!
trap 'kill $PF_PID 2>/dev/null || true' EXIT
sleep 3

WEB="http://127.0.0.1:15001"
COOKIE=$(mktemp)
trap 'kill $PF_PID 2>/dev/null || true; rm -f "$COOKIE"' EXIT

# --- Admin login (CSRF-aware) -------------------------------------------
echo "==> admin login"
TOKEN=$(curl -sf -c "$COOKIE" -b "$COOKIE" "$WEB/auth" \
  | grep -oE 'name="csrf_token"[^>]*value="[^"]+"' \
  | head -1 \
  | grep -oE 'value="[^"]+"' | cut -d'"' -f2)
if [[ -z "$TOKEN" ]]; then echo "could not scrape csrf_token"; exit 1; fi

LOGIN_STATUS=$(curl -s -c "$COOKIE" -b "$COOKIE" -e "$WEB/auth" \
  -X POST "$WEB/login" \
  --data-urlencode "email=$ADMIN_EMAIL" \
  --data-urlencode "password=$ADMIN_PASSWORD" \
  --data-urlencode "csrf_token=$TOKEN" \
  -o /dev/null -w "%{http_code}\n")
if [[ "$LOGIN_STATUS" != "302" ]]; then
  echo "  login failed (status $LOGIN_STATUS) — check creds"; exit 1
fi
echo "  ok"

call() {
  local label="$1"; shift
  printf "  → %-35s " "$label"
  curl -s -b "$COOKIE" -o /dev/null -w "HTTP %{http_code}\n" "$@"
}

# --- Phase 1: baseline traffic so latency histograms populate ----------
echo "==> phase 1: baseline (~30s of normal traffic)"
for _ in $(seq 1 60); do
  curl -s -b "$COOKIE" -o /dev/null "$WEB/" &
  curl -s -b "$COOKIE" -o /dev/null "$WEB/campaigns" &
  curl -s -b "$COOKIE" -o /dev/null "$WEB/donate" &
  sleep 0.5
done
wait

# --- Phase 2: business activity ----------------------------------------
echo "==> phase 2: donation burst + auth attempts"
call "donation-burst n=50" -X POST "$WEB/system-test/donation-burst?n=50" \
     -H "X-CSRFToken: $TOKEN"

# A few wrong logins to populate ngo_auth_attempts_total{result=invalid}
for _ in 1 2 3 4 5; do
  WRONG_TOKEN=$(curl -sf -b "$COOKIE" -c "$COOKIE" "$WEB/auth" \
    | grep -oE 'name="csrf_token"[^>]*value="[^"]+"' \
    | head -1 \
    | grep -oE 'value="[^"]+"' | cut -d'"' -f2)
  curl -s -b "$COOKIE" -e "$WEB/auth" -X POST "$WEB/login" \
    --data-urlencode "email=does-not-exist@example.com" \
    --data-urlencode "password=nope" \
    --data-urlencode "csrf_token=$WRONG_TOKEN" \
    -o /dev/null
done
echo "  ok"

# --- Phase 3: latency tail (db-slow) -----------------------------------
echo "==> phase 3: latency spike (db-slow)"
for _ in 1 2 3; do
  call "db-slow seconds=2" "$WEB/system-test/db-slow?seconds=2" &
done
wait

# --- Phase 4: log volume ------------------------------------------------
echo "==> phase 4: log storms"
call "log-storm 500 info"  "$WEB/system-test/log-storm?n=500&level=info"
call "log-storm 200 warn"  "$WEB/system-test/log-storm?n=200&level=warning"
call "log-storm 100 error" "$WEB/system-test/log-storm?n=100&level=error"

# --- Phase 5: deep traces (so Jaeger has nice span trees) --------------
echo "==> phase 5: deep traces"
call "trace-deep depth=8"  "$WEB/system-test/trace-deep?depth=8"
call "trace-deep depth=10" "$WEB/system-test/trace-deep?depth=10"
call "trace-deep depth=12" "$WEB/system-test/trace-deep?depth=12"

# --- Phase 6: errors so 5xx panel + ERROR count light up ---------------
echo "==> phase 6: 5xx errors"
for _ in 1 2 3 4 5; do
  call "/system-test/error" "$WEB/system-test/error"
done

# --- Phase 7: sustained load in background -----------------------------
echo "==> phase 7: 60s of 30 rps (background — keep watching dashboards)"
call "load rps=30 d=60" "$WEB/system-test/load?rps=30&duration=60"

echo
echo "==========================================================="
echo " demo driver done. Dashboards are populated."
echo " Wait ~10s for the final scrape, then take screenshots."
echo "==========================================================="
