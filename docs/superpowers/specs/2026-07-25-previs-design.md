# Previs — Design Spec

**Date:** 2026-07-25
**Type:** Hackathon project (GDG / open theme)
**Build tool:** Claude Code in VS Code · **Runtime:** All-Google (Gemini + Imagen + Google Maps) · **Deploy:** Cloud Run + Firebase

---

## 1. Overview

Previs ("pre-visualization") is a **bidirectional multimodal** web app for filmmakers and
screenwriters. It works both directions of pre-production:

- **Words → Pictures** — paste a scene + set a style → an autonomous Gemini "director" agent
  produces a **storyboard** (image per shot) + **real filming-location** suggestions.
- **Pictures → Words** — upload an image → Gemini vision returns a **screenplay** (scene in
  proper screenplay format) describing the shot.
- **Bonus round-trip** — image → screenplay → storyboard, all in one flow.

The agent streams its planning and tool calls live so the audience watches an AI director work.

## 2. Goals & non-goals

**Goals (hackathon scope):**
- **Mode A (Text → Board):** scene text → shot breakdown → storyboard images + per-scene
  real-world locations with map pins.
- **Mode B (Image → Screenplay):** upload image → Gemini vision → screenplay-formatted output.
- Creative style controls that thread through generation.
- Live "Director's Log" stream of the agent's work (Mode A).
- Deployable to GCP (Cloud Run + Firebase).

**Non-goals (explicitly out — post-hackathon):**
- User accounts, login, saved/multi-project persistence.
- Video / animatic generation (Veo).
- Full script *writing* assistant / editor.
- Collaboration; exports beyond a board view (PDF export = stretch).

## 3. Users

Filmmakers, screenwriters, and creatives doing pre-production who want to move fast between
scene text and visuals — in either direction.

## 4. Hero flows (two input modes)

**Mode A — Text → Storyboard + Locations (the agent):**
`scene text + style preset → Gemini director agent → [plan shots] → [generate image per shot]
+ [find real locations per scene] → live-streamed storyboard + location board`

**Mode B — Image → Screenplay (direct multimodal):**
`uploaded image (+ optional style) → Gemini 2.5 vision → screenplay-formatted scene text`

**Bonus:** Mode B output can feed straight into Mode A (photo → screenplay → storyboard).

## 5. Architecture (Approach B — autonomous agent for Mode A)

- **Frontend** — React + Vite + Tailwind SPA on **Firebase Hosting**. Panels:
  1. Input area with a **mode toggle** — *Text* (scene input) or *Image* (upload)
  2. Style controls
  3. Director's Log (live SSE stream of plan + tool calls — Mode A)
  4. Storyboard grid (Mode A) / Screenplay output (Mode B)
  5. Location cards with embedded map pins (Mode A)
- **Backend** — **FastAPI on Cloud Run**. Endpoints:
  - `POST /generate` (SSE) — Mode A agent loop, streams events.
  - `POST /analyze-image` — Mode B: a direct Gemini 2.5 vision call → screenplay text.
- **Agent brain (Mode A)** — **Gemini 2.5** with function-calling tools; reads the scene,
  plans shots, autonomously calls tools in a **bounded loop**.
- **Mode B** is a single multimodal call (not the full agent) to keep it simple + reliable.

### Tools exposed to the agent (Mode A)
- `generate_storyboard_image(shot_description, style)` → Imagen 3 / Gemini image gen
- `find_locations(scene_description, region?)` → Google Maps Places (New) via **MCP**

## 6. Style preset (the "customizable" core)

A structured object injected into the agent's system prompt **and** every image prompt (Mode A),
and optionally into the vision prompt (Mode B, to bias tone):

```json
{
  "genre": "noir",
  "visual_style": "black & white film grain",
  "mood": "tense",
  "aspect_ratio": "2.39:1",
  "color_palette": "high-contrast monochrome",
  "era": "1940s"
}
```

Changing the preset regenerates the board in that style. No login — it's a control panel.

## 7. Data flow

