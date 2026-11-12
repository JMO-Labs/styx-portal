"""Leader probe for styx-portal#6: runs the backend's real LeaderElector and
writes "1" or "0" to $PROBE_DIR/<pid> every 0.2 s. Run from the enterprise backend dir."""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, os.getcwd())
from app.services.leader import LeaderElector  # noqa: E402


async def main() -> None:
    el = LeaderElector()
    out = Path(os.environ["PROBE_DIR"]) / str(os.getpid())
    task = asyncio.create_task(el.run())
    while not task.done():
        out.write_text("1" if el.is_leader else "0")
        await asyncio.sleep(0.2)


asyncio.run(main())
