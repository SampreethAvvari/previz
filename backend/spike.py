"""Previs v1 spike — prove the core magic end-to-end against the REAL Google APIs.

Run from the backend/ dir with the venv, after putting GEMINI_API_KEY in backend/.env:

    cd backend
    .venv/Scripts/python.exe spike.py                       # storyboard from the default noir scene
    .venv/Scripts/python.exe spike.py "INT. DINER - DAY..."  # storyboard from your own scene
    .venv/Scripts/python.exe spike.py --single "a red vintage car in the rain, cinematic"  # one image only

Outputs land in backend/out/. GOOGLE_MAPS_API_KEY is optional (locations are skipped without it).
"""
import base64
import json
import sys
import pathlib

from google.genai import types

from app.config import settings
from app.gemini_client import get_client, generate_image, TEXT_MODEL
from app.models import StylePreset
from app.tools.storyboard import generate_storyboard_image
from app.tools.locations import find_locations

OUT = pathlib.Path("out")
OUT.mkdir(exist_ok=True)

DEFAULT_SCENE = (
    "INT. NOIR BAR - NIGHT. A lone detective nurses a whiskey as rain streaks the "
    "window. The door opens; a woman in a red dress steps into the smoky light."
)


def plan_shots(scene: str, n: int = 3) -> list[str]:
    """Ask Gemini to break a scene into n shot descriptions."""
    resp = get_client().models.generate_content(
        model=TEXT_MODEL,
        contents=(
            f"Break this film scene into exactly {n} storyboard shots. "
            f"Return ONLY a JSON list of objects, each with a 'description' field "
            f"(a vivid one-sentence visual description of the shot). Scene:\n{scene}"
        ),
        config=types.GenerateContentConfig(response_mime_type="application/json"),
    )
    try:
        data = json.loads(resp.text)
        shots = [d["description"] for d in data][:n]
        if shots:
            return shots
    except Exception as e:
        print(f"[warn] shot planning parse failed ({e}); using the whole scene as one shot")
    return [scene]


def single(prompt: str) -> None:
    print(f"Generating one image for: {prompt!r}")
    png = generate_image(prompt, "16:9")
    path = OUT / "single.png"
    path.write_bytes(png)
    print(f"  -> wrote {path} ({len(png)} bytes)")


def storyboard(scene: str, style: StylePreset) -> None:
    print(f"Scene:\n  {scene}\n")
    print(f"Style: {style.genre} / {style.visual_style} / {style.mood} / {style.era}\n")

    print("Planning shots...")
    shots = plan_shots(scene)
    for i, s in enumerate(shots, 1):
        print(f"  {i}. {s}")
    print()

    print("Rendering storyboard frames...")
    for i, shot in enumerate(shots, 1):
        url = generate_storyboard_image(shot, style)
        b64 = url.split(",", 1)[1]
        path = OUT / f"shot_{i}.png"
        path.write_bytes(base64.b64decode(b64))
        print(f"  -> wrote {path}")
    print()

    print("Scouting locations...")
    if settings.google_maps_api_key:
        locs = find_locations(scene)
        if locs:
            for loc in locs:
                print(f"  - {loc.name} — {loc.address}")
        else:
            print("  (no locations returned)")
    else:
        print("  (skipped — no GOOGLE_MAPS_API_KEY set)")

    print(f"\nDone. Open the PNGs in backend/{OUT}/ to see the storyboard.")


if __name__ == "__main__":
    if not settings.gemini_api_key:
        sys.exit("ERROR: set GEMINI_API_KEY in backend/.env before running the spike.")

    args = sys.argv[1:]
    if args and args[0] == "--single":
        single(args[1] if len(args) > 1 else "a lone lighthouse at dusk, cinematic, moody")
    else:
        scene = args[0] if args else DEFAULT_SCENE
        storyboard(
            scene,
            StylePreset(
                genre="noir",
                visual_style="black and white film grain",
                mood="tense",
                aspect_ratio="16:9",
                era="1940s",
            ),
        )
