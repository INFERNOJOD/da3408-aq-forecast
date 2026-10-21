"""Checks on the monitoring config: Prometheus, alert rules, Grafana, compose.

These read the files only. Running them against the live stack is in
docs/PROGRESS.md (Stage 14), with promtool and the Prometheus API.
"""

import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
MON = ROOT / "monitoring"
DASHBOARDS = sorted((MON / "grafana" / "dashboards").glob("*.json"))


def load(path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def lld_metrics():
    """aq_* metric names listed in docs/LLD.md section 5."""
    text = (ROOT / "docs" / "LLD.md").read_text(encoding="utf-8")
    section = text.split("## 5. Prometheus metrics")[1].split("Alert rules")[0]
    return set(re.findall(r"`(aq_[a-z_]+)`", section)) - {"aq_pipeline"}


def dashboard_exprs():
    exprs = []
    for path in DASHBOARDS:
        for panel in json.loads(path.read_text(encoding="utf-8"))["panels"]:
            exprs += [t["expr"] for t in panel.get("targets", [])]
    return exprs


def test_prometheus_scrapes_every_component_every_15s():
    cfg = load(MON / "prometheus.yml")
    assert cfg["global"]["scrape_interval"] == "15s"
    targets = {
        t for job in cfg["scrape_configs"] for sc in job["static_configs"]
        for t in sc["targets"]
    }  # fmt: skip
    for t in ["backend:8000", "model-server:8001", "frontend:8502",
              "pushgateway:9091", "node-exporter:9100", "mlflow:5000"]:  # fmt: skip
        assert t in targets
    push = next(j for j in cfg["scrape_configs"] if j["job_name"] == "pushgateway")
    assert push["honor_labels"] is True  # keeps the pushed stage labels


def test_alert_rules_match_lld():
    rules = {
        r["alert"]: r for g in load(MON / "alerts.yml")["groups"] for r in g["rules"]
    }
    for name in ["PM25DriftHigh", "ForecastErrorHigh", "BackendErrorRateHigh",
                 "TargetDown", "PipelineStageFailed"]:  # fmt: skip
        assert name in rules
    assert rules["PM25DriftHigh"]["expr"] == "aq_drift_detected == 1"
    assert rules["PM25DriftHigh"]["labels"]["action"] == "retrain"
    # Only the drift alert may start a retrain.
    assert [n for n, r in rules.items() if r["labels"].get("action")] == [
        "PM25DriftHigh"
    ]


def test_dashboards_refresh_every_15s_and_use_provisioned_source():
    assert len(DASHBOARDS) == 2
    uids = set()
    for path in DASHBOARDS:
        dash = json.loads(path.read_text(encoding="utf-8"))
        assert dash["refresh"] == "15s"
        uids.add(dash["uid"])
        for panel in dash["panels"]:
            if panel["type"] != "row":
                assert panel["datasource"]["uid"] == "prometheus"
                assert panel["targets"]
    assert len(uids) == 2
    ds = load(MON / "grafana" / "provisioning" / "datasources" / "prometheus.yml")
    assert ds["datasources"][0]["uid"] == "prometheus"


def test_every_lld_metric_is_on_a_dashboard():
    exprs = " ".join(dashboard_exprs())
    missing = [m for m in sorted(lld_metrics()) if m not in exprs]
    assert not missing


def test_compose_limits_memory_and_retention():
    compose = load(ROOT / "docker-compose.yml")
    for name, svc in compose["services"].items():
        assert "mem_limit" in svc, name
    prom = compose["services"]["prometheus"]["command"]
    assert "--storage.tsdb.retention.time=2d" in prom
    # Cold start without manual restarts: wait for health, not only for start.
    deps = compose["services"]["backend"]["depends_on"]
    assert deps["mlflow"]["condition"] == "service_healthy"
    assert "healthcheck" in compose["services"]["mlflow"]
