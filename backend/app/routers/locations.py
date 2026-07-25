"""gaurav · location scouting

Build here. This file is yours alone, so nothing you do collides with another
branch. Do not edit main.py: routers are auto-discovered.

Use: app.tools.locations.find_locations, already correct. Add Places Photos and cache them to disk
"""
from fastapi import APIRouter

router = APIRouter(prefix="/api/locations", tags=["locations"])


@router.get("/ping")
async def ping() -> dict:
    return {"tab": "locations", "ready": False}
