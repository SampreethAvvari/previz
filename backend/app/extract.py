"""Fact extraction into the approval queue (design spec §5.1).

The Canon strip only means something when there is something in it, and the two
layer model only means something when agents actually use the queue. So this reads
a scene and proposes what it establishes: facts, and who learned them and when.

**Nothing here writes canon.** Every result lands in `fact_proposals` with the
agent that produced it and the reasoning that produced it. A person promotes. That
is the whole point of §5.1, and it is the reason an agent can be aggressive here:
a wrong proposal costs one click, while a wrong write costs the story.

Two paths, and the fallback is not decoration. The lab project is shared with
every other team in the room and the venue wifi is a live risk today, so when the
model is unreachable the extractor still produces proposals from the scene text
deterministically, labelled as such. An empty queue on stage would look like a
feature that does not exist rather than a network that is down.
"""
from __future__ import annotations

import json
import re

from app.store import Scene, Story, store

AGENT = "Archivist"

_SENT = re.compile(r"(?<=[.!?])\s+")


def _loads_salvaging(text: str) -> dict:
    """Parse the response, keeping whatever survived a truncation.

    google-genai 1.2.0 cannot turn thinking off, so reasoning tokens come out of
    the same budget as the answer and a long extraction can be cut mid object.
    Four complete facts and a severed fifth is a useful result, and throwing the
    whole response away because of the fifth is not. So on a decode failure the
    text is trimmed back to the last complete object and the brackets are closed.
    """
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text[text.find("{"):]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    cut = text.rfind("},")
    if cut == -1:
        cut = text.rfind("}")
    if cut == -1:
        raise
    try:
        return json.loads(text[:cut + 1].rstrip(",") + "]}")
    except json.JSONDecodeError:
        # One more level up: the object we kept may itself have been inside a
        # partly written array element.
        return json.loads(text[:text.rfind("{")].rstrip(", \n") + "]}")


def _facts_from_model(st: Story, sc: Scene, present: list[str]) -> list[dict]:
    """Ask for facts, with a response schema so the shape is enforced rather than
    requested. Raises on any failure, and the caller falls back."""
    from google.genai import types

    from app.gemini_client import TEXT_MODEL, get_client

    resp = get_client().models.generate_content(
        model=TEXT_MODEL,
        contents=(
            "You are the archivist on a film production, reading one scene and "
            "recording what it establishes as true.\n\n"
            f"Story: {st.title}. {st.logline}\n"
            f"Scene {sc.number}: {sc.slugline}\n"
            f"Synopsis: {sc.synopsis}\n"
            f"Text:\n{sc.body[:4000] or '(not written yet, use the synopsis)'}\n\n"
            f"Characters present: {', '.join(present) or 'unknown'}\n\n"
            "Return JSON: {\"facts\": [{\"fact\": ..., \"learned_by\": ..., "
            "\"rationale\": ...}]}\n\n"
            "  fact · one specific thing this scene establishes, written as a "
            "complete sentence that will still make sense read on its own in six "
            "weeks. Not a summary of the scene. Not a feeling.\n"
            "  learned_by · the name of the character who learns it IN THIS "
            "SCENE, exactly as written above. Use \"\" if it is true of the world "
            "rather than learned by someone.\n"
            "  rationale · the line or action in the scene that establishes it. "
            "A person is about to read this and decide whether to accept it, so "
            "point at the evidence rather than restating the fact.\n\n"
            "Three to six facts. Only what the scene actually establishes: an "
            "invented fact that gets accepted becomes canon and poisons every "
            "generation after it."
        ),
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            # No thinking_config here. The installed google-genai is 1.2.0, whose
            # ThinkingConfig takes only `include_thoughts`, so passing
            # thinking_budget raises a pydantic ValidationError before the request
            # is ever sent. Raising max_output_tokens instead, since reasoning
            # tokens come out of the same budget and a truncated response is a
            # JSONDecodeError rather than a short answer.
            max_output_tokens=8192,
        ),
    )
    data = _loads_salvaging(resp.text)
    out = []
    for f in data.get("facts", []):
        text = (f.get("fact") or "").strip()
        if text:
            out.append({"fact": text,
                        "learned_by": (f.get("learned_by") or "").strip(),
                        "rationale": (f.get("rationale") or "").strip()
                                     or "extracted from the scene text",
                        "source": "model"})
    return out


def _facts_from_text(sc: Scene, present: list[str]) -> list[dict]:
    """The offline path. Sentences from the scene, attributed to whoever is in it.

    Deliberately dumb. It is not pretending to understand the scene, it is putting
    the scene's own sentences in front of a person to accept or reject, which is
    still the correct mechanism with none of the network.
    """
    source = sc.body.strip() or sc.synopsis.strip()
    out = []
    for s in _SENT.split(source):
        s = s.strip()
        if len(s) < 25 or s.isupper():        # skip sluglines and shouted cues
            continue
        named = [p for p in present if p.split()[0].lower() in s.lower()]
        out.append({
            "fact": s.rstrip(".") + ".",
            "learned_by": named[0] if named else "",
            "rationale": ("Taken verbatim from the text of scene "
                          f"{sc.number}. No model was reachable, so this is the "
                          "scene's own sentence rather than an extraction."),
            "source": "text",
        })
        if len(out) >= 5:
            break
    return out


def extract_scene(story_id: str, scene_number: int, emit=None) -> dict:
    """Propose what a scene establishes. Returns a summary, writes proposals.

    `emit` is the SSE writer when this is streamed, and None when it is called
    directly. Every proposal is announced, so the Canon strip fills in front of
    the user rather than after a silence.
    """
    st = store.story(story_id)
    sc = st.scene_by_number(scene_number)
    if not sc:
        raise KeyError(f"no scene {scene_number}")

    present = [st.characters[cid].name for cid in sc.characters
               if cid in st.characters]
    if emit:
        emit.thinking(f"reading scene {sc.number} · {sc.slugline}", AGENT)

    mode = "model"
    try:
        facts = _facts_from_model(st, sc, present)
        if not facts:
            raise ValueError("model returned no facts")
    except Exception as exc:                            # noqa: BLE001
        mode = "text"
        if emit:
            emit.thinking(
                f"model unavailable ({type(exc).__name__}), reading the scene "
                f"text instead", AGENT)
        facts = _facts_from_text(sc, present)

    made = []
    for f in facts:
        who = st.character_by_name(f["learned_by"]) if f["learned_by"] else None
        if who:
            # A fact somebody learns is a horizon edge, so it is proposed against
            # that character with `knows` as the field. Promotion appends it with
            # this scene as `since_scene`, which is what stops them referring to
            # it in any earlier scene.
            p = store.propose(story_id, "character", who.id, "knows",
                              {"fact": f["fact"], "since_scene": sc.number},
                              f["rationale"], AGENT)
        else:
            # True of the world rather than learned by anyone, so it belongs to
            # the scene's synopsis.
            p = store.propose(story_id, "scene", sc.id, "synopsis", f["fact"],
                              f["rationale"], AGENT)
        made.append(p)
        if emit:
            emit.proposal(p.id, p.field, f"{f['fact']} · {f['rationale']}")

    if emit:
        emit.thinking(
            f"{len(made)} proposal(s) queued. Nothing is canon until you promote "
            f"it.", AGENT)
    return {"scene": sc.number, "mode": mode, "proposed": len(made),
            "proposals": [p.id for p in made],
            "characters_present": present}
