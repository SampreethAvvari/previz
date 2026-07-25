import respx, httpx
from app.tools.locations import find_locations

@respx.mock
def test_find_locations_parses_places():
    respx.post("https://places.googleapis.com/v1/places:searchText").mock(
        return_value=httpx.Response(200, json={"places": [{
            "displayName": {"text": "The Blue Bar"},
            "formattedAddress": "1 Main St",
            "location": {"latitude": 40.0, "longitude": -73.0},
            "id": "abc"}]}))
    out = find_locations("a dim noir bar")
    assert out[0].name == "The Blue Bar"
    assert out[0].lat == 40.0
    assert "abc" in out[0].maps_url

@respx.mock
def test_find_locations_empty_on_error():
    respx.post("https://places.googleapis.com/v1/places:searchText").mock(
        return_value=httpx.Response(500))
    assert find_locations("x") == []

@respx.mock
def test_find_locations_empty_on_malformed_place():
    respx.post("https://places.googleapis.com/v1/places:searchText").mock(
        return_value=httpx.Response(200, json={"places": "not-a-list"}))
    assert find_locations("x") == []
