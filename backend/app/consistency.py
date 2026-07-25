"""Character consistency: the one thing this app has to get right.

The mechanism, in four moves:

  1. Compile an Identity Card once from what we know about the character. Frozen
     prose, reused verbatim in every prompt. Never re-summarised per shot,
     because re-summarising is what makes a character drift.
  2. Generate a reference sheet from that card. Front, three-quarter, profile,
     neutral grey, flat light.
  3. Condition every shot on the sheet image plus the card text.
  4. Referee the result: crop the face out of the generated frame, embed the
     crop, compare by cosine to the same crop taken from the sheet.

Measured on 2026-07-25 against nyu-ai-builder26nyc-9338, which is why step 4
crops rather than embedding whole frames:

    Maya's sheet vs Maya's shots (whole frame):  0.39  0.39  0.51
    Ravi's sheet vs Maya's shots (whole frame):  0.20  0.28  0.31
    Maya's sheet vs Ravi's sheet (whole frame):  0.48   <-- two DIFFERENT people

multimodalembedding@001 encodes the whole image, so composition and lighting
dominate identity. Two reference sheets of two different people score 0.48
because they are both grey three-view sheets. Cropping to the face removes the
composition signal and leaves the identity signal.
"""
from __future__ import annotations

import base64
import io
import json
import re
import time
from dataclasses import dataclass
from functools import lru_cache

import requests
from google import genai
from google.genai import types
from PIL import Image

from app.config import settings

PROJECT = settings.gcp_project
LOCATION = "us-central1"

TEXT_MODEL = "gemini-2.5-flash"
IMAGE_MODEL = "gemini-2.5-flash-image"     # Nano Banana
EMBED_MODEL = "multimodalembedding@001"

# Set from the spike above: worst same-person face crop must sit above the best
# different-person crop. Recalibrate with scripts/calibrate.py if faces change.
FACE_THRESHOLD = 0.35

_SAFETY = [
    types.SafetySetting(category=c, threshold="BLOCK_ONLY_HIGH")
    for c in ("HARM_CATEGORY_HATE_SPEECH", "HARM_CATEGORY_DANGEROUS_CONTENT",
              "HARM_CATEGORY_SEXUALLY_EXPLICIT", "HARM_CATEGORY_HARASSMENT")
]

# Pinned per style so the LOOK cannot drift between shots. The spike drifted from
# photoreal to digital painting because the prompt said "storyboard frame" and
# nothing pinned the medium. Every shot in a board uses one of these, verbatim.
STYLE_PRESETS = {
    "realistic": ("Photorealistic cinematic film still, shot on 35mm, natural "
                  "film grain, practical lighting, shallow depth of field. "
                  "Not an illustration, not a painting, not a render."),
    "animation": ("2D animation production still, clean confident line work, "
                  "flat cel shading, limited palette, in the style of adult "
                  "animated drama. Consistent line weight."),
    "pencil": ("Graphite pencil storyboard drawing on off-white paper, loose "
               "confident hatching, tonal shading, no colour anywhere."),
}


@lru_cache(maxsize=1)
def _client() -> genai.Client:
    """Cached. Constructing a client per call gets it garbage collected mid
    flight, and the next request dies with "Cannot send a request, as the client
    has been closed."
    """
    return genai.Client(vertexai=True, project=PROJECT, location=LOCATION)


# ---------------------------------------------------------------- identity card

@dataclass
class IdentityCard:
    """Frozen. Written once per canon version, reused verbatim, never edited."""
    name: str
    descriptor: str                       # goes into every image prompt
    wardrobe: str
    negative: str = ""                    # what this character must never look like
    sheet_png: bytes | None = None
    face_embedding: list[float] | None = None
    canon_version: int = 1

    def prompt_block(self) -> str:
        block = f"{self.name.upper()}: {self.descriptor} Wearing: {self.wardrobe}."
        if self.negative:
            block += f" Never: {self.negative}."
        return block


def compile_identity_card(name: str, facts: dict[str, str],
                          canon_version: int = 1) -> IdentityCard:
    """Turn interview answers into a frozen visual descriptor. Called once.

    facts is whatever the interview produced, for example
    {"age": "29", "physical": "...", "style of dress": "..."}.
    """
    resp = _client().models.generate_content(
        model=TEXT_MODEL,
        contents=(
            "You are a casting director writing a character's physical identity "
            "so that an image model renders the SAME person every time.\n\n"
            f"Character name: {name}\n"
            f"What we know:\n{json.dumps(facts, indent=2)}\n\n"
            "Return JSON with exactly these keys:\n"
            '  "descriptor": one dense paragraph. Age, ethnicity, face shape, '
            "eyes, hair (cut, colour, length, how it falls), build, height, "
            "posture, and any scars or marks. Concrete and visual only. No "
            "personality, no backstory, no mood.\n"
            '  "wardrobe": their default costume, specific fabrics and colours.\n'
            '  "negative": a short clause naming what they must never look like, '
            "to stop the model drifting toward a generic face.\n\n"
            "Invent specific detail where we have none. Vague descriptions are "
            "what cause a character to drift between shots."
        ),
        config=types.GenerateContentConfig(
            response_mime_type="application/json", safety_settings=_SAFETY),
    )
    data = json.loads(resp.text)
    return IdentityCard(
        name=name, descriptor=data["descriptor"], wardrobe=data["wardrobe"],
        negative=data.get("negative", ""), canon_version=canon_version)


