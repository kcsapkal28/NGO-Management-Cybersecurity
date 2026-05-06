"""Centralized observability for the NGO management app.

Owns:
  - Structured JSON logging enriched with request_id/user_id/route/trace_id
  - OTel tracer provider with K8s-aware Resource and Flask/SQLAlchemy/Requests/Jinja2/Logging auto-instrumentation
  - Prometheus default metrics (via prometheus-flask-exporter) plus custom business metrics
  - before/after_request hooks that attach a request id to every response

Public surface used by route modules:
  setup(app, db_engine)               — wire everything up (call once)
  get_tracer()                        — for manual spans on business flows
  record_donation(campaign_id, ...)
  record_auth_attempt(result)
  record_rate_limit(endpoint)

OBSERVABILITY_V2 env var (default "true") gates the v2 enhancements:
  - log enrichment + otelTraceID/otelSpanID injection
  - Requests/Jinja2/Logging auto-instrumentation
  - business metric helpers
  - rate-limit error handler
Set to "false" for one-flag rollback to legacy Flask+SQLAlchemy-only behavior.
"""
from __future__ import annotations

import logging
import os
import sys
import uuid

from flask import g, has_request_context, request, session
from prometheus_client import Counter, Gauge, Histogram
from prometheus_flask_exporter import PrometheusMetrics
from pythonjsonlogger import jsonlogger

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.flask import FlaskInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

try:
    from opentelemetry.instrumentation.jinja2 import Jinja2Instrumentor
    from opentelemetry.instrumentation.logging import LoggingInstrumentor
    from opentelemetry.instrumentation.requests import RequestsInstrumentor
    _V2_AVAILABLE = True
except ImportError:
    _V2_AVAILABLE = False


SERVICE_NAME = "ngo-management-app"
SERVICE_VERSION = "1.1.0"
NAMESPACE = "ngo"


# ---------- Custom business metrics --------------------------------------

ngo_donations_total = Counter(
    "ngo_donations_total",
    "Donations recorded, labelled by campaign id and final status.",
    ["campaign", "status"],
)
ngo_donation_amount_dollars = Histogram(
    "ngo_donation_amount_dollars",
    "Distribution of donation amounts in USD.",
    buckets=(1, 5, 10, 25, 50, 100, 250, 500, 1000, 5000),
)
ngo_auth_attempts_total = Counter(
    "ngo_auth_attempts_total",
    "Authentication attempts.",
    ["result"],  # success | invalid | missing_fields | locked
)
ngo_db_pool_in_use = Gauge(
    "ngo_db_pool_in_use",
    "SQLAlchemy connections currently checked out.",
)
ngo_rate_limit_hits_total = Counter(
    "ngo_rate_limit_hits_total",
    "Requests rejected by Flask-Limiter.",
    ["endpoint"],
)

# Pre-initialise known label combos at zero so dashboards & alerts can sum
# rates from the first scrape rather than waiting for the first event.
# A labeled counter with no .labels() call exposes no series at all.
for _r in ("success", "invalid", "missing_fields", "locked"):
    ngo_auth_attempts_total.labels(result=_r)
for _s in ("completed", "rejected", "failed"):
    ngo_donations_total.labels(campaign="none", status=_s)


def record_donation(campaign_id, status: str, amount_dollars: float | None = None) -> None:
    label = str(campaign_id) if campaign_id else "none"
    ngo_donations_total.labels(campaign=label, status=status).inc()
    if status == "completed" and amount_dollars is not None:
        try:
            ngo_donation_amount_dollars.observe(float(amount_dollars))
        except (TypeError, ValueError):
            pass


def record_auth_attempt(result: str) -> None:
    ngo_auth_attempts_total.labels(result=result).inc()


def record_rate_limit(endpoint: str | None) -> None:
    ngo_rate_limit_hits_total.labels(endpoint=endpoint or "unknown").inc()


# ---------- Resource (k8s.* from downward API) ---------------------------

def _build_resource() -> Resource:
    attrs: dict[str, str] = {
        "service.name": SERVICE_NAME,
        "service.version": SERVICE_VERSION,
        "service.namespace": NAMESPACE,
        "deployment.environment": os.environ.get("APP_ENV", "dev"),
    }
    pod = os.environ.get("K8S_POD_NAME")
    ns = os.environ.get("K8S_NAMESPACE")
    node = os.environ.get("K8S_NODE_NAME")
    if pod:
        attrs["k8s.pod.name"] = pod
    if ns:
        attrs["k8s.namespace.name"] = ns
    if node:
        attrs["k8s.node.name"] = node
    return Resource.create(attrs)


