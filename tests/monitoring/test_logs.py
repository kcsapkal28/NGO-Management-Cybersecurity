"""Fire each system-test endpoint and confirm the log shows up in Elasticsearch."""
from __future__ import annotations

import time
from pathlib import Path

import pytest
import requests
import yaml
from tenacity import Retrying, stop_after_delay, wait_fixed

from _helpers import es_count

FIXTURE = Path(__file__).parent / "fixtures" / "expected_logs.yaml"
_cases = yaml.safe_load(FIXTURE.read_text())["cases"]


@pytest.fixture(scope="session")
def admin_session(web_url):
    """Log in as admin so we can hit /system-test/* endpoints.

    The login form is CSRF-protected (Flask-WTF), so we must:
      1. GET /auth to mint a session and a csrf_token hidden input
      2. POST /login with csrf_token + credentials

    Reads ADMIN_EMAIL/ADMIN_PASSWORD from env. Skip messages distinguish
    between (a) env unset, (b) login form unreachable, (c) CSRF token not
    found, (d) credentials rejected.
    """
    import os
    import re
    import logging

    log = logging.getLogger(__name__)

    email = os.environ.get("ADMIN_EMAIL")
    password = os.environ.get("ADMIN_PASSWORD")
    if not (email and password):
        pytest.skip("[env] ADMIN_EMAIL / ADMIN_PASSWORD not set")

    log.info("admin login: email=%r len(password)=%d", email, len(password))
    s = requests.Session()

    # 1. Fetch the form to get a session cookie + CSRF token
    r = s.get(f"{web_url}/auth", timeout=10)
    if r.status_code != 200:
        pytest.skip(f"[form] GET /auth returned {r.status_code} — login page not reachable")

    m = re.search(
        r'name=["\']csrf_token["\']\s+[^>]*value=["\']([^"\']+)["\']',
        r.text,
    ) or re.search(
        r'value=["\']([^"\']+)["\']\s+[^>]*name=["\']csrf_token["\']',
        r.text,
    )
    if not m:
        pytest.skip("[csrf] csrf_token hidden input not found on /auth")
    csrf_token = m.group(1)

    # 2. POST credentials with token
    r = s.post(
        f"{web_url}/login",
        data={"email": email, "password": password, "csrf_token": csrf_token},
        headers={"Referer": f"{web_url}/auth"},
        allow_redirects=False,
        timeout=10,
    )
    if r.status_code not in (302, 303):
        pytest.skip(f"[post] /login returned {r.status_code} — CSRF/limiter rejected")

    # The route redirects to /admin/dashboard on admin success, /donor/dashboard otherwise.
    location = r.headers.get("Location", "")
    if "admin" not in location:
        pytest.skip(f"[creds] login succeeded but redirect={location!r} — not an admin user")

    log.info("admin login OK → %s", location)
    return s


@pytest.mark.smoke
@pytest.mark.parametrize("case", _cases, ids=[c["name"] for c in _cases])
def test_log_reaches_elasticsearch(case, admin_session, web_url, elasticsearch_url):
    # Fire the trigger N times so a single dropped log doesn't flake the test.
    for _ in range(3):
        r = admin_session.get(f"{web_url}{case['trigger']}", timeout=10)
        assert r.status_code in (200, 500), f"unexpected {r.status_code} from {case['trigger']}"

    # Fluentd flushes every 1s; ES refresh_interval default is 1s; allow ~10s.
    for attempt in Retrying(stop=stop_after_delay(20), wait=wait_fixed(1), reraise=True):
        with attempt:
            hits = es_count(elasticsearch_url, case["query"])
            assert hits >= case["min_hits"], (
                f"{case['query']}: got {hits} hits, expected >= {case['min_hits']}"
            )


@pytest.mark.smoke
def test_elasticsearch_cluster_healthy(elasticsearch_url):
    r = requests.get(f"{elasticsearch_url}/_cluster/health", timeout=10)
    r.raise_for_status()
    status = r.json()["status"]
    # Single-node ES legitimately reports 'yellow' (replicas unassigned). Reject only red.
    assert status in ("green", "yellow"), f"ES cluster status is {status}"


@pytest.mark.smoke
def test_fluentd_index_exists(elasticsearch_url):
    today = time.strftime("%Y.%m.%d")
    r = requests.get(f"{elasticsearch_url}/_cat/indices/fluentd-*?format=json", timeout=10)
    r.raise_for_status()
    indices = r.json()
    assert indices, "no fluentd-* indices exist — log pipeline never wrote anything"
    # Don't require today's index — could be early in the day with no traffic yet.
    names = [i["index"] for i in indices]
    assert any(n.startswith("fluentd-") for n in names), names
