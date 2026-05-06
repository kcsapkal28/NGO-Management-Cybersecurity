# NGO Management Platform — Project Overview

A donation-tracking web app for an NGO ("Hope Foundation") with a fully-instrumented observability stack. Originally built for a cybersecurity coursework focus on operational visibility — every layer (app, DB, logs, traces, metrics, alerts) is wired up and validated by an end-to-end test suite.

---

## 1. Stack

| Layer | Component | Notes |
|---|---|---|
| Web framework | Flask 3.0 + Gunicorn | sync workers |
| ORM | SQLAlchemy 3 | Postgres in K8s, SQLite fallback for dev |
| Database | Postgres 15 | StatefulSet, headless `db-service` |
| Auth | Session cookies + bcrypt | CSRF via Flask-WTF, rate-limit via Flask-Limiter |
| Frontend | Server-rendered Jinja + Bootstrap 5 | no SPA |
| Metrics | Prometheus + prometheus-flask-exporter + custom counters/histograms/gauges | scrape via K8s pod SD |
| Tracing | OpenTelemetry → Jaeger (all-in-one) → Elasticsearch backend | Flask + SQLAlchemy + Requests + Jinja2 + Logging instrumented |
| Logs | python-json-logger → Fluentd (DaemonSet) → Elasticsearch | log↔trace correlated via `otelTraceID` |
| Dashboards | Grafana 9.5, three dashboards provisioned via configmap | App / Infrastructure / Logs+Traces |
| Alerting | Alertmanager + 8 starter rules | log-only receiver until destination is wired |
| Orchestration | Kubernetes (Kind locally) via kustomize | docker-compose path also kept for parity |
| Testing | pytest + bash | 62 assertions across metrics/logs/traces/alerts/dashboards |

---

## 2. Architecture (text diagram)

```
                              ┌────────────────┐
                              │   Browser      │
                              └────────┬───────┘
                                       │ NodePort 30001
                                       ▼
   ┌──────────────────────────────────────────────────────────┐
   │  web (Deployment, gunicorn × 4 workers)                  │
   │  ───────────────────────────────────────                 │
   │  Flask + observability.py                                │
   │   • OTel auto-instrumentation                            │
   │   • Custom metrics (donations, auth, db_pool, …)         │
   │   • Structured JSON logs (otelTraceID, request_id, …)    │
   │  ───────────────────────────────────────                 │
   │  ▼ stdout                                                │
   └──┬─────┬──────────────┬────────────────────────────────  ┘
      │     │              │
      │     │              │ /metrics                        scrape via SD
      │     │              ▼                                       ↑
      │     │      ┌───────────────┐    ┌──────────────────┐       │
      │     │      │ Prometheus    │───▶│ Alertmanager     │       │
      │     │      │ (rules+SD)    │    │ (log-only rcvr)  │       │
      │     │      └─────┬─────────┘    └──────────────────┘       │
      │     │            │ scrapes                                 │
      │     │            ▼                                         │
      │     │  exporters:  node-exporter (DS)                      │
      │     │              kube-state-metrics                      │
      │     │              postgres-exporter                       │
      │     │              elasticsearch-exporter                  │
      │     │              jaeger (admin port :14269)              │
      │     │              alertmanager self-metrics               │
      │     │
      │     │ OTLP gRPC :4317                  ┌─────────────────┐
      │     └──────────────────────────────────▶│   Jaeger AIO    │
      │                                        │  (UI :16686)    │
      │                                        └────────┬────────┘
      │ JSON to stdout                                  │ span storage
      │  ↓ collected by                                 ▼
      │  /var/log/containers/*.log              ┌───────────────┐
      │                                         │ Elasticsearch │
      │  ┌─────────────────┐                    │  (1g heap,    │
      │  │ Fluentd (DS)    │───────────────────▶│  ILM 14d,     │
      │  │  CRI parser     │                    │  template,    │
      │  │  +pod_name xtr  │                    │  watermarks)  │
      │  └─────────────────┘                    └───────┬───────┘
      │                                                 │
      │                                                 ▼
      │                                        ┌────────────────┐
      └─ session, donations ──▶  Postgres      │   Grafana      │
                                 (StatefulSet) │  (3 dashbds)   │
                                               └────────────────┘
```

---

## 3. Routes

All routes are defined under `routes/`. Auth model: session cookies; admin pages additionally require `session['is_admin']`.

### 3.1 Public (`routes/public.py`)

| Method | Path | Auth | Returns |
|---|---|---|---|
| GET | `/` | none | `index.html` — top-3 active campaigns |
| GET | `/about` | none | `about.html` — mission/vision/history (text + faker team) |
| GET | `/blogs` | none | `blogs.html` — 6 sample blog posts |

### 3.2 Auth (`routes/auth.py`)

