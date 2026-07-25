"""End to end check of the consistency core. Run from backend/.

    python verify_consistency.py

Generates a real 6 shot board for one character and prints the face match score
for every frame, plus the first-to-last drift score which is the number that
actually matters. Writes every image to demo_cache/ so the frontend has
something to show and so the demo survives the wifi dying.
"""
import json
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).parent))

from app import consistency as C  # noqa: E402

CACHE = pathlib.Path(__file__).parent / "demo_cache"
CACHE.mkdir(exist_ok=True)

FACTS = {
    "name": "Maya Raghavan",
    "age": "29",
    "physical": ("Tall and lean, South Asian, sharp jaw, deep-set dark brown "
                 "eyes, thick black hair cut blunt at the collarbone with a "
                 "small scar through the right eyebrow. Holds herself very "
                 "still, like she is used to being watched."),
    "style of dress": "worn olive canvas jacket, grey t-shirt, black cargo trousers, scuffed boots",
    "occupation": "night shift dispatcher at a bus depot",
    "voice": "low and unhurried, never raises it",
}

SHOTS = [
    "MEDIUM CLOSE UP, eye level, 50mm. She sits in a parked car at night, rain on the glass, sodium streetlight from camera left, looking off screen right.",
    "WIDE SHOT, low angle, 24mm. She stands alone at the end of an empty motel corridor, fluorescent tubes overhead, one flickering.",
    "EXTREME CLOSE UP, 85mm. Her eyes, harsh top light, half her face in shadow.",
    "MEDIUM SHOT, high angle, 35mm. She crouches on wet asphalt beside a bus tyre, torch in her teeth, headlights raking across her from behind.",
    "OVER THE SHOULDER, 50mm. From behind her, she looks through a depot window at rows of parked buses in blue pre-dawn light.",
    "CLOSE UP, eye level, 85mm. She turns her head toward camera, finally looking straight down the lens, dawn light warm on one cheek.",
]


def main() -> None:
    t_start = time.monotonic()

    print("1. compiling the Identity Card (once, reused verbatim after this)")
    card = C.compile_identity_card("Maya Raghavan", FACTS)
    print(f"   descriptor: {card.descriptor[:150]}...")
    print(f"   wardrobe:   {card.wardrobe[:90]}")
    print(f"   negative:   {card.negative[:90]}")
    (CACHE / "maya_card.json").write_text(json.dumps({
        "name": card.name, "descriptor": card.descriptor,
        "wardrobe": card.wardrobe, "negative": card.negative,
    }, indent=2), encoding="utf-8")

    print("\n2. reference sheet")
    card.sheet_png = C.generate_reference_sheet(card)
    (CACHE / "maya_sheet.png").write_bytes(card.sheet_png)
    print(f"   {len(card.sheet_png)//1024} KB")

    print("\n3. fingerprint (face crop from the sheet, not the whole sheet)")
    card.face_embedding = C.fingerprint(card)
    if card.face_embedding is None:
        print("   FAILED: no face detected in the reference sheet.")
        print("   The referee cannot run. Conditioning still works; ship without scores.")
        return
    print(f"   {len(card.face_embedding)} dims")
    crop = C.crop_face(card.sheet_png)
    if crop:
        (CACHE / "maya_face.png").write_bytes(crop)

    print(f"\n4. generating {len(SHOTS)} shots, conditioned on sheet + card")
    scores, prev = [], None
    for i, desc in enumerate(SHOTS, 1):
        t0 = time.monotonic()
        frame, verdicts, attempts = C.generate_shot_with_referee(
            desc, [card], style="realistic", previous_frame=prev)
        v = verdicts[card.name]
        ms = int((time.monotonic() - t0) * 1000)
        (CACHE / f"maya_shot{i}.png").write_bytes(frame)
        s = f"{v.score:.4f}" if v.score is not None else "  n/a"
        flag = "ok " if v.passed else "DRIFT"
        print(f"   shot {i}: {s}  {flag}  {attempts} attempt(s)  {ms:>6} ms  "
              f"{'' if v.face_found else '(no face found)'}")
        scores.append(v.score)
        prev = frame

    real = [s for s in scores if s is not None]
    print("\n" + "=" * 62)
    if real:
        print(f"  mean face match:     {sum(real)/len(real):.4f}")
        print(f"  worst face match:    {min(real):.4f}")
    if len(real) >= 2:
        a = C.embed_image(C.crop_face((CACHE / 'maya_shot1.png').read_bytes()) or b"")
        b = C.embed_image(C.crop_face((CACHE / f'maya_shot{len(SHOTS)}.png').read_bytes()) or b"")
        print(f"  FIRST vs LAST shot:  {C.cosine(a, b):.4f}   <- the drift number")
    print(f"  total wall clock:    {int(time.monotonic()-t_start)}s")
    print(f"  images cached in     {CACHE}")
    print("=" * 62)


if __name__ == "__main__":
    main()
