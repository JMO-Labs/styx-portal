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


BACKUP_DIR = RULE_FILE.parent
FORBIDDEN_KINDS = {"ObjectStore", "ScheduledBackup", "Cluster"}  # owned by the CNPG overlay (#24)


def check_backup_dir(path: Path = BACKUP_DIR) -> None:
    for f in sorted(path.glob("*.y*ml")):
        for doc in yaml.safe_load_all(f.read_text()):
            if not isinstance(doc, dict):
                continue
            kind = doc.get("kind")
            if kind in FORBIDDEN_KINDS:
                raise ValueError(f"{f.name}: {kind} belongs in the CNPG overlay, not backup/")
            if kind == "Secret" and "stringData" in doc:
                raise ValueError(f"{f.name}: plain Secret with stringData is not allowed")
