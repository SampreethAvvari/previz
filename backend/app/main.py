"""Magic Hour. Serves the UI and mounts the API.

DO NOT ADD ROUTES TO THIS FILE. Add a module under app/api/ and include it in
app/api/__init__.py. That rule exists so several people can build several tabs on
several branches with nothing to conflict on at merge time.
"""
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

app = FastAPI(title="Magic Hour")
STATIC = Path(__file__).parent / "static"
CACHE = Path(__file__).parent.parent / "demo_cache"

# Mounted defensively on purpose. Several tabs are being written in parallel
# right now, so app/api/ can be momentarily unimportable (a router referenced
# before its module exists). One half-written tab must not stop the app from
# booting, because a demo that will not start is worse than a tab that 404s.
API_ERROR: str | None = None
try:
    from app.api import api

    app.include_router(api)
    print("  api mounted")
except Exception as exc:  # noqa: BLE001
    API_ERROR = f"{type(exc).__name__}: {exc}"
    print(f"  API FAILED TO MOUNT: {API_ERROR}")

# Cached frames, sheets and dialogue, served from disk. The venue wifi dying, the
# lab project expiring and the shared image quota running out are all live risks
# today, and cached assets survive all three.
if CACHE.is_dir():
    app.mount("/cache", StaticFiles(directory=CACHE), name="cache")


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": API_ERROR is None, "api_error": API_ERROR,
            "routes": sorted({r.path for r in app.routes
                              if getattr(r, "path", "").startswith("/api/")})}


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")