# ---------- Logging filter (request scope into every record) -------------

class _RequestContextFilter(logging.Filter):
    _DEFAULTS = {
        "request_id": "-",
        "user_id": "-",
        "route": "-",
        "method": "-",
        "remote_addr": "-",
    }

    def filter(self, record: logging.LogRecord) -> bool:
        # Always set sane defaults so the JSON formatter can interpolate.
        for k, v in self._DEFAULTS.items():
            if not hasattr(record, k):
                setattr(record, k, v)
        try:
            if has_request_context():
                record.request_id = getattr(g, "request_id", "-") or "-"
                record.user_id = session.get("user_id", "-")
                record.route = (request.url_rule.rule if request.url_rule else "-")
                record.remote_addr = (
                    request.headers.get("X-Forwarded-For", request.remote_addr) or "-"
                )
                record.method = request.method
        except Exception:
            # Never block a log line because of context lookup
            pass
        return True


def _setup_logging() -> None:
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for h in list(root.handlers):
        root.removeHandler(h)

    handler = logging.StreamHandler(sys.stdout)
    fmt = (
        "%(asctime)s %(levelname)s %(name)s %(message)s "
        "%(request_id)s %(user_id)s %(route)s %(method)s %(remote_addr)s "
        "%(otelTraceID)s %(otelSpanID)s %(otelServiceName)s"
    )
    handler.setFormatter(jsonlogger.JsonFormatter(fmt))
    handler.addFilter(_RequestContextFilter())
    root.addHandler(handler)
    # Re-enable werkzeug — we lose access logs at WARNING.
    logging.getLogger("werkzeug").setLevel(logging.INFO)


# ---------- Tracing ------------------------------------------------------

def _setup_tracing() -> None:
    trace.set_tracer_provider(TracerProvider(resource=_build_resource()))
    jaeger_host = os.environ.get("JAEGER_HOST", "jaeger")
    exporter = OTLPSpanExporter(endpoint=f"http://{jaeger_host}:4317", insecure=True)
    trace.get_tracer_provider().add_span_processor(BatchSpanProcessor(exporter))


# ---------- Request hooks ------------------------------------------------

_access_log = logging.getLogger("ngo.access")


def _setup_request_hooks(app) -> None:
    @app.before_request
    def _start_request_scope():
        g.request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]

    @app.after_request
    def _stamp_response(resp):
        rid = getattr(g, "request_id", None)
        if rid:
            resp.headers["X-Request-ID"] = rid
        # Emit a structured access record correlated with the current trace.
        # gunicorn's own access log bypasses Python logging, so without this
        # we get no per-request log line through the JSON formatter.
        try:
            _access_log.info(
                "request",
                extra={"status_code": resp.status_code, "content_length": resp.calculate_content_length()},
            )
        except Exception:
            pass
        return resp


# ---------- Public entrypoint --------------------------------------------

def setup(app, db_engine=None) -> PrometheusMetrics:
    """Wire up logging, tracing, and metrics. Idempotent within a process.

    Call AFTER db.init_app(app) and BEFORE register_all_routes(app) so the
    request_id hook runs before any route-level before_request handlers.
    """
    v2 = os.environ.get("OBSERVABILITY_V2", "true").lower() == "true"

    _setup_logging()
    _setup_tracing()

    FlaskInstrumentor().instrument_app(app)
    if db_engine is not None:
        SQLAlchemyInstrumentor().instrument(engine=db_engine)
        # Live gauge that reflects the current pool checkout count on every scrape.
        ngo_db_pool_in_use.set_function(lambda: db_engine.pool.checkedout())

    metrics = PrometheusMetrics(app)
    metrics.info("app_info", "Application info", version=SERVICE_VERSION)

    if v2 and _V2_AVAILABLE:
        # set_logging_format=True is required: with False, the LogRecordFactory
        # is a no-op and otelTraceID/otelSpanID never get attached. The flag
        # *also* calls logging.basicConfig() but that's a no-op for us because
        # the root logger already has the handler we installed in _setup_logging.
        LoggingInstrumentor().instrument(set_logging_format=True)
        RequestsInstrumentor().instrument()
        Jinja2Instrumentor().instrument()

    if v2:
        _setup_request_hooks(app)

        @app.errorhandler(429)
        def _on_rate_limit(_err):
            record_rate_limit(request.endpoint)
            return ("Too Many Requests", 429)

    return metrics


def get_tracer():
    return trace.get_tracer("ngo.app")
