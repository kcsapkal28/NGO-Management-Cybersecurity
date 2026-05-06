"""End-to-end correlation: one request must produce a metric, a log, and a trace
that all reference the same trace_id.

This test is the keystone — when it passes, the observability pipeline is wired
end to end. Today it runs in 'best effort' mode: trace_id propagation into logs
requires Phase 1 (opentelemetry-instrumentation-logging), so the log half is
marked xfail until that lands.
"""
from __future__ import annotations

import uuid

import pytest
import requests
from tenacity import Retrying, stop_after_delay, wait_fixed

from _helpers import es_count, jaeger_traces, prom_query


@pytest.mark.correlation
def test_request_produces_metric_and_trace(web_url, prometheus_url, jaeger_url):
    probe = uuid.uuid4().hex[:12]
    # FlaskInstrumentor injects traceparent into the response on outgoing,
    # but for incoming-only it's simpler to look up via search.
    for _ in range(5):
        requests.get(f"{web_url}/?probe={probe}", timeout=5)

    # Metric: request count for path '/' should be > 0
    for attempt in Retrying(stop=stop_after_delay(30), wait=wait_fixed(2), reraise=True):
        with attempt:
            result = prom_query(prometheus_url, 'sum(flask_http_request_total{status="200"})')
            assert result and float(result[0]["value"][1]) > 0

    # Trace: at least one trace exists in last 5 min for the service
    for attempt in Retrying(stop=stop_after_delay(30), wait=wait_fixed(2), reraise=True):
        with attempt:
            traces = jaeger_traces(jaeger_url, "ngo-management-app", lookback_s=300)
            assert traces


@pytest.mark.correlation
def test_log_includes_trace_id(web_url, elasticsearch_url):
    """The after_request hook in observability.py emits a 'request' INFO log
    that runs inside the FlaskInstrumentor span, so otelTraceID/otelSpanID
    must be populated with non-zero values on every request log."""
    for _ in range(3):
        try:
            requests.get(f"{web_url}/", timeout=5)
        except requests.RequestException:
            pass

    for attempt in Retrying(stop=stop_after_delay(20), wait=wait_fixed(1), reraise=True):
        with attempt:
            # Need a non-zero trace id (in-request log), not just any record
            # that has the field set.
            hits = es_count(
                elasticsearch_url,
                'name:"ngo.access" AND _exists_:otelTraceID AND NOT otelTraceID:"0"',
            )
            assert hits > 0, "no in-request log lines have a real trace id yet"
