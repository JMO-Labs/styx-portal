#!/usr/bin/env python3
"""Refresh Squid category blocklists from UT1 (ADR-0040). Stdlib only.

Writes <category>.txt (dstdomain: leading dot, deduped, sorted) atomically into --out.
If any download fails nothing is written and the exit code is 1 (old files stay).
"""
import argparse
import io
import os
import re
import shutil
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

CATEGORIES = ["filehosting", "webmail", "vpn", "redirector", "strong_redirector"]
VENDORED = "paste"
HOST = re.compile(r"^(?=.{1,253}$)([a-z0-9_]([a-z0-9_-]{0,61}[a-z0-9_])?\.)+[a-z]{2,63}$")


def parse(lines) -> str:
    """Normalise hostnames into a squid dstdomain body (no IPs, no covered subdomains)."""
    hosts = {x.strip().lower().lstrip(".") for x in lines if x.strip() and not x.startswith("#")}
    hosts = {h for h in hosts if HOST.match(h)}
    keep = [h for h in sorted(hosts)
            if not any(p in hosts for p in _parents(h))]  # squid rejects covered subdomains
    return "".join(f".{h}\n" for h in keep)


def _parents(host: str):
    parts = host.split(".")
    return (".".join(parts[i:]) for i in range(1, len(parts) - 1))


def write_atomic(path: Path, text: str) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def fetch(base_url: str, cat: str) -> list[str]:
    with urllib.request.urlopen(f"{base_url.rstrip('/')}/{cat}.tar.gz", timeout=120) as r:
        data = r.read()
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tf:
        member = next((m for m in tf.getmembers() if m.isfile() and m.name.endswith("/domains")), None)
        if member is None:
            raise ValueError(f"{cat}: no domains file in tarball")
        return tf.extractfile(member).read().decode("utf-8", "replace").splitlines()


def seed(seed_dir: Path, out: Path) -> None:
    """Copy vendored lists for categories that have no list yet."""
    for f in sorted(seed_dir.glob("*.txt")):
        if not (out / f.name).exists():
            shutil.copyfile(f, out / f.name)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default=os.environ.get("UT1_BASE_URL", ""))
    ap.add_argument("--out", type=Path, default=Path(os.environ.get("OUT_DIR", "/categories")))
    ap.add_argument("--seed", type=Path, default=Path(os.environ.get("SEED_DIR", "/seed")))
    a = ap.parse_args(argv)
    a.out.mkdir(parents=True, exist_ok=True)
    seed(a.seed, a.out)
    try:
        bodies = {c: parse(fetch(a.base_url, c)) for c in CATEGORIES}
        bodies[VENDORED] = parse((a.seed / f"{VENDORED}.txt").read_text().splitlines())
    except Exception as e:  # noqa: BLE001 - any failure keeps the old lists
        print(f"update failed, keeping previous lists: {e}", file=sys.stderr)
        return 1
    for cat, body in bodies.items():
        write_atomic(a.out / f"{cat}.txt", body)
    print("updated: " + ", ".join(f"{c}={b.count(chr(10))}" for c, b in bodies.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