All limited by Flask-Limiter; rejected requests bump `ngo_rate_limit_hits_total{endpoint}`.

| Method | Path | Auth | Body | Notes |
|---|---|---|---|---|
| GET | `/auth` | none | — | renders `login_signup.html` (form has CSRF token) |
| POST | `/signup` | none | `username`, `email`, `password`, `csrf_token` | rate: `5/min, 20/hour`. Span: `auth.register`. Counter: `ngo_auth_attempts_total` |
| POST | `/login` | none | `email`, `password`, `csrf_token` | rate: `10/min, 100/hour`. On admin success → redirect `/admin`. Span: `auth.login` |
| GET | `/logout` | session | — | clears session |

### 3.3 Donor (`routes/donor.py`)

| Method | Path | Auth | Body / Params | Notes |
|---|---|---|---|---|
| GET | `/campaigns` | none | — | list active campaigns |
| GET | `/donate` | optional | `?campaign_id=N` | render donation form |
| POST | `/api/process_payment` | session | JSON `{amount, campaign_id, donation_type, payment_method}` | rate: `10/min, 50/hour`. Span: `donation.create`. Counter: `ngo_donations_total{campaign,status}`. Histogram: `ngo_donation_amount_dollars`. Cap: `MAX_DONATION_AMOUNT=$100,000` |
| GET | `/dashboard` | session | — | donor's donation history (`donor_dashboard.html`) |

### 3.4 Admin (`routes/admin.py`)

All require `session['is_admin']`. Promote a user with `flask promote-admin <email>` (CLI command in `app.py`).

| Method | Path | Body / Params | Notes |
|---|---|---|---|
| GET | `/admin` | — | dashboard: total raised, active donors/campaigns, recent transactions, top donors |
| GET | `/admin/campaigns` | `?page=N` | paginated campaign list (10/page) |
| POST | `/admin/campaigns` | `title`, `description`, `goal_amount`, `category` | create new campaign |
| POST | `/admin/campaigns/<id>/close` | — | mark `is_active=False` |
| GET | `/admin/donors` | `?page=N` | aggregate donors (20/page) |
| GET | `/admin/transactions` | `?page=N` | all donations (50/page) |
| POST | `/admin/generate_dummy_data` | — | seeds 10 campaigns + 50 users + 300 donations via Faker |

### 3.5 System Test (`routes/system_test.py`)

**Gated globally** by `SYSTEM_TEST_ENABLED=true` env. When unset, every `/system-test/*` returns plain `404 Not Found` (looks unmounted). Heavy ops are throttled by a process-wide `BoundedSemaphore(2)` and return `429` if 2 are already running. All require admin auth.

| Method | Path | Heavy? | Purpose |
|---|---|---|---|
| GET | `/system-test/` | no | HTML control panel with a button per endpoint |
| GET | `/system-test/traffic` | no | random-status-code response |
| GET | `/system-test/error` | no | logs ERROR + returns 500 |
| GET | `/system-test/warning` | no | logs WARNING |
| GET | `/system-test/slow` | no | random 0.5–3s sleep |
| GET | `/system-test/logs` | no | fires DEBUG/INFO/WARNING/ERROR/CRITICAL |
| GET | `/system-test/simulate` | no | mixed log+latency+error walk |
| GET | `/system-test/load?rps=N&duration=S&path=/` | yes | background thread drives load. caps: `rps≤100`, `duration≤120s` |
| GET | `/system-test/db?n=N` | yes | N×2 SQLAlchemy queries. cap: `n≤500` |
| GET | `/system-test/db-slow?seconds=N` | yes | `pg_sleep(N)` on Postgres, Python sleep on SQLite. cap: `≤10s` |
| GET | `/system-test/trace-deep?depth=N` | no | nested manual OTel spans. cap: `depth≤15` |
| GET | `/system-test/log-storm?n=N&level=info` | yes | N JSON log lines. cap: `n≤5000` |
| GET | `/system-test/memory-leak?mb=N&hold=S` | yes | allocate, hold, release. cap: `mb≤200`, `hold≤60s` |
| GET | `/system-test/panic` | no | uncaught `RuntimeError` → 500 + span error |
| GET/POST | `/system-test/donation-burst?n=N` | yes | inserts N synthetic `Donation` rows. cap: `n≤200`. CSRF-exempt for the POST form |
| GET | `/system-test/healthcheck-deep` | no | in-pod probe of ES/Prom/Jaeger/self with timing report (JSON) |

---

## 4. Custom Metrics (Prometheus)

All registered in `observability.py`. Pre-initialized at zero with known label combos so dashboards work from the first scrape.

