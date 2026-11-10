#!/usr/bin/env python3
"""Idempotently PUT the Styx ILM policy, templates and shipper role into Elastic (#11).

Stdlib only. Uses a separate *setup* API key (never the shipper key):
  ELASTIC_URL            https://siem.example.internal:9200 (https required)
  ELASTIC_SETUP_API_KEY  base64 "id:api_key" with manage_ilm, manage_index_templates,
                         manage_security (role only)
  ELASTIC_CA_FILE        optional org CA bundle (PEM); hostname is always verified
  RETENTION_DELETE_DAYS  delete phase age in days, default 455 (90 d hot + 1 y archive)
Usage: bootstrap.py [--dry-run]
"""
import argparse
import json
import os
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
# Order matters: ILM and component templates must exist before the index templates.
KINDS = (("ilm", "_ilm/policy"), ("component-templates", "_component_template"),
         ("index-templates", "_index_template"), ("roles", "_security/role"))
DEFAULT_RETENTION_DAYS = "455"


def plan(env) -> list[tuple[str, dict]]:
    days = env.get("RETENTION_DELETE_DAYS") or DEFAULT_RETENTION_DAYS
    if not days.isdigit() or int(days) < 365:
        raise ValueError(f"RETENTION_DELETE_DAYS must be whole days >= 365 (AU-11), got {days!r}")
    out = []
    for folder, api in KINDS:
        for f in sorted((HERE / folder).glob("*.json")):
            body = json.loads(f.read_text().replace("${RETENTION_DELETE_DAYS}", days))
            out.append((f"{api}/{f.stem}", body))
    return out


def _put(url, key, ctx, path, body):
    req = urllib.request.Request(
        f"{url.rstrip('/')}/{path}", data=json.dumps(body).encode(), method="PUT",
        headers={"Authorization": f"ApiKey {key}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, context=ctx, timeout=30) as r:  # noqa: S310 (https only)
        return r.status


def main(argv=None, env=None) -> int:
    env = os.environ if env is None else env
    args = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    args.add_argument("--dry-run", action="store_true", help="print the requests only")
    opts = args.parse_args(argv)
    try:
        steps = plan(env)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    if opts.dry_run:
        for path, _ in steps:
            print(f"PUT {path}")
        return 0
    url, key = env.get("ELASTIC_URL", ""), env.get("ELASTIC_SETUP_API_KEY", "")
    if not url.startswith("https://") or not key:
        print("error: set ELASTIC_URL (https://...) and ELASTIC_SETUP_API_KEY", file=sys.stderr)
        return 2
    ctx = ssl.create_default_context(cafile=env.get("ELASTIC_CA_FILE") or None)
    for path, body in steps:
        try:
            print(f"PUT {path} -> {_put(url, key, ctx, path, body)}")
        except urllib.error.HTTPError as e:
            print(f"error: PUT {path} -> {e.code} {e.read()[:500].decode(errors='replace')}",
                  file=sys.stderr)
            return 1
        except urllib.error.URLError as e:
            print(f"error: PUT {path}: {e.reason}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
