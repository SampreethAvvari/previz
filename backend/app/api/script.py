"""Script: the screenplay, and dialogue with the voice referee.

OWNER: Sampreeth. `app/voice.py` is the engine.

The load bearing detail is in `write_exchange`, and it was found by getting it
wrong: `scene` is shared with every character sub-agent, so it must contain
nothing any character in it does not know. Secrets go in that character's `knows`
list, never in the scene brief. A first run put "Maya already knew and did not
tell him" in the brief, and Ravi accused her of it on his third line, because he
read it there. The knowledge horizon is only as tight as the text around it.

So this endpoint builds the brief from the scene's *slugline and synopsis* and
passes per character knowledge separately, from `character.knows_by(scene)`.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.bible import build_pack, reindex_entity
from app.sse import stream
from app.store import scene_json, store

router = APIRouter()


def _sid(story_id: str | None) -> str:
    try:
        return store.story(story_id).id
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc


class DialogueIn(BaseModel):
    turns: int = 4
    brief: str = ""          # overrides the scene synopsis if given
    character_ids: list[str] = []


@router.post("/scenes/{number}/dialogue")
def write_dialogue(number: int, body: DialogueIn, story_id: str | None = None):
    """One sub-agent per character present, each speaking from its own card.

    No single agent holds every character. That is what makes the voices
    genuinely separate rather than one model doing impressions of several people.
    """
    sid = _sid(story_id)
    st = store.story(sid)
    sc = st.scene_by_number(number)
    if not sc:
        raise HTTPException(404, f"no scene {number}")

    ids = body.character_ids or sc.characters
    present = [st.characters[c] for c in ids if c in st.characters]
    if not present:
        raise HTTPException(400, "no characters in this scene")

    def work(emit):
        from app.voice import VoiceCard, compile_voice_card, embed_text, write_exchange

        cards, refused = [], []
        for c in present:
            if c.core_answered < 12:
                # Refuse rather than invent a person. §9.2.
                refused.append(c.name)
                emit.violation(
                    "incomplete_character",
                    f"{c.name} has {c.core_answered} of 12 core answers. "
                    f"Writing their dialogue would be inventing them, not "
                    f"writing them. Open the interview.")
                continue
            if not c.voice_card:
                emit.thinking(f"{c.name} has no Voice Card yet, compiling one",
                              agent="DialogueCoach")
                vc = compile_voice_card(c.name, c.answers, c.canon_version)
                c.voice_card = {"card": vc.card, "register": vc.register,
                                "phrases": vc.phrases,
                                "never_says": vc.never_says,
                                "samples": vc.samples,
                                "embedding": vc.embedding,
                                "canon_version": c.canon_version}
                reindex_entity(sid, "character", c.id)
            d = c.voice_card
            card = VoiceCard(name=c.name, card=d["card"],
                             register=d.get("register", {}),
                             phrases=d.get("phrases", []),
                             never_says=d.get("never_says", []),
                             samples=d.get("samples", []),
                             embedding=d.get("embedding"),
                             canon_version=d.get("canon_version", 1))
            if card.embedding is None and card.samples:
                # Fingerprint the samples now. Without it there is no referee, and
                # a referee that cannot score is reported, not faked.
                vecs = embed_text(card.samples)
                card.embedding = [sum(x) / len(x) for x in zip(*vecs)]
                c.voice_card["embedding"] = card.embedding
            cards.append(card)

        if not cards:
            raise RuntimeError(
                f"no character in scene {number} has the 12 core answers "
                f"needed to write dialogue: {', '.join(refused)}")

        # The brief is what a camera in the room could see. Nothing private.
        brief = body.brief or f"{sc.slugline}. {sc.synopsis}"
        by_name = {c.name: c for c in present}
        knows = {card.name: by_name[card.name].knows_by(number)
                 for card in cards if card.name in by_name}
        states = {}
        for card in cards:
            ch = by_name.get(card.name)
            cont = sc.continuity.get(ch.id) if ch else None
            if cont:
                states[card.name] = "; ".join(
                    v for v in (cont.get("physical"), cont.get("emotional"))
                    if v)

        pack = build_pack(sid, query=brief, character_ids=[c.id for c in present],
                          scene_number=number)
        emit.context(pack.report()["slots"], pack.chunk_ids, pack.dropped)
        for card in cards:
            emit.thinking(
                f"{card.name}: sub-agent built from Voice Card v"
                f"{card.canon_version}, verbatim. Knows "
                f"{len(knows.get(card.name, []))} facts as of scene {number}.",
                agent="DialogueDirector")

        lines = write_exchange(cards, brief, knows, states, turns=body.turns)
        for ln in lines:
            emit.line_ready(ln)
            if ln.get("passed") is False:
                emit.violation("voice_drift",
                               f"{ln['character']}: {ln.get('reason','')}")

        # Append to the scene body in screenplay form and reindex, so the next
        # call to this scene reads what this one wrote.
        block = "\n".join(f"{ln['character'].upper()}\n{ln['line']}\n"
                          for ln in lines if ln["line"] != "[says nothing]")
        if block:
            sc.body = (sc.body + "\n\n" + block).strip()
            sc.status = "written"
            reindex_entity(sid, "scene", sc.id)
        return {"lines": lines, "scene": scene_json(sc), "refused": refused}

    return stream(work, agent="DialogueDirector")


class ActionIn(BaseModel):
    intent: str = ""


@router.post("/scenes/{number}/action")
def write_action(number: int, body: ActionIn, story_id: str | None = None):
    """Exactly one action paragraph. Enforced by response schema, not by asking.

    That is the whole mechanism behind "no slop": a model given a
    `{"action": string}` schema cannot return three paragraphs and a scene
    heading, however much it would like to.
    """
    sid = _sid(story_id)
    st = store.story(sid)
    sc = st.scene_by_number(number)
    if not sc:
        raise HTTPException(404, f"no scene {number}")

    def work(emit):
        from google.genai import types

        from app.consistency import _SAFETY, _client
        from app.voice import REASONING_MODEL

        pack = build_pack(sid, query=body.intent or sc.synopsis,
                          character_ids=sc.characters, scene_number=number)
        emit.context(pack.report()["slots"], pack.chunk_ids, pack.dropped)
        emit.thinking("one action paragraph, present tense, only what a camera "
                      "sees", agent="ActionWriter")
        resp = _client().models.generate_content(
            model=REASONING_MODEL,
            contents=(
                "You are writing screenplay action. Present tense. Only what a "
                "camera could see or a microphone could hear. No interiority, no "
                "adverbs doing the work a verb should do, no camera directions.\n\n"
                f"{pack.text()}\n\n"
                f"SCENE {number}: {sc.slugline}\n{sc.synopsis}\n"
                + (f"\nSCENE SO FAR:\n{sc.body[-1200:]}" if sc.body else "")
                + (f"\n\nWHAT THIS PARAGRAPH MUST DO: {body.intent}"
                   if body.intent else "")
                + "\n\nReturn JSON {\"action\": \"...\"} with EXACTLY ONE "
                  "paragraph, at most four lines."),
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema={"type": "object",
                                 "properties": {"action": {"type": "string"}},
                                 "required": ["action"]},
                safety_settings=_SAFETY),
        )
        import json as _json
        action = _json.loads(resp.text)["action"].strip()
        emit.partial("action", action)
        sc.body = (sc.body + "\n\n" + action).strip()
        sc.status = "written"
        reindex_entity(sid, "scene", sc.id)
        return {"action": action, "scene": scene_json(sc)}

    return stream(work, agent="ActionWriter")


@router.post("/scenes/{number}/supervise")
def supervise(number: int, story_id: str | None = None):
    """ScriptSupervisor: check what is written against canon and the horizon.

    Findings come back as proposals and violations, never as edits. The user
    decides. §5.1.
    """
    sid = _sid(story_id)
    st = store.story(sid)
    sc = st.scene_by_number(number)
    if not sc:
        raise HTTPException(404, f"no scene {number}")
    if not sc.body.strip():
        raise HTTPException(400, "nothing written in this scene yet")

    def work(emit):
        import json as _json

        from google.genai import types

        from app.consistency import _SAFETY, _client
        from app.voice import REASONING_MODEL

        horizon = {st.characters[c].name: st.characters[c].knows_by(number)
                   for c in sc.characters if c in st.characters}
        pack = build_pack(sid, query=sc.synopsis,
                          character_ids=sc.characters, scene_number=number)
        emit.context(pack.report()["slots"], pack.chunk_ids, pack.dropped)
        emit.thinking("checking for knowledge violations, prop and wardrobe "
                      "contradictions, and time of day mismatches",
                      agent="ScriptSupervisor")
        resp = _client().models.generate_content(
            model=REASONING_MODEL,
            contents=(
                "You are a script supervisor. Find continuity errors in this "
                "scene against established canon. Be specific and be strict, but "
                "do not invent problems: an empty list is a valid answer.\n\n"
                f"{pack.text()}\n\n"
                f"WHAT EACH CHARACTER KNOWS AS OF SCENE {number}:\n"
                f"{_json.dumps(horizon, indent=1)}\n\n"
                f"SCENE {number} AS WRITTEN:\n{sc.body[:4000]}\n\n"
                'Return JSON {"findings": [{"kind": '
                '"knowledge|prop|wardrobe|time|voice", "detail": "...", '
                '"quote": "the exact text at fault"}]}'),
            config=types.GenerateContentConfig(
                response_mime_type="application/json", safety_settings=_SAFETY),
        )
        findings = _json.loads(resp.text).get("findings", [])
        for f in findings:
            emit.violation(f.get("kind", "unknown"), f.get("detail", ""))
            p = store.propose(sid, "scene", sc.id, "continuity",
                              f.get("quote", ""), f.get("detail", ""),
                              "ScriptSupervisor")
            emit.proposal(p.id, "continuity", f.get("detail", ""))
        return {"findings": findings, "clean": not findings}

    return stream(work, agent="ScriptSupervisor")
