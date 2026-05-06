"""Assert that every metric the dashboards depend on is actually scraped."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from _helpers import prom_query

FIXTURE = Path(__file__).parent / "fixtures" / "expected_metrics.yaml"
_data = yaml.safe_load(FIXTURE.read_text())


@pytest.mark.smoke
@pytest.mark.parametrize(
    "case",
    _data["required"],
    ids=[c["expr"] for c in _data["required"]],
)
def test_required_metric_present(prometheus_url, case):
    result = prom_query(prometheus_url, case["expr"])
    assert result, (
        f"no samples for {case['expr']!r} — {case['why']}\n"
        f"check that the target is up and the metric is registered"
    )


if _data.get("phase_1_pending"):
    @pytest.mark.full
    @pytest.mark.parametrize(
        "case",
        _data["phase_1_pending"],
        ids=[c["expr"] for c in _data["phase_1_pending"]],
    )
    def test_phase_1_metric_present(prometheus_url, case):
        """xfail until the relevant phase lands."""
        result = prom_query(prometheus_url, case["expr"])
        if not result:
            pytest.xfail(f"metric not deployed yet: {case['expr']}")
        assert result