| Metric | Type | Labels |
|---|---|---|
| `ngo_donations_total` | Counter | `campaign`, `status` (`completed`/`rejected`/`failed`) |
| `ngo_donation_amount_dollars` | Histogram | buckets: `1, 5, 10, 25, 50, 100, 250, 500, 1000, 5000` |
| `ngo_auth_attempts_total` | Counter | `result` (`success`/`invalid`/`missing_fields`/`locked`) |
| `ngo_db_pool_in_use` | Gauge | (live, via `set_function(pool.checkedout)`) |
| `ngo_rate_limit_hits_total` | Counter | `endpoint` |

Plus the default Flask metrics (`flask_http_request_total`, `flask_http_request_duration_seconds_bucket`, etc.) and python-client process metrics.

## 5. Alerts

8 rules in `k8s/monitoring/prometheus-rules.yaml`, evaluated every 30s.

| Group | Alert | Threshold | Severity |
|---|---|---|---|
| ngo-app | HighErrorRate | 5xx ratio > 5% for 10m | warning |
| ngo-app | HighLatencyP95 | P95 > 1s for 10m | warning |
| ngo-app | WebAppDown | `up{job="flask_app"}==0` for 2m | critical |
| infra | PodCrashLooping | >3 restarts in 15m for 5m | warning |
| infra | PodNotReady | not ready for 10m | warning |
| storage | ESClusterUnhealthy | status RED for 5m | critical |
| storage | PostgresDown | `pg_up==0` for 2m | critical |
| storage | ESDiskPressure | filesystem >85% for 10m | warning |

---

## 6. Starting Setup

### 6.1 Prerequisites

| Tool | Version |
|---|---|
| docker | recent |
| kind | ≥0.20 |
| kubectl | ≥1.27 |
| python | 3.11+ |
| make | any |

### 6.2 First-time bring-up (Kubernetes / Kind)

```bash
# 1. Create the cluster
kind create cluster --name kind --config k8s/kind-config.yaml

# 2. Build the app + fluentd images and load them into Kind
docker build -t ngo-web-app:latest .
docker build -t ngo-fluentd:latest monitoring/fluentd
kind load docker-image ngo-web-app:latest --name kind
kind load docker-image ngo-fluentd:latest --name kind

# 3. Apply everything (kustomize bundle: secrets, app, monitoring stack)
kubectl apply -k k8s/

# 4. Wait for rollouts (or just run smoke.sh which waits + verifies)
bash tests/monitoring/bash/smoke.sh

# 5. Promote yourself to admin
#    (sign up via /auth in the browser first, then:)
kubectl exec deploy/web -- flask promote-admin you@example.com
```

Access points:
| URL | What |
|---|---|
| `http://localhost:30001/` | App (NodePort) |
| `http://localhost:30001/auth` | Login / signup |
| `http://localhost:30001/system-test/` | Fault-injection panel (admin) |
| `http://localhost:30002/` | Grafana — admin / admin |

For the in-cluster components without NodePort, use port-forward:
```bash
kubectl port-forward svc/prometheus-service    9090:9090
kubectl port-forward svc/jaeger-service       16686:16686
kubectl port-forward svc/elasticsearch-service 9200:9200
kubectl port-forward svc/alertmanager-service  9093:9093
```

### 6.3 Local-only (no Kubernetes)

`docker-compose.yml` is kept in sync for the same stack. From repo root:

```bash
docker-compose up -d
```

Then `http://localhost:5001/` for the app and `http://localhost:3000/` for Grafana.

