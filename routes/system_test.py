"""Monitoring fault-injection toolkit.

These endpoints exist to drive every signal the dashboards depend on:
metrics histograms, structured logs at every level, OTel spans, DB activity,
errors, and resource pressure. They are the primary fixtures used by the
end-to-end tests under tests/monitoring/.

Every endpoint is admin-gated. The whole blueprint is gated additionally by
the SYSTEM_TEST_ENABLED env var — when unset the routes return 404, so this
module can ship to prod safely.

The 'heavy' endpoints (load, db, log-storm, memory-leak) acquire a process-
wide BoundedSemaphore so a misclick can't take a pod down.
"""
from __future__ import annotations

import os
import random
import threading
import time
import uuid
import logging
from typing import Any

import requests
from flask import jsonify, render_template, request
from sqlalchemy import text

from extensions import csrf
from models import db, Campaign, Donation
from utils import admin_required

try:
    from observability import get_tracer, record_donation
    _tracer = get_tracer()
except Exception:  # pragma: no cover - module always available today, guard for safety
    _tracer = None
    def record_donation(*_a, **_kw):  # type: ignore
        pass

logger = logging.getLogger(__name__)

# Cap concurrent heavy operations across the whole worker.
_HEAVY = threading.BoundedSemaphore(2)


def _enabled() -> bool:
    return os.environ.get("SYSTEM_TEST_ENABLED", "false").lower() == "true"


def _heavy(fn):
    """Acquire the heavy-op semaphore or fail fast with 429."""
    from functools import wraps

    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not _HEAVY.acquire(blocking=False):
            return jsonify({"error": "too many concurrent system-test ops"}), 429
        try:
            return fn(*args, **kwargs)
        finally:
            _HEAVY.release()
    return wrapped


def _disabled_response():
    # Mimic Flask's default 404 so the endpoint looks unmounted.
    return ("Not Found", 404)


