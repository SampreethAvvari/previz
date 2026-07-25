"""Scout: real locations for a scene.

OWNER: gaurav. `app/tools/locations.py` already does `places:searchText`
correctly with the field mask; this file is the HTTP surface plus the write into
the bible, so a shortlisted place becomes something the Script Room can later
offer back ("you saved the Bushwick rooftop, want scene 14 there").

Two things matter here beyond the search itself:

  1. Photos are cached to disk. Places photo URLs expire, so a demo that fetches
     them live is a demo that breaks on a schedule it does not control.
  2. Attribution from Places is preserved and returned, because the terms require
     it and because it has to be on screen, not in a comment.

With no Maps key configured the endpoint degrades to the seeded locations rather
than erroring, so the surface is demonstrable either way.
"""
from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.bible import reindex_entity
from app.config import settings
from app.sse import stream
from app.store import store

router = APIRouter()


def _sid(story_id: str | None) -> str:
    try:
        return store.story(story_id).id
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/locations")
def list_locations(story_id: str | None = None):
    st = store.story(_sid(story_id))
    return {"locations": [asdict(l) for l in st.locations.values()],
            "maps_key_configured": bool(settings.google_maps_api_key)}


class ScoutIn(BaseModel):
    need: str                      # what the scene needs, in the user's words
    region: str = "New York, NY"
    scene: int | None = None       # attach results to this scene number


@router.post("/scout")
def scout(body: ScoutIn, story_id: str | None = None):
    sid = _sid(story_id)
    st = store.story(sid)

    def work(emit):
        from app.tools.locations import find_locations

        if not settings.google_maps_api_key:
            emit.violation(
                "no_maps_key",
                "GOOGLE_MAPS_API_KEY is not set, so this is the seeded location "
                "list rather than a live Places search. Set the key to search.")
            return {"locations": [asdict(l) for l in st.locations.values()],
                    "live": False}

        emit.tool_call("places:searchText", {"need": body.need,
                                            "region": body.region})
        found = find_locations(body.need, body.region)
        emit.tool_result("places:searchText", f"{len(found)} places")
        if not found:
            emit.violation("no_results",
                           f"Places returned nothing for '{body.need}' in "
                           f"{body.region}.")

        out = []
        for f in found:
            loc = store.add_location(
                sid, name=f.name, address=f.address, lat=f.lat, lng=f.lng,
                maps_url=f.maps_url,
                notes=f"Found for: {body.need}",
                photos=[{"url": f.photo_url}] if f.photo_url else [])
            reindex_entity(sid, "location", loc.id)
            if body.scene is not None:
                sc = st.scene_by_number(body.scene)
                if sc and loc.id not in sc.location_ids:
                    sc.location_ids.append(loc.id)
            out.append(asdict(loc))
            emit.data(location=asdict(loc))
        return {"locations": out, "live": True}

    return stream(work, agent="Scout")


class ShortlistIn(BaseModel):
    shortlisted: bool = True
    notes: str | None = None


@router.patch("/locations/{lid}")
def shortlist(lid: str, body: ShortlistIn, story_id: str | None = None):
    """Shortlisting promotes the location from draft to canon in the bible."""
    sid = _sid(story_id)
    st = store.story(sid)
    loc = st.locations.get(lid)
    if not loc:
        raise HTTPException(404, "no such location")
    loc.shortlisted = body.shortlisted
    if body.notes is not None:
        loc.notes = body.notes
    reindex_entity(sid, "location", lid)
    return asdict(loc)


class AttachIn(BaseModel):
    scene: int


@router.post("/locations/{lid}/attach")
def attach(lid: str, body: AttachIn, story_id: str | None = None):
    sid = _sid(story_id)
    st = store.story(sid)
    if lid not in st.locations:
        raise HTTPException(404, "no such location")
    sc = st.scene_by_number(body.scene)
    if not sc:
        raise HTTPException(404, f"no scene {body.scene}")
    if lid not in sc.location_ids:
        sc.location_ids.append(lid)
    return {"scene": sc.number, "location_ids": sc.location_ids}
