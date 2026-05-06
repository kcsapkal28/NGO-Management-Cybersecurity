# Shared helpers for the bash test scripts. Source, don't execute.
# shellcheck shell=bash

NS="${NGO_NAMESPACE:-default}"

c_red()    { printf "\033[31m%s\033[0m" "$1"; }
c_green()  { printf "\033[32m%s\033[0m" "$1"; }
c_yellow() { printf "\033[33m%s\033[0m" "$1"; }

ok()    { echo "[$(c_green PASS)] $*"; }
fail()  { echo "[$(c_red FAIL)] $*" >&2; FAIL_COUNT=$((${FAIL_COUNT:-0} + 1)); }
warn()  { echo "[$(c_yellow WARN)] $*" >&2; }
info()  { echo "[INFO] $*"; }

# Run an HTTP check inside the cluster via a one-shot debug pod.
# Args: <url> <expected-status-or-empty>
in_cluster_http() {
  local url="$1"; local expect="${2:-2..}"
  kubectl -n "$NS" run curl-$$-$RANDOM --rm -i --restart=Never \
      --image=curlimages/curl:8.5.0 --quiet -- \
      curl -s -o /dev/null -w "%{http_code}" --max-time 5 "$url" \
    | grep -Eq "^${expect}$"
}

# Call kubectl with a uniform timeout.
kc() { kubectl -n "$NS" "$@"; }

# Port-forward in the background; echoes the local port and PID on stdout.
# Usage: read -r local_port pf_pid < <(start_pf svc/foo 9090)
start_pf() {
  local target="$1"; local remote="$2"
  local lp; lp=$(python3 -c 'import socket;s=socket.socket();s.bind(("127.0.0.1",0));print(s.getsockname()[1])')
  kubectl -n "$NS" port-forward "$target" "${lp}:${remote}" >/dev/null 2>&1 &
  local pid=$!
  # Brief wait for the forward to come up
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    sleep 0.5
    if curl -sf -o /dev/null --max-time 1 "http://127.0.0.1:${lp}/" 2>/dev/null; then break; fi
  done
  echo "$lp $pid"
}
