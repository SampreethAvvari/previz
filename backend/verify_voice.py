"""Do two characters actually sound different, measurably? Run from backend/.

    python verify_voice.py

Compiles a Voice Card for two characters, writes one exchange with a sub-agent
per character, scores every line against its speaker's fingerprint, and runs
calibration to check the voices are separable at all.
"""
import json
import pathlib
import sys
import warnings

warnings.filterwarnings("ignore")
sys.path.insert(0, str(pathlib.Path(__file__).parent))

from app import voice as V  # noqa: E402

CACHE = pathlib.Path(__file__).parent / "demo_cache"
CACHE.mkdir(exist_ok=True)

MAYA = {
    "What is your full name?": "Maya Raghavan",
    "What does your voice sound like?":
        "Low, unhurried. I never raise it. People lean in to hear me and I let them.",
    "What words and/or phrases do you use very frequently?":
        "'Sure.' 'That's fine.' 'I'll handle it.' I say 'fine' when it isn't.",
    "Do you have any quirks, strange mannerisms, annoying habits?":
        "I go completely still when I'm angry. I answer questions with questions.",
    "What do you consider the most important event of your life so far?":
        "My mother died on a night I was working and I didn't pick up the phone.",
    "What is your greatest regret?": "That phone call.",
    "What is your greatest fear?":
        "Being completely known by someone. Being seen all the way through.",
    "How honest are you about your thoughts and feelings?":
        "Almost never. I tell people the version that ends the conversation.",
    "In general, how do you treat others?":
        "Politely, at a distance. Warmth is a thing I do on purpose, not by accident.",
    "What is your greatest strength as a person?": "I don't panic. Ever.",
    "What is your greatest weakness?": "I would rather be alone than be wrong in front of someone.",
    "What three words best describe your personality?": "Contained. Watchful. Tired.",
}

RAVI = {
    "What is your full name?": "Ravi Menon",
    "What does your voice sound like?":
        "Loud, warm, a bit hoarse. I talk over people and then apologise for it.",
    "What words and/or phrases do you use very frequently?":
        "'Listen, listen.' 'My friend.' 'Arre.' I call everyone boss.",
    "Do you have any quirks, strange mannerisms, annoying habits?":
        "I fill silences. I cannot leave a silence alone. I laugh at my own jokes first.",
    "What do you consider the most important event of your life so far?":
        "Driving the depot's night route for twenty two years without one accident.",
    "What is your greatest regret?": "I never learned to read properly. Nobody knows.",
    "What is your greatest fear?": "Being useless. Being retired.",
    "How honest are you about your thoughts and feelings?":
        "Completely. Too much. It gets me in trouble constantly.",
    "In general, how do you treat others?":
        "Like family whether they want it or not. I feed people.",
    "What is your greatest strength as a person?": "Nobody stays a stranger around me.",
    "What is your greatest weakness?": "I talk when I should listen.",
    "What three words best describe your personality?": "Loud. Kind. Restless.",
}

SCENE = ("INT. BUS DEPOT OFFICE - 4 AM. Maya is closing out the night shift. "
         "Ravi comes in off his last route, soaked from the rain, holding a "
         "printed notice.")
# Camera-visible only. Anything one character knows and the other does not goes
# in KNOWS, never here: the scene brief is shared with every sub-agent, so a
# secret placed here leaks to everyone.

KNOWS = {
    "Maya Raghavan": [
        "The night route is being cut at the end of the month.",
        "She has known for nine days and said nothing to Ravi.",
        "Ravi has driven this route for twenty two years.",
    ],
    "Ravi Menon": [
        "He found out tonight, from a notice taped to the depot door.",
        "He has driven this route for twenty two years without an accident.",
        # Deliberately NOT told that Maya knew. The knowledge horizon should
        # stop him referring to it.
    ],
}
STATES = {"Maya Raghavan": "Exhausted, already braced for this conversation.",
          "Ravi Menon": "Soaked, still in his jacket, holding the notice."}


def main() -> None:
    print("1. compiling Voice Cards (once each, reused verbatim after this)\n")
    cards = []
    for name, answers in (("Maya Raghavan", MAYA), ("Ravi Menon", RAVI)):
        c = V.compile_voice_card(name, answers)
        cards.append(c)
        print(f"  {name}")
        print(f"    card:       {c.card[:150]}")
        print(f"    register:   {json.dumps(c.register)[:150]}")
        print(f"    phrases:    {'; '.join(c.phrases[:4])}")
        print(f"    never_says: {'; '.join(c.never_says[:5])}")
        print(f"    fingerprint: {len(c.embedding) if c.embedding else 0} dims\n")

    print("2. calibration: are these two voices separable at all?\n")
    cal = V.calibrate_voice(cards)
    for k, v in cal.items():
        print(f"    {k}: {v}")
    if cal.get("separable"):
        print(f"\n    SEPARABLE. Threshold belongs at "
              f"{cal['suggested_threshold']:.3f} "
              f"(currently {V.VOICE_THRESHOLD})")
    else:
        print("\n    NOT SEPARABLE at the sample level. Show scores, do not "
              "auto-reject.")

    print("\n3. the exchange, one sub-agent per character\n")
    lines = V.write_exchange(cards, SCENE, KNOWS, STATES, turns=6)
    for ln in lines:
        s = f"{ln['score']:.3f}" if ln["score"] is not None else " n/a "
        flag = "" if ln["passed"] else "  << DRIFT"
        print(f"  [{s}]{flag}")
        print(f"  {ln['character'].upper()}")
        print(f"      {ln['line']}\n")

    (CACHE / "dialogue.json").write_text(json.dumps({
        "scene": SCENE, "calibration": cal, "lines": lines,
        "cards": [{"name": c.name, "card": c.card, "register": c.register,
                   "phrases": c.phrases, "never_says": c.never_says,
                   "samples": c.samples} for c in cards],
    }, indent=2), encoding="utf-8")
    real = [l["score"] for l in lines if l["score"] is not None]
    if real:
        print(f"  mean voice match: {sum(real)/len(real):.4f}   "
              f"worst: {min(real):.4f}")
    print(f"  cached to {CACHE / 'dialogue.json'}")


if __name__ == "__main__":
    main()
