# Monitoring tests

End-to-end validation that the observability stack (Prometheus, Grafana, Jaeger,
Fluentd, Elasticsearch) is working. Runnable locally against a Kind cluster and
in CI.

## Quick start

```bash
# 1. Install Python deps (uses ../../venv/ if present, else errors with hint)
make install

# 2. After a fresh deploy, run smoke (~30s)
make smoke

# 3. Full suite (smoke + full + correlation tests)
make full
```

> **Homebrew/PEP 668 note:** macOS + Homebrew Python refuses system-wide
> `pip install`. The Makefile auto-detects the project venv at
> `<repo>/venv/bin/python` and uses it. If you don't have one yet:
> ```
> python3 -m venv ../../venv
> ../../venv/bin/pip install -r ../../requirements.txt
> make install
> ```
> To use a different interpreter: `make install PYTHON=/path/to/python`.

By default the tests use `kubectl port-forward` to reach each service. Override
any URL via env var to skip the port-forward (e.g. when ingress is set up):

```
PROMETHEUS_URL=http://prom.local:9090 \
ELASTICSEARCH_URL=http://es.local:9200 \
JAEGER_URL=http://jaeger.local:16686 \
GRAFANA_URL=http://grafana.local:3000 \
WEB_URL=http://app.local:5001 \
make smoke
```

## What's in the box

| File | What it does |
|---|---|
| `test_metrics.py`         | Asserts every metric a dashboard depends on is in Prometheus |
| `test_logs.py`            | Fires `/system-test/*` endpoints and confirms ES has the records |
| `test_traces.py`          | Confirms `ngo-management-app` is registered in Jaeger and has spans |
| `test_e2e_correlation.py` | Single request → metric + trace + (Phase 1) log all share trace_id |
| `test_dashboards.py`      | Walks every dashboard JSON and runs each panel's query against its datasource |
| `test_alerts.py`          | Skipped until Phase 1.4 deploys Alertmanager |
| `bash/smoke.sh`           | Workload health + per-component health probe |
| `bash/pipeline-check.sh`  | In-cluster `curl` to each service from a one-shot pod |
| `bash/load.sh`            | `hey`/curl driver, appends P50/P95/P99 to `results/load.csv` |
| `bash/chaos.sh`           | Rolling-restarts each workload and re-smokes |
| `bash/bootstrap.sh`       | `kubectl apply -k`, wait for rollouts, smoke |
| `bash/teardown.sh`        | Reap old ES indices + stale CSVs |

## Markers

```
pytest -m smoke         # ~30s
pytest -m full          # everything except correlation
pytest -m correlation   # the keystone end-to-end test
```

## Admin credentials

`test_logs.py` exercises admin-gated endpoints. Provide:

```
ADMIN_EMAIL=you@example.com
ADMIN_PASSWORD='...'
```

If these aren't set, the log tests are skipped (not failed).

## CI

`.github/workflows/monitoring.yml` spins up Kind, runs `bootstrap.sh`, then
`make smoke && make dash-check`. Logs are uploaded on failure.
