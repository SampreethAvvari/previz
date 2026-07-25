from unittest.mock import patch
from app.tools.storyboard import generate_storyboard_image
from app.models import StylePreset

def test_storyboard_returns_data_url():
    with patch("app.tools.storyboard.generate_image", return_value=b"\x89PNG..."):
        url = generate_storyboard_image("wide shot of a bar", StylePreset(genre="noir"))
    assert url.startswith("data:image/png;base64,")

def test_storyboard_placeholder_on_failure():
    with patch("app.tools.storyboard.generate_image", side_effect=RuntimeError):
        url = generate_storyboard_image("x", StylePreset())
    assert url.startswith("data:image/png;base64,")
