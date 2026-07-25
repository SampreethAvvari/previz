# Magic Hour · Architecture Design Spec

**Date:** 2026-07-25
**Status:** approved, authoritative
**Supersedes:** [`2026-07-25-previs-design.md`](2026-07-25-previs-design.md) (kept for history; see §16 for what carries forward)
**Product name:** Magic Hour. Repo is currently named `previz`; renaming is a team decision, not a blocker.
**GCP project:** `nyu-ai-builder26nyc-9338` (hackathon lab, temporary). Migration path in §15.

---

## 1. What Magic Hour is

An AI filmmaking studio. Six tools that share one story bible, so nothing drifts.

| Surface | What it does |
|---|---|
| **Bible** | The knowledge layer. Characters, scenes, locations, style. Everything else reads from it. |
| **Script** | Screenplay editor with a writing partner that knows your story and your voice. |
| **Board** | Storyboards, scene by scene and shot by shot, with characters whose faces stay the same. |
| **Cast** | A 100 question interview that turns a name into someone who can speak. |
| **Scout** | Real locations for a scene, pinned to scene numbers. |
| **Muse** | Talk through the story. Every idea lands in the right place. |

The thesis, and the thing to protect above all else: **consistency is a property of the knowledge layer, not of any single feature.** A character sounds the same in scene 18 as in scene 3 because both dialogue calls read the same canon. A face looks the same in shot 41 as in shot 2 because both image calls condition on the same locked reference sheet, and a referee measures the result. Every design decision below serves that.

### 1.1 Non-goals

Out of scope, deliberately, and not because we ran out of time:

- Video or animatics (Veo). Storyboards are still frames.
- Real time collaboration, presence, or multi user editing of one story.
- Revision colours, page locking, dual dialogue, production paperwork (call sheets, breakdowns).
- Exports beyond what the browser shows. No PDF board, no FDX writeback.
- Voice in Muse. The transport interface is kept clean so it can be added later without a rewrite (§9.6).
- Fetching copyrighted screenplays from public script sites. Users upload what they legally hold.
- Mobile layouts. Desktop first, 1280px minimum.

---

## 2. Verified environment

Everything in this section was measured, not assumed. Re-verify with `scripts/preflight.sh` and `scripts/probe-models.sh` after any project change.

### 2.1 Project and access

| | Value |
|---|---|
| Project ID | `nyu-ai-builder26nyc-9338` (note the numeric suffix; the credential card omits it) |
| Project number | `775345250143` |
| Billing | Enabled, `billingAccounts/01108A-537F1E-A5BFFC` |
| Created | 2026-07-23 |
| Roles held | `editor`, `aiplatform.admin`, `run.admin`, `bigquery.admin`, `secretmanager.admin`, `storage.admin`, `datastore.owner`, `compute.networkAdmin`, `pubsub.admin`, `source.admin` |
| Notable gap | only `serviceusage.apiKeysViewer`, so Maps API key creation may need the console or a higher role |

### 2.2 Org policies

All present but **effectively permissive**. This was worth checking, because assuming otherwise costs a VPC we do not need.

| Constraint | Effective value | Consequence |
|---|---|---|
| `run.allowedIngress` | `allValues: ALLOW` | Public Cloud Run URL is allowed |
| `iam.allowedPolicyMemberDomains` | `allValues: ALLOW` | `allUsers` can be granted |
| `sql.restrictPublicIp` | not enforced | **Cloud SQL public IP with IAM auth. No VPC, no private service access, no connector.** |
| `storage.publicAccessPrevention` | not enforced | We still use signed URLs by choice |
| `iam.disableServiceAccountKeyCreation` | not enforced | We still never create SA keys (§13, item 2) |

Read `--effective` and inspect the value. A policy object existing is not the same as a policy being enforced.

### 2.3 Model availability, measured by real calls

| Model | Result | Role |
|---|---|---|
| `gemini-2.5-pro` | 200 (`us-central1`, `global`) | Cinematographer, ScriptSupervisor, Muse, SceneArchitect |
| `gemini-2.5-flash` | 200 | Interviewer, CharacterVoice, parsers, Scout |
| `gemini-2.5-flash-lite` | 200 | Summarisation, classification, cheap judging |
| `gemini-2.5-flash-image` | 200 | **Nano Banana. All image generation.** |
| `gemini-embedding-001` | 200 | Knowledge chunk embeddings |
| `text-embedding-005`, `-004` | 200 | Fallback text embeddings |
| `multimodalembedding@001` | 200 | **Face fingerprints. The continuity referee.** |
| `gemini-3-pro-preview`, `gemini-3-flash-preview`, `gemini-3-pro-image-preview` | **404** | Not allowlisted on this project |

**Consequences.** No Nano Banana Pro, so we use `gemini-2.5-flash-image`, which does reference image character consistency, which is what we need. `gemini-flash-latest` and `gemini-pro-latest` are AI Studio aliases and **404 on Vertex**; Previs v1 uses `gemini-flash-latest` and must be repointed (§18).

Every model ID lives in exactly one file (§10) so a rename or an upgrade to Gemini 3 on a different project is a one line change.

### 2.4 APIs to enable

