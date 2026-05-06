"""Shared fixtures for monitoring tests.

Each backend (Prometheus, Elasticsearch, Jaeger, Grafana, the web app) is
reached over HTTP. By default we start ``kubectl port-forward`` subprocesses
for the duration of the session. Override any URL via env var to skip the
port-forward (useful in CI where services may already be reachable).
"""
from __future__ import annotations

import logging
import os
import socket
import subprocess
import time
from contextlib import closing
from dataclasses import dataclass
from typing import Iterator

import pytest
import requests

log = logging.getLogger(__name__)

NAMESPACE = os.environ.get("NGO_NAMESPACE", "default")


@dataclass(frozen=True)
class Service:
    name: str          # k8s service name
    remote_port: int   # service port
    env_var: str       # override URL via this env var
    health_path: str   # path that returns 2xx when healthy


SERVICES = {
    "prometheus":    Service("prometheus-service",    9090,  "PROMETHEUS_URL",    "/-/ready"),
    "elasticsearch": Service("elasticsearch-service", 9200,  "ELASTICSEARCH_URL", "/_cluster/health"),
    "jaeger":        Service("jaeger-service",        16686, "JAEGER_URL",        "/"),
    "grafana":       Service("grafana-service",       3000,  "GRAFANA_URL",      "/api/health"),
    "web":           Service("web-service",           5001,  "WEB_URL",           "/"),
    "alertmanager":  Service("alertmanager-service",  9093,  "ALERTMANAGER_URL",  "/-/ready"),
}


def _free_port() -> int:
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_http(url: str, timeout: float = 30.0) -> None:
    deadline = time.time() + timeout
    last_err: Exception | None = None
    while time.time() < deadline:
        try:
            r = requests.get(url, timeout=2)
            if r.status_code < 500:
                return
        except requests.RequestException as e:
            last_err = e
        time.sleep(0.5)
    raise RuntimeError(f"timed out waiting for {url}: {last_err}")


class PortForward:
    def __init__(self, svc: Service, namespace: str):
        self.svc = svc
        self.namespace = namespace
        self.local_port = _free_port()
        self.proc: subprocess.Popen | None = None

    def start(self) -> str:
        cmd = [
            "kubectl", "-n", self.namespace, "port-forward",
            f"svc/{self.svc.name}",
            f"{self.local_port}:{self.svc.remote_port}",
        ]
        log.info("starting port-forward: %s", " ".join(cmd))
        self.proc = subprocess.Popen(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE
        )
        url = f"http://127.0.0.1:{self.local_port}"
        _wait_http(url + self.svc.health_path, timeout=20)
        return url

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()


def _resolve(svc_key: str) -> Iterator[str]:
    svc = SERVICES[svc_key]
    override = os.environ.get(svc.env_var)
    if override:
        _wait_http(override.rstrip("/") + svc.health_path, timeout=10)
        yield override.rstrip("/")
        return
    pf = PortForward(svc, NAMESPACE)
    try:
        yield pf.start()
    finally:
        pf.stop()


@pytest.fixture(scope="session")
def prometheus_url() -> Iterator[str]:
    yield from _resolve("prometheus")


@pytest.fixture(scope="session")
def elasticsearch_url() -> Iterator[str]:
    yield from _resolve("elasticsearch")


@pytest.fixture(scope="session")
def jaeger_url() -> Iterator[str]:
    yield from _resolve("jaeger")


@pytest.fixture(scope="session")
def grafana_url() -> Iterator[str]:
    yield from _resolve("grafana")


@pytest.fixture(scope="session")
def web_url() -> Iterator[str]:
    yield from _resolve("web")


@pytest.fixture(scope="session")
def alertmanager_url() -> Iterator[str]:
    yield from _resolve("alertmanager")


@pytest.fixture(scope="session")
def run_id() -> str:
    """Stamp injected into generated test data so it's identifiable & reapable."""
    return f"montest-{int(time.time())}"


@pytest.fixture(scope="session", autouse=True)
def _warmup_traffic(web_url, prometheus_url):
    """Ensure the request counters exist before any test asserts on them.

    A freshly-rolled web pod has zero `flask_http_request_total` samples until
    something hits it. We drive a handful of requests at session start so
    histogram buckets, counters, and labels exist by the time assertions run.
    Then we wait for Prometheus to scrape (15s default) so metrics are visible.
    """
    log.info("warmup: sending baseline traffic to %s", web_url)
    for _ in range(5):
        try:
            requests.get(f"{web_url}/", timeout=3)
        except requests.RequestException:
            pass

    # Poll until samples appear, up to ~30s (well past the 15s scrape interval).
    deadline = time.time() + 35
    while time.time() < deadline:
        try:
            r = requests.get(
                f"{prometheus_url}/api/v1/query",
                params={"query": "flask_http_request_total"},
                timeout=3,
            )
            if r.ok and r.json().get("data", {}).get("result"):
                log.info("warmup: metrics visible in Prometheus")
                break
        except requests.RequestException:
            pass
        time.sleep(2)
    yield


@pytest.fixture
def http() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": "ngo-monitoring-tests/1.0"})
    return s
