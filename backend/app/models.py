from typing import Literal, Optional
from pydantic import BaseModel

class StylePreset(BaseModel):
    genre: str = "cinematic"
    visual_style: str = "photorealistic"
    mood: str = "neutral"
    aspect_ratio: str = "16:9"
    color_palette: str = "natural"
    era: str = "present day"

class Shot(BaseModel):
    index: int
    description: str
    camera: Optional[str] = None

class LocationSuggestion(BaseModel):
    name: str
    address: str
    lat: float
    lng: float
    maps_url: str
    photo_url: Optional[str] = None

class ShotPlanned(BaseModel):
    type: Literal["shot_planned"] = "shot_planned"
    shots: list[Shot]

class ImageReady(BaseModel):
    type: Literal["image_ready"] = "image_ready"
    shot_index: int
    image_data_url: str

class LocationFound(BaseModel):
    type: Literal["location_found"] = "location_found"
    scene: str
    locations: list[LocationSuggestion]

class Done(BaseModel):
    type: Literal["done"] = "done"

class ErrorEvent(BaseModel):
    type: Literal["error"] = "error"
    message: str
