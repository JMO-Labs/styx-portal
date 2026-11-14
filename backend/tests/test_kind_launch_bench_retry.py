"""scripts/kind/30-launch-bench.sh must re-feed the manifest on retry (#342)."""

import os
import shutil
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "kind" / "30-launch-bench.sh"

# Fake kubectl: first pod apply fails like a kyverno webhook reset; any apply
# or delete with an empty manifest fails like real kubectl does.
FAKE_KUBECTL = r"""#!/usr/bin/env bash
verb=$1; shift
case "$verb" in
  apply|delete)
    f=""
    while [ $# -gt 0 ]; do [ "$1" = "-f" ] && f=$2; shift; done
    if [ "$f" = "-" ]; then body=$(cat); else body=$(cat "$f"); fi
    if [ -z "$body" ]; then echo "error: no objects passed to $verb" >&2; exit 1; fi
    if [ "$verb" = apply ] && grep -q "bench-1" <<<"$body" && [ ! -e "$STATE/failed" ]; then
      touch "$STATE/failed"
      echo "connection reset by peer" >&2; exit 1
    fi
    echo "$verb ok" >> "$STATE/log"
    ;;
esac
exit 0
"""


def test_retry_refeeds_manifest_after_transient_error(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "kubectl").write_text(FAKE_KUBECTL)
    (bin_dir / "sleep").write_text("#!/bin/sh\nexit 0\n")
    for f in bin_dir.iterdir():
        f.chmod(0o755)
    work = tmp_path / "work"
    bench = Path("test") / "kind" / "launch-bench"
    shutil.copytree(REPO / bench, work / bench)
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "STATE": str(tmp_path),
        "LAUNCH_BENCH_PODS": "2",
    }
    r = subprocess.run(["bash", str(SCRIPT)], cwd=work, env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert (tmp_path / "failed").exists()
    assert "no objects passed" not in r.stderr
    assert "LAUNCH_P95_SECONDS=" in r.stdout
