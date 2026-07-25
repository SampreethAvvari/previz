import httpx
from app.config import settings
from app.models import LocationSuggestion

_URL = "https://places.googleapis.com/v1/places:searchText"

def find_locations(scene_description: str, region: str | None = None) -> list[LocationSuggestion]:
    query = scene_description if not region else f"{scene_description} in {region}"
    headers = {
        "X-Goog-Api-Key": settings.google_maps_api_key,
        "X-Goog-FieldMask": "places.displayName,places.formattedAddress,places.location,places.id",
    }
    try:
        r = httpx.post(_URL, headers=headers, json={"textQuery": query, "maxResultCount": 3}, timeout=10)
        r.raise_for_status()
        places = r.json().get("places", [])
    except Exception:
        return []
    out = []
    for p in places[:3]:
        loc = p.get("location", {})
        pid = p.get("id", "")
        out.append(LocationSuggestion(
            name=p.get("displayName", {}).get("text", "Unknown"),
            address=p.get("formattedAddress", ""),
            lat=loc.get("latitude", 0.0), lng=loc.get("longitude", 0.0),
            maps_url=f"https://www.google.com/maps/place/?q=place_id:{pid}",
        ))
    return out
