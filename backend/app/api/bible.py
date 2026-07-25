"""Bible: the story, hybrid search over it, and the Canon strip.

This is the surface every other surface reads from. It has no model calls except
the embedding leg of search, so it is the one part of the app that works with the
network down.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.bible import BUDGETS, build_pack, index, reindex_entity, reindex_story
from app.store import scene_json, store, story_json

router = APIRouter()


def _sid(story_id: str | None) -> str:
    try:
        return store.story(story_id).id
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc


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

    The retrieved chunks come back in full, not as a list of ids. A panel that
    shows `c0037` and makes the reader go and look it up is a panel nobody reads
    twice, and the whole value of this endpoint is that a bad line is traced to
    the fact behind it in one glance rather than in three clicks.
    """
    sid = _sid(story_id)
    ids = [i for i in character_ids.split(",") if i]
    pack = build_pack(sid, query=q, character_ids=ids or None,
                      scene_number=scene)
    return {"report": pack.report(), "slots": pack.slots, "text": pack.text(),
            # The budgets ship with the pack so the panel can draw a slot against
            # its ceiling. Hardcoding them in the client would let the two drift,
            # and a meter that reads full when the slot is half used is worse than
            # no meter.
            "budgets": BUDGETS,
            "chunks": [index.chunks[c].json() for c in pack.chunk_ids
                       if c in index.chunks]}


@router.get("/bible/chunks/{cid}")
def chunk(cid: str, story_id: str | None = None):
    """One chunk with the row it was derived from.

    Chunks are DERIVED (§4.1). So the interesting question about any chunk is
    never "what does it say", it is "what wrote it, and is that thing canon". This
    resolves `source_ref` into the actual entity, which is what makes a chunk id
    in the Context panel a link rather than a label.
    """
    sid = _sid(story_id)
    ch = index.chunks.get(cid)
    if not ch or ch.story_id != sid:
        raise HTTPException(404, f"no such chunk: {cid}")
    st = store.story(sid)

    source: dict = {"kind": ch.entity_type, "ref": ch.source_ref}
    if ch.entity_type == "character" and ch.entity_id in st.characters:
        c = st.characters[ch.entity_id]
        source.update(name=c.name, role=c.role, canon_version=c.canon_version,
                      answers=len(c.answers), tab="cast")
    elif ch.entity_type == "scene" and ch.entity_id in st.scenes:
        s = st.scenes[ch.entity_id]
        source.update(name=s.slugline, number=s.number, status=s.status,
                      synopsis=s.synopsis, tab="script")
    elif ch.entity_type == "location" and ch.entity_id in st.locations:
        l = st.locations[ch.entity_id]
        source.update(name=l.name, address=l.address,
                      shortlisted=l.shortlisted, tab="scout")
    elif ch.entity_type in ("story", "style"):
        source.update(name=st.title, tab="bible")
    elif ch.entity_type == "edge":
        source.update(name="story graph", tab="bible")

    return {**ch.json(), "embedded": ch.embedding is not None,
            "source": source}


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

    out = []
    for p in st.proposals.values():
        if status != "all" and p.status != status:
            continue
        d = asdict(p)
        # The strip has to show what it is asking you to accept, and what it would
        # change. A queue that shows a rationale but not the value is asking for a
        # signature on an unread document.
        d["about"] = _about(st, p)
        d["preview"] = _preview(p)
        out.append(d)
    return {"proposals": out}


def _about(st, p) -> str:
    """Which row this proposal would change, in words a person recognises."""
    if p.entity_type == "character" and p.entity_id in st.characters:
        return st.characters[p.entity_id].name
    if p.entity_type == "scene" and p.entity_id in st.scenes:
        sc = st.scenes[p.entity_id]
        return f"scene {sc.number} · {sc.slugline}"
    if p.entity_type == "location" and p.entity_id in st.locations:
        return st.locations[p.entity_id].name
    return p.entity_type


def _preview(p) -> str:
    """The proposed value as one readable line, whatever shape it is in."""
    v = p.proposed
    if isinstance(v, dict):
        if "fact" in v:
            since = v.get("since_scene")
            return v["fact"] + (f"  (known from scene {since})" if since else "")
        return ", ".join(f"{k}: {x}" for k, x in v.items())
    if isinstance(v, list):
        return "; ".join(str(x) for x in v)
    return str(v)


class ExtractIn(BaseModel):
    scene: int


@router.post("/bible/extract")
def extract(body: ExtractIn, story_id: str | None = None):
    """Read a scene and propose what it establishes. Streams.

    This is the producer side of §5.1. Agents have no write path to canon, so the
    Archivist proposes with its reasoning attached and the Canon strip fills in
    front of you. Nothing it finds is true until a person promotes it.
    """
    from app.extract import extract_scene
    from app.sse import stream

    sid = _sid(story_id)

    def work(emit):
        return extract_scene(sid, body.scene, emit)

    return stream(work, agent="Archivist")


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
    if p.entity_type == "character" and p.field == "knows" \
            and p.entity_id in st.characters:
        # A learned fact is a horizon edge, not an interview answer, so it is
        # appended to `knows` with the scene it was learned in. That scene number
        # is the whole value of promoting it: it is what stops the character
        # referring to the fact in any earlier scene.
        c = st.characters[p.entity_id]
        v = p.proposed if isinstance(p.proposed, dict) else {"fact": str(p.proposed)}
        fact = (v.get("fact") or "").strip()
        if fact and not any(k.get("fact") == fact for k in c.knows):
            c.knows.append({"fact": fact,
                            "since_scene": int(v.get("since_scene", 1))})
        # Deliberately no canon_version bump. The Identity and Voice Cards are
        # compiled from the interview answers, and the horizon is injected per
        # call, so staling both cards here would force a needless recompile: about
        # thirty seconds of image quota to change nothing about the face.
        reindex_entity(sid, "character", p.entity_id)
        from app.graph import graph, reindex_edges
        graph.sync_from_store(sid, force=True)
        reindex_edges(sid)
    elif p.entity_type == "character" and p.entity_id in st.characters:
        store.set_answers(sid, p.entity_id, {p.field: str(p.proposed)})
        reindex_entity(sid, "character", p.entity_id)
    elif p.entity_type == "scene" and p.entity_id:
        sc = st.scenes.get(p.entity_id)
        if sc and hasattr(sc, p.field):
            current = getattr(sc, p.field)
            # Append rather than assign for the prose fields. Promoting one
            # extracted fact must not silently delete a synopsis somebody wrote:
            # an accept button that destroys the thing it is adding to is a button
            # nobody presses twice.
            if p.field in ("synopsis", "body") and isinstance(current, str) \
                    and current.strip():
                addition = str(p.proposed).strip()
                if addition and addition not in current:
                    joiner = "\n\n" if p.field == "body" else " "
                    setattr(sc, p.field, current.rstrip() + joiner + addition)
            else:
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
