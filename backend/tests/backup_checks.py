"""Validation helpers for deploy/enterprise/backup/prometheusrule.yaml."""
from pathlib import Path

import yaml

RULE_FILE = Path(__file__).resolve().parents[2] / "deploy/enterprise/backup/prometheusrule.yaml"
STALE_SECONDS = "93600"  # 26 h


def load_rule(path: Path = RULE_FILE) -> dict:
    return yaml.safe_load(path.read_text())


def alerts(rule: dict) -> dict:
    return {r["alert"]: r for g in rule["spec"]["groups"] for r in g["rules"] if "alert" in r}


def check_stale(name: str, alert: dict) -> None:
    expr = alert["expr"]
    if STALE_SECONDS not in expr:
        raise ValueError(f"{name}: stale expr lacks {STALE_SECONDS}")
    if "absent(" not in expr:
        raise ValueError(f"{name}: stale expr lacks absent(")


def check_stale_alerts(rule: dict) -> None:
    for name, a in alerts(rule).items():
        if name.endswith("Stale"):
            check_stale(name, a)
