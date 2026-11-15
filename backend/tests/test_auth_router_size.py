from pathlib import Path

import app.routers as routers_pkg


def test_auth_router_modules_under_500_lines():
    base = Path(routers_pkg.__file__).parent
    for name in ("auth.py", "auth_link.py"):
        assert len((base / name).read_text().splitlines()) <= 500, name
