"""kk · character builder

Build here. This file is yours alone, so nothing you do collides with another
branch. Do not edit main.py: routers are auto-discovered.

Use: data/seed/character_questions.json, then app.consistency.compile_identity_card and app.voice.compile_voice_card
"""
from fastapi import APIRouter

router = APIRouter(prefix="/api/characters", tags=["characters"])


@router.get("/ping")
async def ping() -> dict:
    return {"tab": "characters", "ready": False}
