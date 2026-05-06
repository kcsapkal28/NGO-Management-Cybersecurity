# Setup Guide — Cybersecurity NGO Management Platform

End-to-end instructions for running the platform on a local Kubernetes cluster (kind). Covers prerequisites, image builds, deployment, smoke tests, day-to-day operations, troubleshooting, and teardown.

---

## 1. What gets deployed

Applying `k8s/` brings up the workloads below in the `default` namespace.

### App tier
| Workload          | Kind        | Image                                            | Exposure                      |
|-------------------|-------------|--------------------------------------------------|-------------------------------|
| `web`             | Deployment  | `ngo-web-app:latest` (built locally)             | NodePort 30001 → 5001         |
| `db`              | StatefulSet | `postgres:15-alpine`                             | ClusterIP (headless)          |

### Observability core
| Workload          | Kind        | Image                                            | Exposure                      |
|-------------------|-------------|--------------------------------------------------|-------------------------------|
| `prometheus`      | StatefulSet | `prom/prometheus:latest`                         | ClusterIP 9090                |
| `alertmanager`    | Deployment  | `prom/alertmanager:v0.27.0`                      | ClusterIP 9093                |
| `grafana`         | StatefulSet | `grafana/grafana:9.5.18`                         | NodePort 30002 → 3000         |
| `jaeger`          | Deployment  | `jaegertracing/all-in-one:latest`                | UI 16686, OTLP 4317, metrics 14269 |
| `elasticsearch`   | StatefulSet | `elasticsearch:8.10.2`                           | ClusterIP 9200                |
| `elasticsearch-init` | Job      | `curlimages/curl:8.5.0`                          | one-shot (PUTs ILM + template) |
| `fluentd`         | DaemonSet   | `ngo-fluentd:latest` (built locally)             | ClusterIP 24224               |

### Exporters (annotation-discovered by Prometheus)
| Workload                  | Image                                                  | Source of metrics             |
|---------------------------|--------------------------------------------------------|-------------------------------|
| `node-exporter`           | `prom/node-exporter:v1.7.0`                            | DaemonSet — host CPU/mem/disk/net |
| `kube-state-metrics`      | `kube-state-metrics:v2.10.1`                           | Pod inventory, restarts, deployment health |
| `postgres-exporter`       | `prometheuscommunity/postgres-exporter:v0.15.0`        | `pg_up`, connection counts, commit rate |
| `elasticsearch-exporter`  | `prometheuscommunity/elasticsearch-exporter:v1.7.0`    | Cluster health, JVM heap, indexing rate |

`DATABASE_URL` is sourced from the `app-secrets` Secret. Other app config (`JAEGER_HOST`, `JAEGER_SERVICE_NAME`, `SYSTEM_TEST_ENABLED`) lives in the `app-config` ConfigMap. Grafana datasources/dashboards (3 dashboards: App Overview, Infrastructure, Logs & Traces) are provisioned via Kustomize-generated ConfigMaps from `k8s/base/grafana-provisioning/`. Prometheus rules (8 starter alerts) come from the `prometheus-rules` ConfigMap.

---

## 2. Prerequisites

Install once:

```bash
brew install kind kubectl
# Docker Desktop: https://www.docker.com/products/docker-desktop/
# ngrok (optional, for the public-tunnel helper): https://ngrok.com/download
```

Verify:

```bash
docker info --format '{{.ServerVersion}}'   # any recent version
kind version
kubectl version --client
```

Docker Desktop must be running before any of the steps below.

---

## 3. Optional: clean Docker state

Skip this unless you want a true clean slate. **This wipes every container, image, volume, and build cache on the machine — not just this project.**

```bash
kind delete clusters --all 2>/dev/null || true
docker ps -aq | xargs -r docker rm -f
docker system prune -af --volumes
docker builder prune -af
```

Verify:

```bash
docker ps -a            # empty
docker images -a        # empty
docker volume ls        # empty
kind get clusters       # "No kind clusters found."
```

---

## 4. Build the local images

The web and fluentd Deployments use `imagePullPolicy: Never`, so the cluster will not try to fetch them from a registry. They must be built on the host first.

```bash
docker build -t ngo-web-app:latest .
docker build -t ngo-fluentd:latest ./monitoring/fluentd
```

Verify:

