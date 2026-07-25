import base64
from app.models import StylePreset
from app.gemini_client import generate_image

_PLACEHOLDER = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="

def _prompt(shot: str, s: StylePreset) -> str:
    return (f"Film storyboard frame. {shot}. Style: {s.genre}, {s.visual_style}, "
            f"{s.mood} mood, {s.color_palette} palette, {s.era}. Cinematic composition.")

def generate_storyboard_image(shot_description: str, style: StylePreset) -> str:
    try:
        png = generate_image(_prompt(shot_description, style), style.aspect_ratio)
        return "data:image/png;base64," + base64.b64encode(png).decode()
    except Exception:
        return _PLACEHOLDER
