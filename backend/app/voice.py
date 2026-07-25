"""Voice consistency: the same mechanism as faces, applied to dialogue.

A character sounding wrong is as damaging as looking wrong and much easier to
miss, so it gets the same four moves:

  1. Compile a Voice Card once from the interview answers. Frozen.
  2. Fingerprint it by embedding its sample lines.
  3. Build one sub-agent per character in the scene, each receiving its own card
     VERBATIM. A sub-agent never summarises its own character, because
     re-summarising per call is exactly what makes a voice drift across a script.
  4. Referee every generated line against the fingerprint. A line that does not
     sound like them goes back with the specific register axis that is off.

The Voice Card is not a vibe summary. It is structured, and `never_says` does
more work than anything else in it: telling a model what a character would never
say constrains far harder than telling it what they might.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

import requests
from google.genai import types

from app.consistency import (LOCATION, PROJECT, TEXT_MODEL, _SAFETY, _access_token,
                             _client, cosine)

REASONING_MODEL = "gemini-2.5-pro"     # compiling cards: reasoning earns its keep
# Speaking a line: gemini-2.5-flash, because it is the only one of the two that
# accepts thinking_budget=0 (Pro always thinks and returns 400 on 0), and because
# a character does not deliberate before speaking.
VOICE_MODEL = "gemini-2.5-flash"
EMBED_TEXT = "text-embedding-005"          # 768 dims, verified on this project
# Calibrated 2026-07-25 on real generated lines, not on sample-vs-own-centroid.
# That distinction matters: calibrate_voice() scores each sample against a
# centroid the sample is itself part of, which inflates it to 0.77 and would set
# the bar above anything real. Measured instead:
#
#   generated Maya lines vs Maya fingerprint:  0.715  0.827  0.806
#   generated Ravi lines vs Ravi fingerprint:  0.682  0.647  0.684
#   best cross-character sample score:         0.613
#
# 0.62 sits between the best cross-character score and the worst genuine
# generated line. Re-derive from a bigger sample before trusting it further.
VOICE_THRESHOLD = 0.62

# The 12 core interview questions. Fewer than these answered and we refuse to
# write dialogue rather than inventing a person.
CORE_QUESTIONS = [
    "full name", "what does your voice sound like", "words and phrases you use",
    "quirks and mannerisms", "most important event of your life", "greatest regret",
    "greatest fear", "how honest are you about your thoughts and feelings",
    "how do you treat others", "greatest strength", "greatest weakness",
    "goal you most want to accomplish",
]


def embed_text(texts: list[str]) -> list[list[float]]:
    """text-embedding-005 via REST :predict. Proven on this project."""
    r = requests.post(
        f"https://{LOCATION}-aiplatform.googleapis.com/v1/projects/{PROJECT}"
        f"/locations/{LOCATION}/publishers/google/models/{EMBED_TEXT}:predict",
        headers={"Authorization": f"Bearer {_access_token()}"},
        json={"instances": [{"content": t} for t in texts]},
        timeout=60,
    )
    r.raise_for_status()
    return [p["embeddings"]["values"] for p in r.json()["predictions"]]


@dataclass
class VoiceCard:
    """Frozen. Written once per canon version, injected verbatim, never edited."""
    name: str
    card: str                                     # prose: how they speak and why
    register: dict[str, str] = field(default_factory=dict)
    phrases: list[str] = field(default_factory=list)
    never_says: list[str] = field(default_factory=list)
    samples: list[str] = field(default_factory=list)
    embedding: list[float] | None = None
    canon_version: int = 1

    def system_prompt(self, scene: str, knows: list[str],
                      state: str = "") -> str:
        """The sub-agent's entire brief. Card goes in verbatim, never summarised."""
        return (
            f"You ARE {self.name}. You are not writing about her, you are her.\n\n"
            f"HOW YOU SPEAK (this is fixed, do not reinterpret it):\n{self.card}\n\n"
            f"YOUR REGISTER:\n"
            + "\n".join(f"  {k}: {v}" for k, v in self.register.items())
            + (f"\n\nPHRASES YOU ACTUALLY USE: {'; '.join(self.phrases)}"
               if self.phrases else "")
            + (f"\n\nYOU WOULD NEVER SAY: {'; '.join(self.never_says)}"
               if self.never_says else "")
            + (f"\n\nLINES THAT ARE UNMISTAKABLY YOURS:\n"
               + "\n".join(f"  \"{s}\"" for s in self.samples)
               if self.samples else "")
            + f"\n\nTHE SCENE: {scene}"
            + (f"\n\nWHERE YOU ARE RIGHT NOW: {state}" if state else "")
            + (f"\n\nWHAT YOU KNOW AT THIS POINT IN THE STORY:\n"
               + "\n".join(f"  - {k}" for k in knows)
               if knows else "\n\nYou know nothing beyond this scene.")
            + ("\n\nYou cannot refer to anything not on that list. You have not "
               "learned it yet.\n\n"
               "Speak ONE line. Dialogue only, no action, no character name, no "
               "quotation marks, no stage direction. If silence is truer for you "
               "here, return exactly: [says nothing]")
        )