```bash
docker images --format '{{.Repository}}:{{.Tag}}' | grep ngo-
# ngo-web-app:latest
# ngo-fluentd:latest
```

> **Note on parallel builds.** Running both builds plus `kind create cluster` simultaneously can saturate the network and trip pip's default 15s read timeout. If you see `ReadTimeoutError: HTTPSConnectionPool(host='files.pythonhosted.org' ...)`, just rerun the failing build serially — no code change needed.

---

## 5. Create the kind cluster

```bash
kind create cluster --name kind --config k8s/kind-config.yaml
```

`k8s/kind-config.yaml` exposes the cluster's NodePorts 30001 and 30002 on the host's loopback interface, so the web app and Grafana are reachable directly at `127.0.0.1` without `kubectl port-forward`.

Verify:

```bash
kind get clusters                      # "kind"
kubectl config current-context         # "kind-kind"
kubectl get nodes                      # 1 node, Ready
```

---

## 6. Load the local images into kind

The kind node is itself a container with its own image cache. Pre-load both local images so kubelet finds them:

```bash
kind load docker-image ngo-web-app:latest --name kind
kind load docker-image ngo-fluentd:latest --name kind
```

---

## 7. Apply the manifests

```bash
kubectl apply -k k8s/
```

Expected: ~9 ConfigMaps, 1 Secret, 2 ServiceAccounts, 2 ClusterRoles + bindings, ~12 Services, 6 Deployments, 4 StatefulSets, 2 DaemonSets, 1 Job (~40 objects).

Optional pre-flight render:

```bash
kubectl kustomize k8s/ | less
```

---

## 8. Wait for rollouts

In rollout-dependency order:

```bash
# Data layer first
kubectl rollout status statefulset/db                --timeout=300s
kubectl rollout status statefulset/elasticsearch     --timeout=600s

# Core observability
kubectl rollout status statefulset/prometheus        --timeout=300s
kubectl rollout status statefulset/grafana           --timeout=300s
kubectl rollout status deploy/jaeger                 --timeout=300s
kubectl rollout status deploy/alertmanager           --timeout=300s

# Exporters (Phase 1.2)
kubectl rollout status deploy/kube-state-metrics     --timeout=180s
kubectl rollout status deploy/postgres-exporter      --timeout=180s
kubectl rollout status deploy/elasticsearch-exporter --timeout=180s
kubectl rollout status ds/node-exporter              --timeout=180s

# Log pipeline + app
kubectl rollout status ds/fluentd                    --timeout=180s
kubectl rollout status deploy/web                    --timeout=300s

# ES init Job (PUTs ILM policy + index template)
kubectl wait --for=condition=complete job/elasticsearch-init --timeout=180s
```

Total cold-start time on a clean Docker is ~6–10 min, dominated by the Elasticsearch image pull (~1 GB).

> **Expected during bootstrap:** `jaeger` and `elasticsearch-exporter` will CrashLoopBackOff a few times before Elasticsearch is Ready — both depend on it. Self-heal once ES is up. 1–4 restarts is normal.

Final state:

```bash
kubectl get pods
# All workloads should be 1/1 Running (or Completed for the init Job)
bash tests/monitoring/bash/smoke.sh   # confirms each component end-to-end
```

---

## 9. Smoke test

```bash
curl -s -o /dev/null -w "web    HTTP %{http_code}\n" http://127.0.0.1:30001/
curl -s -o /dev/null -w "graf   HTTP %{http_code}\n" http://127.0.0.1:30002/api/health
```

Both should return `200`.

---

## 10. Access the services

Always-on (via kind port-mappings):

| Service | URL |
|---------|-----|
| Web app | http://127.0.0.1:30001 |
| Grafana | http://127.0.0.1:30002  (admin / admin) |

Port-forward in separate terminals when needed:

```bash
kubectl port-forward svc/prometheus-service    9090:9090     # http://localhost:9090
kubectl port-forward svc/jaeger-service        16686:16686   # http://localhost:16686
kubectl port-forward svc/elasticsearch-service 9200:9200     # http://localhost:9200
```

Public tunnel (uses the bundled helper):

```bash
./start-stack.sh
# Brings up kind if needed, waits for the web pod, and exposes 30001 via ngrok.
```

---

## 11. Day-to-day operations

### Rebuild and redeploy the web app