def init_system_test_routes(app):

    # Global gate: if disabled, every system-test route returns 404 BEFORE
    # admin_required runs, so it doesn't even reveal that the routes exist.
    @app.before_request
    def _system_test_gate():
        if request.path.startswith("/system-test/") and not _enabled():
            return _disabled_response()

    # ---- Original simulators (kept for backwards compat with old tests) ----

    @app.route('/system-test/traffic')
    @admin_required
    def simulate_traffic():
        codes = [200, 200, 200, 201, 204, 404]
        code = random.choice(codes)
        logger.info("simulated traffic", extra={"sim_status": code})
        return f"Simulated traffic with status {code}", code

    @app.route('/system-test/error')
    @admin_required
    def simulate_error():
        try:
            logger.error("simulating critical system error")
            1 / 0
            return "", 500  # unreachable
        except ZeroDivisionError as e:
            logger.exception("caught simulated error: %s", e)
            return jsonify({"error": "Internal Server Error"}), 500

    @app.route('/system-test/warning')
    @admin_required
    def simulate_warning():
        logger.warning("simulated warning: high CPU usage detected (not really)")
        return "Warning logged!", 200

    @app.route('/system-test/slow')
    @admin_required
    def simulate_slow_request():
        delay = random.uniform(0.5, 3.0)
        logger.info("simulating slow request", extra={"delay_s": round(delay, 2)})
        time.sleep(delay)
        return f"Slow request finished after {delay:.2f}s", 200

    @app.route('/system-test/logs')
    @admin_required
    def test_logs():
        logger.debug("DEBUG log")
        logger.info("INFO log")
        logger.warning("WARNING log")
        logger.error("ERROR log")
        logger.critical("CRITICAL log")
        return "All log levels fired!", 200

    @app.route('/system-test/simulate')
    @admin_required
    def simulate_complex_load():
        iterations = random.randint(3, 8)
        results = []
        for i in range(iterations):
            choice = random.random()
            if choice < 0.6:
                logger.info("simulation step normal", extra={"step": i})
                results.append("Normal")
            elif choice < 0.8:
                logger.warning("simulation step bottleneck", extra={"step": i})
                results.append("Warning")
                time.sleep(random.uniform(0.1, 0.5))
            else:
                logger.error("simulation step partial failure", extra={"step": i})
                results.append("Error")
        return jsonify({"status": "Simulation complete", "steps": results, "total_iterations": iterations})

    # ---- New: load generator -------------------------------------------------

    @app.route('/system-test/load')
    @admin_required
    @_heavy
    def load_generator():
        """Spawn a background thread that hits a path repeatedly.
        Caps prevent the pod from DoSing itself.
        """
        rps = min(int(request.args.get("rps", 20)), 100)
        duration = min(int(request.args.get("duration", 30)), 120)
        path = request.args.get("path", "/")
        target = f"http://127.0.0.1:5001{path}"

        def _drive():
            interval = 1.0 / max(rps, 1)
            end = time.time() + duration
            sent = 0
            while time.time() < end:
                try:
                    requests.get(target, timeout=2)
                except requests.RequestException:
                    pass
                sent += 1
                time.sleep(interval)
            logger.info("load generator finished", extra={"sent": sent, "rps": rps, "duration_s": duration})

        threading.Thread(target=_drive, name="systest-load", daemon=True).start()
        return jsonify({"status": "started", "rps": rps, "duration_s": duration, "target": path}), 202

    # ---- New: DB exercises ---------------------------------------------------

    @app.route('/system-test/db')
    @admin_required
    @_heavy
    def db_exercise():
        """Run N small queries against real tables. Drives SQLAlchemy spans."""
        n = min(int(request.args.get("n", 50)), 500)
        results: list[dict[str, Any]] = []
        for _ in range(n):
            campaign_count = db.session.query(Campaign).count()
            donation_count = db.session.query(Donation).count()
            results.append({"campaigns": campaign_count, "donations": donation_count})
        logger.info("db exercise complete", extra={"queries": n * 2})
        return jsonify({"queries_run": n * 2, "last": results[-1] if results else None})

    @app.route('/system-test/db-slow')
    @admin_required
    @_heavy
    def db_slow():
        """Force a 2-second DB call. Postgres uses pg_sleep; SQLite falls back to Python sleep."""
        seconds = min(float(request.args.get("seconds", 2.0)), 10.0)
        dialect = db.engine.dialect.name
        logger.warning("db-slow forcing slow query", extra={"dialect": dialect, "seconds": seconds})
        if dialect == "postgresql":
            db.session.execute(text("SELECT pg_sleep(:s)"), {"s": seconds})
        else:
            time.sleep(seconds)
            db.session.execute(text("SELECT 1"))
        return jsonify({"slept_s": seconds, "dialect": dialect})

    # ---- New: tracing --------------------------------------------------------

    @app.route('/system-test/trace-deep')
    @admin_required
    def trace_deep():
        """Emit nested manual spans to exercise Jaeger drilldown."""
        depth = min(int(request.args.get("depth", 5)), 15)
        if _tracer is None:
            return jsonify({"error": "OTel tracer not configured"}), 503

        def recurse(n: int):
            if n == 0:
                return
            with _tracer.start_as_current_span(f"systest.layer.{depth - n + 1}") as span:
                span.set_attribute("layer", depth - n + 1)
                span.set_attribute("remaining", n - 1)
                time.sleep(0.01)
                recurse(n - 1)

        recurse(depth)
        return jsonify({"status": "ok", "depth": depth})

    # ---- New: log storm ------------------------------------------------------

    @app.route('/system-test/log-storm')
    @admin_required
    @_heavy
    def log_storm():
        """Emit N JSON logs at the chosen level. Stress-tests Fluentd buffer + ES indexing."""
        n = min(int(request.args.get("n", 200)), 5000)
        level = request.args.get("level", "info").lower()
        log_fn = {
            "debug": logger.debug,
            "info": logger.info,
            "warning": logger.warning,
            "error": logger.error,
            "critical": logger.critical,
        }.get(level, logger.info)

        burst_id = uuid.uuid4().hex[:8]
        for i in range(n):
            log_fn(
                "log storm event",
                extra={
                    "burst_id": burst_id,
                    "seq": i,
                    "level_requested": level,
                    "user_id": session_user_id_or_none(),
                },
            )
        return jsonify({"emitted": n, "level": level, "burst_id": burst_id})

    # ---- New: memory leak ----------------------------------------------------

    # Keep allocations on the app object so multiple calls don't compound silently.
    app._systest_ballast: list[bytes] = []

    @app.route('/system-test/memory-leak')
    @admin_required
    @_heavy
    def memory_leak():
        """Allocate `mb` MB and hold for `hold` seconds, then release.
        Drives the process_resident_memory_bytes panel and OOMKill alert.
        """
        mb = min(int(request.args.get("mb", 50)), 200)
        hold = min(int(request.args.get("hold", 10)), 60)

        chunk = b"x" * (mb * 1024 * 1024)
        app._systest_ballast.append(chunk)
        logger.warning("memory ballast allocated", extra={"mb": mb, "hold_s": hold})

        def _release():
            time.sleep(hold)
            try:
                app._systest_ballast.remove(chunk)
            except ValueError:
                pass
            logger.info("memory ballast released", extra={"mb": mb})

        threading.Thread(target=_release, name="systest-mem-release", daemon=True).start()
        return jsonify({"allocated_mb": mb, "hold_s": hold})

    # ---- New: panic ----------------------------------------------------------

    @app.route('/system-test/panic')
    @admin_required
    def panic():
        """Raise an uncaught exception. Validates 500 path + exception logging + span error."""
        logger.error("about to panic on request")
        raise RuntimeError(f"systest panic at {time.time()}")

    # ---- New: donation burst -------------------------------------------------

    @app.route('/system-test/donation-burst', methods=['GET', 'POST'])
    @csrf.exempt
    @admin_required
    @_heavy
    def donation_burst():
        """Insert N synthetic donations against random active campaigns.
        Exercises the full Donation write path: metrics, traces, logs, DB.
        """
        n = min(int(request.args.get("n", 20)), 200)
        campaigns = Campaign.query.filter_by(is_active=True).limit(50).all()
        if not campaigns:
            return jsonify({"error": "no active campaigns to donate against"}), 412

        inserted = 0
        for i in range(n):
            c = random.choice(campaigns)
            amount = round(random.uniform(5, 200), 2)
            donation = Donation(
                user_id=None,
                campaign_id=c.id,
                full_name=f"Sys Test #{i}",
                email=f"systest+{uuid.uuid4().hex[:8]}@example.com",
                amount=amount,
                donation_type="One-time",
                payment_method="systest",
                transaction_id=f"systest-{uuid.uuid4().hex}",
                status="Completed",
            )
            db.session.add(donation)
            c.raised_amount += amount
            inserted += 1
            record_donation(c.id, "completed", amount)

        db.session.commit()
        logger.info("donation burst committed", extra={"inserted": inserted, "campaigns": len(campaigns)})
        return jsonify({"inserted": inserted, "campaigns_used": len(campaigns)})

    # ---- New: deep healthcheck ----------------------------------------------

    @app.route('/system-test/healthcheck-deep')
    @admin_required
    def healthcheck_deep():
        """Probe each backend from inside the pod. Distinguishes ingress from in-cluster issues."""
        targets = {
            "elasticsearch": "http://elasticsearch-service:9200/_cluster/health",
            "prometheus":    "http://prometheus-service:9090/-/ready",
            "jaeger":        "http://jaeger-service:16686/",
            "self_metrics":  "http://127.0.0.1:5001/metrics",
        }
        report: dict[str, dict[str, Any]] = {}
        for name, url in targets.items():
            t0 = time.time()
            try:
                r = requests.get(url, timeout=3)
                report[name] = {"status": r.status_code, "ms": int((time.time() - t0) * 1000), "ok": r.ok}
            except requests.RequestException as e:
                report[name] = {"status": None, "ms": int((time.time() - t0) * 1000), "ok": False, "error": str(e)[:200]}
        all_ok = all(v.get("ok") for v in report.values())
        return jsonify({"ok": all_ok, "checks": report}), (200 if all_ok else 503)

    # ---- Control panel UI ----------------------------------------------------

    @app.route('/system-test/')
    @admin_required
    def control_panel():
        return render_template('system_test.html')


def session_user_id_or_none():
    """Best-effort session lookup that won't crash if Flask context isn't ready."""
    try:
        from flask import session as _session
        return _session.get("user_id")
    except Exception:
        return None
