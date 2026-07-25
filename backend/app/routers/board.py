"""Sahaj · imagen and storyboard

Build here. This file is yours alone, so nothing you do collides with another
branch. Do not edit main.py: routers are auto-discovered.

Use: app.consistency: compile_identity_card, generate_reference_sheet, fingerprint, generate_shot_with_referee
"""
from fastapi import APIRouter

router = APIRouter(prefix="/api/board", tags=["board"])


@router.get("/ping")
async def ping() -> dict:
    return {"tab": "board", "ready": False}
