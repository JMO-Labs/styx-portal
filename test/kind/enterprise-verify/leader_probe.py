"""Leader probe for styx-portal#6: runs the backend's real LeaderElector and
writes "1\n" or "0\n" to $PROBE_DIR/<pid> every 0.2 s. Run from the enterprise backend dir.
On exit the file is reset to "0\n"; if the elector task raised, the probe exits 1."""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, os.getcwd())
from app.services.leader import LeaderElector  # noqa: E402


async def main() -> int:
    el = LeaderElector()
    out = Path(os.environ["PROBE_DIR"]) / str(os.getpid())
    task = asyncio.create_task(el.run())
    try:
        while not task.done():
            out.write_text("1\n" if el.is_leader else "0\n")
            await asyncio.sleep(0.2)
    finally:
        out.write_text("0\n")
    exc = task.exception() if not task.cancelled() else None
    if exc is not None:
        print(f"leader_probe: elector task failed: {exc!r}", file=sys.stderr)
        return 1
    return 0


sys.exit(asyncio.run(main()))