**Already enabled:** `aiplatform`, `bigquery*`, `storage*`, `datastore`, `iam*`, `logging`, `monitoring`, `cloudtrace`, `texttospeech`, `generativelanguage`, `sql-component`, `iap`, `modelarmor`.

**Must be enabled:** `run`, `cloudbuild`, `artifactregistry`, `sqladmin` (note: `sql-component` alone is not sufficient), `secretmanager`, `places`, `maps-backend`, `apikeys`, and `firebase` plus `identitytoolkit` only if Firebase Auth wins §13.1.

---

## 3. Architecture

```
                    Browser · Next.js 15 App Router · Tailwind · RSC + SSE
                                        │
                                        │  session cookie / ID token
                                        ▼
                    ┌───────────────────────────────────────────┐
                    │  Cloud Run · magic-hour-web               │  PUBLIC ingress
                    │  UI, auth, BFF route handlers             │  min-instances 1
                    │  owns the session, holds no model keys    │
                    └────────────────┬──────────────────────────┘
                                     │  Google-signed ID token, audience = agents URL
                                     ▼
                    ┌───────────────────────────────────────────┐
                    │  Cloud Run · magic-hour-agents            │  INTERNAL ingress
                    │  FastAPI + Google ADK                     │  not reachable publicly
                    │  agent trees, tools, SSE event stream     │  min-instances 1
                    └──┬─────────┬─────────┬─────────┬──────────┘
                       │         │         │         │
             ┌─────────┘         │         │         └──────────┐
             ▼                   ▼         ▼                    ▼
    ┌────────────────┐  ┌──────────────┐  ┌──────────┐  ┌───────────────┐
    │ Vertex AI      │  │ Cloud SQL    │  │   GCS    │  │   BigQuery    │
    │ Gemini 2.5 ×3  │  │ Postgres 16  │  │ frames   │  │ agent_runs    │
    │ Nano Banana    │  │ + pgvector   │  │ sheets   │  │ tool_calls    │
    │ 2 embed models │  │ canon+draft  │  │ uploads  │  │ generations   │
    └────────────────┘  └──────────────┘  └──────────┘  │ evals         │
                                                         └───────────────┘
             ▼                                       ▼
    ┌────────────────────────┐          ┌─────────────────────────────┐
    │ Maps Platform          │          │ MCP server · story-bible    │
    │ Places (New), Photos   │          │ consumed via ADK MCPToolset │
    └────────────────────────┘          └─────────────────────────────┘
```

**Why two services.** The browser must never hold a model key or a database credential, and the agent service must never be reachable from the internet. `magic-hour-agents` runs with `--ingress=internal`, and the only identity permitted to invoke it is `mh-web@`, verified by Google-signed ID token. This is architectural security rather than a checkbox, and it is cheap: one flag and one IAM binding.

**Why `min-instances 1` on both.** Cold starting a Python container that imports ADK and the Vertex SDK is 4 to 8 seconds. On a demo stage that reads as broken. Two warm instances cost a few dollars a day and remove the single most likely live failure.

### 3.1 Repo layout

```
previz/                          (repo; product is Magic Hour)
├─ apps/
│  ├─ web/                       Next.js 15, TypeScript, Tailwind
│  │  ├─ app/                    routes, RSC, route handlers (BFF)
│  │  ├─ components/             design system + feature UI
│  │  └─ lib/                    auth, api client, SSE client
│  └─ agents/                    Python 3.12, FastAPI, google-adk
│     ├─ magic_hour/
│     │  ├─ agents/              one module per agent tree
│     │  ├─ tools/               librarian, imagegen, places, fingerprint
│     │  ├─ context/             Continuity Pack assembly
│     │  ├─ models.py            pinned model IDs, the only place
│     │  ├─ trace.py             callbacks → BigQuery + SSE
│     │  └─ db.py                asyncpg + pgvector
│     └─ tests/
├─ packages/contracts/           JSON Schema → generated TS types + Pydantic
├─ mcp/story-bible/              MCP server exposing bible read tools
├─ db/migrations/                numbered SQL, forward only
├─ infra/                        Terraform
├─ scripts/                      preflight.sh, probe-models.sh, bootstrap.sh, seed.sh
├─ data/seed/                    character-questions.txt, demo story
├─ evals/                        golden set + runner
└─ docs/superpowers/{specs,plans}/
```

**One rule about file size.** No source file over roughly 300 lines. When a module grows past that it is doing too much, and both humans and models edit it less reliably. Split by responsibility, not by line count.

---

## 4. Data model

Cloud SQL Postgres 16, `CREATE EXTENSION vector`. Public IP, **IAM database authentication, no passwords anywhere.** Cloud Run connects through the built in Cloud SQL connector over a unix socket.

Embedding dimensions are **verified at bootstrap** by calling each model once and asserting the vector length, because a wrong dimension is a silent corruption rather than an error. Expected: text 768 (`gemini-embedding-001` with `output_dimensionality=768`), face 1408 (`multimodalembedding@001`).