def compile_voice_card(name: str, answers: dict[str, str],
                       canon_version: int = 1) -> VoiceCard:
    """Compile the card. Called once per canon version, then reused forever."""
    resp = _client().models.generate_content(
        model=REASONING_MODEL,
        contents=(
            "You are a dialogue coach building a reusable voice specification so "
            "that a language model writes this character identically every time, "
            "across scenes written weeks apart.\n\n"
            f"Character: {name}\n"
            f"Interview answers:\n{json.dumps(answers, indent=2)}\n\n"
            "Return JSON with exactly these keys:\n"
            '  "card": two or three sentences on HOW they speak and WHY, tying '
            "the speech pattern to something real in their history. Not what they "
            "talk about. How the words come out.\n"
            '  "register": object with keys sentence_length, formality, profanity, '
            "hedging, humour, silence. Each a short concrete value, for example "
            '"short, often fragments" or "swears only when frightened".\n'
            '  "phrases": 3 to 6 things they verbatim say. Real tics, not '
            "catchphrases.\n"
            '  "never_says": 4 to 8 words or constructions that would be out of '
            "character. Be specific and unobvious. This list constrains the model "
            "harder than anything else, so make it earn its place.\n"
            '  "samples": 4 lines of dialogue that could only be this person. '
            "These become the fingerprint their generated lines are measured "
            "against, so they must be maximally characteristic.\n\n"
            "Infer aggressively from what you were given. A vague voice "
            "specification produces a generic character, which is the failure "
            "we are preventing."
        ),
        config=types.GenerateContentConfig(
            response_mime_type="application/json", safety_settings=_SAFETY),
    )
    d = json.loads(resp.text)
    vc = VoiceCard(
        name=name, card=d["card"], register=d.get("register", {}),
        phrases=d.get("phrases", []), never_says=d.get("never_says", []),
        samples=d.get("samples", []), canon_version=canon_version)
    if vc.samples:
        vecs = embed_text(vc.samples)
        # Fingerprint is the centroid of the samples: one vector representing
        # "sounds like this person", which a single line can be compared against.
        vc.embedding = [sum(c) / len(c) for c in zip(*vecs)]
    return vc


# thinking_budget=0 for two reasons. Practically: 2.5-flash is a thinking model,
# and with a small max_output_tokens the reasoning tokens consume the entire budget
# and the line comes back truncated mid-word ("Arre, boss, I"). Artistically:
# dialogue should be instinctive, not reasoned. A character does not deliberate
# before speaking, and lines written after visible deliberation read like it.
#
# The field only exists from google-genai 1.10 or so. The venv here is on 1.2.0,
# whose ThinkingConfig takes include_thoughts and nothing else, and passing an
# unknown field raises a pydantic ValidationError BEFORE the call goes out, which
# took down every generated line. So it is probed once at import rather than
# assumed. When it is unavailable the model thinks, so the token ceiling goes up
# to leave room for reasoning plus a whole line, which is the mitigation
# CLAUDE.md already prescribes for the same failure on 2.5-pro.
_HAS_THINKING_BUDGET = "thinking_budget" in types.ThinkingConfig.model_fields


def _speech_config() -> "types.GenerateContentConfig":
    kw: dict = {"safety_settings": _SAFETY, "temperature": 1.0}
    if _HAS_THINKING_BUDGET:
        kw["thinking_config"] = types.ThinkingConfig(thinking_budget=0)
        kw["max_output_tokens"] = 400
    else:
        kw["max_output_tokens"] = 2048
    return types.GenerateContentConfig(**kw)


def speak(card: VoiceCard, scene: str, knows: list[str], state: str = "",
          heard: list[str] | None = None) -> str:
    """One line from one character. One call, one line."""
    convo = ("\n\nWHAT HAS BEEN SAID SO FAR IN THIS SCENE:\n"
             + "\n".join(heard) if heard else "")
    resp = _client().models.generate_content(
        model=VOICE_MODEL,
        contents=card.system_prompt(scene, knows, state) + convo,
        config=_speech_config(),
    )
    line = (resp.text or "").strip().strip('"').strip()
    # Strip a leading character name if the model slipped one in despite the brief.
    prefix = f"{card.name.upper()}:"
    if line.upper().startswith(prefix):
        line = line[len(prefix):].strip()
    return line


@dataclass
class VoiceVerdict:
    score: float | None
    passed: bool
    reason: str


