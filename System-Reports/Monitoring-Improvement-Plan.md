# Monitoring Improvement Plan

> **Status: ✅ Complete (2026-05-06).** All phases shipped. Test suite went from 0 → 62 passing assertions across metrics/logs/traces/alerts/dashboards.
>
> | Phase | Status | Highlights |
> |---|---|---|
> | §5 / Phase 5 — Test module | ✅ | `tests/monitoring/` with pytest + bash, autodiscovers backends via port-forward |
> | §4 / Phase 4 — System-test expansion | ✅ | 14 fault-injection endpoints, kill-switch, semaphore, HTML control panel |
> | §1.1 — App instrumentation | ✅ | `observability.py`, log↔trace correlation, 5 custom business metrics |
> | §1.2 — Infra exporters | ✅ | node-exporter, kube-state-metrics, postgres-exporter, ES exporter, Jaeger metrics |
> | §1.3 — Prometheus K8s SD + RBAC | ✅ | annotation-driven scrape; static target list retired |
> | §1.4 — Alerting | ✅ | Alertmanager + 8 starter rules (log-only receiver, swap when destination chosen) |
> | §2 — Grafana dashboards | ✅ | 3 focused dashboards (App / Infra / Logs+Traces); old super-dashboard retired |
> | §3 — ES hardening | ✅ | Index template, ILM (14d delete), 1g heap, watermarks, pod_name extractor |
>
> Original plan kept below as historical record.

---

Scope: Flask app + Prometheus + Grafana + Jaeger + Fluentd + Elasticsearch deployed on Kind/Kubernetes (`k8s/monitoring/*`). This plan upgrades each layer and adds a comprehensive testing module that validates the end-to-end pipeline.

---

## 0. Current state — what's actually wrong

A short audit of what exists today, so the proposed changes have context.