```sql
-- Ownership. uid is the OIDC subject, never an email.
create table users (
  uid          text primary key,
  email        text not null,
  display_name text,
  created_at   timestamptz not null default now()
);

create table stories (
  id         uuid primary key default gen_random_uuid(),
  owner_uid  text not null references users(uid) on delete cascade,
  title      text not null,
  logline    text,
  format     text not null default 'short' check (format in ('short','feature','series')),
  summary    text,                       -- rolling summary, refreshed on scene write
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index on stories (owner_uid);

-- Taste. project_id null means the user's default card.
create table style_cards (
  id          uuid primary key default gen_random_uuid(),
  owner_uid   text not null references users(uid) on delete cascade,
  story_id    uuid references stories(id) on delete cascade,
  version     int  not null default 1,
  card        jsonb not null,            -- prose + structured axes, human editable
  metrics     jsonb,                     -- measured from uploaded scripts
  created_at  timestamptz not null default now()
);
create unique index on style_cards (owner_uid, coalesce(story_id::text,''), version);

create table characters (
  id             uuid primary key default gen_random_uuid(),
  story_id       uuid not null references stories(id) on delete cascade,
  name           text not null,
  aliases        text[] not null default '{}',
  role           text,                   -- lead, supporting, bit
  look           jsonb,                  -- frozen physical descriptor, drives prompts
  sheet_gcs      text,                   -- locked reference sheet object
  face_embedding vector(1408),           -- the fingerprint
  completeness   real not null default 0,-- 0..1 across the 7 interview parts
  created_at     timestamptz not null default now()
);
create index on characters (story_id);

-- The 100 questions, loaded from data/seed/character-questions.txt
create table questions (
  id       int primary key,
  part     text not null,                -- 'basics','growing_up','past','beliefs',
                                         -- 'relationships','likes','self'
  text     text not null,
  is_core  boolean not null default false, -- the 12 that gate usability
  weight   real not null default 1        -- contribution to completeness
);

create table character_answers (
  id           uuid primary key default gen_random_uuid(),
  character_id uuid not null references characters(id) on delete cascade,
  question_id  int  not null references questions(id),
  answer       text not null,
  source       text not null check (source in ('user','agent_drafted','agent_inferred')),
  layer        text not null check (layer in ('canon','draft')),
  created_at   timestamptz not null default now(),
  unique (character_id, question_id)
);

create table scenes (
  id           uuid primary key default gen_random_uuid(),
  story_id     uuid not null references stories(id) on delete cascade,
  number       int not null,
  order_index  int not null,
  slugline     text not null,            -- 'INT. MOTEL ROOM - NIGHT'
  int_ext      text check (int_ext in ('INT','EXT','INT/EXT')),
  place_name   text,
  time_of_day  text,
  synopsis     text,                     -- one line, feeds the scene index
  body         text not null default '', -- the screenplay text
  status       text not null default 'draft'
               check (status in ('draft','written','locked')),
  updated_at   timestamptz not null default now(),
  unique (story_id, number)
);

create table shots (
  id            uuid primary key default gen_random_uuid(),
  scene_id      uuid not null references scenes(id) on delete cascade,
  number        int not null,
  shot_size     text,                    -- ECU, CU, MCU, MS, MWS, WS, EWS
  angle         text,                    -- eye, low, high, dutch, OTS, POV
  lens          text,                    -- 18mm, 35mm, 85mm
  movement      text,                    -- static, pan, dolly, handheld, crane
  subject       text,
  description   text not null,
  prompt        text,                    -- exact prompt sent, for reproducibility
  style_preset  text check (style_preset in ('animation','realistic','pencil')),
  image_gcs     text,
  face_scores   jsonb,                   -- {character_id: cosine}
  version       int not null default 1,
  supersedes    uuid references shots(id) on delete set null,
  status        text not null default 'planned'
                check (status in ('planned','generating','ready','flagged','failed')),
  created_at    timestamptz not null default now(),
  unique (scene_id, number, version)
);

create table locations (
  id           uuid primary key default gen_random_uuid(),
  story_id     uuid not null references stories(id) on delete cascade,
  place_id     text,                     -- Google Places id
  name         text not null,
  address      text,
  lat          double precision,
  lng          double precision,
  photos       jsonb not null default '[]',  -- [{gcs, attribution, width, height}]
  notes        text,
  shortlisted  boolean not null default false,
  created_at   timestamptz not null default now()
);
create index on locations (story_id);

create table scene_locations (
  scene_id    uuid references scenes(id) on delete cascade,
  location_id uuid references locations(id) on delete cascade,
  primary key (scene_id, location_id)
);

-- Retrieval index. DERIVED. Written in the same transaction as its source row.
create table knowledge_chunks (
  id           uuid primary key default gen_random_uuid(),
  story_id     uuid not null references stories(id) on delete cascade,
  entity_type  text not null check (entity_type in
                 ('character','scene','shot','location','style','story','note')),
  entity_id    uuid,
  layer        text not null check (layer in ('canon','draft')),
  text         text not null,
  embedding    vector(768),
  tsv          tsvector generated always as (to_tsvector('english', text)) stored,
  source_ref   text,                     -- 'character_answers:<uuid>' etc
  created_by   text,                     -- agent name, or 'user'
  created_at   timestamptz not null default now()
);
create index on knowledge_chunks (story_id, layer);
create index on knowledge_chunks using gin (tsv);
create index on knowledge_chunks using hnsw (embedding vector_cosine_ops);

-- The approval queue. Agents write here, never to canon.
create table fact_proposals (
  id            uuid primary key default gen_random_uuid(),
  story_id      uuid not null references stories(id) on delete cascade,
  entity_type   text not null,
  entity_id     uuid,
  field         text not null,
  proposed      jsonb not null,
  rationale     text not null,           -- why the agent believes it
  source_agent  text not null,
  source_run_id text,                    -- joins to BigQuery agent_runs
  status        text not null default 'pending'
                check (status in ('pending','accepted','rejected')),
  created_at    timestamptz not null default now(),
  decided_at    timestamptz
);
create index on fact_proposals (story_id, status);

create table assets (              -- uploaded scripts and reference images
  id         uuid primary key default gen_random_uuid(),
  story_id   uuid not null references stories(id) on delete cascade,
  kind       text not null check (kind in ('script_pdf','script_text','script_fdx','image')),
  gcs        text not null,
  filename   text,
  bytes      bigint,
  created_at timestamptz not null default now()
);
```

