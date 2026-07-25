"""Core Previs pipeline: scene text -> shot breakdown -> storyboard images + locations.

Shared by the CLI spike and the FastAPI web app so there is one source of truth.
"""
import json

from google.genai import types

from app.config import settings
from app.gemini_client import get_client, TEXT_MODEL
from app.models import StylePreset
from app.tools.storyboard import generate_storyboard_image
from app.tools.locations import find_locations


def plan_shots(scene: str, style: StylePreset, n: int = 3) -> list[str]:
    """Ask Gemini to break a scene into n vivid shot descriptions."""
    resp = get_client().models.generate_content(
        model=TEXT_MODEL,
        contents=(
            f"Break this film scene into exactly {n} storyboard shots for a "
            f"{style.genre} film. Return ONLY a JSON list of objects, each with a "
            f"'description' field: one vivid sentence describing the shot "
            f"(camera framing + subject + action). Scene:\n{scene}"
        ),
        config=types.GenerateContentConfig(response_mime_type="application/json"),
    )
    try:
        data = json.loads(resp.text)
        shots = [d["description"] for d in data if isinstance(d, dict) and d.get("description")][:n]
        if shots:
            return shots
    except Exception:
        pass
    return [scene]


def generate_storyboard(scene: str, style: StylePreset, n: int = 3) -> dict:
    """Run the full pipeline. Returns:

    {
      "shots": [{"index": int, "description": str, "image_data_url": str}, ...],
      "locations": [{"name","address","lat","lng","maps_url","photo_url"}, ...],
    }
    """
    shots = plan_shots(scene, style, n)
    result_shots = []
    for i, desc in enumerate(shots):
        image_data_url = generate_storyboard_image(desc, style)
        result_shots.append({"index": i, "description": desc, "image_data_url": image_data_url})

    locations = []
    if settings.google_maps_api_key:
        locations = [loc.model_dump() for loc in find_locations(scene)]

    return {"shots": result_shots, "locations": locations}