| Area | Current | Problem |
|---|---|---|
| App metrics | `prometheus-flask-exporter` default counters/histograms | No business metrics, no DB pool, no auth/rate-limit, no per-endpoint labels |
| App tracing | OTel Flask + SQLAlchemy auto-instrumentation only | No Requests/HTTPX, no Jinja, no manual spans for business flows (donate, login, admin actions); resource has only `service.name` |
| App logs | `pythonjsonlogger` to stdout — fields: `asctime/levelname/name/message` | No request_id/trace_id correlation, no user_id, no route. Werkzeug logs at WARNING+ only — losing access logs |
| Prometheus scrape | One target: `web-service:5001` | No node-exporter, no kube-state-metrics, no ES/Jaeger/Fluentd self-metrics, no Alertmanager |
| Fluentd | Tails `/var/log/containers/*_default_*.log`, JSON parser, no k8s metadata filter | Glob is brittle; container runtime wraps app JSON in another JSON envelope, so app fields stay inside `log` string and aren't searchable. No `kubernetes_metadata_filter`, no record_transformer to lift level/logger/trace_id |
| Elasticsearch | `single-node`, security off, fixed 512m heap, no index template, no ILM, 2Gi PVC | Indices grow forever; fields auto-mapped as `text+keyword` so dashboards depend on guessed `.keyword` subfields (e.g. `source.keyword` doesn't exist → "Logs by source" tile is empty). No retention, no shard sizing, no rollover |
| Grafana | One dashboard, datasources point at bare hostnames `prometheus`, `jaeger`, `elasticsearch` | In K8s these resolve to `*-service` — datasource URLs are wrong unless overridden by the configmap in `k8s/base/grafana-provisioning`. "Logs by source" panel queries a non-existent field. No alerting rules, no variables (env, pod, route) |
| `routes/system_test.py` | 6 endpoints that emit logs / 500 / sleep | Useful for smoke, but doesn't exercise tracing, doesn't generate the cardinality needed for histogram buckets, doesn't validate that data actually reaches Prom/ES/Jaeger |
| Tests | None for monitoring | No verification that metrics/logs/traces appear after a deploy |

---

## 1. Improve instrumentation across all services

### 1.1 Application (Flask)

**Goal:** every request emits a metric, a structured log line, and a trace span — all correlated by `trace_id`.

- Replace ad-hoc setup with a single `observability.py` module imported once from `app.py`. It owns: logger config, OTel tracer provider, Prometheus exporter, propagators, and a `before_request`/`after_request` pair that injects `trace_id`/`span_id`/`request_id`/`user_id` into the log record.
- Add OTel auto-instrumentations:
  - `opentelemetry-instrumentation-requests` (outbound HTTP)
  - `opentelemetry-instrumentation-jinja2`
  - `opentelemetry-instrumentation-logging` (sets `otelTraceID`/`otelSpanID` on every record so logs join traces in Grafana)
- Enrich the OTel `Resource`: `service.name`, `service.version`, `service.namespace=ngo`, `deployment.environment=$ENV`, `k8s.pod.name`, `k8s.namespace.name` (from downward API env vars).
- Add manual spans on business flows in `routes/donor.py`, `routes/auth.py`, `routes/admin.py`: `donation.create`, `auth.login`, `auth.register`, `admin.promote`, `campaign.create`. Attributes: `donation.amount`, `auth.method`, `campaign.id`, etc. Mark errors with `span.record_exception` + `span.set_status(StatusCode.ERROR)`.
- Custom Prometheus metrics (`prometheus-flask-exporter` `Counter/Histogram` registered at module import):
  - `ngo_donations_total{campaign,status}`
  - `ngo_donation_amount_dollars` (Histogram, buckets `[1,5,10,25,50,100,500,1000]`)
  - `ngo_auth_attempts_total{result}` (success/fail/locked)
  - `ngo_db_pool_in_use` (gauge from SQLAlchemy pool)
  - `ngo_rate_limit_hits_total{endpoint}`
- Logging — extend the JSON formatter format string to `'%(asctime)s %(levelname)s %(name)s %(message)s %(otelTraceID)s %(otelSpanID)s %(request_id)s %(user_id)s %(route)s %(remote_addr)s %(status_code)s'`. Re-enable werkzeug at `INFO` so access logs flow.

### 1.2 Infrastructure exporters

Add as new K8s manifests under `k8s/monitoring/`:

- **node-exporter** (`DaemonSet`) — host CPU/memory/disk/network.
- **kube-state-metrics** (`Deployment`) — pod restarts, deployment health, PVC usage.
- **postgres-exporter** sidecar (or standalone Deployment) — connection count, slow queries, replication lag, table size.
- **elasticsearch-exporter** — JVM heap, indexing rate, search latency, cluster health.
- **fluentd-prometheus-plugin** — already shipped; expose port 24231 and add a Service + scrape config.
- **jaeger-collector metrics** — Jaeger emits Prometheus on `:14269` (collector) and `:16687` (query).

### 1.3 Prometheus scrape config

Replace static targets with K8s SD so new pods are discovered automatically:

```yaml
scrape_configs:
  - job_name: 'kubernetes-pods'
    kubernetes_sd_configs: [{role: pod}]
    relabel_configs:
      - source_labels: [__meta_kubernetes_pod_annotation_prometheus_io_scrape]
        action: keep
        regex: true
      - source_labels: [__meta_kubernetes_pod_annotation_prometheus_io_path]
        action: replace
        target_label: __metrics_path__
      # ... standard pod-SD relabels ...
```

Then annotate each workload (`web`, `node-exporter`, `kube-state-metrics`, `*-exporter`) with `prometheus.io/scrape: "true"` and the right path/port. Drops the hand-maintained target list.

Prometheus needs RBAC: a `ServiceAccount` + `ClusterRole` allowing `get/list/watch` on `pods/nodes/services/endpoints`. Add to `k8s/monitoring/prometheus.yaml`.

### 1.4 Alerting

Add **Alertmanager** (`k8s/monitoring/alertmanager.yaml`) and a `prometheus-rules` ConfigMap with starter rules:

- `HighErrorRate` — `sum(rate(flask_http_request_total{status=~"5.."}[5m])) / sum(rate(flask_http_request_total[5m])) > 0.05` for 10m
- `HighLatencyP95` — `histogram_quantile(0.95, ...) > 1` for 10m
- `PodCrashLooping` — `increase(kube_pod_container_status_restarts_total[15m]) > 3`
- `ESClusterUnhealthy` — `elasticsearch_cluster_health_status{color="red"} == 1`
- `LogPipelineStalled` — `rate(fluentd_output_status_buffer_total_bytes[5m])` flat for 15m

Route to a webhook or stdout receiver for now; Slack/email can wire in later.

---

## 2. Improve the Grafana dashboard

Goal: replace the single 21-panel "super-dashboard" with **3 focused dashboards**, fix broken panels, and add variables.

### 2.1 Fix the broken/weak panels

| Panel | Issue | Fix |
|---|---|---|
| "Logs by Source (stdout vs stderr)" | Queries `source.keyword` — that field is never set anywhere in the pipeline | Drop this panel. Replace with **"Logs by Level"** using `level.keyword` (which the JSON formatter does emit as `levelname`) or **"Logs by Pod"** using `kubernetes.pod_name.keyword` once the k8s_metadata filter is in place |
| "Logs by Tag" rendered as **Gauge** with multiple series | Wrong viz — gauge can't compare categories | Change `type` to `barchart` or `piechart` |
| "DB SELECT/INSERT Traces" status-history panels | Always empty unless an op named exactly `SELECT ngo_db` exists | Replace with a Jaeger search panel filtered by `db.system=postgresql` and a Prometheus panel `histogram_quantile(0.95, sum(rate(db_client_operation_duration_seconds_bucket[5m])) by (le, db_operation))` once OTel SQL spans flow into a Prom histogram via the metrics-from-spans connector |
| Datasource URLs `http://prometheus:9090` etc. | K8s Services are `prometheus-service`, `jaeger-service`, `elasticsearch-service` | Update `monitoring/grafana/provisioning/datasources/datasources.yml` and the in-cluster ConfigMap to the `*-service` names |
| `time.from = now-5m` | Too short; most panels look empty on first load | Default to `now-1h`, refresh `30s` |

### 2.2 Three dashboards instead of one

1. **App Overview** — RED metrics (Rate/Errors/Duration), top routes by latency, top routes by error rate, donation funnel (`ngo_donations_total` by status), auth attempts. Drilldown links to Jaeger by `route` variable.
2. **Infrastructure** — node CPU/memory/disk (node-exporter), pod restarts (kube-state-metrics), DB pool / Postgres stats, Elasticsearch cluster health, Jaeger collector throughput.
3. **Logs & Traces** — log volume by level, error log live tail (filtered by `$pod` and `$level` variables), trace search panel, top slow operations from Jaeger.

### 2.3 Variables

Add at dashboard scope: `namespace`, `pod` (from `label_values(kube_pod_info, pod)`), `route`, `level`, `interval` (`$__rate_interval`). All panels parameterize on these. Lets one dashboard serve dev/staging/prod.

### 2.4 Folder structure & provisioning

```
monitoring/grafana/provisioning/dashboards/
  app/         # app-overview.json
  infra/       # infrastructure.json
  logs/        # logs-traces.json
```

Update `dashboards.yml` to recurse with `foldersFromFilesStructure: true`. Mount each as a separate ConfigMap so a single dashboard edit doesn't invalidate the whole bundle.

---

## 3. Improve Elasticsearch configuration

### 3.1 Index template

Define an index template applied at startup (via an init Job that calls the ES API) for `fluentd-*`:

- Explicit mappings for `level`, `logger`, `message`, `kubernetes.pod_name`, `kubernetes.namespace`, `kubernetes.container_name`, `otelTraceID`, `request_id`, `user_id` — all `keyword` except `message` (`text` + `keyword` subfield, ignore_above 8192).
- `index.refresh_interval: 5s`, `number_of_shards: 1`, `number_of_replicas: 0` (single-node).
- `index.codec: best_compression`.

Without this, every new field gets a dynamic mapping with both `text` and `.keyword` subfields, ballooning storage and producing fields like `source.keyword` that dashboards then fail to find.

### 3.2 ILM (Index Lifecycle Management)

Policy `fluentd-logs`:

- **hot** — rollover at 1GB or 1d, max 7d
- **delete** — at 14d total

Apply via the same init Job. Without ILM the StatefulSet's 2Gi PVC will fill in days under any real load.

### 3.3 Cluster hardening

- Bump heap to a sized value: `ES_JAVA_OPTS=-Xms1g -Xmx1g` and add resource requests/limits matching it (heap should be ≤50% of container memory limit).
- Enable security in dev too (`xpack.security.enabled=true` with bootstrap password from a Secret) — keeps prod parity.
- Add `cluster.routing.allocation.disk.watermark.*` thresholds so ES doesn't go read-only when the PVC fills.
- PVC: bump to **10Gi** and switch to a `StorageClass` with `volumeBindingMode: WaitForFirstConsumer` so it binds on the right node in Kind.

### 3.4 Fluentd improvements

Update `k8s/base/configmaps.yaml` `fluent.conf`:

- Add `<filter kubernetes.**>` with `@type kubernetes_metadata` to enrich every record with pod/namespace/container/labels.
- Add `<filter kubernetes.**>` with `@type parser` on the `log` field so the JSON the app emits is lifted to top-level (otherwise `level`, `request_id`, `otelTraceID` stay buried inside the `log` string).
- Add `<filter>` with `@type record_transformer` to add `cluster: ngo-kind`, `env: dev`.
- Tighten the buffer: `chunk_limit_size 8MB`, `total_limit_size 512MB`, `retry_max_interval 30`, `flush_thread_count 2`, `overflow_action block` (don't drop logs).
- Add `<match fluent.**>` to discard fluentd's own internal logs from ES.
- Drop the `latest` tag on the fluentd image; pin a version.

---

## 4. Make the system-test module practical

Today `routes/system_test.py` is six toy endpoints. Expand it into a **monitoring fault-injection toolkit** that exercises every signal the dashboards depend on.

### 4.1 New endpoints (add to `routes/system_test.py`)

| Endpoint | Behavior | Validates |
|---|---|---|
| `POST /system-test/load?rps=N&duration=S` | Internal goroutine-equivalent (thread) hammers `/` for `S` seconds at `N` rps | Histogram buckets, rate panels, scrape resolution |
| `GET /system-test/db?n=100` | Runs N small queries with random parameters | SQLAlchemy spans, DB pool gauge, slow-query alert |
| `GET /system-test/db-slow` | Forces a 2s `pg_sleep(2)` query | Slow-query alert, P99 latency spike |
| `GET /system-test/trace-deep?depth=5` | Emits nested manual spans | Jaeger drilldown, span hierarchy |
| `GET /system-test/log-storm?n=1000&level=info` | Emits N JSON logs at given level with realistic shape (route, user_id, trace_id) | Fluentd buffer, ES indexing rate, log-level dashboard |
| `GET /system-test/memory-leak?mb=50&hold=30` | Allocates `mb` MB into a list for `hold`s | Memory panel, OOMKill alert |
| `GET /system-test/panic` | Raises uncaught — Flask 500 + span error | Error rate alert, exception logging |
| `POST /system-test/donation-burst?n=50` | Calls the real donation flow N times with fake users | End-to-end metrics: `ngo_donations_total`, traces, audit logs |
| `GET /system-test/healthcheck-deep` | Pings ES, Prometheus, Jaeger from inside the pod and returns a JSON map | Verifies cluster networking and component liveness in one call |

All gated by `@admin_required`. Add a kill-switch env var `SYSTEM_TEST_ENABLED=true` that, when unset, makes the blueprint return 404 — so this can ship to prod safely.

### 4.2 Frontend control panel

Add `templates/system_test.html` with buttons for each endpoint and a live result pane (XHR). Linked from admin nav so testing doesn't require curl.

### 4.3 Resource limits

Wrap the heavy endpoints in a per-process semaphore (`threading.BoundedSemaphore(2)`) so a misclick can't take down the pod.

---

## 5. Comprehensive testing module (Python + Bash)

A new top-level directory `tests/monitoring/` that proves the observability stack is working — runnable locally, in CI, and post-deploy.

### 5.1 Layout

```
tests/monitoring/
  README.md
  conftest.py                 # fixtures: K8s context, port-forwards, HTTP clients
  pytest.ini
  fixtures/
    expected_metrics.yaml     # list of metric names that MUST exist
    expected_logs.yaml        # log queries that must return >0 hits
    expected_traces.yaml      # service+operation pairs that must exist
  test_metrics.py             # asserts each metric in fixtures is scraped
  test_logs.py                # asserts ES has docs for each fixture query
  test_traces.py              # asserts Jaeger has spans for each fixture
  test_alerts.py              # fires the load-test endpoint, polls Prom for alert ACTIVE state
  test_dashboards.py          # for each panel in each dashboard JSON, runs the query against Grafana proxy and asserts non-error response
  test_e2e_correlation.py     # sends a request, extracts trace_id, asserts the same trace_id is in (a) Jaeger, (b) ES logs, (c) Prom exemplar
  bash/
    smoke.sh                  # 30-second post-deploy smoke (curl + jq)
    chaos.sh                  # restarts pods sequentially, runs smoke between, asserts SLO not breached
    load.sh                   # uses hey or wrk against the cluster ingress for N minutes
    pipeline-check.sh         # one-liner per component: kubectl exec ... + curl /metrics, /_cluster/health, etc.
    bootstrap.sh              # idempotent: applies kustomize, waits for rollouts, runs smoke.sh
    teardown.sh               # tears down test indices/data (not the cluster)
```

### 5.2 Python side — what each test does

- **`test_metrics.py`** — parametrised on `expected_metrics.yaml`. Queries Prometheus `/api/v1/query` for each; asserts `result` non-empty and value type as expected. Catches regressions where a new code path stops exposing a counter.
- **`test_logs.py`** — uses the ES `_search` API. For each fixture (e.g. `level=ERROR AND kubernetes.container_name=web` in last 5m, hits > 0 after firing `/system-test/error`). Forces deterministic data first via the system-test endpoints, then asserts.
- **`test_traces.py`** — calls Jaeger HTTP API `/api/services` then `/api/traces?service=ngo-management-app&operation=donation.create&limit=5`. Asserts `data` non-empty and that span has expected attributes.
- **`test_e2e_correlation.py`** — the keystone test. Generates a UUID, sends `GET /?probe=<uuid>`, captures `traceparent` from response headers, then within 30s polls all three backends until the same trace_id is present in each. Proves the propagation chain isn't silently broken.
- **`test_dashboards.py`** — loads every JSON in `monitoring/grafana/provisioning/dashboards/`, walks `panels[*].targets`, runs each `expr` against Prometheus / each ES query against ES, fails if any returns an error. Means dashboard breakage shows up in CI, not at 2am.
- **`test_alerts.py`** — fires `/system-test/load?rps=200&duration=120`, polls Prometheus `/api/v1/alerts` until `HighErrorRate` is `firing` (or asserts it never fires depending on the alert), then waits for it to clear.

### 5.3 Bash side — what each script does

- **`bootstrap.sh`** — `kubectl apply -k k8s/`, `kubectl rollout status` for every Deployment/StatefulSet, then `pytest -m smoke`. The single command an operator runs after `kind create cluster`.
- **`smoke.sh`** — 30-second pipeline check. Hits each NodePort, asserts 200, queries Prometheus `up{}`, asserts every job is `1`. Returns non-zero on first failure with a clear `FAIL: <component> — <reason>` line.
- **`pipeline-check.sh`** — for each backend, `kubectl exec` into a debug pod and `curl` the in-cluster URL. Distinguishes "ingress broken" from "service broken" from "pod broken".
- **`chaos.sh`** — `for d in $(kubectl get deploy -o name); do kubectl rollout restart $d; sleep 30; ./smoke.sh; done`. Verifies the system recovers gracefully.
- **`load.sh`** — wraps `hey` or `wrk` (auto-installs via `brew`/`apt` if missing). Outputs P50/P95/P99 to stdout and to a CSV under `tests/monitoring/results/` for trend tracking.

### 5.4 Wiring

- Add `tests/monitoring/Makefile`: targets `smoke`, `full`, `chaos`, `load`, `dash-check`. Make is the lingua franca between Python and Bash here.
- Add a GitHub Actions workflow `.github/workflows/monitoring.yml`: spins up Kind, runs `bootstrap.sh`, runs `make smoke && make dash-check`, uploads logs on failure.
- Add `pytest -m smoke` markers so the same test file serves both fast CI and full nightly runs.

### 5.5 Test data hygiene

- `conftest.py` creates a per-run UUID stamp and tears down ES docs matching it after the run (`DELETE fluentd-*/_doc/_query`) so successive runs don't accumulate.
- Tests are idempotent and don't rely on absolute counts — only on "≥ N after we fired N+ events" deltas.

---

## Phasing & rough sizing

A suggested order so each phase compounds:

1. **Phase 1 — Instrumentation (1–2d)** — §1.1, §1.2, §1.3. New metrics flowing.
2. **Phase 2 — ES & Fluentd hardening (1d)** — §3. Logs become structured & retained.
3. **Phase 3 — Dashboards (1d)** — §2. Now the new data is visible.
4. **Phase 4 — Alerts (0.5d)** — §1.4.
5. **Phase 5 — System-test expansion (0.5d)** — §4.
6. **Phase 6 — Test module (1–2d)** — §5. Closes the loop.

---

## Open questions for you

- Single-node ES forever, or do you want a multi-node setup once we're off Kind? -Yes 
- Alertmanager destination — Slack webhook, email, or just stdout for now? - Slack Webhook 
- Do you want the system-test module behind a feature flag, or admin-only is enough?- Yes
- Postgres exporter as sidecar to `db` pod, or standalone Deployment?-Sidecar
