#!/usr/bin/env bash
# Idempotent: apply k8s manifests, wait for rollouts, then run smoke.sh.
# Single command for an operator after `kind create cluster`.
set -eu
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
# shellcheck source=_lib.sh
source "${SCRIPT_DIR}/_lib.sh"

info "applying manifests under ${REPO_ROOT}/k8s"
if [[ -f "${REPO_ROOT}/k8s/kustomization.yaml" ]]; then
  kubectl apply -k "${REPO_ROOT}/k8s"
else
  kubectl apply -f "${REPO_ROOT}/k8s/base"
  kubectl apply -f "${REPO_ROOT}/k8s/app"
  kubectl apply -f "${REPO_ROOT}/k8s/monitoring"
fi

info "waiting for rollouts"
for w in deployment/web statefulset/grafana statefulset/prometheus \
         deployment/jaeger statefulset/elasticsearch; do
  kc rollout status "$w" --timeout=300s
done
kc rollout status daemonset/fluentd --timeout=180s

info "rollouts complete — running smoke"
"${SCRIPT_DIR}/smoke.sh"
