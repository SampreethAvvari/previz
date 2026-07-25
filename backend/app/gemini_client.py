from functools import lru_cache
from google import genai
from app.config import settings

@lru_cache
def get_client() -> genai.Client:
    return genai.Client(api_key=settings.gemini_api_key)

IMAGE_MODEL = "gemini-2.5-flash-image"
TEXT_MODEL = "gemini-flash-latest"

def generate_image(prompt: str, aspect_ratio: str = "16:9") -> bytes:
    """Generate one image from a text prompt via Gemini's native image model.

    Uses generate_content (the Imagen `predict` models are not available to new
    API keys) and returns the raw image bytes from the first inline_data part.
    """
    client = get_client()
    full_prompt = f"{prompt}. Cinematic {aspect_ratio} widescreen framing."
    resp = client.models.generate_content(model=IMAGE_MODEL, contents=full_prompt)
    for part in resp.candidates[0].content.parts:
        inline = getattr(part, "inline_data", None)
        if inline and inline.data:
            return inline.data
    raise RuntimeError("model returned no image")
