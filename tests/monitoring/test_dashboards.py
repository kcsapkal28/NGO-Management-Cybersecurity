"""Walk every dashboard JSON, run each panel's query, fail if any errors out.

Doesn't validate that results are non-empty (a freshly-deployed dashboard often
has cold panels). Only that the queries are syntactically valid and the
referenced datasource exists.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import requests

DASH_DIR = Path(__file__).parents[2] / "monitoring" / "grafana" / "provisioning" / "dashboards"


def _iter_panels(dash: dict):
    for panel in dash.get("panels", []):
        if panel.get("type") == "row":
            for sub in panel.get("panels", []) or []:
                yield sub
            continue
        yield panel


def _collect_targets():
    out = []
    for path in DASH_DIR.rglob("*.json"):
        dash = json.loads(path.read_text())
        for panel in _iter_panels(dash):
            ds = (panel.get("datasource") or {})
            ds_type = ds.get("type") if isinstance(ds, dict) else None
            for tgt in panel.get("targets", []) or []:
                out.append((path.name, panel.get("title", "?"), ds_type, tgt))
    return out


_TARGETS = _collect_targets()


@pytest.mark.full
@pytest.mark.skipif(not _TARGETS, reason="no dashboards found")
@pytest.mark.parametrize(
    "case",
    _TARGETS,
    ids=[f"{p}::{t}" for p, t, _, _ in _TARGETS],
)
def test_panel_query_valid(case, prometheus_url, elasticsearch_url):
    dash, title, ds_type, target = case

    if ds_type == "prometheus":
        expr = target.get("expr")
        if not expr:
            pytest.skip("no expr")
        # Grafana resolves these macros at render time. Substitute concrete
        # values so the validator can post the expression to Prometheus.
        expr = (
            expr.replace("$__rate_interval", "5m")
                .replace("$__interval", "1m")
                .replace("$__range", "1h")
        )
        r = requests.get(
            f"{prometheus_url}/api/v1/query",
            params={"query": expr},
            timeout=10,
        )
        body = r.json()
        assert body.get("status") == "success", (
            f"{dash}::{title} prometheus error: {body.get('error') or body}"
        )
    elif ds_type == "elasticsearch":
        # Run the query_string portion as a count; we don't translate the
        # full Grafana ES query DSL, just verify the basic query parses.
        q = target.get("query") or "*"
        r = requests.post(
            f"{elasticsearch_url}/fluentd-*/_search",
            json={"size": 0, "query": {"query_string": {"query": q}}},
            timeout=10,
            headers={"Content-Type": "application/json"},
        )
        if r.status_code == 404:
            pytest.skip("no fluentd-* indices yet")
        assert r.ok, f"{dash}::{title} ES error: {r.status_code} {r.text[:200]}"
    elif ds_type == "jaeger":
        # No public 'validate query' endpoint — assert datasource reachable
        # and the service param resolves.
        pytest.skip("jaeger panels validated by test_traces.py")
    else:
        pytest.skip(f"datasource type {ds_type!r} not validated")
