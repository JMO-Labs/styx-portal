"""apply_selkies_patches.sh applies the series in order and fails on a bad patch."""

import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "apply_selkies_patches.sh"

GOOD = """--- a/pkg/mod.py
+++ b/pkg/mod.py
@@ -1,2 +1,2 @@
 one
-two
+TWO
"""
BAD = GOOD.replace(" one\n-two", " nope\n-nada")


def _setup(tmp_path, patches):
    site = tmp_path / "site"
    (site / "pkg").mkdir(parents=True)
    (site / "pkg" / "mod.py").write_text("one\ntwo\n")
    pdir = tmp_path / "patches"
    pdir.mkdir()
    for name, body in patches.items():
        (pdir / name).write_text(body)
    (pdir / "series").write_text("# order\n\n" + "\n".join(patches) + "\n")
    return site, pdir


def _run(site, pdir):
    return subprocess.run(
        ["bash", str(SCRIPT), str(site)],
        env={"PATH": "/usr/bin:/bin", "SELKIES_PATCH_DIR": str(pdir)},
        capture_output=True,
        text=True,
    )


def test_clean_patch_applies(tmp_path):
    site, pdir = _setup(tmp_path, {"01-good.patch": GOOD})
    r = _run(site, pdir)
    assert r.returncode == 0, r.stderr
    assert (site / "pkg" / "mod.py").read_text() == "one\nTWO\n"


def test_broken_patch_fails(tmp_path):
    site, pdir = _setup(tmp_path, {"01-bad.patch": BAD})
    assert _run(site, pdir).returncode != 0


def test_stops_at_first_failure(tmp_path):
    site, pdir = _setup(tmp_path, {"01-bad.patch": BAD, "02-good.patch": GOOD})
    assert _run(site, pdir).returncode != 0
    assert (site / "pkg" / "mod.py").read_text() == "one\ntwo\n"


def test_missing_arg_fails():
    assert subprocess.run(["bash", str(SCRIPT)], capture_output=True).returncode != 0
