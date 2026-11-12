import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("check_patch_notes", ROOT / "scripts" / "check_patch_notes.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

GOOD = """# Note
- **Upstream project:** selkies-project/selkies
- **Offered:** not yet
- **Status:** local-only
- **Reason kept locally:** needs more testing
"""


def make(tmp_path, note=GOOD, series="# order\n01-a.patch\n"):
    (tmp_path / "patches/selkies").mkdir(parents=True)
    (tmp_path / "docs/upstream").mkdir(parents=True)
    (tmp_path / "patches/selkies/series").write_text(series)
    (tmp_path / "patches/selkies/01-a.patch").write_text("x")
    if note is not None:
        (tmp_path / "docs/upstream/01-a.md").write_text(note)
    return tmp_path


def test_pass(tmp_path):
    assert mod.check(make(tmp_path)) == []


def test_missing_note(tmp_path):
    errs = mod.check(make(tmp_path, note=None))
    assert errs and "01-a" in errs[0]


def test_missing_field(tmp_path):
    errs = mod.check(make(tmp_path, note=GOOD.replace("- **Offered:** not yet\n", "")))
    assert any("Offered" in e for e in errs)


def test_empty_field(tmp_path):
    errs = mod.check(make(tmp_path, note=GOOD.replace("not yet", "")))
    assert any("Offered" in e for e in errs)


def test_bad_status(tmp_path):
    errs = mod.check(make(tmp_path, note=GOOD.replace("local-only", "maybe")))
    assert any("Status" in e for e in errs)


def test_missing_patch_file(tmp_path):
    root = make(tmp_path)
    (root / "patches/selkies/01-a.patch").unlink()
    assert any("missing patch" in e for e in mod.check(root))


def test_repo_is_clean():
    assert mod.check(ROOT) == []
