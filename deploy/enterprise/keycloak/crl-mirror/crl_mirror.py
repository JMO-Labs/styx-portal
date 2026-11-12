"""Mirror issuer CRLs to a shared volume and export nextUpdate (issue #130, ADR-0017).

Stdlib only. Config: CRL_URLS = JSON {"name": "url"}; CRL_DIR; PROM_DIR (textfile); PUSHGATEWAY_URL (optional).
Also holds decide(): the fail-closed revocation rule the realm config implements
(OCSP enabled, fail-open false, CRL checking on).
"""
import datetime as dt
import json
import os
import re
import sys
import urllib.request

UTC = dt.timezone.utc
NAME = re.compile(r"^[A-Za-z0-9_.-]+$")


def _tlv(b, i):
    tag = b[i]
    n = b[i + 1]
    i += 2
    if n & 0x80:
        k = n & 0x7F
        n = int.from_bytes(b[i:i + k], "big")
        i += k
    return tag, i, i + n


def _children(b, start, end):
    while start < end:
        tag, s, e = _tlv(b, start)
        yield tag, s, e
        start = e


def _time(tag, raw):
    t = raw.decode()
    if tag == 0x17:  # UTCTime
        y = int(t[:2])
        t = ("19" if y >= 50 else "20") + t
    return dt.datetime.strptime(t[:14], "%Y%m%d%H%M%S").replace(tzinfo=UTC)


def parse_crl(der):
    """Return (next_update or None, set of revoked serials). ValueError if not a CRL."""
    try:
        tag, s, e = _tlv(der, 0)
        if tag != 0x30:
            raise ValueError("not a SEQUENCE")
        tag, s, e = _tlv(der, s)  # tbsCertList
        if tag != 0x30:
            raise ValueError("no tbsCertList")
        items = list(_children(der, s, e))
        if items[0][0] == 0x02:  # optional version
            items = items[1:]
        times = [(t, a, b) for t, a, b in items[2:] if t in (0x17, 0x18)]
        if not times:
            raise ValueError("no thisUpdate")
        nxt = _time(times[1][0], der[times[1][1]:times[1][2]]) if len(times) > 1 else None
        revoked = set()
        for t, a, b in items[2:]:
            if t == 0x30:
                for ct, ca, cb in _children(der, a, b):
                    st, sa, sb = next(_children(der, ca, cb))
                    revoked.add(int.from_bytes(der[sa:sb], "big", signed=True))
                break
        return nxt, revoked
    except (IndexError, StopIteration) as exc:
        raise ValueError("malformed CRL") from exc


def next_update(der):
    return parse_crl(der)[0]


def decide(ocsp, crl_der, serial, now):
    """'allow'/'refuse'. ocsp: good|revoked|unreachable. Fail closed."""
    if ocsp == "good":
        return "allow"
    if ocsp != "unreachable" or crl_der is None:
        return "refuse"
    try:
        nxt, revoked = parse_crl(crl_der)
    except ValueError:
        return "refuse"
    if nxt is None or nxt <= now or serial in revoked:
        return "refuse"
    return "allow"


def fetch(url):
    with urllib.request.urlopen(url, timeout=30) as r:  # nosec - operator-set URLs
        return r.read()


def _atomic(path, data):
    tmp = f"{path}.tmp{os.getpid()}"
    with open(tmp, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def run(urls, crl_dir, prom_dir, fetch=fetch, now=None):
    now = now or dt.datetime.now(UTC)
    lines = ["# TYPE crl_next_update_timestamp_seconds gauge"]
    ok = True
    for name, url in urls.items():
        try:
            if not NAME.match(name):
                raise ValueError("bad name")
            data = fetch(url)
            nxt = next_update(data)
            if nxt is None:
                raise ValueError("CRL has no nextUpdate")
            _atomic(os.path.join(crl_dir, f"{name}.crl"), data)
        except Exception as exc:  # keep the previous file; report via exit code
            print(f"crl {name}: {type(exc).__name__}: {exc}", file=sys.stderr)
            ok = False
            old = os.path.join(crl_dir, f"{name}.crl")
            try:
                with open(old, "rb") as f:
                    nxt = next_update(f.read())
            except (OSError, ValueError):
                continue
        lines.append(f'crl_next_update_timestamp_seconds{{crl="{name}"}} {int(nxt.timestamp())}')
    if ok:
        lines += ["# TYPE crl_mirror_last_success_timestamp_seconds gauge",
                  f"crl_mirror_last_success_timestamp_seconds {int(now.timestamp())}"]
    _atomic(os.path.join(prom_dir, "crl_mirror.prom"), ("\n".join(lines) + "\n").encode())
    return 0 if ok else 1


def push(url, prom_dir):
    """POST the textfile to a Pushgateway (POST keeps metrics absent from this push)."""
    with open(os.path.join(prom_dir, "crl_mirror.prom"), "rb") as f:
        body = f.read()
    req = urllib.request.Request(f"{url.rstrip('/')}/metrics/job/crl-mirror", data=body, method="POST")
    urllib.request.urlopen(req, timeout=15).read()  # nosec - operator-set URL


if __name__ == "__main__":
    prom = os.environ.get("PROM_DIR", "/prom")
    rc = run(json.loads(os.environ["CRL_URLS"]), os.environ.get("CRL_DIR", "/crl"), prom)
    if os.environ.get("PUSHGATEWAY_URL"):
        try:
            push(os.environ["PUSHGATEWAY_URL"], prom)
        except OSError as exc:
            print(f"pushgateway: {exc}", file=sys.stderr)
            rc = 1
    sys.exit(rc)
