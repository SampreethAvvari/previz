from app.models import StylePreset, Shot, ShotPlanned

def test_style_preset_defaults():
    s = StylePreset()
    assert s.aspect_ratio == "16:9"

def test_shot_planned_event_type():
    ev = ShotPlanned(shots=[Shot(index=0, description="wide of a bar")])
    assert ev.type == "shot_planned"
    assert ev.shots[0].index == 0