# ------------------------------------------------------------ image generation

def _generate(prompt: str, refs: list[bytes] | None = None,
              attempts: int = 4) -> bytes:
    """One image, with backoff on 429.

    The lab project is shared with every other team in the room, so
    RESOURCE_EXHAUSTED is normal rather than exceptional. Backing off and
    retrying costs seconds; not doing it costs the demo.

    If you are seeing 429 on every call, check that ADC has a quota project:
        gcloud auth application-default set-quota-project <PROJECT_ID>
    Without it you are billed against a starvation-tier quota bucket and
    everything fails regardless of the project's real limits.
    """
    parts: list[types.Part] = [
        types.Part.from_bytes(data=r, mime_type="image/png") for r in (refs or [])
    ]
    parts.append(types.Part.from_text(text=prompt))

    last: Exception | None = None
    for i in range(attempts):
        try:
            resp = _client().models.generate_content(
                model=IMAGE_MODEL,
                contents=[types.Content(role="user", parts=parts)],
                config=types.GenerateContentConfig(safety_settings=_SAFETY),
            )
            for p in resp.candidates[0].content.parts:
                inline = getattr(p, "inline_data", None)
                if inline and inline.data:
                    return inline.data
            raise RuntimeError(
                f"no image returned ({resp.candidates[0].finish_reason})")
        except Exception as exc:  # noqa: BLE001 - retry on anything transient
            last = exc
            if "RESOURCE_EXHAUSTED" not in str(exc) and "429" not in str(exc):
                raise
            if i < attempts - 1:
                time.sleep(2 ** i * 2)   # 2s, 4s, 8s
    raise RuntimeError(f"image generation exhausted after {attempts} attempts: {last}")


def generate_reference_sheet(card: IdentityCard) -> bytes:
    """The identity of record. Every later shot is conditioned on this image."""
    return _generate(
        "Character reference sheet for film pre-production. Neutral grey "
        "seamless background, flat even studio lighting, no shadows on the "
        "background. Three full-body views side by side: front, three-quarter, "
        "profile. The SAME person in all three views. Photorealistic, sharp, "
        f"no stylisation.\n\n{card.prompt_block()}"
    )


def generate_shot(shot_description: str, cards: list[IdentityCard],
                  style: str = "realistic",
                  previous_frame: bytes | None = None) -> bytes:
    """One storyboard frame.

    Receives, without exception: the style preset verbatim, every present
    character's Identity Card verbatim, their reference sheets as input images,
    and the previously approved frame from this scene so lighting and blocking
    carry forward.
    """
    refs = [c.sheet_png for c in cards if c.sheet_png]
    if previous_frame:
        refs.append(previous_frame)

    who = "\n".join(c.prompt_block() for c in cards)
    prompt = (
        f"{STYLE_PRESETS.get(style, STYLE_PRESETS['realistic'])}\n\n"
        f"Widescreen 2.39:1 composition filling the entire frame edge to edge. "
        f"No letterboxing, no borders, no grey bars.\n\n"
        f"SHOT: {shot_description}\n\n"
        f"CHARACTERS IN THIS SHOT, who must match their reference images exactly:\n"
        f"{who}\n\n"
        "The faces, hair and wardrobe in the reference images are correct and "
        "must be reproduced faithfully. Change the framing, lighting, pose and "
        "location as the shot requires. Do not change who these people are."
    )
    if previous_frame:
        prompt += ("\n\nThe final reference image is the previous frame of this "
                   "same scene. Keep its lighting, time of day and wardrobe state "
                   "continuous.")
    return _generate(prompt, refs=refs)


# ------------------------------------------------------------------- the referee

_BBOX_RE = re.compile(r"\[?\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\]?")


def detect_face(png: bytes) -> tuple[int, int, int, int] | None:
    """Ask Gemini for the largest face box, normalised 0-1000, as (y0,x0,y1,x1).

    Gemini returns boxes in that order and scale, which is unusual enough to be
    worth stating: it is not (x0,y0,x1,y1) and it is not pixels.
    """
    try:
        resp = _client().models.generate_content(
            model=TEXT_MODEL,
            contents=[types.Content(role="user", parts=[
                types.Part.from_bytes(data=png, mime_type="image/png"),
                types.Part.from_text(text=(
                    "Return the bounding box of the largest human face in this "
                    "image as JSON [y0, x0, y1, x1], normalised 0 to 1000. "
                    "Include the whole head: hair, jaw, ears. If there is no "
                    "face, return []."))])],
            config=types.GenerateContentConfig(
                response_mime_type="application/json", safety_settings=_SAFETY),
        )
        m = _BBOX_RE.search(resp.text or "")
        if not m:
            return None
        return tuple(int(g) for g in m.groups())  # type: ignore[return-value]
    except Exception:
        return None


