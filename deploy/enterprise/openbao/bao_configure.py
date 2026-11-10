#!/usr/bin/env python3
"""Idempotent OpenBao configuration from files in this directory (issue #4, ADR-0042).

Checks the stdout file audit device (declared in the server HCL: OpenBao 2.7 refuses
API-created audit devices), then applies the kv/ (KV v2) mount plus extra-mounts.json,
Kubernetes auth, every policies/*.hcl and every role in auth-roles.json. Reads state first and
only enables what is missing; policy and role writes are upserts. With BAO_GITLAB_JWT_ISSUER set
it also configures auth/jwt for GitLab CI id_tokens and the roles in jwt-roles.json (issue #10),
writing only what differs. Stdlib only; calls `bao`.

Usage: BAO_ADDR=https://... BAO_CACERT=ca.crt BAO_TOKEN=... ./bao_configure.py [--dry-run]
"""

import argparse
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

K8S_HOST = "https://kubernetes.default.svc"


def die(msg: str) -> None:
    print(f"bao_configure: {msg}", file=sys.stderr)
    sys.exit(2)


def check_env() -> None:
    for var in ("BAO_ADDR", "BAO_CACERT"):
        if not os.environ.get(var):
            die(f"{var} must be set")
    if not os.environ["BAO_ADDR"].startswith("https://"):
        die("BAO_ADDR must be https://; refusing to send the token in cleartext")
    issuer = os.environ.get("BAO_GITLAB_JWT_ISSUER")
    if issuer is not None and not issuer.startswith("https://"):
        die("BAO_GITLAB_JWT_ISSUER must be https://")
    for var in ("BAO_SKIP_VERIFY", "VAULT_SKIP_VERIFY"):
        if var in os.environ:
            die(f"{var} is set; refusing to talk to OpenBao without TLS verification")


def read(*args: str) -> dict | None:
    """Run a read-only bao command; None only when the path does not exist."""
    res = subprocess.run(["bao", *args], capture_output=True, text=True)
    # bao also exits 2 on 403, TLS and connection errors: those must not read as "absent".
    if res.returncode == 2 and "No value found" in res.stderr:
        return None
    if res.returncode != 0:
        die(f"bao {shlex.join(args)} failed: {res.stderr.strip()}")
    return json.loads(res.stdout or "{}")


class Applier:
    def __init__(self, dry_run: bool):
        self.dry_run = dry_run

    def __call__(self, *args: str, stdin: str | None = None) -> None:
        print("bao " + shlex.join(args) + (f" <<< {stdin}" if stdin else ""))
        if self.dry_run:
            return
        res = subprocess.run(["bao", *args], capture_output=True, text=True, input=stdin)
        if res.returncode != 0:
            die(f"bao {shlex.join(args)} failed: {res.stderr.strip()}")


def mounts(conf: Path) -> list[dict]:
    extra = json.loads((conf / "extra-mounts.json").read_text())
    return [{"path": "kv", "type": "kv-v2"}, *extra]


def mount_matches(current: dict, want_type: str) -> bool:
    if want_type == "kv-v2":
        return current.get("type") == "kv" and (current.get("options") or {}).get("version") == "2"
    return current.get("type") == want_type


def apply_mounts(conf: Path, bao: Applier) -> None:
    existing = read("secrets", "list", "-format=json") or {}
    for m in mounts(conf):
        cur = existing.get(m["path"].strip("/") + "/")
        if cur is None:
            bao("secrets", "enable", f"-path={m['path']}", m["type"])
        elif not mount_matches(cur, m["type"]):
            die(f"mount {m['path']}/ exists with type {cur.get('type')}, want {m['type']}")


def check_audit() -> None:
    devices = (read("audit", "list", "-format=json") or {}).values()
    if not any(d.get("type") == "file" and (d.get("options") or {}).get("file_path") == "stdout"
               for d in devices):
        die('no file audit device to stdout; declare audit "file" "stdout" in the server config')


def apply_k8s_auth(bao: Applier) -> None:
    methods = read("auth", "list", "-format=json") or {}
    if "kubernetes/" not in methods:
        bao("auth", "enable", "kubernetes")
        current = None
    else:
        current = read("read", "-format=json", "auth/kubernetes/config")
    if ((current or {}).get("data") or {}).get("kubernetes_host") != K8S_HOST:
        bao("write", "auth/kubernetes/config", f"kubernetes_host={K8S_HOST}")


def apply_policies(conf: Path, bao: Applier) -> None:
    for path in sorted((conf / "policies").glob("*.hcl")):
        bao("policy", "write", path.stem, str(path))


def apply_roles(conf: Path, bao: Applier) -> None:
    for r in json.loads((conf / "auth-roles.json").read_text()):
        bao("write", f"auth/kubernetes/role/{r['name']}",
            "bound_service_account_names=" + ",".join(r["bound_service_account_names"]),
            "bound_service_account_namespaces=" + ",".join(r["bound_service_account_namespaces"]),
            "policies=" + ",".join(r["policies"]),
            f"token_ttl={int(r['token_ttl'])}", f"token_max_ttl={int(r['token_ttl'])}")


def apply_gitlab_jwt(conf: Path, bao: Applier, issuer: str) -> None:
    if "jwt/" not in (read("auth", "list", "-format=json") or {}):
        bao("auth", "enable", "jwt")
        cfg, enabled = {}, False
    else:
        cfg, enabled = (read("read", "-format=json", "auth/jwt/config") or {}).get("data") or {}, True
    if cfg.get("bound_issuer") != issuer or cfg.get("oidc_discovery_url") != issuer:
        bao("write", "auth/jwt/config", f"bound_issuer={issuer}", f"oidc_discovery_url={issuer}")
    for r in json.loads((conf / "jwt-roles.json").read_text()):
        want = {k: v for k, v in r.items() if k not in ("name", "policies")}
        want |= {"token_policies": r["policies"], "token_max_ttl": int(r["token_ttl"])}
        path = f"auth/jwt/role/{r['name']}"
        cur = ((read("read", "-format=json", path) if enabled else None) or {}).get("data") or {}
        if any(cur.get(k) != v for k, v in want.items()):
            bao("write", path, "-", stdin=json.dumps(want, sort_keys=True))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true", help="print planned writes, change nothing")
    ap.add_argument("--dir", type=Path, default=Path(__file__).resolve().parent,
                    help="directory with policies/, auth-roles.json, extra-mounts.json")
    args = ap.parse_args(argv)
    check_env()
    bao = Applier(args.dry_run)
    check_audit()
    apply_mounts(args.dir, bao)
    apply_k8s_auth(bao)
    apply_policies(args.dir, bao)
    apply_roles(args.dir, bao)
    if issuer := os.environ.get("BAO_GITLAB_JWT_ISSUER"):
        apply_gitlab_jwt(args.dir, bao, issuer)
    return 0


if __name__ == "__main__":
    sys.exit(main())
