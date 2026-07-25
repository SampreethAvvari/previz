from functools import lru_cache
from google import genai
from app.config import settings

@lru_cache
def get_client() -> genai.Client:
    return genai.Client(api_key=settings.gemini_api_key)

def generate_image(prompt: str, aspect_ratio: str = "16:9") -> bytes:
    client = get_client()
    resp = client.models.generate_images(
        model="imagen-3.0-generate-002",
        prompt=prompt,
        config={"number_of_images": 1, "aspect_ratio": aspect_ratio},
    )
    return resp.generated_images[0].image.image_bytes
