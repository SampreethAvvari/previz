"""Previs CLI spike — run the shared pipeline against the REAL Google APIs and save PNGs.

    cd backend
    .venv/Scripts/python.exe spike.py                       # storyboard from the default noir scene
    .venv/Scripts/python.exe spike.py "INT. DINER - DAY..."  # storyboard from your own scene
    .venv/Scripts/python.exe spike.py --single "a red car in the rain, cinematic"  # one image only

Outputs land in backend/out/. GOOGLE_MAPS_API_KEY is optional.
"""
import base64
import pathlib
import sys

from app.config import settings
from app.gemini_client import generate_image
from app.models import StylePreset
from app.pipeline import generate_storyboard

OUT = pathlib.Path("out")
OUT.mkdir(exist_ok=True)

DEFAULT_SCENE = (
    "INT. NOIR BAR - NIGHT. A lone detective nurses a whiskey as rain streaks the "
    "window. The door opens; a woman in a red dress steps into the smoky light."
)


def single(prompt: str) -> None:
    print(f"Generating one image for: {prompt!r}")
    png = generate_image(prompt, "16:9")
    (OUT / "single.png").write_bytes(png)
    print(f"  -> wrote out/single.png ({len(png)} bytes)")


def storyboard(scene: str, style: StylePreset) -> None:
    print(f"Scene:\n  {scene}\n")
    print("Running pipeline...\n")
    result = generate_storyboard(scene, style)

    for s in result["shots"]:
        b64 = s["image_data_url"].split(",", 1)[1]
        path = OUT / f"shot_{s['index'] + 1}.png"
        path.write_bytes(base64.b64decode(b64))
        print(f"  {s['index'] + 1}. {s['description']}")
        print(f"     -> {path}")

    names = [loc["name"] for loc in result["locations"]]
    print("\nLocations:", ", ".join(names) if names else "(none / no maps key)")
    print(f"\nDone. Open the PNGs in backend/{OUT}/.")


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
