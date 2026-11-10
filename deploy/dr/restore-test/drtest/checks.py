"""Integrity checks. Each yields {name, pass, detail}. All SQL here is SELECT-only."""

import hashlib
import random
import re
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

from .guards import Refused

IDENT = re.compile(r"[a-z_][a-z0-9_]*")
READ_ONLY = {"PGOPTIONS": "-c default_transaction_read_only=on"}


def check(name, ok, detail):
    return {"name": name, "pass": bool(ok), "detail": detail}


def _quote(name):
    parts = name.split(".")
    if not 1 <= len(parts) <= 2 or not all(IDENT.fullmatch(p) for p in parts):
        raise Refused(f"bad SQL identifier {name!r}")
    return ".".join(f'"{p}"' for p in parts)


def fingerprint_sql(table, pk):
    order = ", ".join(f"t.{_quote(c.strip())}" for c in pk.split(","))
    return (f"SELECT count(*), md5(coalesce(string_agg(t::text, '' ORDER BY {order}), '')) "
            f"FROM {_quote(table)} AS t")


def psql_argv(conn, sql):
    return ["psql", "-X", "-A", "-t", "-F", "|", "-v", "ON_ERROR_STOP=1",
            "-h", conn["host"], "-p", str(conn["port"]), "-U", conn["user"],
            "-d", conn["dbname"], "-c", sql]


def query(runner, conn, sql, step):
    """Run one SELECT in a read-only transaction; (ok, stdout-or-error)."""
    p = runner(psql_argv(conn, sql), step=step, env=READ_ONLY)
    return p.returncode == 0, (p.stdout if p.returncode == 0 else p.stderr).strip()


def fingerprint_tables(runner, conn, tables):
    """{table: {count, md5}} or {table: {error}}."""
    out = {}
    for table, pk in tables.items():
        ok, res = query(runner, conn, fingerprint_sql(table, pk), "psql-fingerprint")
        try:
            count, md5 = res.split("|") if ok else ("", "")
            out[table] = {"count": int(count), "md5": md5}
        except ValueError:
            out[table] = {"error": res[-300:]}
    return out


def table_checks(actual, baseline):
    res = []
    for table in sorted(set(actual) | set(baseline)):
        a, b = actual.get(table), baseline.get(table)
        if not a or not b or "error" in a:
            res.append(check(f"rows:{table}", False,
                             f"{table}: baseline={b} restored={a}"))
            continue
        ok = a == b
        res.append(check(f"rows:{table}", ok,
                         f"{table}: count {a['count']}/{b['count']}, md5 "
                         f"{'match' if a['md5'] == b['md5'] else 'MISMATCH'}"))
    return res


def amcheck(runner, conn):
    p = runner(["pg_amcheck", "--heapallindexed", "-h", conn["host"], "-p", str(conn["port"]),
                "-U", conn["user"], conn["dbname"]], step="pg-amcheck")
    return check("cnpg:pg_amcheck", p.returncode == 0,
                 "ok" if p.returncode == 0 else (p.stdout + p.stderr).strip()[-300:])


def alembic(runner, conn, head):
    ok, v = query(runner, conn, "SELECT version_num FROM alembic_version", "psql-alembic")
    return check("cnpg:alembic-head", ok and v == head, f"restored={v!r} expected={head!r}")


def parse_ts(s):
    """Aware UTC datetime from ISO 8601 / psql timestamptz text; None if absent."""
    if not s:
        return None
    t = datetime.fromisoformat(s.strip().replace(" ", "T", 1))
    if t.tzinfo is None:
        raise ValueError(f"timestamp without zone: {s}")
    return t.astimezone(UTC)


def replay_point(runner, conn):
    ok, v = query(runner, conn, "SELECT pg_last_xact_replay_timestamp()", "psql-replay-ts")
    try:
        t = parse_ts(v) if ok else None
    except ValueError:
        t = None
    return t.isoformat().replace("+00:00", "Z") if t else None


def sha256_sample(runner, k, root_obj, target, n, seed):
    """sha256 of N restored files (seeded sample) == sha256 of the same file in the repo."""
    root = Path(target)
    files = sorted(str(p.relative_to(root)) for p in root.rglob("*")
                   if p.is_file() and not p.is_symlink())
    if not files:
        return check(f"kopia:sha256:{target}", False, "no files restored")
    sample = random.Random(seed).sample(files, min(n, len(files)))
    bad = []
    for rel in sample:
        p = runner([*k, "show", f"{root_obj}/{rel}"], step="kopia-show", binary=True)
        local = hashlib.sha256((root / rel).read_bytes()).hexdigest()
        if p.returncode or hashlib.sha256(p.stdout).hexdigest() != local:
            bad.append(rel)
    return check(f"kopia:sha256:{target}", not bad,
                 f"{len(sample) - len(bad)}/{len(sample)} match"
                 + (f"; mismatch: {', '.join(bad[:10])}" if bad else ""))


def health(url, attempts, interval):
    """GET url until 200. Returns (check, time of the passing response or None)."""
    if not url.startswith(("http://", "https://")):
        return check("app:health", False, f"bad url {url!r}"), None
    last = None
    for i in range(max(1, attempts)):
        try:
            with urllib.request.urlopen(url, timeout=10) as r:  # noqa: S310 (scheme checked)
                last = r.status
        except urllib.error.HTTPError as e:
            last = e.code
        except OSError as e:
            last = str(e)
        if last == 200:
            return check("app:health", True, f"GET {url} -> 200"), datetime.now(UTC)
        if i + 1 < attempts:
            time.sleep(interval)
    return check("app:health", False, f"GET {url} -> {last}"), None
