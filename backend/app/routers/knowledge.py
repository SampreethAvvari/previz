"""Sampreeth · knowledge base

Build here. This file is yours alone, so nothing you do collides with another
branch. Do not edit main.py: routers are auto-discovered.

Use: nothing exists yet. This owns the store that feeds voice.write_exchange(knows=...)
"""
from fastapi import APIRouter

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


@router.get("/ping")
async def ping() -> dict:
    return {"tab": "knowledge", "ready": False}
