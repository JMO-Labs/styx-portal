"""Test helper: the first-run setup code field for POST /api/auth/setup bodies."""
from app.security import setup_token

# Bound to the test DB session by the autouse fixture in conftest.
SESSION = None


async def st() -> dict:
    return {"setup_token": await setup_token.current(SESSION)}
