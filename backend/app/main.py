"""Magic Hour. Serves the UI and mounts one router per tab.

DO NOT ADD ROUTES TO THIS FILE. Add a module to app/routers/ that exposes
`router`, and it is discovered automatically. That rule exists so five people can
build five tabs on five branches with nothing to conflict on at merge time.
"""
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app import routers
from app.models import StylePreset
from app.pipeline import generate_storyboard

app = FastAPI(title="Magic Hour")
STATIC = Path(__file__).parent / "static"
CACHE = Path(__file__).parent.parent / "demo_cache"

MOUNTED = routers.register_all(app)
print(f"  mounted tabs: {', '.join(MOUNTED) or 'none'}")

# Cached generated frames, sheets and dialogue. Served straight from disk so the
# demo survives the venue wifi dying, the lab project expiring, or the shared
# image quota running out mid presentation. All three are live risks today.
if CACHE.is_dir():
    app.mount("/cache", StaticFiles(directory=CACHE), name="cache")


class GenerateRequest(BaseModel):
    scene: str
    style: StylePreset = StylePreset()


@app.get("/healthz")
def healthz():
    return {"ok": True, "tabs": MOUNTED}


@app.post("/generate")
def generate(req: GenerateRequest):
    """Scene text + style -> storyboard frames + real filming locations."""
    return generate_storyboard(req.scene, req.style)


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")
