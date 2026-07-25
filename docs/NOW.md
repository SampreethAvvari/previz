# NOW · the next 100 minutes

**Written 13:20 EDT 2026-07-25. Deadline 15:30. Stop coding at 15:00 and rehearse.**

This file overrides both plans in `docs/superpowers/plans/` for the duration of the
hackathon. Those plans are correct and they are for a 48 hour build. We have
about 100 minutes. Read this instead.

## Cancelled. Do not start any of these today.

Cloud SQL and pgvector · Terraform · CI/CD · Workload Identity · login and auth ·
the Next.js rewrite · the ADK migration · the MCP server · contract codegen ·
splitting into two Cloud Run services · moving `backend/` to `apps/agents/`.

Cloud SQL alone is eight minutes of provisioning before the first debugging
round trip. Every item above is real engineering with zero demo value inside 100
minutes.

## Keep. This is the whole build.

Everything runs in **one FastAPI process**, the one already at `backend/app/`.
State in memory plus a JSON seed file. Retrieval is cosine over roughly 50
chunks in numpy, which is instant and needs no infrastructure. One
`gcloud run deploy --source backend` at 15:00.

## What is already proven, by real calls

Measured against `nyu-ai-builder26nyc-9338` at 13:07 today:

- `gemini-2.5-flash-image` (Nano Banana) **holds a character's face** across a
  completely different composition and lighting setup when conditioned on a
  reference sheet. Verified by eye, not by metric. This is the demo.
- `gemini-2.5-pro`, `-flash`, `-flash-lite`, `gemini-embedding-001` and
  `multimodalembedding@001` all answer. Gemini 3 returns 404 on this project, so
  there is no Nano Banana Pro.
- `gemini-flash-latest` **404s on Vertex**. It is an AI Studio alias. This is
  currently in `gemini_client.py` and must change to `gemini-2.5-flash`.
- The SDK's `embed_content` **fails** on `multimodalembedding@001` with "Empty
  instances". That model needs a raw REST `:predict` call. Already handled in
  `consistency.py:embed_image`.

## What the spike also caught, so nobody rediscovers it

**Whole-frame embeddings cannot referee identity.** Numbers from the spike:

```
Maya's sheet vs Maya's 3 shots:   0.39  0.39  0.51
Ravi's sheet vs Maya's 3 shots:   0.20  0.28  0.31    <- control
Maya's sheet vs Ravi's sheet:     0.48    <- two DIFFERENT people, scored HIGH
```

`multimodalembedding@001` encodes the entire image, so composition and lighting
swamp identity. Two reference sheets of two different people score 0.48 because
both are grey three-view sheets. **Fix: crop the face first, then embed.**
`consistency.py:crop_face` does this with a Gemini bounding box call.

**Style drifts even when identity does not.** The spike's sheet was photoreal and
the first shot came back as a digital painting, because the prompt said
"storyboard frame" and nothing pinned the medium. `STYLE_PRESETS` in
`consistency.py` pins it, and every shot in a board must use the same preset
string verbatim.

## Who does what

| Who | Owns | Done when |
|---|---|---|
| **Sampreeth** | `consistency.py`: Identity Cards, reference sheets, conditioned shots, the face-crop referee. Voice Cards and the per-character dialogue agents. | A character generated in shot 1 is visibly the same person in shot 6, with a score shown per shot |
| **Sahaj** | Frontend. Restyle `app/static/index.html`: near black, character cards with their reference sheet, shot grid with a score badge per frame. Do **not** edit `tools/storyboard.py`, Sampreeth is wiring `consistency.py` into it. | It looks like a product, not a form |
| **kik728** | `data/seed/story.json`: Sampreeth's story, 3 characters, answers to the 12 core questions each, 6 to 8 scenes with sluglines and synopses, 2 locations. Real texture, not Character A. | The app opens with a story already in it |
| **gp2610** | Port `gemini_client.py` to Vertex: `genai.Client(vertexai=True, project="nyu-ai-builder26nyc-9338", location="us-central1")`, `TEXT_MODEL = "gemini-2.5-flash"`. Then the dialogue endpoint. | No AI Studio key anywhere and nothing 404s |

## Demo spine, five minutes

1. Open on the seeded story. Story bible with 3 characters, scenes, locations.
2. Open a character. Show their Identity Card and Voice Card, both compiled from
   the interview answers. Point out that these are frozen and reused verbatim.
3. Generate a storyboard for one scene. Frames stream in. **Each frame shows its
   face match score.** Regenerate one and watch the score move.
4. Scroll back to shot 1 and forward to shot 6. Same person. That is the point.
5. Write one line of dialogue. Show that three character subagents each got their
   own Voice Card. Read the line. It sounds like her.
6. Location scouting on one scene, real places, real photos.

## Rules for the last hour

- **15:00 is a hard stop on features.** After that: rehearse, cache fallbacks,
  fix only crashes.
- **Cache every demo asset.** Generated sheets and frames go to disk and get
  committed. If the venue wifi dies or the lab project expires mid demo, the app
  still shows a full board.
- **The lab project expires today.** Do not put anything in it we cannot lose.
- Hard cap on image generation per story so a loop bug cannot eat the budget.
