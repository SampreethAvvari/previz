"""Sampreeth · script and story builder

Build here. This file is yours alone, so nothing you do collides with another
branch. Do not edit main.py: routers are auto-discovered.

Use: app.voice: compile_voice_card, write_exchange, referee_line. Do NOT rewrite these, they are built and verified
"""
from fastapi import APIRouter

router = APIRouter(prefix="/api/story", tags=["story"])


@router.get("/ping")
async def ping() -> dict:
    return {"tab": "story", "ready": False}
