"""The Style Card. How the film looks and feels, asked once and reused verbatim.

The character interview exists because a character asked no questions comes out
generic. The same is true of a film, and until now nothing asked. `Story.style`
was written by the seed and by nothing else, so any story a user created had an
empty style slot, and the slot the Continuity Pack refuses to drop was the one
slot with nothing in it.

Same mechanism as everywhere else in this product: compile once, store, reuse
verbatim, recompile only when the filmmaker changes it. Never re-derive per call,
because a look re-described before every image is a different look by shot 20.

Seven axes, chosen because each one changes what a model produces and each one is
answerable in a sentence by someone who has not thought about it before:

    medium     what kind of image this is at all, the strongest single lever
    palette    the colours the film lives in
    light      where light comes from and how hard it is
    lens       focal length, depth, how close the camera stands
    mood       what the film feels like before anyone speaks
    era        when it is, which fixes wardrobe, cars and technology
    aspect     the shape of the frame

`medium` is deliberately the same idea as `consistency.STYLE_PRESETS`, which pins
the medium on every image call. The preset is what stops a photoreal story
returning a digital painting; this is the filmmaker's own wording of it.
"""
from __future__ import annotations

import json

from app.store import store

# Asked in this order. Each one is a real question rather than a field label,
# because "palette" produces a blank stare and "what colours does this film live
# in" produces an answer.
AXES: list[dict] = [
    {"key": "medium", "label": "Medium",
     "question": "What kind of images is this?",
     "hint": "photorealistic film still, 35mm",
     "why": "The strongest lever on every frame. Unsaid, the model drifts "
            "between photoreal and illustration."},
    {"key": "palette", "label": "Palette",
     "question": "What colours does this film live in?",
     "hint": "sodium vapour orange on wet blue-black",
     "why": "Named colours carry across shots. Unnamed ones do not."},
    {"key": "light", "label": "Light",
     "question": "Where does light come from, and how hard is it?",
     "hint": "practicals only, fluorescent, no fill",
     "why": "Light is what makes two shots feel like one film."},
    {"key": "lens", "label": "Lens",
     "question": "How close does the camera stand, and on what glass?",
     "hint": "35mm and 50mm, shallow",
     "why": "Focal length decides how the audience sits with a character."},
    {"key": "mood", "label": "Mood",
     "question": "What does it feel like before anyone speaks?",
     "hint": "held breath, small rooms",
     "why": "Reaches the dialogue as well as the images."},
    {"key": "era", "label": "Era",
     "question": "When is it?",
     "hint": "present day",
     "why": "Fixes wardrobe, cars and signage without listing them."},
    {"key": "aspect", "label": "Aspect",
     "question": "What shape is the frame?",
     "hint": "2.39:1",
     "why": "Composition is built to the frame, so changing it reframes "
            "every shot."},
]

KEYS = [a["key"] for a in AXES]

# Free prose alongside the axes. The spec's style card is prose plus axes (§5.4),
# and the prose is where a filmmaker says the thing that does not fit an axis.
PROSE = "look"


def get_style(story_id: str) -> dict:
    """The card as it stands, with every axis present so the client can render a
    complete form rather than only the answered half."""
    st = store.story(story_id)
    style = st.style or {}
    return {
        "axes": [{**a, "value": style.get(a["key"], "")} for a in AXES],
        "look": style.get(PROSE, ""),
        "answered": sum(1 for k in KEYS if style.get(k)),
        "total": len(KEYS),
        # Extra axes somebody added by hand. Kept and shown rather than dropped
        # on the next save, because a filmmaker who invents an axis meant it.
        "extra": {k: v for k, v in style.items()
                  if k not in KEYS and k != PROSE},
    }


def set_style(story_id: str, axes: dict[str, str], look: str | None = None) -> dict:
    """Write the card and reindex it. Typed by a person, so canon immediately.

    Reindexing here rather than in a background pass is invariant one from §4.1:
    a style axis that is not retrievable is a style axis no agent will find.
    """
    from app.bible import reindex_story

    st = store.story(story_id)
    style = dict(st.style or {})
    for k, v in (axes or {}).items():
        v = (v or "").strip()
        if v:
            style[k] = v
        else:
            style.pop(k, None)
    if look is not None:
        look = look.strip()
        if look:
            style[PROSE] = look
        else:
            style.pop(PROSE, None)
    st.style = style
    reindex_story(story_id)
    return get_style(story_id)


def compile_axes(description: str, title: str = "", logline: str = "") -> dict:
    """Turn how a filmmaker actually talks into the seven axes.

    Nobody opens a tool and types "palette: sodium vapour orange against wet
    blue-black". They type "it should feel like a wet night shift". So this reads
    the sentence and proposes the axes, and the filmmaker edits them before
    anything is saved.

    Suggestions only. This never writes. The user reviews and saves, which is what
    keeps §5.1 honest: inference does not become canon on its own.
    """
    from google.genai import types

    from app.gemini_client import TEXT_MODEL, get_client

    resp = get_client().models.generate_content(
        model=TEXT_MODEL,
        contents=(
            "You are a cinematographer and a production designer reading a "
            "director's description of a film, and writing down the specific "
            "decisions it implies.\n\n"
            + (f"Title: {title}\n" if title else "")
            + (f"Logline: {logline}\n" if logline else "")
            + f"\nThe director says:\n{description}\n\n"
            "Return JSON with exactly these keys: "
            + ", ".join(KEYS) + ".\n\n"
            "Each value is one short concrete phrase, not a sentence and not an "
            "adjective on its own. Write what a crew could act on:\n"
            "  medium · the kind of image, for example "
            "\"photorealistic cinematic film still, 35mm\"\n"
            "  palette · named colours in relation to each other\n"
            "  light · sources and hardness\n"
            "  lens · focal lengths and depth\n"
            "  mood · what it feels like before anyone speaks\n"
            "  era · when it is\n"
            "  aspect · a ratio\n\n"
            "Commit to specifics. This card is pasted verbatim into every image "
            "and every line for the whole film, so a vague axis produces a "
            "generic film, which is the failure being prevented. Infer from what "
            "the director said rather than asking for more."
        ),
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            # google-genai 1.2.0 cannot disable thinking, and reasoning tokens
            # come out of this budget, so it is set well above what the answer
            # needs.
            max_output_tokens=4096,
        ),
    )
    data = json.loads(resp.text)
    return {k: str(data.get(k, "")).strip() for k in KEYS}
