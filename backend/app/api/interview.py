"""The front door: the interview, and the home page it is served on."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app import interview
from app.store import store, story_json

router = APIRouter()
STATIC = Path(__file__).resolve().parents[1] / "static"


def _sid(story_id: str | None) -> str:
    try:
        return store.story(story_id).id
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/interview")
def get_interview(story_id: str | None = None):
    """Every question with what is already answered, plus where to resume."""
    return interview.state(_sid(story_id))


class AnswerIn(BaseModel):
    id: str
    value: str = ""


@router.post("/interview/answer")
def post_answer(body: AnswerIn, story_id: str | None = None):
    """Write one answer and return the new state.

    The whole state comes back rather than an acknowledgement, because answering
    "who is in it" with two names adds twenty four questions and the client should
    not have to know that.
    """
    return interview.answer(_sid(story_id), body.id, body.value)


class NewStoryIn(BaseModel):
    title: str = "Untitled"


@router.post("/interview/new")
def post_new(body: NewStoryIn):
    """Start a fresh film and point every tab at it."""
    sid = interview.new_story(body.title)
    return {"story_id": sid, **interview.state(sid)}


class ActivateIn(BaseModel):
    story_id: str


@router.post("/interview/activate")
def activate(body: ActivateIn):
    """Point every tab at an existing film.

    Starting a new one would otherwise strand whatever was open, including the
    seeded story the demo runs on, with no way back to it.
    """
    sid = _sid(body.story_id)
    store.default_story_id = sid
    return {"story_id": sid, **interview.state(sid)}


@router.get("/interview/home")
def home_page():
    """The home page. Served here rather than mounted, so it exists whether or
    not anyone has touched main.py."""
    p = STATIC / "home.html"
    if not p.exists():
        raise HTTPException(404, "home.html not built yet")
    return FileResponse(p)


@router.get("/interview/stories")
def stories():
    """Everything on disk to resume, newest last. Used by the home page to offer
    a continue rather than making the filmmaker start again."""
    return {"stories": [story_json(s, deep=False) for s in store.stories.values()],
            "active": store.default_story_id}
