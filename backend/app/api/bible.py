"""Bible: the story, hybrid search over it, and the Canon strip.

This is the surface every other surface reads from. It has no model calls except
the embedding leg of search, so it is the one part of the app that works with the
network down.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.bible import build_pack, index, reindex_entity, reindex_story
from app.store import scene_json, store, story_json

router = APIRouter()


def _sid(story_id: str | None) -> str:
    try:
        return store.story(story_id).id
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/health")
def health():
    """Health, under /api because /healthz does not survive Cloud Run.

    Measured, not guessed: /healthz is registered in the app and answers 200
    locally, and on Cloud Run it returns Google's own 404 page while /healthz/
    still 307s to it. The request never reaches the container and never appears in
    the logs, so the frontend is intercepting that exact path. Anything under /api
    is untouched, so health lives here and /healthz stays for local use.
    """
    from app.bible import index as _index
    from app.config import settings

    sid = store.default_story_id
    chunks = _index.for_story(sid) if sid else []
    return {"ok": True,
            "project": settings.gcp_project,
            "location": settings.gcp_location,
            "story_id": sid,
            "stories": len(store.stories),
            "chunks": len(chunks),
            "chunks_embedded": sum(1 for c in chunks
                                   if c.embedding is not None),
            "maps_key": bool(settings.google_maps_api_key)}


@router.get("/story")
def get_story(story_id: str | None = None):
    """The whole bible in one call. The client caches this and re-fetches after
    any write, which at this size is cheaper than maintaining client state.
    """
    return story_json(store.story(_sid(story_id)))


@router.get("/stories")
def list_stories():
    return {"stories": [story_json(s, deep=False) for s in store.stories.values()],
            "default": store.default_story_id}


class StoryIn(BaseModel):
    title: str
    logline: str = ""
    format: str = "short"


@router.post("/stories")
def create_story(body: StoryIn):
    st = store.create_story(body.title, body.logline, format=body.format)
    reindex_story(st.id)
    return story_json(st)


@router.get("/bible/search")
def search(q: str, story_id: str | None = None, k: int = 8,
           layers: str = "canon,draft"):
    """Hybrid search. `layers` filters canon, draft, or both."""
    sid = _sid(story_id)
    return {"query": q,
            "hits": index.search(sid, q, k=k,
                                 layers=tuple(layers.split(",")))}


@router.get("/bible/chunks")
def chunks(story_id: str | None = None):
    sid = _sid(story_id)
    all_ = index.for_story(sid)
    return {"count": len(all_),
            "embedded": sum(1 for c in all_ if c.embedding is not None),
            "chunks": [c.json() for c in all_]}


@router.post("/bible/embed")
def embed(story_id: str | None = None):
    """Fill in missing embeddings. Called once after startup, and after imports.

    Until this runs, search is lexical only. That is a visible degradation rather
    than a wrong answer, which is the correct failure mode.
    """
    sid = _sid(story_id)
    n = index.embed_pending(sid)
    all_ = index.for_story(sid)
    return {"embedded_now": n, "total": len(all_),
            "embedded_total": sum(1 for c in all_ if c.embedding is not None)}


@router.get("/bible/context")
def context(q: str = "", story_id: str | None = None,
            scene: int | None = None, character_ids: str = ""):
    """Preview exactly what a model call would receive. This is the Context tab,
    and it is the fastest way to find out why a generation went wrong.
    """
    sid = _sid(story_id)
    ids = [i for i in character_ids.split(",") if i]
    pack = build_pack(sid, query=q, character_ids=ids or None,
                      scene_number=scene)
    return {"report": pack.report(), "slots": pack.slots, "text": pack.text()}


@router.get("/scenes/{number}")
def get_scene(number: int, story_id: str | None = None):
    st = store.story(_sid(story_id))
    sc = st.scene_by_number(number)
    if not sc:
        raise HTTPException(404, f"no scene {number}")
    return scene_json(sc)


class SceneIn(BaseModel):
    number: int
    slugline: str
    synopsis: str = ""
    int_ext: str = "INT"
    time_of_day: str = "DAY"
    body: str = ""
    characters: list[str] = []


@router.post("/scenes")
def create_scene(body: SceneIn, story_id: str | None = None):
    sid = _sid(story_id)
    st = store.story(sid)
    if st.scene_by_number(body.number):
        raise HTTPException(409, f"scene {body.number} already exists")
    sc = store.add_scene(sid, body.number, body.slugline,
                         synopsis=body.synopsis, int_ext=body.int_ext,
                         time_of_day=body.time_of_day, body=body.body,
                         characters=body.characters)
    reindex_entity(sid, "scene", sc.id)   # invariant one, §4.1
    return scene_json(sc)


class SceneBody(BaseModel):
    body: str | None = None
    synopsis: str | None = None
    status: str | None = None


@router.patch("/scenes/{number}")
def update_scene(number: int, body: SceneBody, story_id: str | None = None):
    sid = _sid(story_id)
    st = store.story(sid)
    sc = st.scene_by_number(number)
    if not sc:
        raise HTTPException(404, f"no scene {number}")
    for f in ("body", "synopsis", "status"):
        v = getattr(body, f)
        if v is not None:
            setattr(sc, f, v)
    reindex_entity(sid, "scene", sc.id)
    return scene_json(sc)


# ------------------------------------------------------------- the Canon strip

@router.get("/proposals")
def proposals(story_id: str | None = None, status: str = "pending"):
    st = store.story(_sid(story_id))
    from dataclasses import asdict
    return {"proposals": [asdict(p) for p in st.proposals.values()
                          if status == "all" or p.status == status]}


@router.post("/proposals/{pid}/promote")
def promote(pid: str, story_id: str | None = None):
    """Write the proposed value into canon and reindex, in one call.

    Deliberately not reachable by any agent (§5.1). Agents call propose_fact;
    only a person promotes. That is the whole reason the two layers exist.
    """
    sid = _sid(story_id)
    st = store.story(sid)
    p = st.proposals.get(pid)
    if not p:
        raise HTTPException(404, "no such proposal")
    if p.entity_type == "character" and p.entity_id in st.characters:
        store.set_answers(sid, p.entity_id, {p.field: str(p.proposed)})
        reindex_entity(sid, "character", p.entity_id)
    elif p.entity_type == "scene" and p.entity_id:
        sc = st.scenes.get(p.entity_id)
        if sc and hasattr(sc, p.field):
            setattr(sc, p.field, p.proposed)
            reindex_entity(sid, "scene", sc.id)
    p.status = "accepted"
    from dataclasses import asdict
    return asdict(p)


@router.post("/proposals/{pid}/reject")
def reject(pid: str, story_id: str | None = None):
    st = store.story(_sid(story_id))
    p = st.proposals.get(pid)
    if not p:
        raise HTTPException(404, "no such proposal")
    p.status = "rejected"
    from dataclasses import asdict
    return asdict(p)
