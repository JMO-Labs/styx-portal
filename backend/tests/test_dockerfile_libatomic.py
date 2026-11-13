from pathlib import Path

DOCKERFILE = Path(__file__).resolve().parents[1] / "Dockerfile"


def test_libatomic1_installed_before_playwright_deps():
    text = DOCKERFILE.read_text()
    assert "libatomic1" in text
    assert text.index("libatomic1") < text.index("playwright install-deps")