### 4.1 The one invariant that matters

**A structured row and its knowledge chunks are written in the same transaction, or neither is written.** Implemented as a single `reindex_entity(conn, entity_type, entity_id)` call inside every write path, not as a trigger and not as a background job. A fact and its embedding cannot disagree, because there is no window in which they could.

Consequence to accept: writes are slower by one embedding call. That is the correct trade. An eventually consistent index is exactly the bug class this product exists to avoid.

### 4.2 Ownership enforcement

Every query filters on `owner_uid` derived from the verified session, never from a request parameter. The agents service receives `story_id` plus the caller's `uid` and re-checks ownership on entry. There is no code path where a `story_id` alone grants access.

---

## 5. The knowledge base

### 5.1 Two layers

| Layer | Who writes | How it is retrieved |
|---|---|---|
| `canon` | the user only, by promoting a proposal or typing directly | injected as hard fact; agents must not contradict it |
| `draft` | any agent, freely | injected labelled `unconfirmed`; usable, never settled |

Agents have no write path to canon. They call `propose_fact`, which lands in `fact_proposals` with a rationale and the run id that produced it. The **Canon strip** in the UI shows pending proposals with their source; one click promotes, which writes the structured row and reindexes in one transaction.

Anything the user typed themselves is canon immediately. The queue exists for inference, not for typing.

### 5.2 Chunking

Chunks are semantic units, not fixed windows:

- one chunk per answered interview question (`Maya · greatest fear · ...`)
- one chunk per scene synopsis, plus one per 40 line span of scene body
- one chunk per character `look` descriptor
- one chunk per location with its notes
- one chunk per style card axis

Every chunk carries a human readable prefix naming its entity, which makes both lexical search and model comprehension better than a bare fragment.

### 5.3 Hybrid retrieval

Every search runs pgvector cosine and Postgres `tsvector` in one statement and fuses by reciprocal rank (`k = 60`), canon boosted over draft.

Pure vector search fails on exactly the things screenplays are made of. `INT. MOTEL ROOM - NIGHT` and "the motel" are the same place but not neighbours in embedding space, and character names demand exact matching. Two retrievers in one database, one query, no second system to keep in sync.

### 5.4 The Continuity Pack

One function assembles context for every model call in the product. Fixed slots, fixed budgets, deterministic, logged.

| Slot | Contents | Budget |
|---|---|---|
| `style` | style card, prose plus axes | 400 |
| `spine` | logline, rolling summary, full scene index (number, slugline, synopsis) | 700 |
| `cast` | canon block per character or location in scope | 300 each |
| `retrieved` | hybrid search top k, canon first, draft flagged | 800 |
| `local` | tail of the previous scene, current scene so far | 600 |
| `turn` | recent conversation, chat surfaces only | 600 |

Overflow drops the lowest priority slot content first (`retrieved`, then `local`, then `turn`), never `style` or `cast`. The assembled pack, its slot sizes, and every chunk id are recorded on the run and rendered in the **Context** tab, each chunk clickable back to its source row.

This is context management as a visible, debuggable artifact. It is also how a bad line gets diagnosed in five seconds instead of twenty minutes.

---

## 6. Character consistency

The hardest problem in the product. Four stages.

**1 · Casting.** Before any storyboarding, each character is cast. `PortraitArtist` generates four candidates from the character's canon `look` plus the story's visual style. The user picks one.

**2 · Lock the sheet.** The chosen portrait is regenerated as a small reference sheet (front, three quarter, profile) on a neutral background, with a frozen wardrobe note. Stored at `characters.sheet_gcs`. This is the identity of record.

**3 · Condition every shot on it.** Every image call for a shot containing that character receives the reference sheet as an input image alongside the prompt, plus the frozen text descriptor. Within a scene, the previously approved shot is also passed, so lighting, wardrobe state and blocking carry forward.

**4 · Referee the result.** After generation, the frame is embedded with `multimodalembedding@001` and compared by cosine to `characters.face_embedding`. Below threshold means drift: regenerate once with a stronger reference emphasis, then a second time, then flag rather than burn money. Scores are written to `shots.face_scores` and streamed to BigQuery.