If you don't even want Docker, plain Flask:
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
export SECRET_KEY=$(python -c "import secrets;print(secrets.token_hex(32))")
export OBSERVABILITY_V2=true
export SYSTEM_TEST_ENABLED=true
python app.py
```
SQLite is the fallback (`ngo_database.db` in the project root); no Postgres needed. Tracing/logs still emit but with no Jaeger/Fluentd to receive them they're inert.

### 6.4 Configuration knobs

| Env var | Default | Effect |
|---|---|---|
| `SECRET_KEY` | (required) | Flask session signing |
| `DATABASE_URL` | sqlite | Postgres DSN |
| `JAEGER_HOST` | `jaeger` | OTLP gRPC collector hostname |
| `OBSERVABILITY_V2` | `true` | Enable v2 instrumentation (log enrichment, custom metrics, requests/jinja/logging instrumentation). `false` = legacy minimal setup |
| `SYSTEM_TEST_ENABLED` | `false` | Mount the `/system-test/*` blueprint |
| `APP_ENV` | `dev` | `deployment.environment` resource attribute |
| `K8S_POD_NAME`/`K8S_NAMESPACE`/`K8S_NODE_NAME` | (downward API) | Resource attributes on every span/log |
| `SESSION_COOKIE_SECURE` | `false` | Set `true` behind HTTPS |

Secrets in K8s come from `k8s/base/secrets.yaml` (`postgres-user`, `postgres-password`, `database-url`, `secret-key`).

---

## 7. Test Suite

```
tests/monitoring/
├── conftest.py                # auto-port-forward fixtures for every backend
├── _helpers.py                # prom_query, es_count, jaeger_*
├── fixtures/                  # expected_metrics.yaml, expected_logs.yaml, expected_traces.yaml
├── test_metrics.py            # 16 metrics validated against Prometheus
├── test_logs.py               # 8 log queries against Elasticsearch (admin auth)
├── test_traces.py             # 4 Jaeger checks (service, ops, traces with spans)
├── test_alerts.py             # 4 Alertmanager + rule-loaded checks
├── test_dashboards.py         # validates every panel query in all 3 dashboards
├── test_e2e_correlation.py    # keystone: a request → metric + trace + log all sharing trace_id
├── Makefile                   # smoke / full / chaos / load / dash-check / bootstrap / teardown
└── bash/                      # smoke.sh, pipeline-check.sh, load.sh, chaos.sh, bootstrap.sh, teardown.sh
```

Run from repo root or from `tests/monitoring/`:
```bash
make smoke          # ~10s, 18 assertions
make full           # ~15s, 62 assertions (covers smoke + full + correlation + alerts)
make chaos          # restart each workload, re-smoke between
make load           # hey/curl, append P50/P95/P99 to results/load.csv
make dash-check     # walk every panel, validate query against datasource
```

For log tests:
```bash
export ADMIN_EMAIL=you@example.com
export ADMIN_PASSWORD='...'
make full
```

---

## 8. Workspace Layout

```
.
├── app.py                       # Flask entrypoint, CLI command
├── observability.py             # logging + tracing + metrics + hooks
├── extensions.py                # CSRFProtect, Limiter
├── models.py                    # User / Campaign / Donation
├── utils.py                     # login_required / admin_required
├── routes/
│   ├── public.py
│   ├── auth.py
│   ├── donor.py
│   ├── admin.py
│   └── system_test.py
├── templates/                   # Jinja2 (server-rendered)
├── static/                      # CSS, images
├── monitoring/                  # docker-compose-side configs (kept in sync)
│   ├── fluentd/{Dockerfile,fluent.conf}
│   ├── prometheus/prometheus.yml
│   └── grafana/provisioning/{datasources,dashboards}
├── k8s/
│   ├── kustomization.yaml
│   ├── kind-config.yaml
│   ├── base/{secrets,configmaps,grafana-provisioning}
│   ├── app/{db,web}.yaml
│   └── monitoring/              # 12 manifests (prometheus, jaeger, ES, fluentd,
│                                #   grafana, alertmanager, exporters, init Job)
├── tests/monitoring/            # full test module (62 assertions)
├── Dockerfile                   # web app image
├── docker-compose.yml
├── requirements.txt
├── pytest.ini                   # rooted at repo, scopes pytest to tests/monitoring
└── System-Reports/              # design docs
    ├── Monitoring-Improvement-Plan.md
    ├── K8s-User-Guide.md
    └── PROJECT-OVERVIEW.md      # this file
```

---

## 9. Common Operations

### Get / promote admin

```bash
kubectl exec deploy/web -- flask promote-admin you@example.com
```
The user must exist (sign up first via `/auth`).

### Tail app logs (filtered to ERRORs)

```bash
kubectl logs -l app=web --tail=100 -f | jq 'select(.levelname=="ERROR")'
```

### Drop & recreate ES indices (force template re-application)

```bash
kubectl port-forward svc/elasticsearch-service 9200:9200 &
curl -X DELETE 'http://localhost:9200/fluentd-*'
```

### Switch the alertmanager destination

Edit the `receivers:` block in `k8s/monitoring/alertmanager.yaml`, swap the `webhook_configs` entry for `slack_configs`/`email_configs`/etc., then:

```bash
kubectl apply -f k8s/monitoring/alertmanager.yaml
kubectl rollout restart deployment/alertmanager
```

### Rebuild + redeploy the app after a code change

```bash
docker build -t ngo-web-app:latest . && \
kind load docker-image ngo-web-app:latest --name kind && \
kubectl rollout restart deployment/web && \
kubectl rollout status deployment/web
```

### Disable observability v2 if it misbehaves

```bash
kubectl set env deploy/web OBSERVABILITY_V2=false
kubectl rollout status deployment/web
```
Reverts to legacy Flask + SQLAlchemy auto-instrumentation only — keeps the app up while you debug.

### Disable system-test endpoints in prod

```bash
kubectl set env deploy/web SYSTEM_TEST_ENABLED=false
```
Every `/system-test/*` route returns 404 again.

---

## 10. References

- `Monitoring-Improvement-Plan.md` — original improvement plan, all phases now complete
- `K8s-User-Guide.md` — k8s-specific operator notes
- Default Grafana login: `admin` / `admin` (set in `k8s/monitoring/grafana.yaml`)
