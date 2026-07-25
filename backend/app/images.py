"""Image bytes to disk, served back over HTTP.

GCS with signed URLs is the design (§13 item 6) and is cancelled for today. Disk
is the substitute, and it buys something the demo actually needs: every generated
frame survives a restart, so a board generated at 14:00 is still on screen at
15:30 without regenerating anything.

Two directories, on purpose:

  demo_cache/  committed. Frames we want to still be there if the venue wifi dies
               or the lab project expires mid demo.
  .cache/      gitignored. Everything generated at runtime.

Both are served under /cache/, demo_cache winning, so a committed frame always
beats a runtime one with the same name.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException
from fastapi.responses import FileResponse

BACKEND = Path(__file__).resolve().parents[1]
DEMO = BACKEND / "demo_cache"
RUNTIME = BACKEND / ".cache"
RUNTIME.mkdir(exist_ok=True)


def save_png(data: bytes, name: str) -> str:
    """Write bytes and return the URL the client should use."""
    safe = "".join(ch for ch in name if ch.isalnum() or ch in "-_")
    p = RUNTIME / f"{safe}.png"
    p.write_bytes(data)
    return f"/cache/{safe}.png"


def load_png(url_or_name: str) -> bytes | None:
    """Read a frame back off disk. Used to pass the previous approved frame into
    the next generation so lighting and blocking carry forward (§6.2 step 4).
    """
    name = url_or_name.rsplit("/", 1)[-1]
    for d in (DEMO, RUNTIME):
        p = d / name
        if p.exists():
            return p.read_bytes()
    return None


def serve(name: str) -> FileResponse:
    safe = Path(name).name
    for d in (DEMO, RUNTIME):
        p = d / safe
        if p.exists():
            return FileResponse(p, media_type="image/png",
                                headers={"Cache-Control": "public, max-age=3600"})
    raise HTTPException(404, f"no cached image {safe}")