**Mode A (Text → Board):**
1. User submits scene text + style → frontend opens SSE stream to `/generate`.
2. Backend launches the Gemini agent (system prompt = goal + style + tool schemas).
3. Agent emits tool calls; backend executes + streams events:
   `shot_planned`, `image_ready`, `location_found`, `done`.
4. Frontend renders progressively — shot list → images fill in → location cards appear.

**Mode B (Image → Screenplay):**
1. User uploads an image (+ optional style) → `POST /analyze-image`.
2. Backend sends the image to Gemini 2.5 vision with a "write this as a screenplay scene" prompt.
3. Returns screenplay-formatted text; frontend renders it (and offers "→ Generate storyboard").

## 8. Demo-safety engineering (makes Approach B safe on stage)

- **Bounded agent loop** — hard caps (≤6 shots, max total tool calls) so it can't run away.
- **Live streaming (SSE)** — turns latency into the show ("watch the AI direct").
- **Safe mode (deterministic Approach A) behind a flag** — fallback if the agent misbehaves live.
- **Cached demo scene + demo image** — pre-generated fallbacks if wifi/API dies.
- **Parallel image gen** for independently-planned shots.

## 9. Error handling

- Image gen fails → retry once → placeholder card showing the prompt.
- Maps returns nothing → agent broadens the query → else a text location description.
- Vision analysis fails / unsupported file → clear UI error, keep the app usable.
- Gemini safety refusal → caught, friendly message, continue.
- Rate limits → exponential backoff + capped concurrency.

## 10. Testing (hackathon-appropriate)

- 2 "golden" scenes (Mode A) + 1 "golden" image (Mode B) run repeatedly.
- Unit-test the tool wrappers (`generate_storyboard_image`, `find_locations`) and the
  `analyze-image` handler in isolation.
- Mock agent events for frontend development.

## 11. Tech stack

- **Frontend:** React + Vite + Tailwind · Firebase Hosting
- **Backend:** FastAPI · Cloud Run · SSE streaming
- **Models:** Gemini 2.5 (function-calling + vision) · Imagen 3 / Gemini image gen
- **Tools:** Google Maps Places (New) via MCP
- **Secrets:** Secret Manager (prod) / `.env` (local)
- **Built with:** Claude Code in VS Code

## 12. API keys & prerequisites

| # | Item | Notes |
|---|------|-------|
| 1 | GCP project w/ billing | Imagen + Maps require billing; free credits/tiers apply |
| 2 | `GEMINI_API_KEY` (AI Studio) | Local dev; covers Gemini 2.5 text + vision + Imagen. Prod → Vertex AI + ADC |
| 3 | `GOOGLE_MAPS_API_KEY` | Places API (New) enabled; server key IP-restricted |
| 4 | Browser Maps key | Embed/JS API, HTTP-referrer-restricted (frontend map only) |
| 5 | Firebase project + CLI | Hosting; `firebase login` |
| 6 | Cloud Run / Cloud Build / Artifact Registry APIs | Backend deploy |
| 7 | `gcloud` + `firebase-tools` + Node 20 + Python 3.11 | Local toolchain |

## 13. Deployment

- **Frontend** → Firebase Hosting (`firebase deploy`).
- **Backend** → Cloud Run (`gcloud run deploy`), secrets via Secret Manager, Gemini via Vertex/ADC.

## 14. Demo script (~90 seconds)

1. **Mode B:** upload a photo of an empty diner → Gemini returns a screenplay scene
   (`INT. DINER — DAY …`).
2. Click **→ Generate storyboard**, pick "1940s noir / B&W / 2.39:1", hit Generate.
3. **Mode A:** Director's Log streams *"planning 5 shots… rendering shot 1… scouting diners
   near downtown…"* → storyboard fills in → 3 real diner locations appear with map pins.

## 15. Post-hackathon roadmap

Accounts + saved projects (Firebase Auth + Firestore) · Veo animatics · full script editor ·
shot-list / call-sheet export · collaboration.
