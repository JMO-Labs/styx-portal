"""Static checks for scripts/enterprise/ha_demo.sh (issue #103)."""

import re
from pathlib import Path

from app.models import SetupToken

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/enterprise/ha_demo.sh"


def test_setup_token_query_uses_model_table():
    src = SCRIPT.read_text()
    tables = re.findall(r"FROM\s+(\w+)\s+WHERE\s+id=1", src)
    assert tables, "ha_demo.sh no longer reads the setup token"
    assert set(tables) == {SetupToken.__tablename__}
