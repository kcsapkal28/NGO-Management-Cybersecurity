"""Alertmanager + rule-loading checks (Phase 1.4).

These don't drive actual alert firing — that needs 5–10 minutes of clock and
real load — but they verify the wiring: rules parse, Prometheus has them
loaded, and Alertmanager is reachable from Prometheus's perspective.
"""
from __future__ import annotations

import pytest
import requests


@pytest.mark.smoke
def test_alertmanager_reachable(alertmanager_url):
    r = requests.get(f"{alertmanager_url}/api/v2/status", timeout=10)
    r.raise_for_status()
    body = r.json()
    assert body["versionInfo"]["version"], body


@pytest.mark.smoke
def test_prometheus_has_alertmanager_configured(prometheus_url):
    """Prometheus knows about its Alertmanager and considers it 'up'."""
    r = requests.get(f"{prometheus_url}/api/v1/alertmanagers", timeout=10)
    r.raise_for_status()
    body = r.json()
    active = body.get("data", {}).get("activeAlertmanagers", [])
    assert active, f"Prometheus has no active Alertmanagers: {body}"
    urls = [a.get("url", "") for a in active]
    assert any("alertmanager-service:9093" in u for u in urls), urls


@pytest.mark.smoke
def test_prometheus_rules_loaded(prometheus_url):
    """Required alert rules are present and not in error state."""
    expected = {
        "HighErrorRate", "HighLatencyP95", "WebAppDown",
        "PodCrashLooping", "PodNotReady",
        "ESClusterUnhealthy", "PostgresDown", "ESDiskPressure",
    }
    r = requests.get(f"{prometheus_url}/api/v1/rules", timeout=10)
    r.raise_for_status()
    groups = r.json()["data"]["groups"]
    found = {rule["name"] for g in groups for rule in g["rules"] if rule.get("type") == "alerting"}
    missing = expected - found
    assert not missing, f"missing alerts: {missing}\nhave: {sorted(found)}"

    # No rule should be permanently in error (bad expr, parse fail).
    bad = [
        f"{g['name']}::{r['name']}"
        for g in groups for r in g["rules"]
        if r.get("health") == "err"
    ]
    assert not bad, f"rules in error state: {bad}"


@pytest.mark.smoke
def test_no_critical_alerts_at_baseline(prometheus_url):
    """At rest, no critical alert should be firing.

    Warnings can fire transiently after deploy churn (PodNotReady during
    rollout, etc.), so we only assert on severity=critical.
    """
    r = requests.get(f"{prometheus_url}/api/v1/alerts", timeout=10)
    r.raise_for_status()
    firing = [
        a for a in r.json().get("data", {}).get("alerts", [])
        if a.get("state") == "firing" and a.get("labels", {}).get("severity") == "critical"
    ]
    assert not firing, f"critical alerts firing at baseline: {[a['labels'] for a in firing]}"