```bash
docker build -t ngo-web-app:latest .
kind load docker-image ngo-web-app:latest --name kind
kubectl rollout restart deploy/web
kubectl rollout status   deploy/web --timeout=180s
```

### Tail logs

```bash
kubectl logs -f deploy/web
kubectl logs -f deploy/jaeger
kubectl logs -f ds/fluentd
kubectl logs -f statefulset/elasticsearch
```

### Inspect cluster state

```bash
kubectl get pods,svc,statefulset,deploy,ds
kubectl describe pod <pod>
kubectl exec -it deploy/web -- /bin/sh
```

### Connect to Postgres from your laptop

```bash
kubectl port-forward svc/db-service 5432:5432
# in another terminal:
psql postgresql://postgres:postgres@127.0.0.1:5432/ngo_db
```

### Update Grafana provisioning

Datasources/dashboards in `k8s/base/grafana-provisioning/` are bundled into Kustomize-generated ConfigMaps. After editing them:

```bash
kubectl apply -k k8s/                  # generates new hashed ConfigMap
kubectl rollout restart statefulset/grafana
```

---

## 12. Troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `web` pod stuck on `Init:0/1` | Postgres not Ready yet | Wait — the `wait-for-db` initContainer polls until the DB accepts connections |
| `jaeger` in CrashLoopBackOff during first ~5 min | Elasticsearch not Ready yet | No action — Jaeger self-heals once ES is up |
| `pip._vendor.urllib3.exceptions.ReadTimeoutError` during web build | Network contention with parallel pulls | Re-run `docker build -t ngo-web-app:latest .` alone |
| `ErrImageNeverPull` on web or fluentd | Image not loaded into kind node | `kind load docker-image <name>:latest --name kind` |
| `web` returns 500 on first hit | Tables not yet created | The init container runs `db.create_all()`; wait for the Deployment to be Ready |
| Grafana shows "No data" on the dashboard | Prometheus scrape hasn't run / app emitted no metrics | Hit the web app a few times, wait 15s (scrape interval), refresh |
| `kubectl` says cluster unreachable | kind context not selected | `kubectl config use-context kind-kind` |

Useful diagnostics:

```bash
kubectl describe pod <pod>             # events, image-pull status, probe failures
kubectl get events --sort-by=.lastTimestamp | tail -20
kubectl logs <pod> --previous          # logs from the prior crash
```

---

## 13. Teardown

Remove the application stack but keep the cluster:

```bash
kubectl delete -k k8s/
```

Destroy the entire kind cluster (and its PVs):

```bash
kind delete cluster --name kind
```

---

## 14. Reference: file layout

```
k8s/
├── kind-config.yaml              # kind cluster (port mappings 30001, 30002)
├── kustomization.yaml            # entrypoint for `kubectl apply -k`
├── base/
│   ├── secrets.yaml              # postgres-user, postgres-password, database-url, secret-key
│   ├── configmaps.yaml           # app-config (incl. SYSTEM_TEST_ENABLED), prometheus-config (k8s SD), fluentd-config (CRI parser)
│   └── grafana-provisioning/     # datasources + 3 dashboards (mounted via generated CMs)
├── app/
│   ├── db.yaml                   # Postgres StatefulSet + headless Service
│   └── web.yaml                  # web Deployment + NodePort, downward-API env, prometheus.io/* annotations
└── monitoring/
    ├── prometheus.yaml           # StatefulSet + ServiceAccount/ClusterRole for k8s SD
    ├── prometheus-rules.yaml     # ConfigMap: 8 starter alert rules
    ├── alertmanager.yaml         # Deployment + Service + log-only receiver
    ├── grafana.yaml              # StatefulSet, NodePort 30002
    ├── jaeger.yaml               # all-in-one, ES backend, admin metrics 14269
    ├── elasticsearch.yaml        # 1g heap, watermarks, probes tuned for Docker pause
    ├── elasticsearch-init.yaml   # Job: PUT ILM policy + index template
    ├── fluentd.yaml              # DaemonSet tailing /var/log/containers/*_default_*.log
    ├── node-exporter.yaml        # DaemonSet
    ├── kube-state-metrics.yaml   # Deployment + RBAC
    ├── postgres-exporter.yaml    # Deployment, libpq DSN from app-secrets
    └── elasticsearch-exporter.yaml
```

Mirror configs for the docker-compose path live under `monitoring/` at repo root (kept in sync; less actively used).
