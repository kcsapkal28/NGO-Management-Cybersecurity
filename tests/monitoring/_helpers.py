"""Small helpers shared between test files."""
from __future__ import annotations

import time
from typing import Any, Callable

import requests
from tenacity import Retrying, stop_after_delay, wait_fixed


def prom_query(prom_url: str, expr: str) -> list[dict]:
    """Run an instant query against Prometheus, return the result list."""
    r = requests.get(
        f"{prom_url}/api/v1/query",
        params={"query": expr},
        timeout=10,
    )
    r.raise_for_status()
    body = r.json()
    if body.get("status") != "success":
        raise AssertionError(f"prometheus query failed: {body}")
    return body["data"]["result"]


def es_count(es_url: str, query_string: str, index: str = "fluentd-*", lookback: str = "now-15m") -> int:
    """Count docs matching a query_string in a given index pattern."""
    body = {
        "size": 0,
        "query": {
            "bool": {
                "must": [
                    {"query_string": {"query": query_string}},
                    {"range": {"@timestamp": {"gte": lookback}}},
                ]
            }
        },
    }
    r = requests.post(
        f"{es_url}/{index}/_search",
        json=body,
        timeout=10,
        headers={"Content-Type": "application/json"},
    )
    if r.status_code == 404:
        # No index yet — treat as zero hits, not an error.
        return 0
    r.raise_for_status()
    return r.json()["hits"]["total"]["value"]


def jaeger_services(jaeger_url: str) -> list[str]:
    r = requests.get(f"{jaeger_url}/api/services", timeout=10)
    r.raise_for_status()
    return r.json().get("data") or []


def jaeger_operations(jaeger_url: str, service: str) -> list[str]:
    r = requests.get(
        f"{jaeger_url}/api/operations",
        params={"service": service},
        timeout=10,
    )
    r.raise_for_status()
    data = r.json().get("data") or []
    # Some Jaeger versions return [{"name": "...", ...}], older ones return ["..."]
    if data and isinstance(data[0], dict):
        return [op["name"] for op in data]
    return data


def jaeger_traces(jaeger_url: str, service: str, lookback_s: int = 300, limit: int = 20) -> list[dict]:
    end = int(time.time() * 1_000_000)
    start = end - lookback_s * 1_000_000
    r = requests.get(
        f"{jaeger_url}/api/traces",
        params={
            "service": service,
            "start": start,
            "end": end,
            "limit": limit,
        },
        timeout=10,
    )
    r.raise_for_status()
    return r.json().get("data") or []


def retry(timeout: float = 30.0, interval: float = 1.0) -> Callable:
    """Decorator: retry the wrapped callable until it returns truthy or times out."""
    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        def wrapped(*args, **kwargs):
            for attempt in Retrying(
                stop=stop_after_delay(timeout),
                wait=wait_fixed(interval),
                reraise=True,
            ):
                with attempt:
                    result = fn(*args, **kwargs)
                    if not result:
                        raise AssertionError(f"{fn.__name__} returned falsy")
                    return result
        return wrapped
    return decorator