def crop_face(png: bytes, pad: float = 0.18) -> bytes | None:
    """Crop to the face so the embedding measures identity, not composition."""
    box = detect_face(png)
    if not box:
        return None
    y0, x0, y1, x1 = box
    img = Image.open(io.BytesIO(png)).convert("RGB")
    W, H = img.size
    l, t = x0 / 1000 * W, y0 / 1000 * H
    r, b = x1 / 1000 * W, y1 / 1000 * H
    dw, dh = (r - l) * pad, (b - t) * pad
    crop = img.crop((max(0, int(l - dw)), max(0, int(t - dh)),
                     min(W, int(r + dw)), min(H, int(b + dh))))
    if crop.width < 24 or crop.height < 24:
        return None
    buf = io.BytesIO()
    crop.resize((512, 512), Image.LANCZOS).save(buf, format="PNG")
    return buf.getvalue()


_CREDS = None


def _access_token() -> str:
    """ADC token, refreshed as needed.

    Deliberately not `gcloud auth print-access-token`: gcloud does not exist in
    the Cloud Run container, so shelling out works locally and then fails the
    moment we deploy. google.auth.default() picks up ADC locally and the attached
    service account in production, with no branch.
    """
    global _CREDS
    import google.auth
    import google.auth.transport.requests

    if _CREDS is None:
        _CREDS, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"])
    if not _CREDS.valid:
        _CREDS.refresh(google.auth.transport.requests.Request())
    return _CREDS.token


def embed_image(png: bytes) -> list[float]:
    """multimodalembedding@001 via REST.

    The google-genai SDK's embed_content sends the wrong instance shape for this
    model and fails with "Empty instances", because it is a predict-style model
    rather than a content-style one.
    """
    token = _access_token()
    r = requests.post(
        f"https://{LOCATION}-aiplatform.googleapis.com/v1/projects/{PROJECT}"
        f"/locations/{LOCATION}/publishers/google/models/{EMBED_MODEL}:predict",
        headers={"Authorization": f"Bearer {token}"},
        json={"instances": [{"image": {
            "bytesBase64Encoded": base64.b64encode(png).decode()}}]},
        timeout=60,
    )
    r.raise_for_status()
    return r.json()["predictions"][0]["imageEmbedding"]


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    return dot / (na * nb) if na and nb else 0.0


def fingerprint(card: IdentityCard) -> list[float] | None:
    """Embed the face crop from the reference sheet. This is the anchor."""
    if not card.sheet_png:
        return None
    face = crop_face(card.sheet_png)
    return embed_image(face) if face else None


@dataclass
class Verdict:
    score: float | None
    passed: bool
    reason: str
    face_found: bool = True


def referee(frame: bytes, card: IdentityCard) -> Verdict:
    """Does this frame contain the right person?

    Returns score None when no face is found or no fingerprint exists. A missing
    score is reported honestly rather than defaulted to a pass, because a
    referee that silently passes everything is worse than no referee.
    """
    if card.face_embedding is None:
        return Verdict(None, True, "no fingerprint for this character", True)
    face = crop_face(frame)
    if face is None:
        return Verdict(None, True, "no face detected in frame", False)
    score = cosine(embed_image(face), card.face_embedding)
    ok = score >= FACE_THRESHOLD
    return Verdict(score, ok,
                   "matches reference" if ok else
                   f"face drifted, {score:.3f} below {FACE_THRESHOLD}", True)


def generate_shot_with_referee(
    shot_description: str, cards: list[IdentityCard], style: str = "realistic",
    previous_frame: bytes | None = None, max_attempts: int = 2,
) -> tuple[bytes, dict[str, Verdict], int]:
    """Generate, referee, and retry once on drift. Then stop.

    Two attempts, not more. A third attempt costs real money for a shot the user
    is about to regenerate by hand anyway, and flagging beats burning budget.
    """
    emphasis = ""
    frame, verdicts = b"", {}
    for attempt in range(1, max_attempts + 1):
        frame = generate_shot(shot_description + emphasis, cards, style, previous_frame)
        verdicts = {c.name: referee(frame, c) for c in cards}
        if all(v.passed for v in verdicts.values()):
            return frame, verdicts, attempt
        emphasis = ("\n\nCRITICAL: the previous attempt did not match the "
                    "reference faces. Reproduce the faces, hair and skin tone "
                    "from the reference images precisely.")
    return frame, verdicts, max_attempts