**Why embeddings are the referee and not the conditioner.** You cannot feed a vector into an image model. Image models condition on reference images and text. So the embedding does the job it is actually good at: measuring whether the output matches the intended identity. That turns consistency from a claim into a number, which is also §14's accuracy metric.

**Thresholds are calibrated, not guessed.** During integration we generate 20 frames of a cast character and 20 of a different person, then set the threshold between the distributions. The calibration run and the chosen value are recorded in `evals/`.

---

## 7. Script import

Four input paths converge on the same structured `scenes` rows.

| Format | Method |
|---|---|
| **Fountain / plain text** | Deterministic parser. Fountain is the plain text screenplay standard, so this path is exact and has no failure modes. Preferred for demo reliability. |
| **PDF** | Two pass. First a deterministic slugline prescan (`^(INT|EXT|INT/EXT)[\. ].*(DAY|NIGHT|...)`) establishes scene boundaries as ground truth. Then Gemini 2.5 Flash fills structure within those boundaries with a JSON response schema. The model never decides where a scene starts. |
| **Final Draft `.fdx`** | XML, exact parse, no model. |
| **Written in app** | Already structured. No parser. |

Handled explicitly because real screenplays contain them: title pages, `(CONT'D)`, `(MORE)`, page breaks mid scene, dual dialogue, revision marks, and scene numbers in both margins.

Parsed output is always shown for confirmation before it is committed. An import that silently mis-splits 22 scenes into 31 is worse than one that asks.

---

## 8. Location scouting

Deliberately simple. Places, photos, coordinates, shortlist. No permits, no fees, no enrichment.

1. The user describes what the scene needs, with a city or region and optional budget note.
2. `Scout` turns that into one or more Places `searchText` queries.
3. Results return as cards: name, address, real coordinates, rating, opening hours, and photos fetched through Places Photos and cached to GCS. Caching matters, because Places photo URLs expire and a demo cannot depend on a fresh fetch.
4. Shortlisting writes a `locations` row and reindexes it into the bible.
5. Attaching to scene numbers writes `scene_locations`.

Because shortlisted places are in the bible, the Script Room can later offer: you saved the Bushwick rooftop, want scene 14 there. That link between two features is the whole point of a shared knowledge layer.

Attribution from Places is preserved and displayed, as the terms require.

---

## 9. The agents

Built on Google ADK. One tree per surface. Every agent gets the Librarian tools.

### 9.1 Librarian · the shared tool layer

Not an LLM. The only way any agent touches the bible.

| Tool | Contract |
|---|---|
| `search_bible(story_id, query, k, layers)` | hybrid search, returns chunks with layer, score, source_ref |
| `get_canon(story_id, entity_type, entity_id)` | full canon block for one entity |
| `get_scene_index(story_id)` | every scene: number, slugline, synopsis, status |
| `write_draft(story_id, entity_type, entity_id, text)` | append to the draft layer |
| `propose_fact(story_id, entity_type, entity_id, field, value, rationale)` | queue for approval |

`promote_fact` is a user action over HTTP, not a tool. No agent can reach it.

### 9.2 Script Room

- **`SceneArchitect`** · `gemini-2.5-pro`. Given intent, produces the scene's purpose, beats, and slugline. Writes no prose. Output is a JSON schema, so it cannot drift into writing the scene.
- **`ActionWriter`** · `gemini-2.5-pro`. Writes **exactly one action paragraph** per call. Enforced by response schema (`{action: string}`), not by asking politely in a prompt. This is how "no slop" becomes a guarantee rather than a hope.
- **`DialogueDirector`** · custom ADK agent. Reads who is present, then **compiles one `CharacterVoice` LlmAgent per character at request time**, system prompt built from that character's canon answers: voice, frequent phrases, honesty, what they want, what they hide, what they refuse. Runs them as a `ParallelAgent` for candidate lines, then sequences the exchange. If a character has no usable knowledge (fewer than the 12 core answers) it **refuses and offers to open the interview** rather than inventing a person.
- **`ScriptSupervisor`** · `gemini-2.5-pro` inside a `LoopAgent`, max 2 iterations. Runs after every write. Checks new text against canon for: knowledge violations (a character knows something not yet established), prop and wardrobe contradictions, time of day mismatches, and voice drift. Violations return to the writer as structured feedback. **This is the reasoning loop, and it is load bearing rather than decorative.**

### 9.3 Camera Department

`SceneParser` → `Cinematographer` (`gemini-2.5-pro`, produces the shot list with size, angle, lens, movement, subject) → **user edits the list as cheap text** → `ShotPromptWriter` (composes prompt from shot, style preset, character sheets, location photo if attached) → Nano Banana → `ContinuityReferee` in a `LoopAgent` (§6 stage 4).

All deciding happens in text before any image is paid for, because text iteration is instant and free and image iteration is neither.

### 9.4 Casting

