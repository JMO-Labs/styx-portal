#!/usr/bin/env python3
"""Fail-closed check for deploy/enterprise/images/phase1.lock (issue #25).

Every non-comment line must be `repo@sha256:<64 hex>` (no tag, no placeholder) and its repo
must be listed in phase1.images. --strict also requires every image to be locked.
"""
import re
import sys
from pathlib import Path

REF = re.compile(r"^[a-z0-9][a-z0-9._-]*(?::\d+)?(?:/[a-z0-9._-]+)+@sha256:[0-9a-f]{64}$")
IMG_DIR = Path(__file__).resolve().parents[1] / "deploy" / "enterprise" / "images"


def _lines(text):
    return [x.strip() for x in text.splitlines() if x.strip() and not x.lstrip().startswith("#")]


def _repo(ref):
    return re.split(r"[@]", ref)[0] if "@" in ref else re.sub(r":[^:/]+$", "", ref)


def check(lock, images, strict=False):
    errs, locked = [], set()
    refs = _lines(lock)
    if not refs:
        errs.append("lock is empty")
    for r in refs:
        if not REF.match(r):
            errs.append(f"not a digest-pinned ref: {r}")
        locked.add(_repo(r))
    known = {_repo(i) for i in _lines(images)}
    errs += [f"locked repo not in phase1.images: {r}" for r in sorted(locked - known)]
    if strict:
        errs += [f"missing from lock: {r}" for r in sorted(known - locked)]
    return errs


def main(argv):
    strict = "--strict" in argv
    args = [a for a in argv if not a.startswith("--")]
    lock = Path(args[0]) if args else IMG_DIR / "phase1.lock"
    images = Path(args[1]) if len(args) > 1 else IMG_DIR / "phase1.images"
    if not lock.is_file():
        print(f"missing {lock}", file=sys.stderr)
        return 1
    errs = check(lock.read_text(), images.read_text(), strict)
    for e in errs:
        print(f"ERROR: {e}", file=sys.stderr)
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
