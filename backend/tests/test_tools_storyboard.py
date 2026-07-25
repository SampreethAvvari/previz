import base64
from unittest.mock import patch
from app.tools.storyboard import generate_storyboard_image, _PLACEHOLDER
from app.models import StylePreset

def test_storyboard_returns_data_url():
    fake_png = b"\x89PNG_fake_bytes"
    expected = "data:image/png;base64," + base64.b64encode(fake_png).decode()
    with patch("app.tools.storyboard.generate_image", return_value=fake_png):
        url = generate_storyboard_image("wide shot of a bar", StylePreset(genre="noir"))
    assert url == expected

def test_storyboard_placeholder_on_failure():
    with patch("app.tools.storyboard.generate_image", side_effect=RuntimeError):
        url = generate_storyboard_image("x", StylePreset())
    assert url == _PLACEHOLDER