`Interviewer` (`gemini-2.5-flash`, adaptive: asks the 12 core questions first, follows up on interesting answers, skips what canon already implies) → `Ghostwriter` (`gemini-2.5-pro`, drafts remaining answers in the character's established voice as editable cards, marked `agent_drafted`) → `PortraitArtist` → `Fingerprint`.

The completeness meter shows which of the seven parts are thin, because thin knowledge is exactly what makes dialogue generic.

### 9.5 Scout

`gemini-2.5-flash` with the Places tools and the Librarian. Turns scene needs into queries, returns cards, writes shortlists.

### 9.6 Muse

`gemini-2.5-pro`, temperature high, every Librarian tool, plus ADK handoff to `Interviewer` or `Scout` mid conversation. Its job: ask what you are going for, throw scenarios, collide characters, break blocks, and file everything in the right place as it goes. It writes freely to draft and proposes canon. It does not write script and does not generate images.

**Transport seam for later voice.** Muse's HTTP surface is `POST /muse/turn` taking `{text}` and returning an SSE event stream. A future voice mode replaces the transport only. No agent, tool, or context code changes.

**Safety posture, stated honestly.** All creative calls run Vertex safety at `BLOCK_ONLY_HIGH`, the loosest setting available, with system prompts establishing that fiction depicting violence, cruelty and moral failure is legitimate craft. This unlocks genuinely dark material, and most refusals people hit are prompt framing rather than policy. What it does not do is disable the filters: Vertex will still refuse explicit sexual content and a narrow band of extreme material. Recorded here so nobody discovers it on stage.

### 9.7 Instrumentation, written once

ADK callbacks (`before_agent`, `after_agent`, `before_model`, `after_model`, `before_tool`, `after_tool`) all feed one `trace.py` writer that fans out to:

- **BigQuery**, batched and async, never on the request path
- **the SSE stream**, so the UI Trace tab shows agent thinking live

One piece of code delivers the monitoring story, the agentic visibility story, and the removal of every spinner from the demo.

---

## 10. Model configuration

`apps/agents/magic_hour/models.py` is the **only** place a model ID appears. Nowhere else in the codebase, including tests, prompts, or docs that get copied into code.

```python
LOCATION = "us-central1"

REASONING = "gemini-2.5-pro"          # architect, cinematographer, supervisor, muse
FAST      = "gemini-2.5-flash"        # interviewer, character voices, parsers, scout
CHEAP     = "gemini-2.5-flash-lite"   # summaries, classification, judging
IMAGE     = "gemini-2.5-flash-image"  # nano banana
EMBED_TEXT      = "gemini-embedding-001"      # output_dimensionality=768
EMBED_MULTIMODAL = "multimodalembedding@001"  # 1408

# Verified against nyu-ai-builder26nyc-9338 on 2026-07-25 by scripts/probe-models.sh.
# Gemini 3 (gemini-3-pro-preview, gemini-3-pro-image-preview) returns 404 on this
# project. On a project where it is allowlisted, REASONING and IMAGE are the only
# two lines that change.
```

`scripts/probe-models.sh` runs in CI against the live project and fails the build if a pinned model stops answering. A model deprecation should break a pipeline, not a demo.

---

## 11. API contracts

The web service is a BFF. The browser calls only `/api/*` on the web service. Types are generated from JSON Schema in `packages/contracts/` into both TypeScript and Pydantic, so a contract change breaks the build on both sides rather than at runtime.

### 11.1 Web routes (browser facing)

| Route | Purpose |
|---|---|
| `GET  /api/stories` · `POST /api/stories` | list, create |
| `GET  /api/stories/:id/bible?q=` | hybrid search over the bible |
| `GET  /api/stories/:id/proposals` · `POST /api/proposals/:id/promote` · `/reject` | the Canon strip |
| `POST /api/stories/:id/import` | multipart upload, returns parsed scenes for confirmation |
| `POST /api/stories/:id/scenes/:n/write` (SSE) | Script Room, mode `action` or `dialogue` |
| `POST /api/stories/:id/scenes/:n/shots` (SSE) | Cinematographer shot list |
| `POST /api/shots/:id/render` (SSE) | generate or regenerate one shot |
| `POST /api/characters` · `POST /api/characters/:id/interview` (SSE) | Cast |
| `POST /api/characters/:id/cast` (SSE) | portrait candidates, then lock sheet |
| `POST /api/stories/:id/scout` (SSE) | location search |
| `POST /api/stories/:id/muse` (SSE) | brainstorm turn |
| `GET  /api/evals` | metrics dashboard data |

### 11.2 SSE event envelope

One envelope for every stream, so the client has one parser and the Trace tab renders everything without special cases.

```ts
type Event =
  | { t:'run_start';   run_id:string; agent:string }
  | { t:'thinking';    run_id:string; agent:string; text:string }
  | { t:'tool_call';   run_id:string; agent:string; tool:string; args:unknown }
  | { t:'tool_result'; run_id:string; tool:string; summary:string; ms:number }
  | { t:'context';     run_id:string; slots:Record<string,number>; chunk_ids:string[] }
  | { t:'partial';     run_id:string; field:string; text:string }
  | { t:'shot_ready';  run_id:string; shot_id:string; url:string;
                       face_scores:Record<string,number> }
  | { t:'proposal';    run_id:string; proposal_id:string; field:string; rationale:string }
  | { t:'violation';   run_id:string; kind:string; detail:string; iteration:number }
  | { t:'run_end';     run_id:string; ms:number; tokens:number; usd:number }
  | { t:'error';       run_id:string; message:string; retryable:boolean }
```

Previs v1's event model (`shot_planned`, `image_ready`, `location_found`, `done`) maps onto this cleanly, and its shape informed the design (§16).

---

## 12. Design system

Derived from the existing `sampreethavvari.github.io` design system, which already settles the visual language: Apple neutral palette, near black dark mode, WebGL starfield, glass panels, per section accents.

**Concept.** Magic hour is the only time you see the last warm light and the first stars together. Background is the existing `SpaceField` WebGL starfield at ~0.35 opacity with scroll warp and nebula churn removed, over a fixed gradient from `#0B1020` at top to an 8 percent `#F5A524` bloom at the bottom edge. It never moves fast, so it never competes with content.

**Palette.** Surfaces `#000` / `#0A0A0C`, text `#F5F5F7`, glass panels. Per surface accent, used only on the active rail item and one panel edge glow: Board `#F5A524`, Script `#5B8DEF`, Scout `#34D399`, Cast `#A78BFA`, Muse `#22D3EE`, Bible warm white. Body copy stays neutral.

**Type.** SF Pro / Inter for the app. **Courier Prime for the screenplay editor**, because screenplays are Courier 12pt by convention and every filmmaker recognises it instantly.

**Motion.** 180ms ease out. `prefers-reduced-motion` fully respected. The only expressive animation is frames blooming in as they arrive.

**Layout.** Left icon rail (story switcher, then the six surfaces, collapses to 56px), centre workspace showing one surface at a time, right inspector drawer with three tabs: **Context**, **Trace**, **Canon**. Desktop first, 1280px minimum.

**Screenplay editor.** Element cycling on Tab and Enter across scene heading, action, character, parenthetical, dialogue, transition, matching industry muscle memory. Correct margins. The AI panel sits beside it and writes one element at a time, never a whole scene.

---

## 13. Security

1. **No secret reaches the browser.** Model calls and database access happen only in `magic-hour-agents`. The web service holds a session key and nothing else.
2. **No service account keys, ever.** GitHub Actions authenticates by Workload Identity Federation. Cloud Run uses attached service accounts. There is no JSON key to leak.
3. **The agents service is not on the internet.** `--ingress=internal`, invocable only by `mh-web@` with a Google signed ID token whose audience is checked.
4. **Least privilege.** `mh-web@`: `run.invoker` on agents, nothing else. `mh-agents@`: `aiplatform.user`, `cloudsql.client`, `storage.objectAdmin` scoped to one bucket, `bigquery.dataEditor` scoped to one dataset. `mh-ci@`: deploy only.
5. **Database auth is IAM.** No password exists to steal or rotate.
6. **Storage is private.** Uniform bucket access, no public objects, time limited signed URLs for reads.
7. **Secrets in Secret Manager**, mounted at deploy. Never in git, never in an image layer.
8. **Public repo discipline.** `gitleaks` as a pre-commit hook and as a required CI job. `.gitignore` covers `.env*`, `*-sa.json`, `*.tfvars`, `*.pem`.
9. **Ownership on every query**, from the verified session, never from a request parameter.
10. **Generation caps.** Hard per story and per hour limits on image generation, enforced server side, so a loop bug cannot spend the budget.

### 13.1 Authentication, with the decision explicitly open

Two candidates, resolved in the first hour by testing which enables cleanly on the lab project:

- **Preferred: Firebase Auth**, Google sign in. Handles the OAuth consent screen for us. Needs `firebase.googleapis.com` and `identitytoolkit.googleapis.com`, neither currently enabled.
- **Fallback: Auth.js v5** with a Google OAuth client created in this project, session as an encrypted JWT cookie. No extra GCP service, but requires configuring the consent screen by hand.

Either way `users.uid` is the OIDC `sub`, never the email, and the rest of the system is unaffected. Whichever wins, the loser is documented as the migration path.

---

## 14. Observability and accuracy

Traces stream to BigQuery `magic_hour_telemetry`: `agent_runs`, `tool_calls`, `generations`, `evals`. Cloud Logging and Cloud Trace on both services. One alert: agent error rate over 5 percent for 5 minutes.

**Five metrics on a golden set**, run by `evals/run.py`, results in BigQuery, rendered on `/evals`:

| Metric | Method | Target |
|---|---|---|
| **Face identity** | cosine of each generated frame against the character fingerprint; report mean and min | mean ≥ 0.80, min ≥ 0.65 |
| **Continuity violations caught** | ScriptSupervisor findings per 100 lines on a corpus with 10 deliberately seeded contradictions | ≥ 8 of 10 caught |
| **Voice fidelity** | `gemini-2.5-flash-lite` as judge, scoring generated dialogue against that character's canon, 1 to 5, blind to which character generated it | mean ≥ 4.0 |
| **Grounding coverage** | share of asserted facts traceable to a retrieved chunk | ≥ 0.90 |
| **Latency and cost** | p50 and p95 per surface, USD per run | board ≤ 45s for 6 shots |

Targets are commitments to measure against, not predictions. A missed target is a finding to report, not a number to quietly adjust.

---

## 15. Infrastructure and CI/CD

**Terraform** in `infra/` covers: APIs, three service accounts and their bindings, Cloud SQL instance with the `vector` extension, GCS bucket with uniform access, BigQuery dataset and tables, Secret Manager secrets, Artifact Registry, both Cloud Run services, the WIF pool and provider. GCS remote state.

**`scripts/bootstrap.sh`** recreates the entire stack in an empty project in under ten minutes. This exists because the lab project is temporary and can be revoked without warning.

**Pipeline.** Push to `main` → GitHub Actions → WIF auth → Cloud Build both images → deploy with `--no-traffic` → run migrations as a Cloud Run job → smoke test the new revision URL → migrate traffic to 100 percent. Pull requests run lint, typecheck, unit tests, `gitleaks`, `probe-models.sh`, and post `terraform plan`.

**Migrations** are numbered, forward only, and idempotent. No down migrations; in 48 hours a bad migration is fixed by a new migration.

**Fallback if WIF cannot be configured** on the lab project: a Cloud Build trigger connected to the GitHub repo, running inside the project. Same pipeline, different runner, still no keys.

---

## 16. What carries forward from Previs v1

Sahaj's v1 (`sahajm99/previz`, 223 lines) proved the storyboard path. It is a spike, and its judgment is worth keeping even where its code is not.

**Adopted:**
- `places:searchText` with the `X-Goog-FieldMask` header. Correct use of Places New; becomes the basis of the Scout tool.
- The SSE event model shape. Directly informed §11.2.
- The `StylePreset` object. Becomes the `style_preset` enum plus the story visual style block.
- Placeholder on failure rather than a broken card.
- The demo safety instincts: bounded loops, hard caps, cached fallbacks. Promoted into §13 item 10 and the rehearsal plan.
- **Image to screenplay.** Not in the original six surfaces and worth keeping. It becomes a "write a scene here" action on a location card and on any uploaded image, feeding straight into the Script editor. Genuinely multimodal, cheap, and it pairs with Scout: photograph a place, get a scene.

**Must change:**
- **Client.** `genai.Client(api_key=...)` targets AI Studio. Magic Hour uses Vertex AI with ADC. Same SDK, different constructor.
- **Model ID.** `TEXT_MODEL = "gemini-flash-latest"` **404s on Vertex**; it is an AI Studio only alias. Repoint to `gemini-2.5-flash` from `models.py`.
- **Persistence.** v1 holds no state. Every artifact now writes to Postgres and GCS. Images move from base64 data URLs to GCS objects with signed URLs, because data URLs will not survive a real board.
- **Shot planning.** v1 asks for `n` shot descriptions in one call. Replaced by `Cinematographer` producing a structured, user editable shot list with size, angle, lens and movement (§9.3).
- **Character consistency.** Absent in v1 and the single most important addition (§6).

**Superseded:** the v1 spec's non-goals ("no accounts, no persistence, no script editor") are Magic Hour's core requirements. The old spec stays in the repo for history.

---

## 17. Risks

| Risk | Severity | Mitigation |
|---|---|---|
| **Lab project revoked mid build or mid demo** | high | `bootstrap.sh` rebuilds everything in a new project in under 10 minutes; nightly SQL dump committed as seed data; no project ID hardcoded outside one config |
| **Two repos, two specs, split team** | high | this spec lands in Sahaj's repo as a PR; every surface has a module contract so nobody waits for permission to start |
| **Maps API key cannot be created** (`apiKeysViewer` only) | medium | create it by hand in the console, or get `apiKeysAdmin`; Scout degrades to cached demo locations if neither works |
| **Nano Banana latency on a 6 shot board** | medium | parallel generation, frames stream in as they land, demo board precomputed so live generation is one deliberate regenerate |
| **Face threshold miscalibrated** | medium | calibrate on 40 frames before trusting it (§6); until calibrated, show the score and do not auto reject |
| **Gemini 3 unavailable** | low | 2.5 covers everything; two lines change if a project has 3 |
| **Vertex safety refusal on dark material** | low | `BLOCK_ONLY_HIGH` plus craft framing; limits documented in §9.6 so they are not a surprise |
| **PDF parse mis-splits scenes** | low | deterministic slugline prescan owns boundaries; parse always confirmed before commit |

---

## 18. Open questions

1. **Lab project expiry.** Unknown. Determines how hard we lean on `bootstrap.sh`.
2. **Auth provider.** Firebase Auth or Auth.js (§13.1). Resolved by testing which enables on this project.
3. **Repo name.** Product is Magic Hour, repo is `previz`. Team decision, not a blocker.
4. **Push access.** `SampreethAvvari` has pull only on `sahajm99/previz`. Work proceeds by fork and PR until collaborator access is granted.
5. **Embedding dimensions.** Expected 768 and 1408, asserted at bootstrap rather than trusted.
6. **Demo script and test PDF.** Sampreeth is supplying a real screenplay. Seed data and the parser fixture depend on it.
7. **Hackathon submission requirements.** Unknown. May add required tags, a video, or a specific product.
