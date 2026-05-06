# Kubernetes User Guide

Operational reference for the Cybersecurity NGO Management platform on Kind. Pairs with `PROJECT-OVERVIEW.md` (architecture/endpoints) and `SETUP.md` (initial bring-up).

---

## 1. Workload inventory

After `kubectl apply -k k8s/`, the cluster runs:

### App tier
| Workload | Kind | Image | Notes |
|---|---|---|---|
| `web` | Deployment | `ngo-web-app:latest` (local) | NodePort 30001 → 5001. Annotated for Prometheus scrape with `prometheus.io/job: flask_app`. Downward-API env (`K8S_POD_NAME`/`NAMESPACE`/`NODE_NAME`). |
| `db` | StatefulSet | `postgres:15-alpine` | Headless `db-service`, PVC `postgres-data` 1Gi |

### Observability tier
| Workload | Kind | Image | Purpose |
|---|---|---|---|
| `prometheus` | StatefulSet | `prom/prometheus:latest` | Scrape via K8s pod SD; rules from `prometheus-rules` configmap; alerts to `alertmanager-service` |
| `alertmanager` | Deployment | `prom/alertmanager:v0.27.0` | 8 starter rules; log-only receiver until destination wired |
| `grafana` | StatefulSet | `grafana/grafana:9.5.18` | NodePort 30002. 3 dashboards provisioned |
| `jaeger` | Deployment | `jaegertracing/all-in-one:latest` | Stores spans in ES; admin metrics on `:14269` |
| `elasticsearch` | StatefulSet | `elasticsearch:8.10.2` | 1g heap, 2Gi PVC, watermark `85/90/95%`. ILM policy `fluentd-logs` (delete at 14d), index template applied via init Job |
| `elasticsearch-init` | Job | `curlimages/curl:8.5.0` | One-shot: PUTs ILM policy + `fluentd-*` index template. Idempotent, re-runs on each apply |
| `fluentd` | DaemonSet | `ngo-fluentd:latest` (local) | CRI parser, JSON re-parser, pod_name extractor from filename |

### Exporters (Phase 1.2)
| Workload | Image | Scrapes |
|---|---|---|
| `node-exporter` | `prom/node-exporter:v1.7.0` | Host CPU/memory/disk/network — DaemonSet |
| `kube-state-metrics` | `kube-state-metrics:v2.10.1` | Pod inventory, restarts, deployment health |
| `postgres-exporter` | `prometheuscommunity/postgres-exporter:v0.15.0` | `pg_up`, connection counts, commit rate |
| `elasticsearch-exporter` | `prometheuscommunity/elasticsearch-exporter:v1.7.0` | Cluster health, JVM heap, indexing rate |

All annotated `prometheus.io/scrape: "true"`. Adding a new exporter is a one-file change — no Prometheus configmap edit needed.

---

## 2. Quick start

```bash
# 1. Cluster
kind create cluster --name kind --config k8s/kind-config.yaml

# 2. Build + load local images
docker build -t ngo-web-app:latest .
docker build -t ngo-fluentd:latest ./monitoring/fluentd
kind load docker-image ngo-web-app:latest --name kind
kind load docker-image ngo-fluentd:latest --name kind

# 3. Apply everything (kustomize bundle)
kubectl apply -k k8s/

# 4. Verify
bash tests/monitoring/bash/smoke.sh
```

---

## 3. Access

| Service | Method | URL |
|---|---|---|
| Web app | NodePort | http://localhost:30001 |
| Grafana | NodePort | http://localhost:30002 (admin / admin) |
| System-test panel | NodePort + admin | http://localhost:30001/system-test/ |
| Jaeger | port-forward `svc/jaeger-service 16686:16686` | http://localhost:16686 |
| Prometheus | port-forward `svc/prometheus-service 9090:9090` | http://localhost:9090 |
| Elasticsearch | port-forward `svc/elasticsearch-service 9200:9200` | http://localhost:9200 |
| Alertmanager | port-forward `svc/alertmanager-service 9093:9093` | http://localhost:9093 |

---

## 4. Common operations

### Promote yourself to admin
```bash
kubectl exec deploy/web -- flask promote-admin you@example.com
```
Prereq: the user must already exist (sign up via `/auth` first).

### Tail app logs (filter by level)
```bash
kubectl logs -l app=web --tail=100 -f | jq 'select(.levelname=="ERROR")'
```

### Rebuild + redeploy the app
```bash
docker build -t ngo-web-app:latest .
kind load docker-image ngo-web-app:latest --name kind
kubectl rollout restart deploy/web
kubectl rollout status   deploy/web --timeout=180s
```

### Check Prometheus targets
```bash
kubectl port-forward svc/prometheus-service 9090:9090 &
curl -s 'http://127.0.0.1:9090/api/v1/targets' | jq '.data.activeTargets[] | {job:.labels.job, health}'
```