def referee_line(line: str, card: VoiceCard) -> VoiceVerdict:
    """Does this line sound like them? Measured, not judged by feel."""
    if card.embedding is None or not line or line == "[says nothing]":
        return VoiceVerdict(None, True, "no fingerprint or no line to score")
    score = cosine(embed_text([line])[0], card.embedding)
    ok = score >= VOICE_THRESHOLD
    return VoiceVerdict(score, ok, "sounds like them" if ok else
                        f"voice drifted, {score:.3f} below {VOICE_THRESHOLD}")


def write_exchange(cards: list[VoiceCard], scene: str,
                   knows: dict[str, list[str]], states: dict[str, str] | None = None,
                   turns: int = 4) -> list[dict]:
    """The DialogueDirector.

    Builds one sub-agent per character present and alternates them. Each speaks
    from its own card only, and hears only what has actually been said out loud.
    No single agent holds every character, which is what makes the voices
    genuinely separate rather than one model doing impressions.

    CRITICAL, and this was found by it going wrong: `scene` is shared with every
    sub-agent, so it must contain NOTHING that any character in it does not know.
    Put secrets in `knows` for the character who holds them, never in `scene`.

    A first run used the scene brief "Maya already knew, and did not tell him."
    Ravi's `knows` list deliberately omitted that. He accused her of it anyway,
    on his third line, because he read it in the shared brief. The knowledge
    horizon is only as tight as the scene description around it.

    `scene` is what a camera in the room could see. Everything else is per
    character.
    """
    if not cards:
        return []
    leaked = _check_scene_for_secrets(scene, knows)
    if leaked:
        # Loud rather than silent: a leaked secret produces dialogue that looks
        # fine and is wrong, which is the most expensive kind of bug here.
        print(f"  WARNING: scene brief may leak private knowledge: {leaked}")
    states = states or {}
    heard: list[str] = []
    out: list[dict] = []
    for i in range(turns):
        card = cards[i % len(cards)]
        line = speak(card, scene, knows.get(card.name, []),
                     states.get(card.name, ""), heard)
        v = referee_line(line, card)
        if not v.passed:
            # Send it back to that character's own sub-agent, naming the axis.
            line = speak(card, scene, knows.get(card.name, []),
                         states.get(card.name, ""),
                         heard + [f"(That last attempt did not sound like you. "
                                  f"Your register is: {card.register}. Try again, "
                                  f"more like your sample lines.)"])
            v = referee_line(line, card)
        heard.append(f"{card.name.upper()}: {line}")
        out.append({"character": card.name, "line": line,
                    "score": v.score, "passed": v.passed, "reason": v.reason,
                    "canon_version": card.canon_version})
    return out


def _check_scene_for_secrets(scene: str, knows: dict[str, list[str]]) -> list[str]:
    """Warn when the shared scene brief states something only one character knows.

    Cheap heuristic, not a proof: for each character, look for a fact that is in
    someone else's `knows` list, absent from theirs, and whose distinctive words
    appear in the scene text. Catches the obvious case, which is the one that
    actually happens.
    """
    STOP = {"the", "a", "an", "is", "was", "has", "have", "and", "or", "of", "to",
            "in", "on", "at", "for", "it", "he", "she", "they", "her", "him",
            "his", "not", "did", "does", "been", "being", "that", "this", "with"}
    low = scene.lower()
    hits: list[str] = []
    for owner, facts in knows.items():
        for other in knows:
            if other == owner:
                continue
            for fact in facts:
                if fact in knows[other]:
                    continue
                words = {w.strip(".,'\"") for w in fact.lower().split()
                         if len(w) > 4 and w not in STOP}
                if words and len(words & set(low.split())) >= max(2, len(words) // 3):
                    hits.append(f"{other} may learn from the brief: {fact[:60]}")
    return hits


def calibrate_voice(cards: list[VoiceCard]) -> dict:
    """Set VOICE_THRESHOLD from measured distributions, not by feel.

    Scores each character's own samples against their own fingerprint, and against
    every other character's. The threshold belongs in the gap. Until this has run,
    show scores and do not auto-reject: an uncalibrated threshold that silently
    rejects good lines is worse than no threshold at all.
    """
    same, cross = [], []
    for c in cards:
        if c.embedding is None:
            continue
        for s in c.samples:
            v = embed_text([s])[0]
            same.append(cosine(v, c.embedding))
            for other in cards:
                if other is not c and other.embedding is not None:
                    cross.append(cosine(v, other.embedding))
    if not same or not cross:
        return {"error": "need at least 2 fingerprinted characters"}
    lo, hi = min(same), max(cross)
    return {"worst_same": lo, "best_cross": hi, "gap": lo - hi,
            "suggested_threshold": (lo + hi) / 2,
            "separable": lo > hi,
            "n_same": len(same), "n_cross": len(cross)}
