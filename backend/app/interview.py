"""The filmmaker interview. One question at a time, every answer written to canon.

Everything downstream needs the same three things: what the film is, how it looks,
and who is in it. Until now each lived behind a different tab with a different
form, and the only way to get a complete story into the system was to know which
tab wrote which field. A filmmaker opening this for the first time had nowhere to
start.

So this is the front door. It computes the next unanswered question from the state
of the story rather than walking a fixed wizard, which means:

  * a half filled story resumes exactly where it stopped
  * answering out of order is fine, and skipping is fine
  * adding a character adds twelve questions to the end, without a step counter
    anywhere needing to know that happened

Every answer is written the moment it is given, through the same paths the tabs
use, so it is canon and it is retrievable immediately. Nothing is staged and there
is no submit at the end to lose.
"""
from __future__ import annotations

from app import questions as Q
from app.store import store
from app.style_card import AXES, PROSE

SECTIONS = [
    {"key": "story", "label": "The film"},
    {"key": "look", "label": "The look"},
    {"key": "cast", "label": "The cast"},
]

# Asked before the axes. Most people can describe a film in a sentence and cannot
# fill in "palette", so this comes first and the axes are suggested from it.
LOOK_OPENER = {
    "id": "look:freeform",
    "section": "look",
    "question": "Describe how the film should look and feel.",
    "hint": "One or two sentences is enough. The next questions get suggested "
            "from this.",
    "placeholder": "a wet night shift, nobody sleeping, everything lit by the "
                   "machines",
    "kind": "long",
    "suggests": True,
}


def _step(**kw) -> dict:
    base = {"hint": "", "placeholder": "", "kind": "text", "optional": False,
            "suggests": False, "value": "", "answered": False}
    return {**base, **kw}


def script(story_id: str) -> list[dict]:
    """Every question, with what is already answered filled in."""
    st = store.story(story_id)
    style = st.style or {}
    steps: list[dict] = [
        _step(id="story:title", section="story",
              question="What is your film called?",
              placeholder="The Night Route",
              value=st.title if st.title != "Untitled" else "",
              answered=bool(st.title and st.title != "Untitled")),
        _step(id="story:logline", section="story",
              question="What happens in it?",
              hint="One sentence. Who wants what, and what is in the way.",
              placeholder="A depot dispatcher learns the night route is being "
                          "cut, and says nothing to the driver who has run it "
                          "for twenty-two years.",
              kind="long", value=st.logline, answered=bool(st.logline)),
        _step(**LOOK_OPENER, value=style.get(PROSE, ""),
              answered=bool(style.get(PROSE)), optional=True),
    ]

    for a in AXES:
        steps.append(_step(
            id=f"look:{a['key']}", section="look",
            question=a["question"], hint=a["why"], placeholder=a["hint"],
            label=a.get("label", a["key"]),
            value=style.get(a["key"], ""), answered=bool(style.get(a["key"]))))

    cast = list(st.characters.values())
    steps.append(_step(
        id="cast:names", section="cast",
        question="Who is in it?",
        hint="Names only, one per line. You can add more later.",
        placeholder="Maya Raghavan\nRavi Menon",
        kind="list",
        value="\n".join(c.name for c in cast), answered=bool(cast)))

    # Twelve core questions per character. Core only, deliberately: they are what
    # gate a character as usable for dialogue, and the other 88 belong in the Cast
    # tab where somebody is choosing to go deep rather than being kept from
    # finishing.
    for c in cast:
        for i, q in enumerate(Q.core_questions()):
            steps.append(_step(
                id=f"char:{c.id}:{i}", section="cast",
                question=q["text"], hint=f"{c.name} · {q.get('part_label', '')}",
                who=c.name, who_id=c.id,
                value=c.answers.get(q["text"], ""),
                answered=bool(c.answers.get(q["text"]))))
    return steps


def state(story_id: str) -> dict:
    steps = script(story_id)
    st = store.story(story_id)
    done = sum(1 for s in steps if s["answered"])
    nxt = next((s["id"] for s in steps if not s["answered"]), None)
    by_section = []
    for sec in SECTIONS:
        mine = [s for s in steps if s["section"] == sec["key"]]
        by_section.append({**sec, "done": sum(1 for s in mine if s["answered"]),
                           "total": len(mine)})
    return {
        "story": {"id": st.id, "title": st.title, "logline": st.logline},
        "steps": steps, "answered": done, "total": len(steps),
        "next": nxt, "complete": nxt is None, "sections": by_section,
    }


def answer(story_id: str, step_id: str, value: str) -> dict:
    """Write one answer through the same path its tab would use.

    Returns the new state, so the client never has to work out what changed or
    how many questions now exist. Adding two characters adds twenty four
    questions, and the client just re-renders.
    """
    from app.bible import reindex_entity, reindex_story
    from app.style_card import set_style

    st = store.story(story_id)
    kind, _, rest = step_id.partition(":")
    value = (value or "").strip()

    if kind == "story":
        if rest == "title" and value:
            st.title = value
        elif rest == "logline":
            st.logline = value
        reindex_story(story_id)

    elif kind == "look":
        if rest == "freeform":
            set_style(story_id, {}, value)
        else:
            set_style(story_id, {rest: value})

    elif kind == "cast" and rest == "names":
        wanted = [n.strip() for n in value.replace(",", "\n").splitlines()
                  if n.strip()]
        for i, name in enumerate(wanted):
            if st.character_by_name(name):
                continue
            c = store.add_character(story_id, name,
                                    role="lead" if i == 0 else "supporting")
            c.aliases = [name.split()[0]]
            reindex_entity(story_id, "character", c.id)

    elif kind == "char":
        cid, _, idx = rest.partition(":")
        core = Q.core_questions()
        if cid in st.characters and idx.isdigit() and int(idx) < len(core):
            # Through set_answers rather than by touching the dict, so a change
            # bumps canon_version and stales the compiled cards. That staling is
            # invariant two (§4.1), and skipping it would leave a corrected fact
            # producing the old face and the old voice forever.
            store.set_answers(story_id, cid, {core[int(idx)]["text"]: value})
            reindex_entity(story_id, "character", cid)

    return state(story_id)


def new_story(title: str = "Untitled") -> str:
    """Start a fresh film and make it the one every tab is looking at."""
    from app.bible import reindex_story

    st = store.create_story(title or "Untitled", "")
    store.default_story_id = st.id
    reindex_story(st.id)
    return st.id