### Force-reapply ES index template + ILM
The init Job is idempotent — just re-run it:
```bash
kubectl delete job elasticsearch-init --ignore-not-found
kubectl apply -f k8s/monitoring/elasticsearch-init.yaml
```

### Disable observability v2 (rollback)
```bash
kubectl set env deploy/web OBSERVABILITY_V2=false
kubectl rollout status deploy/web
```
Reverts to legacy Flask + SQLAlchemy auto-instrumentation only — keeps the app up while you debug.

### Disable system-test endpoints
```bash
kubectl set env deploy/web SYSTEM_TEST_ENABLED=false
```
Every `/system-test/*` route returns 404.

### Connect to Postgres
```bash
kubectl port-forward svc/db-service 5432:5432
psql postgresql://postgres:postgres@127.0.0.1:5432/ngo_db
```

### Switch the Alertmanager destination
Edit the `receivers:` block in `k8s/monitoring/alertmanager.yaml`, swap the `webhook_configs` entry for `slack_configs`/`email_configs`/etc., then:
```bash
kubectl apply -f k8s/monitoring/alertmanager.yaml
kubectl rollout restart deployment/alertmanager
```

---

## 5. Architecture notes

### Workload kinds
- **StatefulSets** (`db`, `elasticsearch`, `prometheus`, `grafana`) — stable network IDs and persistent volumes that re-attach to the same pod.
- **Deployments** (`web`, `jaeger`, `alertmanager`, `kube-state-metrics`, `*-exporter`) — stateless or configmap-backed; can scale horizontally.
- **DaemonSets** (`fluentd`, `node-exporter`) — one pod per node. Fluentd tails `/var/log/containers/*_default_*.log` from the host filesystem.

### Persistence
- `db-0` → `postgres-data` PVC (1Gi)
- `elasticsearch-0` → `elasticsearch-data` PVC (2Gi). 14-day retention via ILM `fluentd-logs` policy.
- `grafana-0` → `grafana-storage` PVC (2Gi)
- `prometheus-0` → `prometheus-data` PVC (5Gi), 15d retention.

### Observability pipeline
1. **Logs**: Flask emits JSON to stdout → kubelet writes to `/var/log/containers/<pod>_<ns>_<container>.log` (CRI format) → Fluentd DaemonSet tails, parses CRI envelope, lifts inner app JSON, extracts pod_name/namespace/container_name from filename → ships to Elasticsearch as `fluentd-YYYY.MM.DD`. Index template applies to new daily indices.
2. **Metrics**: prometheus-flask-exporter on `/metrics` + custom `ngo_*` business metrics + 5 infra exporters → Prometheus scrapes via K8s pod SD (annotation-driven) → Grafana queries.
3. **Traces**: OTel Flask/SQLAlchemy/Requests/Jinja2/Logging instrumentation → OTLP gRPC to Jaeger collector → Jaeger stores spans in Elasticsearch. Trace IDs are correlated with log records via `otelTraceID` field.
4. **Alerts**: Prometheus evaluates 8 rules every 30s → Alertmanager groups + dedupes → currently log-only receiver.

---

## 6. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `web` stuck on `Init:0/1` | Postgres not Ready | Wait — init container polls until DB accepts connections |
| `elasticsearch-0` CrashLoopBackOff | Liveness probe too tight after Docker pause/sleep | Probe is now `failureThreshold=5`, `timeoutSeconds=10` — usually self-heals on restart |
| `jaeger` CrashLoopBackOff during bring-up | ES not Ready yet | Self-heals once ES is up; expect 1–4 restarts on cold start |
| `ErrImageNeverPull` on web/fluentd | Image not loaded into Kind | `kind load docker-image <name>:latest --name kind` |
| Prometheus target shows `down` | Pod missing `prometheus.io/scrape` annotation | Add the three annotations (`scrape`, `port`, `path`) to the pod template |
| `otelTraceID: "0"` in logs | Log emitted outside any Flask span (e.g. background task, OTel exporter retry) | Expected — only in-request logs carry real trace ids |
| `pod_name: "containers"` or `"-"` in ES docs | Tag-parsing regex mismatch | Check Fluentd config in `k8s/base/configmaps.yaml` — `tag_parts[-2]` should hit the filename |
| Alertmanager shows alerts firing | Real condition or rule misconfigured | `kubectl port-forward svc/prometheus-service 9090:9090` → http://localhost:9090/alerts to inspect |

Useful diagnostics:
```bash
kubectl describe pod <pod>
kubectl get events --sort-by=.lastTimestamp | tail -20
kubectl logs <pod> --previous
```

---

## 7. Teardown

Remove the application stack (keep cluster):
```bash
kubectl delete -k k8s/
```

Destroy the entire kind cluster + PVs:
```bash
kind delete cluster --name kind
```

---

*See also*: `PROJECT-OVERVIEW.md` for the canonical endpoint reference and `SETUP.md` for first-time setup details.
