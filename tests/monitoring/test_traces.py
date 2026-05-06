"""Verify Jaeger has spans for the app and for each expected operation."""
from __future__ import annotations

from pathlib import Path

import pytest
import requests
import yaml
from tenacity import Retrying, stop_after_delay, wait_fixed

from _helpers import jaeger_operations, jaeger_services, jaeger_traces

FIXTURE = Path(__file__).parent / "fixtures" / "expected_traces.yaml"
_services = yaml.safe_load(FIXTURE.read_text())["services"]


@pytest.mark.smoke
def test_jaeger_reachable(jaeger_url):
    r = requests.get(f"{jaeger_url}/api/services", timeout=10)
    r.raise_for_status()


@pytest.mark.smoke
@pytest.mark.parametrize("svc", _services, ids=[s["name"] for s in _services])
def test_service_registered(svc, jaeger_url, web_url):
    # Generate traffic so the service has spans to register.
    for _ in range(3):
        try:
            requests.get(f"{web_url}/", timeout=5)
        except requests.RequestException:
            pass

    for attempt in Retrying(stop=stop_after_delay(30), wait=wait_fixed(2), reraise=True):
        with attempt:
            services = jaeger_services(jaeger_url)
            assert svc["name"] in services, (
                f"service {svc['name']!r} not in Jaeger; got {services}"
            )


@pytest.mark.full
@pytest.mark.parametrize("svc", _services, ids=[s["name"] for s in _services])
def test_expected_operations(svc, jaeger_url, web_url):
    # Drive each path so Jaeger sees an operation for it. FlaskInstrumentor
    # names spans "<METHOD> <route>" (e.g. "GET /system-test/db"), so we GET
    # the path and assert the prefixed name appears.
    for path in svc["operations"]:
        try:
            requests.get(f"{web_url}{path}", timeout=5)
        except requests.RequestException:
            pass

    expected = {f"GET {p}" for p in svc["operations"]}

    for attempt in Retrying(stop=stop_after_delay(30), wait=wait_fixed(2), reraise=True):
        with attempt:
            ops = set(jaeger_operations(jaeger_url, svc["name"]))
            missing = sorted(expected - ops)
            assert not missing, (
                f"missing operations for {svc['name']}: {missing}\n"
                f"have: {sorted(ops)}"
            )


@pytest.mark.full
def test_traces_have_spans(jaeger_url, web_url):
    requests.get(f"{web_url}/", timeout=5)
    for attempt in Retrying(stop=stop_after_delay(30), wait=wait_fixed(2), reraise=True):
        with attempt:
            traces = jaeger_traces(jaeger_url, "ngo-management-app", lookback_s=300)
            assert traces, "no traces found in last 5 min"
            assert all(t.get("spans") for t in traces), "trace returned with no spans"
