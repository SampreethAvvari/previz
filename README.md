# Previs

**Pre-visualization for filmmakers.** A bidirectional multimodal web app:

- **Words → Pictures:** paste a scene + pick a style → an autonomous Gemini "director" agent
  produces a **storyboard** (image per shot) and **real filming-location** suggestions,
  streaming its work live.
- **Pictures → Words:** upload an image → Gemini vision returns a **screenplay** scene.

Built with Claude Code in VS Code · runs on Google's stack (Gemini + Imagen + Google Maps) ·
deploys to Cloud Run + Firebase.

## Status

🚧 Hackathon build in progress. See the design spec:
[`docs/superpowers/specs/2026-07-25-previs-design.md`](docs/superpowers/specs/2026-07-25-previs-design.md).

## Stack

| Layer | Tech |
|-------|------|
| Frontend | React + Vite + Tailwind · Firebase Hosting |
| Backend | FastAPI · Cloud Run (SSE streaming) |
| Models | Gemini 2.5 (function-calling + vision) · Imagen 3 |
| Tools | Google Maps Places (New) via MCP |

## Setup (coming as we build)

Two secrets to start:

```
GEMINI_API_KEY=…        # from Google AI Studio
GOOGLE_MAPS_API_KEY=…   # from GCP, Places API (New) enabled
```
