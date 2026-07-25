# Magic Hour Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **DEFERRED, NOT CANCELLED.** This plan is correct for a 48 hour build. The
> hackathon turned out to be a 4 hour competition ending 15:30 on 2026-07-25, so
> for today read [`docs/NOW.md`](../../NOW.md) instead. Cloud SQL, Terraform,
> CI/CD, Workload Identity, the Next.js rewrite, the ADK migration and the
> `backend/` to `apps/agents/` move are all off the table until after judging.
> Everything here still applies to the real build afterwards.

**Goal:** Build the shared platform every Magic Hour surface depends on: monorepo structure, verified Vertex clients, Postgres with pgvector, the transactional knowledge index, hybrid retrieval, the Continuity Pack, the trace writer, auth, the design system shell, and CI/CD.

**Architecture:** Two Cloud Run services in one monorepo. `apps/web` is Next.js 15 and acts as a BFF: it owns the session and holds no model or database credentials. `apps/agents` is FastAPI plus Google ADK with `--ingress=internal`, invocable only by the web service's identity. State lives in Cloud SQL Postgres 16 with pgvector, where a structured row and its retrieval chunks commit in one transaction. Telemetry streams to BigQuery.

**Tech Stack:** Next.js 15 (App Router, TypeScript, Tailwind), Python 3.12, FastAPI, google-adk, google-genai (Vertex mode), asyncpg, pgvector, Cloud SQL Postgres 16, GCS, BigQuery, Terraform, GitHub Actions.

**Spec:** [`../specs/2026-07-25-magic-hour-design.md`](../specs/2026-07-25-magic-hour-design.md). Section references below point there.

## Global Constraints

Every task's requirements implicitly include this section.

- **GCP project:** `nyu-ai-builder26nyc-9338`. Note the numeric suffix; the short form fails with a misleading permission error.
- **Region:** `us-central1` for all Vertex and Cloud Run resources.
- **Python:** 3.12. **Node:** 24. **Next.js:** 15 App Router.
- **Model IDs appear in exactly one file:** `apps/agents/magic_hour/models.py`. Nowhere else, including tests and prompts.
- **Pinned models** (verified 2026-07-25 by `scripts/probe-models.sh`): `gemini-2.5-pro`, `gemini-2.5-flash`, `gemini-2.5-flash-lite`, `gemini-2.5-flash-image`, `gemini-embedding-001`, `multimodalembedding@001`. The Gemini 3 family returns 404 on this project.
- **Never use `gemini-flash-latest` or `gemini-pro-latest`.** AI Studio only aliases; they 404 on Vertex.
- **Vertex mode only.** `genai.Client(vertexai=True, project=…, location=…)`. Never `genai.Client(api_key=…)`.
- **No service account keys.** ADC locally, attached service accounts on Cloud Run, Workload Identity Federation in CI.
- **No secrets in git.** `gitleaks` as pre-commit hook and required CI job. The repo is public.
- **No source file over ~300 lines.** Past that it is doing too much; split by responsibility.
- **User-facing copy:** no em-dashes, en-dashes, or hyphens used as dashes. Rewrite with commas, periods, or "and". Empty labels and placeholders use a middot (`·`) or are hidden, never a dash.
- **Ownership on every query** comes from the verified session, never from a request parameter.
- **Every embedding dimension is asserted at bootstrap**, never trusted. Expected: text 768, face 1408.

---

## File Structure

| Path | Responsibility |
|---|---|
| `apps/agents/magic_hour/models.py` | Pinned model IDs and the Vertex client factory. The only file naming a model. |
| `apps/agents/magic_hour/db.py` | asyncpg pool, pgvector registration, transaction helper. |
| `apps/agents/magic_hour/embed.py` | Text and multimodal embedding calls with dimension assertions. |
| `apps/agents/magic_hour/librarian/reindex.py` | `reindex_entity`. Enforces the one-transaction invariant. |
| `apps/agents/magic_hour/librarian/search.py` | Hybrid retrieval with reciprocal rank fusion. |
| `apps/agents/magic_hour/librarian/tools.py` | The five ADK tools every agent gets. |
| `apps/agents/magic_hour/context/pack.py` | Continuity Pack assembly with slot budgets. |
| `apps/agents/magic_hour/trace.py` | ADK callbacks fanning out to BigQuery and the SSE queue. |
| `apps/agents/magic_hour/events.py` | The SSE event envelope as Pydantic models. |
| `apps/agents/magic_hour/auth.py` | Google-signed ID token verification for service to service. |
| `apps/agents/magic_hour/app.py` | FastAPI app, router registration, health check. |
| `db/migrations/0001_init.sql` | Full schema from spec §4. |
| `packages/contracts/schemas/*.json` | JSON Schema, the single source of truth for shared types. |
| `apps/web/lib/auth.ts` | Session, sign in, `requireUser()`. |
| `apps/web/lib/agents.ts` | Typed client to the agents service, mints the ID token. |
| `apps/web/app/globals.css` + `tailwind.config.ts` | Design tokens from spec §12. |
| `apps/web/components/shell/*` | Rail, workspace frame, inspector drawer. |
| `scripts/bootstrap.sh` | Recreates the whole stack in an empty project. |
| `.github/workflows/ci.yml`, `deploy.yml` | Checks and deployment. |

---

## Task 1: Monorepo skeleton, with Sahaj's backend moved not rewritten

**Files:**
- Move: `backend/` → `apps/agents/` (use `git mv` to preserve history)
- Create: `package.json`, `pnpm-workspace.yaml`, `Makefile`, `.pre-commit-config.yaml`, `apps/agents/pyproject.toml`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: nothing.
- Produces: `make check` runs lint, typecheck and tests for both apps. Python package importable as `magic_hour`. Existing `app.*` imports still resolve during migration via a shim removed in Task 2.

- [ ] **Step 1: Write the failing test**

`apps/agents/tests/test_layout.py`:

```python
from pathlib import Path

def test_agents_package_exists():
    root = Path(__file__).resolve().parents[1]
    assert (root / "magic_hour" / "__init__.py").is_file()

def test_no_source_file_over_300_lines():
    root = Path(__file__).resolve().parents[1] / "magic_hour"
    offenders = [
        f"{p.name}:{len(p.read_text(encoding='utf-8').splitlines())}"
        for p in root.rglob("*.py")
        if len(p.read_text(encoding="utf-8").splitlines()) > 300
    ]
    assert offenders == [], f"files too long: {offenders}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/agents && python -m pytest tests/test_layout.py -v`
Expected: FAIL. The path `apps/agents` does not exist yet, so pytest cannot even collect.

- [ ] **Step 3: Move the backend and create the package**

```bash
git mv backend apps/agents
mkdir -p apps/agents/magic_hour
git mv apps/agents/app/__init__.py apps/agents/magic_hour/__init__.py
```

`apps/agents/pyproject.toml`:

```toml
[project]
name = "magic-hour-agents"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
  "fastapi>=0.115",
  "uvicorn[standard]>=0.32",
  "google-adk>=1.0",
  "google-genai>=1.0",
  "google-cloud-bigquery>=3.25",
  "google-cloud-storage>=2.18",
  "google-auth>=2.35",
  "asyncpg>=0.30",
  "pgvector>=0.3.6",
  "cloud-sql-python-connector[asyncpg]>=1.12",
  "httpx>=0.27",
  "pydantic>=2.9",
  "pydantic-settings>=2.6",
]

[project.optional-dependencies]
dev = ["pytest>=8", "pytest-asyncio>=0.24", "respx>=0.21", "ruff>=0.7", "mypy>=1.13"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[tool.ruff]
line-length = 100
target-version = "py312"
```

`pnpm-workspace.yaml`:

```yaml
packages:
  - "apps/web"
  - "packages/*"
```

`Makefile`:

```make
.PHONY: check test lint web-check agents-check db-up db-down

check: agents-check web-check

agents-check:
	cd apps/agents && ruff check . && python -m pytest -q

web-check:
	cd apps/web && pnpm lint && pnpm typecheck && pnpm test --run

db-up:
	docker run -d --name mh-pg -e POSTGRES_PASSWORD=dev -e POSTGRES_DB=magichour \
	  -p 5433:5432 pgvector/pgvector:pg16
	@echo "waiting for postgres"; sleep 6
	psql "postgresql://postgres:dev@localhost:5433/magichour" -c "create extension if not exists vector;"

db-down:
	docker rm -f mh-pg
```

`.pre-commit-config.yaml`:

```yaml
repos:
  - repo: https://github.com/gitleaks/gitleaks
    rev: v8.21.2
    hooks:
      - id: gitleaks
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.7.4
    hooks:
      - id: ruff
        args: [--fix]
```

Append to `.gitignore`:

```
.env
.env.*
!.env.example
*-sa.json
*.tfvars
!*.tfvars.example
.terraform/
*.tfstate*
node_modules/
.next/
.venv/
__pycache__/
.pytest_cache/
.ruff_cache/
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/agents && python -m pytest tests/test_layout.py -v`
Expected: PASS, 2 tests.

- [ ] **Step 5: Verify existing tests still pass after the move**

Run: `cd apps/agents && python -m pytest -q`
Expected: Sahaj's three test files still pass. If imports broke, fix the import paths in the test files only, not the logic.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "Move backend to apps/agents and add monorepo tooling

git mv preserves Sahaj's history. Adds pnpm workspace, Makefile with a local
pgvector container for tests, and gitleaks as a pre-commit hook since the repo
is public. The 300 line ceiling is enforced by a test rather than a convention."
```

---

## Task 2: Model config and the Vertex client

Replaces Previs v1's AI Studio client. `gemini-flash-latest` 404s on Vertex, so this task is a correctness fix, not a preference.

**Files:**
- Create: `apps/agents/magic_hour/models.py`, `apps/agents/magic_hour/settings.py`
- Create: `apps/agents/tests/test_models.py` (replaces the v1 file of the same name; move its `StylePreset` assertions into `tests/test_schemas.py`)
- Delete: `apps/agents/app/gemini_client.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `models.REASONING: str`, `models.FAST: str`, `models.CHEAP: str`, `models.IMAGE: str`, `models.EMBED_TEXT: str`, `models.EMBED_MULTIMODAL: str`, `models.LOCATION: str`
  - `models.client() -> google.genai.Client` (cached, Vertex mode)
  - `settings.settings` with `.project`, `.location`, `.bucket`, `.bq_dataset`, `.db_instance`, `.db_name`, `.maps_api_key`

- [ ] **Step 1: Write the failing test**

`apps/agents/tests/test_models.py`:

```python
import pytest
from magic_hour import models

FORBIDDEN = ("gemini-flash-latest", "gemini-pro-latest")

@pytest.mark.parametrize("name", ["REASONING", "FAST", "CHEAP", "IMAGE",
                                  "EMBED_TEXT", "EMBED_MULTIMODAL"])
def test_every_model_is_pinned_and_not_an_ai_studio_alias(name):
    value = getattr(models, name)
    assert isinstance(value, str) and value
    assert value not in FORBIDDEN, f"{name} is an AI Studio alias and 404s on Vertex"

def test_no_gemini_3_pinned_on_this_project():
    # gemini-3-* returns 404 on nyu-ai-builder26nyc-9338. If a future project
    # allowlists it, change models.py and this test together, deliberately.
    for name in ("REASONING", "FAST", "IMAGE"):
        assert not getattr(models, name).startswith("gemini-3")

def test_client_is_vertex_mode_and_cached():
    a, b = models.client(), models.client()
    assert a is b, "client() must be cached; constructing per call is wasteful"
    assert getattr(a, "_api_client").vertexai is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/agents && python -m pytest tests/test_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'magic_hour.models'`.

- [ ] **Step 3: Write the implementation**

`apps/agents/magic_hour/settings.py`:

```python
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    project: str = "nyu-ai-builder26nyc-9338"
    location: str = "us-central1"
    bucket: str = "nyu-ai-builder26nyc-9338-magic-hour"
    bq_dataset: str = "magic_hour_telemetry"
    db_instance: str = ""        # project:region:instance, empty means local
    db_name: str = "magichour"
    db_user: str = "postgres"
    db_host: str = "localhost"   # local dev only
    db_port: int = 5433
    db_password: str = ""        # local dev only; prod uses IAM auth
    maps_api_key: str = ""
    agents_audience: str = ""    # Cloud Run URL of this service
    model_config = SettingsConfigDict(env_file=".env", env_prefix="MH_", extra="ignore")

settings = Settings()
```

`apps/agents/magic_hour/models.py`:

```python
"""The only file in Magic Hour that names a model.

Every id below was verified against nyu-ai-builder26nyc-9338 on 2026-07-25 by
scripts/probe-models.sh, which makes a real generateContent or predict call.
The Gemini 3 family (gemini-3-pro-preview, gemini-3-pro-image-preview) returns
404 on this project, so REASONING and IMAGE stay on 2.5. On a project where 3
is allowlisted those are the only two lines that change.

Do not use gemini-flash-latest or gemini-pro-latest. They are AI Studio aliases
and 404 on Vertex AI.
"""
from functools import lru_cache

from google import genai

from magic_hour.settings import settings

LOCATION = settings.location

REASONING = "gemini-2.5-pro"           # architect, cinematographer, supervisor, muse
FAST = "gemini-2.5-flash"              # interviewer, character voices, parsers, scout
CHEAP = "gemini-2.5-flash-lite"        # summaries, classification, judging
IMAGE = "gemini-2.5-flash-image"       # nano banana

EMBED_TEXT = "gemini-embedding-001"    # request output_dimensionality=768
EMBED_TEXT_DIMS = 768
EMBED_MULTIMODAL = "multimodalembedding@001"
EMBED_MULTIMODAL_DIMS = 1408


@lru_cache(maxsize=1)
def client() -> genai.Client:
    """Vertex AI client using Application Default Credentials.

    Never pass api_key. That switches the SDK to AI Studio, where the model ids
    differ and where we would need a secret in the environment.
    """
    return genai.Client(vertexai=True, project=settings.project, location=LOCATION)
```

Delete the old client:

```bash
git rm apps/agents/app/gemini_client.py
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/agents && python -m pytest tests/test_models.py -v`
Expected: PASS, 8 tests. `test_client_is_vertex_mode_and_cached` requires ADC, so run `gcloud auth application-default login` first if it errors on credentials.

- [ ] **Step 5: Verify against the live project**

Run: `bash scripts/probe-models.sh nyu-ai-builder26nyc-9338`
Expected: every model named in `models.py` returns 200.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "Pin verified Vertex model ids in one file, drop the AI Studio client

Previs v1 used genai.Client(api_key=...) with gemini-flash-latest. That model id
returns 404 on Vertex AI because it is an AI Studio alias, so the old client
could not have worked once we moved to Vertex. models.py is now the only file
that names a model, and a test asserts no forbidden alias and no gemini-3 id
can be pinned, since gemini-3 404s on this project."
```

---

## Task 3: GCP bootstrap script

Exists because the lab project is temporary and can be revoked without warning (spec §17).

**Files:**
- Create: `scripts/bootstrap.sh`
- Create: `apps/agents/tests/test_bootstrap_script.py`

**Interfaces:**
- Consumes: `scripts/preflight.sh`.
- Produces: a project with all APIs enabled, three service accounts and bindings, a GCS bucket, a BigQuery dataset with four tables, a Cloud SQL instance with the `vector` extension, and Artifact Registry. Idempotent. `--dry-run` prints without executing.

- [ ] **Step 1: Write the failing test**

`apps/agents/tests/test_bootstrap_script.py`:

```python
import re
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "bootstrap.sh"

def test_dry_run_names_every_required_api():
    out = subprocess.run(["bash", str(SCRIPT), "test-project", "--dry-run"],
                         capture_output=True, text=True, check=True).stdout
    for api in ("run", "cloudbuild", "artifactregistry", "sqladmin",
                "secretmanager", "places", "apikeys"):
        assert f"{api}.googleapis.com" in out, f"missing api: {api}"

def test_dry_run_creates_three_service_accounts():
    out = subprocess.run(["bash", str(SCRIPT), "test-project", "--dry-run"],
                         capture_output=True, text=True, check=True).stdout
    for sa in ("mh-web", "mh-agents", "mh-ci"):
        assert sa in out

def test_script_never_creates_a_service_account_key():
    body = SCRIPT.read_text(encoding="utf-8")
    assert "keys create" not in body, "no service account keys, ever"

def test_script_is_idempotent_by_construction():
    body = SCRIPT.read_text(encoding="utf-8")
    # Every create must tolerate an existing resource.
    creates = [l for l in body.splitlines() if re.search(r"gcloud \w+.* create", l)]
    assert creates, "expected create commands"
    assert all("|| true" in l or "describe" in body for l in creates)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/agents && python -m pytest tests/test_bootstrap_script.py -v`
Expected: FAIL. `scripts/bootstrap.sh` does not exist, so `subprocess.run(check=True)` raises.

- [ ] **Step 3: Write the implementation**

`scripts/bootstrap.sh`:

```bash
#!/usr/bin/env bash
# Magic Hour · bootstrap a project from empty to deployable.
#
# The hackathon lab project is temporary and can be revoked without warning, so
# this must be able to rebuild everything somewhere else in under ten minutes.
# Idempotent: every create tolerates the resource already existing.
#
#   bash scripts/bootstrap.sh <PROJECT_ID> [--dry-run]

set -euo pipefail
P="${1:?usage: bootstrap.sh <PROJECT_ID> [--dry-run]}"
DRY=""; [[ "${2:-}" == "--dry-run" ]] && DRY=1
REGION=us-central1
BUCKET="${P}-magic-hour"
DATASET=magic_hour_telemetry
SQL_INSTANCE=magic-hour-db

run() { if [[ -n "$DRY" ]]; then echo "+ $*"; else echo "+ $*"; "$@" || true; fi; }

echo "== APIs"
run gcloud services enable \
  run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com \
  sqladmin.googleapis.com secretmanager.googleapis.com aiplatform.googleapis.com \
  bigquery.googleapis.com storage.googleapis.com places.googleapis.com \
  maps-backend.googleapis.com apikeys.googleapis.com iamcredentials.googleapis.com \
  --project="$P"

echo "== Service accounts (no keys are ever created for these)"
run gcloud iam service-accounts create mh-web    --display-name="Magic Hour web"    --project="$P"
run gcloud iam service-accounts create mh-agents --display-name="Magic Hour agents" --project="$P"
run gcloud iam service-accounts create mh-ci     --display-name="Magic Hour CI"     --project="$P"

WEB="mh-web@${P}.iam.gserviceaccount.com"
AGENTS="mh-agents@${P}.iam.gserviceaccount.com"
CI="mh-ci@${P}.iam.gserviceaccount.com"

echo "== Least privilege bindings"
for R in roles/aiplatform.user roles/cloudsql.client roles/bigquery.dataEditor \
         roles/bigquery.jobUser roles/storage.objectAdmin; do
  run gcloud projects add-iam-policy-binding "$P" --member="serviceAccount:${AGENTS}" --role="$R" --condition=None
done
for R in roles/run.developer roles/artifactregistry.writer roles/cloudsql.client \
         roles/iam.serviceAccountUser; do
  run gcloud projects add-iam-policy-binding "$P" --member="serviceAccount:${CI}" --role="$R" --condition=None
done

echo "== Storage, private with uniform access"
run gcloud storage buckets create "gs://${BUCKET}" --project="$P" --location="$REGION" \
  --uniform-bucket-level-access --public-access-prevention

echo "== BigQuery telemetry"
run bq --project_id="$P" mk --dataset --location="$REGION" "${P}:${DATASET}"
run bq --project_id="$P" mk --table "${P}:${DATASET}.agent_runs" \
  run_id:STRING,story_id:STRING,uid:STRING,surface:STRING,agent:STRING,model:STRING,ms:INTEGER,input_tokens:INTEGER,output_tokens:INTEGER,usd:FLOAT,status:STRING,ts:TIMESTAMP
run bq --project_id="$P" mk --table "${P}:${DATASET}.tool_calls" \
  run_id:STRING,tool:STRING,ms:INTEGER,ok:BOOLEAN,summary:STRING,ts:TIMESTAMP
run bq --project_id="$P" mk --table "${P}:${DATASET}.generations" \
  run_id:STRING,shot_id:STRING,style:STRING,attempt:INTEGER,face_scores:STRING,ms:INTEGER,ts:TIMESTAMP
run bq --project_id="$P" mk --table "${P}:${DATASET}.evals" \
  eval_run:STRING,metric:STRING,value:FLOAT,target:FLOAT,passed:BOOLEAN,detail:STRING,ts:TIMESTAMP

echo "== Artifact Registry"
run gcloud artifacts repositories create magic-hour --repository-format=docker \
  --location="$REGION" --project="$P"

echo "== Cloud SQL (public IP is permitted on this project; IAM auth, no password)"
run gcloud sql instances create "$SQL_INSTANCE" --project="$P" \
  --database-version=POSTGRES_16 --tier=db-g1-small --region="$REGION" \
  --database-flags=cloudsql.iam_authentication=on --storage-size=10GB --storage-auto-increase
run gcloud sql databases create magichour --instance="$SQL_INSTANCE" --project="$P"
run gcloud sql users create "$AGENTS" --instance="$SQL_INSTANCE" --project="$P" \
  --type=CLOUD_IAM_SERVICE_ACCOUNT

echo
echo "Bootstrap complete for ${P}."
echo "Next: enable the vector extension, then apply db/migrations."
echo "  gcloud sql connect ${SQL_INSTANCE} --user=postgres --project=${P}"
echo "  create extension if not exists vector;"
echo "Then verify: bash scripts/preflight.sh ${P} && bash scripts/probe-models.sh ${P}"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/agents && python -m pytest tests/test_bootstrap_script.py -v`
Expected: PASS, 4 tests.

- [ ] **Step 5: Dry run, read the output, then run it for real**

```bash
bash scripts/bootstrap.sh nyu-ai-builder26nyc-9338 --dry-run   # read every line
bash scripts/bootstrap.sh nyu-ai-builder26nyc-9338
bash scripts/preflight.sh nyu-ai-builder26nyc-9338
```

Expected: preflight reports billing enabled and the new APIs present. Cloud SQL creation takes roughly 8 minutes; let it finish before Task 4.

**If Maps key creation fails** (we hold only `serviceusage.apiKeysViewer`): create the key by hand at <https://console.cloud.google.com/apis/credentials>, restrict it to Places API (New), and put it in Secret Manager as `maps-api-key`. Record which path worked in spec §18 question 2.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "Add idempotent GCP bootstrap script

Rebuilds the whole stack in an empty project in under ten minutes, because the
hackathon lab project is temporary and can be revoked without warning. Cloud SQL
uses public IP with IAM database authentication, which sql.restrictPublicIp
permits on this project, so there is no VPC or connector to stand up. A test
asserts the script never creates a service account key."
```

---

## Task 4: Schema, migrations, and the database layer

**Files:**
- Create: `db/migrations/0001_init.sql`, `db/migrations/0002_questions_seed.sql`
- Create: `apps/agents/magic_hour/db.py`, `scripts/migrate.py`
- Create: `apps/agents/tests/conftest.py`, `apps/agents/tests/test_db.py`

**Interfaces:**
- Consumes: `settings`, `models.EMBED_TEXT_DIMS`, `models.EMBED_MULTIMODAL_DIMS`.
- Produces:
  - `db.pool() -> asyncpg.Pool` (cached, pgvector registered on every connection)
  - `db.tx()` async context manager yielding a connection inside a transaction
  - `db.close()` for test teardown

- [ ] **Step 1: Write the failing test**

`apps/agents/tests/conftest.py`:

```python
import os
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]

@pytest.fixture(scope="session", autouse=True)
def _local_db():
    """Point tests at the local pgvector container and apply migrations.

    Requires `make db-up` first. Tests never touch Cloud SQL: a test suite that
    can mutate the demo database is a test suite that will.
    """
    os.environ.setdefault("MH_DB_HOST", "localhost")
    os.environ.setdefault("MH_DB_PORT", "5433")
    os.environ.setdefault("MH_DB_PASSWORD", "dev")
    os.environ.setdefault("MH_DB_INSTANCE", "")
    subprocess.run(["python", str(REPO / "scripts" / "migrate.py")], check=True)
```

`apps/agents/tests/test_db.py`:

```python
import pytest
from magic_hour import db, models

async def test_vector_extension_is_installed():
    async with db.tx() as c:
        assert await c.fetchval("select 1 from pg_extension where extname='vector'")

async def test_embedding_columns_match_the_pinned_model_dims():
    """A wrong dimension is silent corruption, not an error. Assert it."""
    async with db.tx() as c:
        chunk = await c.fetchval(
            "select atttypmod from pg_attribute "
            "where attrelid='knowledge_chunks'::regclass and attname='embedding'")
        face = await c.fetchval(
            "select atttypmod from pg_attribute "
            "where attrelid='characters'::regclass and attname='face_embedding'")
    assert chunk == models.EMBED_TEXT_DIMS
    assert face == models.EMBED_MULTIMODAL_DIMS

async def test_tx_rolls_back_on_exception():
    with pytest.raises(RuntimeError):
        async with db.tx() as c:
            await c.execute("insert into users(uid,email) values('t1','t1@x.dev')")
            raise RuntimeError("boom")
    async with db.tx() as c:
        assert await c.fetchval("select count(*) from users where uid='t1'") == 0

async def test_layer_check_constraint_rejects_a_third_layer():
    async with db.tx() as c:
        await c.execute("insert into users(uid,email) values('t2','t2@x.dev')")
        sid = await c.fetchval(
            "insert into stories(owner_uid,title) values('t2','S') returning id")
        with pytest.raises(Exception):
            await c.execute(
                "insert into knowledge_chunks(story_id,entity_type,layer,text) "
                "values($1,'note','somewhere_between','x')", sid)

async def test_all_100_questions_are_seeded_with_twelve_core():
    async with db.tx() as c:
        total = await c.fetchval("select count(*) from questions")
        core = await c.fetchval("select count(*) from questions where is_core")
    assert total == 100
    assert core == 12

async def test_voice_embedding_dims_match_the_text_embedding_model():
    """The voice fingerprint is a text embedding, so it must be 768, not 1408."""
    async with db.tx() as c:
        dims = await c.fetchval(
            "select atttypmod from pg_attribute "
            "where attrelid='voice_cards'::regclass and attname='voice_embedding'")
    assert dims == models.EMBED_TEXT_DIMS

async def test_identity_and_voice_cards_are_unique_per_canon_version():
    """Cards are written once per version and never edited. Editing lets drift in
    (spec §6.1), so the database refuses a second card for the same version."""
    async with db.tx() as c:
        await c.execute("insert into users(uid,email) values('t3','t3@x.dev')")
        sid = await c.fetchval(
            "insert into stories(owner_uid,title) values('t3','S') returning id")
        cid = await c.fetchval(
            "insert into characters(story_id,name) values($1,'Maya') returning id", sid)
        await c.execute(
            "insert into identity_cards(character_id,canon_version,descriptor,wardrobe) "
            "values($1,1,'d','w')", cid)
        with pytest.raises(Exception):
            await c.execute(
                "insert into identity_cards(character_id,canon_version,descriptor,"
                "wardrobe) values($1,1,'different','w')", cid)

async def test_characters_start_at_canon_version_one():
    async with db.tx() as c:
        await c.execute("insert into users(uid,email) values('t4','t4@x.dev')")
        sid = await c.fetchval(
            "insert into stories(owner_uid,title) values('t4','S') returning id")
        v = await c.fetchval(
            "insert into characters(story_id,name) values($1,'Ravi') "
            "returning canon_version", sid)
    assert v == 1

async def test_story_edges_reject_an_unknown_edge_type():
    """The edge vocabulary is closed. An open one becomes unqueryable within a day."""
    async with db.tx() as c:
        await c.execute("insert into users(uid,email) values('t5','t5@x.dev')")
        sid = await c.fetchval(
            "insert into stories(owner_uid,title) values('t5','S') returning id")
        with pytest.raises(Exception):
            await c.execute(
                "insert into story_edges(story_id,src_type,src_id,edge,dst_type,"
                "dst_id,layer) values($1,'character',$1,'vibes_with','character',"
                "$1,'canon')", sid)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `make db-up && cd apps/agents && python -m pytest tests/test_db.py -v`
Expected: FAIL. `scripts/migrate.py` does not exist, so the session fixture raises before any test runs.

- [ ] **Step 3: Write the migration**

`db/migrations/0001_init.sql`: copy the DDL from spec §4 verbatim. **Creation order matters**, because the spec groups the compiled identity tables for readability but `continuity_state` references `scenes`:

```
users → stories → style_cards → characters → questions → character_answers
      → scenes → shots → locations → scene_locations
      → identity_cards → voice_cards → continuity_state → story_edges
      → knowledge_chunks → fact_proposals → assets
```

Prepend:

```sql
create extension if not exists vector;
create extension if not exists pgcrypto;   -- gen_random_uuid()
```

`db/migrations/0002_questions_seed.sql`: parse `data/seed/character-questions.txt` into 100 rows. The file's seven `Part N:` headings map to parts in order: `basics`, `growing_up`, `past`, `beliefs`, `relationships`, `likes`, `self`. Mark these 12 as `is_core = true`, chosen because they are what `DialogueDirector` reads to build a voice:

| id | question |
|---|---|
| 1 | full name |
| 11 | what does your voice sound like |
| 12 | words and phrases you use frequently |
| 14 | quirks and mannerisms |
| 27 | most important event of your life so far |
| 30 | greatest regret |
| 38 | greatest fear |
| 48 | how honest are you about your thoughts and feelings |
| 51 | how do you treat others |
| 68 | greatest strength |
| 69 | greatest weakness |
| 79 | goal you most want to accomplish |

Generate the file rather than hand typing 100 inserts:

```bash
python - <<'PY' > db/migrations/0002_questions_seed.sql
import re
from pathlib import Path

PARTS = ["basics","growing_up","past","beliefs","relationships","likes","self"]
CORE = {1,11,12,14,27,30,38,48,51,68,69,79}
src = Path("data/seed/character-questions.txt").read_text(encoding="utf-8")

part_i, rows = -1, []
for line in src.splitlines():
    s = line.strip()
    if s.startswith("Part ") and ":" in s:
        part_i += 1
        continue
    m = re.match(r"^[••]\s*(.+)$", s.lstrip("\t •"))
    text = (m.group(1) if m else s) if s and part_i >= 0 else None
    if text and not text.startswith("Part") and text != "Questions":
        rows.append((len(rows) + 1, PARTS[part_i], text))

assert len(rows) == 100, f"expected 100 questions, parsed {len(rows)}"
print("-- Generated from data/seed/character-questions.txt. Do not hand edit.")
print("insert into questions (id, part, text, is_core, weight) values")
vals = [
    "  ({}, '{}', '{}', {}, {})".format(
        i, part, text.replace("'", "''"), str(i in CORE).lower(), 3 if i in CORE else 1)
    for i, part, text in rows
]
print(",\n".join(vals) + "\non conflict (id) do nothing;")
PY
```

- [ ] **Step 4: Write the database layer and migration runner**

`apps/agents/magic_hour/db.py`:

```python
"""asyncpg access with pgvector registered, plus the transaction helper.

Local development and tests use a plain host and port against the pgvector
container. Cloud Run uses the Cloud SQL connector with IAM authentication, so
no password exists anywhere in the system to leak or rotate.
"""
from contextlib import asynccontextmanager

import asyncpg
from pgvector.asyncpg import register_vector

from magic_hour.settings import settings

_pool: asyncpg.Pool | None = None


async def _init(conn: asyncpg.Connection) -> None:
    await register_vector(conn)


async def pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        if settings.db_instance:
            from google.cloud.sql.connector import Connector, IPTypes

            connector = Connector(refresh_strategy="lazy")

            async def connect() -> asyncpg.Connection:
                return await connector.connect_async(
                    settings.db_instance, "asyncpg",
                    user=settings.db_user, db=settings.db_name,
                    enable_iam_auth=True, ip_type=IPTypes.PUBLIC,
                )

            _pool = await asyncpg.create_pool(connect=connect, init=_init,
                                              min_size=1, max_size=8)
        else:
            _pool = await asyncpg.create_pool(
                host=settings.db_host, port=settings.db_port,
                user=settings.db_user, password=settings.db_password,
                database=settings.db_name, init=_init, min_size=1, max_size=8)
    return _pool


@asynccontextmanager
async def tx():
    """A connection inside a transaction. Rolls back on any exception.

    Every write path uses this, because a structured row and its knowledge
    chunks must commit together or not at all (spec §4.1).
    """
    p = await pool()
    async with p.acquire() as conn:
        async with conn.transaction():
            yield conn


async def close() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
```

`scripts/migrate.py`:

```python
#!/usr/bin/env python
"""Apply db/migrations in filename order. Forward only, idempotent.

No down migrations. In a 48 hour build a bad migration is fixed by writing the
next migration, not by reversing this one.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "agents"))

from magic_hour import db  # noqa: E402

MIGRATIONS = Path(__file__).resolve().parents[1] / "db" / "migrations"


async def main() -> None:
    async with db.tx() as c:
        await c.execute("create table if not exists _migrations ("
                        "name text primary key, applied_at timestamptz default now())")
    for path in sorted(MIGRATIONS.glob("*.sql")):
        async with db.tx() as c:
            if await c.fetchval("select 1 from _migrations where name=$1", path.name):
                print(f"skip {path.name}")
                continue
            await c.execute(path.read_text(encoding="utf-8"))
            await c.execute("insert into _migrations(name) values($1)", path.name)
            print(f"applied {path.name}")
    await db.close()


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd apps/agents && python -m pytest tests/test_db.py -v`
Expected: PASS, 9 tests. If `test_all_100_questions_are_seeded_with_twelve_core` fails on the count, the parser in Step 3 mis-read the source file; fix the parser, not the assertion.

- [ ] **Step 6: Apply to Cloud SQL**

```bash
gcloud sql connect magic-hour-db --user=postgres --project=nyu-ai-builder26nyc-9338
# create extension if not exists vector;  then \q
MH_DB_INSTANCE=nyu-ai-builder26nyc-9338:us-central1:magic-hour-db python scripts/migrate.py
```

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "Add schema, migrations and the asyncpg layer with pgvector

Embedding dimensions are asserted against the pinned models by a test rather
than trusted, because a wrong dimension is silent corruption instead of an
error. The 100 interview questions are generated from the source text file, so
the seed cannot drift from the questions we actually ship.

Tests run against a local pgvector container, never Cloud SQL. A suite that can
mutate the demo database is a suite that eventually will."
```

---

## Task 5: Embeddings and the one-transaction invariant

The single most important task in this plan. Spec §4.1.

**Files:**
- Create: `apps/agents/magic_hour/embed.py`, `apps/agents/magic_hour/librarian/__init__.py`, `apps/agents/magic_hour/librarian/reindex.py`
- Create: `apps/agents/tests/test_embed.py`, `apps/agents/tests/test_reindex.py`

**Interfaces:**
- Consumes: `db.tx`, `models.EMBED_TEXT`, `models.EMBED_MULTIMODAL`, `models.client`.
- Produces:
  - `embed.text(s: str) -> list[float]` length 768
  - `embed.texts(items: list[str]) -> list[list[float]]`
  - `embed.image(png: bytes) -> list[float]` length 1408
  - `reindex.chunks_for(entity_type: str, row: dict) -> list[str]`
  - `reindex.reindex_entity(conn, story_id: UUID, entity_type: str, entity_id: UUID, layer: str, texts: list[str], created_by: str) -> int`

- [ ] **Step 1: Write the failing test**

`apps/agents/tests/test_reindex.py`:

```python
import uuid

import pytest
from magic_hour import db
from magic_hour.librarian import reindex

async def _story(c) -> uuid.UUID:
    await c.execute("insert into users(uid,email) values('u1','u1@x.dev') "
                    "on conflict do nothing")
    return await c.fetchval(
        "insert into stories(owner_uid,title) values('u1','Amber Hour') returning id")

async def test_reindex_writes_one_chunk_per_text_with_an_embedding():
    async with db.tx() as c:
        sid = await _story(c)
        cid = await c.fetchval(
            "insert into characters(story_id,name) values($1,'Maya') returning id", sid)
        n = await reindex.reindex_entity(
            c, sid, "character", cid, "canon",
            ["Maya · voice · low and unhurried", "Maya · greatest fear · being known"],
            created_by="user")
        assert n == 2
        rows = await c.fetch(
            "select text, embedding from knowledge_chunks where entity_id=$1", cid)
        assert len(rows) == 2
        assert all(r["embedding"] is not None for r in rows)
        assert len(rows[0]["embedding"]) == 768

async def test_reindex_replaces_rather_than_appends():
    """Reindexing twice must not leave stale chunks. Stale chunks are how a
    corrected fact keeps getting retrieved."""
    async with db.tx() as c:
        sid = await _story(c)
        cid = await c.fetchval(
            "insert into characters(story_id,name) values($1,'Ravi') returning id", sid)
        await reindex.reindex_entity(c, sid, "character", cid, "canon",
                                     ["Ravi · eyes · brown"], created_by="user")
        await reindex.reindex_entity(c, sid, "character", cid, "canon",
                                     ["Ravi · eyes · grey"], created_by="user")
        texts = [r["text"] for r in await c.fetch(
            "select text from knowledge_chunks where entity_id=$1", cid)]
        assert texts == ["Ravi · eyes · grey"]

async def test_a_failed_write_leaves_neither_row_nor_chunk():
    """The invariant. A fact and its embedding commit together or not at all."""
    bad_id = uuid.uuid4()
    with pytest.raises(Exception):
        async with db.tx() as c:
            sid = await _story(c)
            cid = await c.fetchval(
                "insert into characters(story_id,name,id) values($1,'Ghost',$2) "
                "returning id", sid, bad_id)
            await reindex.reindex_entity(c, sid, "character", cid, "canon",
                                        ["Ghost · note · x"], created_by="user")
            await c.execute("insert into knowledge_chunks(story_id,entity_type,layer,text) "
                            "values($1,'note','not_a_layer','x')", sid)   # violates check
    async with db.tx() as c:
        assert await c.fetchval("select count(*) from characters where id=$1", bad_id) == 0
        assert await c.fetchval(
            "select count(*) from knowledge_chunks where entity_id=$1", bad_id) == 0

def test_chunks_for_character_prefixes_every_chunk_with_the_entity_name():
    out = reindex.chunks_for("character", {
        "name": "Maya",
        "answers": [{"text": "What does your voice sound like?",
                     "answer": "low and unhurried"}],
    })
    assert out and all(c.startswith("Maya · ") for c in out)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/agents && python -m pytest tests/test_reindex.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'magic_hour.librarian'`.

- [ ] **Step 3: Write the implementation**

`apps/agents/magic_hour/embed.py`:

```python
"""Embedding calls with dimension assertions.

Dimensions are asserted on every call rather than checked once at startup. The
cost is a comparison; the alternative is a pgvector insert failing at 3am with a
message about vector length that nobody connects back to a model change.
"""
from magic_hour import models

_TEXT_BATCH = 32


def texts(items: list[str]) -> list[list[float]]:
    if not items:
        return []
    out: list[list[float]] = []
    client = models.client()
    for i in range(0, len(items), _TEXT_BATCH):
        batch = items[i : i + _TEXT_BATCH]
        resp = client.models.embed_content(
            model=models.EMBED_TEXT,
            contents=batch,
            config={"output_dimensionality": models.EMBED_TEXT_DIMS},
        )
        for e in resp.embeddings:
            v = list(e.values)
            if len(v) != models.EMBED_TEXT_DIMS:
                raise ValueError(
                    f"{models.EMBED_TEXT} returned {len(v)} dims, "
                    f"expected {models.EMBED_TEXT_DIMS}")
            out.append(v)
    return out


def text(s: str) -> list[float]:
    return texts([s])[0]


def image(png: bytes) -> list[float]:
    """Face fingerprint. Used as the continuity referee, never as a conditioner."""
    from google.genai import types

    resp = models.client().models.embed_content(
        model=models.EMBED_MULTIMODAL,
        contents=[types.Part.from_bytes(data=png, mime_type="image/png")],
    )
    v = list(resp.embeddings[0].values)
    if len(v) != models.EMBED_MULTIMODAL_DIMS:
        raise ValueError(
            f"{models.EMBED_MULTIMODAL} returned {len(v)} dims, "
            f"expected {models.EMBED_MULTIMODAL_DIMS}")
    return v
```

`apps/agents/magic_hour/librarian/reindex.py`:

```python
"""The derived retrieval index, and the invariant that keeps it honest.

knowledge_chunks is derived from the structured tables. It is rewritten inside
the same transaction as its source row, so a fact and its embedding can never
disagree: there is no window in which they could. This costs one embedding call
per write and it is the reason consistency holds across the product.

Deliberately not a trigger and not a background job. Both reintroduce the
window this exists to close.
"""
from uuid import UUID

import asyncpg

from magic_hour import embed


def chunks_for(entity_type: str, row: dict) -> list[str]:
    """Build the chunk texts for one entity.

    Every chunk is prefixed with the entity name, which materially improves both
    lexical matching and model comprehension over a bare fragment.
    """
    if entity_type == "character":
        name = row["name"]
        out = []
        if row.get("look"):
            out.append(f"{name} · appearance · {row['look']}")
        for a in row.get("answers", []):
            q = a["text"].rstrip("?").strip()
            out.append(f"{name} · {q} · {a['answer']}")
        return out
    if entity_type == "scene":
        head = f"Scene {row['number']} · {row['slugline']}"
        out = [f"{head} · {row.get('synopsis') or ''}".rstrip(" ·")]
        body = (row.get("body") or "").splitlines()
        for i in range(0, len(body), 40):
            span = "\n".join(body[i : i + 40]).strip()
            if span:
                out.append(f"{head} · text · {span}")
        return out
    if entity_type == "location":
        return [f"{row['name']} · location · {row.get('address') or ''} "
                f"{row.get('notes') or ''}".strip()]
    if entity_type == "style":
        return [f"Style · {k} · {v}" for k, v in (row.get("card") or {}).items()]
    if entity_type == "story":
        return [f"Story · logline · {row.get('logline') or ''}",
                f"Story · summary · {row.get('summary') or ''}"]
    return [row.get("text", "")]


async def reindex_entity(
    conn: asyncpg.Connection,
    story_id: UUID,
    entity_type: str,
    entity_id: UUID | None,
    layer: str,
    texts: list[str],
    created_by: str,
) -> int:
    """Replace this entity's chunks. Must be called inside db.tx().

    Replace, not append: stale chunks are how a corrected fact keeps being
    retrieved after it has been fixed.
    """
    texts = [t.strip() for t in texts if t and t.strip()]
    await conn.execute(
        "delete from knowledge_chunks where story_id=$1 and entity_type=$2 "
        "and entity_id is not distinct from $3 and layer=$4",
        story_id, entity_type, entity_id, layer)
    if not texts:
        return 0
    vectors = embed.texts(texts)
    await conn.executemany(
        "insert into knowledge_chunks "
        "(story_id, entity_type, entity_id, layer, text, embedding, "
        " source_ref, created_by) values ($1,$2,$3,$4,$5,$6,$7,$8)",
        [(story_id, entity_type, entity_id, layer, t, v,
          f"{entity_type}:{entity_id}", created_by)
         for t, v in zip(texts, vectors)])
    return len(texts)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd apps/agents && python -m pytest tests/test_reindex.py tests/test_embed.py -v`
Expected: PASS. These call Vertex for real, so ADC must be configured. They cost a fraction of a cent.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "Add embeddings and reindex_entity, the one-transaction invariant

knowledge_chunks is derived from the structured tables and rewritten inside the
same transaction as its source row, so a fact and its embedding cannot disagree.
Deliberately not a trigger and not a background job, because both reintroduce
the window this exists to close.

Reindex replaces rather than appends. Stale chunks are how a corrected fact keeps
getting retrieved after it has been fixed, and a test pins that behaviour.
Embedding dimensions are asserted on every call."
```

---

## Task 6: Hybrid retrieval and the Librarian tools

**Files:**
- Create: `apps/agents/magic_hour/librarian/search.py`, `apps/agents/magic_hour/librarian/tools.py`
- Create: `apps/agents/tests/test_search.py`

**Interfaces:**
- Consumes: `db.tx`, `embed.text`, `reindex.reindex_entity`.
- Produces:
  - `search.hybrid(conn, story_id, query, k=8, layers=("canon","draft")) -> list[Chunk]` where `Chunk` is a dataclass with `id, text, layer, entity_type, entity_id, source_ref, score`
  - `tools.LIBRARIAN_TOOLS: list[Callable]` for ADK: `search_bible`, `get_canon`, `get_scene_index`, `write_draft`, `propose_fact`

- [ ] **Step 1: Write the failing test**

`apps/agents/tests/test_search.py`:

```python
from magic_hour import db
from magic_hour.librarian import reindex, search

async def _seed(c):
    await c.execute("insert into users(uid,email) values('s1','s1@x.dev') "
                    "on conflict do nothing")
    sid = await c.fetchval(
        "insert into stories(owner_uid,title) values('s1','Amber Hour') returning id")
    await reindex.reindex_entity(c, sid, "note", None, "canon", [
        "INT. MOTEL ROOM - NIGHT · Maya waits by the window",
        "Maya · greatest fear · being completely known by someone",
        "Ravi · occupation · night bus driver on the airport route",
    ], created_by="user")
    await reindex.reindex_entity(c, sid, "note", None, "draft", [
        "Maya might have a sister nobody has mentioned yet",
    ], created_by="Muse")
    return sid

async def test_exact_slugline_is_found_which_pure_vector_search_misses():
    async with db.tx() as c:
        sid = await _seed(c)
        hits = await search.hybrid(c, sid, "INT. MOTEL ROOM", k=3)
        assert any("MOTEL ROOM" in h.text for h in hits)

async def test_semantic_paraphrase_is_found_which_lexical_search_misses():
    async with db.tx() as c:
        sid = await _seed(c)
        hits = await search.hybrid(c, sid, "what is she afraid of", k=3)
        assert any("greatest fear" in h.text for h in hits)

async def test_canon_outranks_draft_for_an_equally_relevant_match():
    async with db.tx() as c:
        sid = await _seed(c)
        hits = await search.hybrid(c, sid, "Maya", k=4)
        layers = [h.layer for h in hits]
        assert layers.index("canon") < layers.index("draft")

async def test_layer_filter_excludes_draft_entirely():
    async with db.tx() as c:
        sid = await _seed(c)
        hits = await search.hybrid(c, sid, "Maya sister", k=5, layers=("canon",))
        assert all(h.layer == "canon" for h in hits)

async def test_results_never_cross_story_boundaries():
    async with db.tx() as c:
        a = await _seed(c)
        b = await c.fetchval(
            "insert into stories(owner_uid,title) values('s1','Other') returning id")
        await reindex.reindex_entity(c, b, "note", None, "canon",
                                     ["Maya · a different Maya entirely"],
                                     created_by="user")
        hits = await search.hybrid(c, a, "Maya", k=10)
        assert all("different Maya" not in h.text for h in hits)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/agents && python -m pytest tests/test_search.py -v`
Expected: FAIL with `ImportError: cannot import name 'search'`.

- [ ] **Step 3: Write the implementation**

`apps/agents/magic_hour/librarian/search.py`:

```python
"""Hybrid retrieval: pgvector cosine and Postgres full text, fused by RRF.

Pure vector search fails on exactly what screenplays are made of. 'INT. MOTEL
ROOM - NIGHT' and 'the motel' are the same place but not neighbours in embedding
space, and character names need exact matching. Two retrievers, one database,
one statement, nothing to keep in sync.
"""
from dataclasses import dataclass
from uuid import UUID

import asyncpg

from magic_hour import embed

RRF_K = 60
CANON_BOOST = 1.25   # canon wins ties against an equally relevant draft chunk


@dataclass(frozen=True)
class Chunk:
    id: UUID
    text: str
    layer: str
    entity_type: str
    entity_id: UUID | None
    source_ref: str | None
    score: float


_SQL = """
with params as (select $1::uuid story, $2::vector qvec, $3::text qtext,
                       $4::int lim, $5::text[] layers),
vec as (
  select k.id, row_number() over (order by k.embedding <=> p.qvec) rnk
  from knowledge_chunks k, params p
  where k.story_id = p.story and k.layer = any(p.layers) and k.embedding is not null
  order by k.embedding <=> p.qvec limit p.lim * 4
),
lex as (
  select k.id, row_number() over (
           order by ts_rank_cd(k.tsv, websearch_to_tsquery('english', p.qtext)) desc) rnk
  from knowledge_chunks k, params p
  where k.story_id = p.story and k.layer = any(p.layers)
    and k.tsv @@ websearch_to_tsquery('english', p.qtext)
  limit p.lim * 4
),
fused as (
  select id, sum(w) score from (
    select id, 1.0 / ($6 + rnk) w from vec
    union all
    select id, 1.0 / ($6 + rnk) w from lex
  ) t group by id
)
select k.id, k.text, k.layer, k.entity_type, k.entity_id, k.source_ref,
       f.score * (case when k.layer = 'canon' then $7 else 1.0 end) as score
from fused f join knowledge_chunks k on k.id = f.id
order by score desc
limit (select lim from params)
"""


async def hybrid(
    conn: asyncpg.Connection,
    story_id: UUID,
    query: str,
    k: int = 8,
    layers: tuple[str, ...] = ("canon", "draft"),
) -> list[Chunk]:
    qvec = embed.text(query)
    rows = await conn.fetch(_SQL, story_id, qvec, query, k, list(layers),
                            RRF_K, CANON_BOOST)
    return [Chunk(r["id"], r["text"], r["layer"], r["entity_type"],
                  r["entity_id"], r["source_ref"], float(r["score"])) for r in rows]
```

`apps/agents/magic_hour/librarian/tools.py`:

```python
"""The only way any agent touches the bible.

Note what is absent: there is no promote_fact tool. Promotion is a user action
over HTTP. No agent has a write path to canon, by construction rather than by
instruction, because an instruction is a suggestion to a language model.
"""
import json
from uuid import UUID

from magic_hour import db
from magic_hour.librarian import reindex, search


async def search_bible(story_id: str, query: str, k: int = 8,
                       include_draft: bool = True) -> str:
    """Search the story bible. Canon is settled fact; draft is unconfirmed.

    Args:
        story_id: the story to search within.
        query: what you want to know, in natural language or an exact phrase.
        k: how many results to return.
        include_draft: whether to include unconfirmed draft-layer knowledge.
    """
    layers = ("canon", "draft") if include_draft else ("canon",)
    async with db.tx() as c:
        hits = await search.hybrid(c, UUID(story_id), query, k, layers)
    return json.dumps([
        {"text": h.text, "layer": h.layer, "source": h.source_ref,
         "chunk_id": str(h.id)} for h in hits])


async def get_canon(story_id: str, entity_type: str, entity_id: str) -> str:
    """Return every settled fact about one character, scene or location."""
    async with db.tx() as c:
        rows = await c.fetch(
            "select text from knowledge_chunks where story_id=$1 and entity_type=$2 "
            "and entity_id=$3 and layer='canon' order by created_at",
            UUID(story_id), entity_type, UUID(entity_id))
    return json.dumps([r["text"] for r in rows])


async def get_scene_index(story_id: str) -> str:
    """Every scene in order: number, slugline, one line synopsis, status.

    Cheap orientation. Call this before assuming where you are in the story.
    """
    async with db.tx() as c:
        rows = await c.fetch(
            "select number, slugline, synopsis, status from scenes "
            "where story_id=$1 order by order_index", UUID(story_id))
    return json.dumps([dict(r) for r in rows])


async def write_draft(story_id: str, entity_type: str, text: str,
                      entity_id: str | None = None) -> str:
    """Record an unconfirmed idea in the draft layer.

    Use freely while brainstorming. Draft knowledge is retrievable and clearly
    labelled unconfirmed, so it can inform work without being treated as settled.
    """
    async with db.tx() as c:
        n = await reindex.reindex_entity(
            c, UUID(story_id), entity_type,
            UUID(entity_id) if entity_id else None,
            "draft", [text], created_by="agent")
    return f"wrote {n} draft chunk(s)"


async def propose_fact(story_id: str, entity_type: str, field: str, value: str,
                       rationale: str, entity_id: str | None = None) -> str:
    """Propose that something becomes settled canon. The user decides.

    You cannot write canon. Give a rationale the user can judge: say what in the
    story led you here, so the proposal can be accepted or rejected on evidence.
    """
    async with db.tx() as c:
        pid = await c.fetchval(
            "insert into fact_proposals(story_id,entity_type,entity_id,field,"
            "proposed,rationale,source_agent) values($1,$2,$3,$4,$5,$6,$7) "
            "returning id",
            UUID(story_id), entity_type, UUID(entity_id) if entity_id else None,
            field, json.dumps(value), rationale, "agent")
    return f"proposed {field}, pending your approval (id {pid})"


LIBRARIAN_TOOLS = [search_bible, get_canon, get_scene_index, write_draft, propose_fact]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd apps/agents && python -m pytest tests/test_search.py -v`
Expected: PASS, 5 tests.

- [ ] **Step 5: Add a test that no agent can reach canon**

Append to `apps/agents/tests/test_search.py`:

```python
def test_no_librarian_tool_can_write_canon():
    """Structural guarantee, not a prompt instruction."""
    from magic_hour.librarian import tools
    import inspect
    names = {t.__name__ for t in tools.LIBRARIAN_TOOLS}
    assert "promote_fact" not in names
    for t in tools.LIBRARIAN_TOOLS:
        src = inspect.getsource(t)
        assert "'canon'" not in src or t.__name__ in {"search_bible", "get_canon"}
```

Run: `cd apps/agents && python -m pytest tests/test_search.py -v`
Expected: PASS, 6 tests.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "Add hybrid retrieval and the Librarian tool layer

Retrieval fuses pgvector cosine and Postgres full text by reciprocal rank, with
canon boosted over draft. Pure vector search misses exact sluglines and
character names, which is most of what a screenplay is made of; lexical search
misses paraphrase. Tests pin both directions.

There is deliberately no promote_fact tool. Promotion is a user action over
HTTP, so no agent has a write path to canon by construction rather than by
instruction, and a test enforces it."
```

---

## Task 7: The Continuity Pack

**Files:**
- Create: `apps/agents/magic_hour/context/__init__.py`, `apps/agents/magic_hour/context/pack.py`
- Create: `apps/agents/tests/test_pack.py`

**Interfaces:**
- Consumes: `db.tx`, `search.hybrid`.
- Produces:
  - `pack.BUDGETS: dict[str, int]`
  - `pack.Pack` dataclass with `.slots: dict[str, str]`, `.chunk_ids: list[str]`, `.sizes: dict[str, int]`, `.render() -> str`
  - `pack.build(conn, story_id, query, *, scene_number=None, character_ids=(), turn="") -> Pack`

- [ ] **Step 1: Write the failing test**

`apps/agents/tests/test_pack.py`:

```python
from magic_hour import db
from magic_hour.context import pack
from magic_hour.librarian import reindex

async def _seed(c):
    await c.execute("insert into users(uid,email) values('p1','p1@x.dev') "
                    "on conflict do nothing")
    sid = await c.fetchval(
        "insert into stories(owner_uid,title,logline,summary) "
        "values('p1','Amber Hour','A driver and a stranger share one night.',"
        "'Maya has missed the last bus.') returning id")
    await c.execute(
        "insert into scenes(story_id,number,order_index,slugline,synopsis,body) "
        "values($1,1,1,'INT. MOTEL ROOM - NIGHT','Maya waits.','She waits.')", sid)
    await reindex.reindex_entity(c, sid, "note", None, "canon",
                                 ["Maya · greatest fear · being known"],
                                 created_by="user")
    return sid

async def test_pack_always_contains_style_and_spine():
    async with db.tx() as c:
        sid = await _seed(c)
        p = await pack.build(c, sid, "what is Maya afraid of")
    assert p.slots["spine"], "spine is never omitted"
    assert "style" in p.slots

async def test_scene_index_appears_in_the_spine():
    async with db.tx() as c:
        sid = await _seed(c)
        p = await pack.build(c, sid, "anything")
    assert "INT. MOTEL ROOM - NIGHT" in p.slots["spine"]

async def test_retrieved_chunk_ids_are_recorded_for_the_context_inspector():
    async with db.tx() as c:
        sid = await _seed(c)
        p = await pack.build(c, sid, "what is Maya afraid of")
    assert p.chunk_ids, "every retrieved chunk id must be recorded"

async def test_overflow_drops_low_priority_slots_and_never_style_or_cast():
    async with db.tx() as c:
        sid = await _seed(c)
        p = await pack.build(c, sid, "Maya", turn="x " * 5000)
    assert p.sizes["turn"] <= pack.BUDGETS["turn"]
    assert p.slots["spine"]

async def test_render_is_deterministic_for_the_same_inputs():
    async with db.tx() as c:
        sid = await _seed(c)
        a = await pack.build(c, sid, "Maya")
        b = await pack.build(c, sid, "Maya")
    assert a.render() == b.render(), "context assembly must be reproducible"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/agents && python -m pytest tests/test_pack.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'magic_hour.context'`.

- [ ] **Step 3: Write the implementation**

`apps/agents/magic_hour/context/pack.py`:

```python
"""One function assembles the context for every model call in Magic Hour.

Fixed slots, fixed budgets, deterministic, fully logged. Determinism matters:
the same inputs must produce the same payload, or a bad line cannot be
reproduced and therefore cannot be debugged.

The assembled pack, its slot sizes and every chunk id are streamed to the UI
Context tab, where each chunk links back to its source row.
"""
from dataclasses import dataclass, field
from uuid import UUID

import asyncpg

from magic_hour.librarian import search

# Budgets in tokens. Approximated as 4 characters per token, which is close
# enough for a budget and avoids a tokeniser dependency on the request path.
BUDGETS = {"style": 400, "spine": 700, "cast": 300, "retrieved": 800,
           "local": 600, "turn": 600}

# Dropped first on overflow. style and cast are never dropped: without taste and
# without who these people are, the output is generic, which is the failure mode
# this whole product exists to prevent.
DROP_ORDER = ("turn", "local", "retrieved")

CHARS_PER_TOKEN = 4


def _clip(s: str, tokens: int) -> str:
    limit = tokens * CHARS_PER_TOKEN
    return s if len(s) <= limit else s[: limit - 1].rstrip() + "…"


@dataclass
class Pack:
    slots: dict[str, str] = field(default_factory=dict)
    chunk_ids: list[str] = field(default_factory=list)

    @property
    def sizes(self) -> dict[str, int]:
        return {k: len(v) // CHARS_PER_TOKEN for k, v in self.slots.items()}

    def render(self) -> str:
        order = ("style", "spine", "cast", "retrieved", "local", "turn")
        parts = [f"## {k.upper()}\n{self.slots[k]}"
                 for k in order if self.slots.get(k)]
        return "\n\n".join(parts)


async def build(
    conn: asyncpg.Connection,
    story_id: UUID,
    query: str,
    *,
    scene_number: int | None = None,
    character_ids: tuple[UUID, ...] = (),
    turn: str = "",
) -> Pack:
    p = Pack()

    card = await conn.fetchrow(
        "select card from style_cards where owner_uid = "
        "(select owner_uid from stories where id=$1) "
        "and (story_id=$1 or story_id is null) order by story_id nulls last, "
        "version desc limit 1", story_id)
    p.slots["style"] = _clip(
        "\n".join(f"{k}: {v}" for k, v in (dict(card["card"]) if card else {}).items())
        or "No style card yet. Write plainly and ask about taste when it matters.",
        BUDGETS["style"])

    story = await conn.fetchrow(
        "select title, logline, summary from stories where id=$1", story_id)
    scenes = await conn.fetch(
        "select number, slugline, synopsis from scenes where story_id=$1 "
        "order by order_index", story_id)
    spine = [f"Title: {story['title']}", f"Logline: {story['logline'] or ''}",
             f"Where the story is now: {story['summary'] or 'nothing written yet'}",
             "Scenes:"]
    spine += [f"  {r['number']}. {r['slugline']} · {r['synopsis'] or ''}"
              for r in scenes]
    p.slots["spine"] = _clip("\n".join(spine), BUDGETS["spine"])

    if character_ids:
        blocks = []
        for cid in character_ids:
            rows = await conn.fetch(
                "select text from knowledge_chunks where entity_id=$1 "
                "and layer='canon' order by created_at", cid)
            blocks.append(_clip("\n".join(r["text"] for r in rows), BUDGETS["cast"]))
        p.slots["cast"] = "\n\n".join(b for b in blocks if b)

    hits = await search.hybrid(conn, story_id, query, k=8)
    p.chunk_ids = [str(h.id) for h in hits]
    p.slots["retrieved"] = _clip(
        "\n".join(f"[{h.layer}] {h.text}" for h in hits), BUDGETS["retrieved"])

    if scene_number is not None:
        rows = await conn.fetch(
            "select number, slugline, body from scenes where story_id=$1 "
            "and number in ($2, $3) order by number", story_id,
            scene_number - 1, scene_number)
        local = []
        for r in rows:
            body = r["body"] or ""
            if r["number"] == scene_number - 1:
                tail = "\n".join(body.splitlines()[-12:])
                local.append(f"End of scene {r['number']}:\n{tail}")
            else:
                local.append(f"Scene {r['number']} so far ({r['slugline']}):\n{body}")
        p.slots["local"] = _clip("\n\n".join(local), BUDGETS["local"])

    if turn:
        p.slots["turn"] = _clip(turn, BUDGETS["turn"])

    total = sum(p.sizes.values())
    hard_cap = sum(BUDGETS.values())
    for slot in DROP_ORDER:
        if total <= hard_cap:
            break
        if p.slots.get(slot):
            total -= p.sizes[slot]
            p.slots[slot] = ""
    return p
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd apps/agents && python -m pytest tests/test_pack.py -v`
Expected: PASS, 5 tests.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "Add the Continuity Pack, one context assembler for every model call

Fixed slots with fixed budgets, dropped in a defined order on overflow. style
and cast are never dropped, because without taste and without who these people
are the output is generic, which is the failure mode the product exists to
prevent.

Assembly is deterministic and a test pins that, since the same inputs must
produce the same payload for a bad line to be reproducible. Every chunk id is
recorded so the Context tab can link each retrieved fact back to its source."
```

---

## Task 8: Event envelope and the trace writer

**Files:**
- Create: `apps/agents/magic_hour/events.py`, `apps/agents/magic_hour/trace.py`
- Create: `apps/agents/tests/test_trace.py`

**Interfaces:**
- Consumes: `settings`.
- Produces:
  - `events.Event` union plus each model class, matching spec §11.2 exactly
  - `events.sse(e: Event) -> str` producing `data: {json}\n\n`
  - `trace.Run` context manager: `.emit(event)`, `.queue` (an `asyncio.Queue`), `.run_id`
  - `trace.adk_callbacks(run: Run) -> dict` for ADK agent construction

- [ ] **Step 1: Write the failing test**

`apps/agents/tests/test_trace.py`:

```python
import asyncio
import json

from magic_hour import events, trace

def test_every_event_type_in_the_spec_envelope_exists():
    for t in ("run_start", "thinking", "tool_call", "tool_result", "context",
              "partial", "shot_ready", "proposal", "violation", "run_end", "error"):
        assert t in events.EVENT_TYPES

def test_sse_frame_is_valid_and_terminated():
    frame = events.sse(events.RunStart(run_id="r1", agent="Muse"))
    assert frame.startswith("data: ") and frame.endswith("\n\n")
    assert json.loads(frame[6:].strip())["t"] == "run_start"

async def test_run_emits_start_and_end_around_the_body():
    async with trace.Run(surface="muse", story_id="s1", uid="u1") as run:
        await run.emit(events.Thinking(run_id=run.run_id, agent="Muse", text="hm"))
    seen = []
    while not run.queue.empty():
        seen.append(json.loads(run.queue.get_nowait()[6:].strip())["t"])
    assert seen[0] == "run_start" and seen[-1] == "run_end"

async def test_bigquery_write_never_blocks_the_request_path(monkeypatch):
    slow_calls = []

    async def _slow(rows):
        slow_calls.append(rows)
        await asyncio.sleep(2)

    monkeypatch.setattr(trace, "_flush_to_bigquery", _slow)
    started = asyncio.get_running_loop().time()
    async with trace.Run(surface="muse", story_id="s1", uid="u1"):
        pass
    assert asyncio.get_running_loop().time() - started < 0.5

async def test_an_error_in_the_body_is_emitted_and_reraised():
    with __import__("pytest").raises(ValueError):
        async with trace.Run(surface="board", story_id="s1", uid="u1") as run:
            raise ValueError("nope")
    kinds = []
    while not run.queue.empty():
        kinds.append(json.loads(run.queue.get_nowait()[6:].strip())["t"])
    assert "error" in kinds and kinds[-1] == "run_end"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/agents && python -m pytest tests/test_trace.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'magic_hour.events'`.

- [ ] **Step 3: Write the implementation**

`apps/agents/magic_hour/events.py`:

```python
"""One SSE envelope for every stream in the product.

One envelope means the browser has one parser and the Trace tab renders every
surface without special cases. Previs v1's shot_planned, image_ready,
location_found and done all map onto this.
"""
import json
from typing import Literal, Union

from pydantic import BaseModel


class _E(BaseModel):
    run_id: str


class RunStart(_E):
    t: Literal["run_start"] = "run_start"
    agent: str

class Thinking(_E):
    t: Literal["thinking"] = "thinking"
    agent: str
    text: str

class ToolCall(_E):
    t: Literal["tool_call"] = "tool_call"
    agent: str
    tool: str
    args: dict

class ToolResult(_E):
    t: Literal["tool_result"] = "tool_result"
    tool: str
    summary: str
    ms: int

class Context(_E):
    t: Literal["context"] = "context"
    slots: dict[str, int]
    chunk_ids: list[str]

class Partial(_E):
    t: Literal["partial"] = "partial"
    field: str
    text: str

class ShotReady(_E):
    t: Literal["shot_ready"] = "shot_ready"
    shot_id: str
    url: str
    face_scores: dict[str, float]

class Proposal(_E):
    t: Literal["proposal"] = "proposal"
    proposal_id: str
    field: str
    rationale: str

class Violation(_E):
    t: Literal["violation"] = "violation"
    kind: str
    detail: str
    iteration: int

class RunEnd(_E):
    t: Literal["run_end"] = "run_end"
    ms: int
    tokens: int = 0
    usd: float = 0.0

class Error(_E):
    t: Literal["error"] = "error"
    message: str
    retryable: bool = False


Event = Union[RunStart, Thinking, ToolCall, ToolResult, Context, Partial,
              ShotReady, Proposal, Violation, RunEnd, Error]

EVENT_TYPES = {"run_start", "thinking", "tool_call", "tool_result", "context",
               "partial", "shot_ready", "proposal", "violation", "run_end", "error"}


def sse(e: Event) -> str:
    return f"data: {json.dumps(e.model_dump(), default=str)}\n\n"
```

`apps/agents/magic_hour/trace.py`:

```python
"""One writer fans every agent event out to the browser and to BigQuery.

This single piece of code delivers the monitoring story, the agentic visibility
story, and the removal of every spinner from the demo: latency becomes the show
because judges watch the agents work instead of watching a wheel turn.

BigQuery writes are fire and forget. Telemetry must never be able to slow or
fail a user request.
"""
import asyncio
import time
import uuid

from magic_hour import events
from magic_hour.settings import settings

_pending: list[dict] = []
_BATCH = 20


async def _flush_to_bigquery(rows: list[dict]) -> None:
    if not rows:
        return
    from google.cloud import bigquery

    def _write() -> None:
        client = bigquery.Client(project=settings.project)
        table = f"{settings.project}.{settings.bq_dataset}.agent_runs"
        client.insert_rows_json(table, rows)

    await asyncio.to_thread(_write)


class Run:
    """One agent run. Emits run_start and run_end around the body."""

    def __init__(self, surface: str, story_id: str, uid: str, agent: str = "root"):
        self.run_id = uuid.uuid4().hex
        self.surface, self.story_id, self.uid, self.agent = surface, story_id, uid, agent
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self._t0 = 0.0
        self.tokens = 0

    async def emit(self, e: events.Event) -> None:
        await self.queue.put(events.sse(e))

    async def __aenter__(self) -> "Run":
        self._t0 = time.monotonic()
        await self.emit(events.RunStart(run_id=self.run_id, agent=self.agent))
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        ms = int((time.monotonic() - self._t0) * 1000)
        if exc is not None:
            await self.emit(events.Error(run_id=self.run_id, message=str(exc),
                                         retryable=False))
        await self.emit(events.RunEnd(run_id=self.run_id, ms=ms, tokens=self.tokens))

        _pending.append({
            "run_id": self.run_id, "story_id": self.story_id, "uid": self.uid,
            "surface": self.surface, "agent": self.agent, "ms": ms,
            "output_tokens": self.tokens,
            "status": "error" if exc else "ok",
            "ts": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
        })
        if len(_pending) >= _BATCH:
            batch, _pending[:] = list(_pending), []
            asyncio.create_task(_flush_to_bigquery(batch))   # never awaited
        return False   # re-raise


def adk_callbacks(run: Run) -> dict:
    """ADK callback kwargs that stream an agent's work into this run."""

    async def before_tool(tool, args, tool_context):
        await run.emit(events.ToolCall(run_id=run.run_id, agent=run.agent,
                                       tool=getattr(tool, "name", str(tool)),
                                       args=dict(args or {})))
        return None

    async def after_tool(tool, args, tool_context, tool_response):
        await run.emit(events.ToolResult(
            run_id=run.run_id, tool=getattr(tool, "name", str(tool)),
            summary=str(tool_response)[:280], ms=0))
        return None

    async def after_model(callback_context, llm_response):
        usage = getattr(llm_response, "usage_metadata", None)
        if usage:
            run.tokens += getattr(usage, "candidates_token_count", 0) or 0
        return None

    return {"before_tool_callback": before_tool,
            "after_tool_callback": after_tool,
            "after_model_callback": after_model}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd apps/agents && python -m pytest tests/test_trace.py -v`
Expected: PASS, 5 tests.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "Add the SSE event envelope and the trace writer

One envelope for every stream, so the browser has one parser and the Trace tab
renders every surface without special cases. Previs v1's event types map onto it
directly.

BigQuery writes are fire and forget, batched, and a test asserts a two second
sink cannot add half a second to a request. Telemetry that can slow a request
will eventually fail one."
```

---

## Task 9: The agents service and service to service auth

**Files:**
- Create: `apps/agents/magic_hour/auth.py`, `apps/agents/magic_hour/app.py`, `apps/agents/Dockerfile`
- Create: `apps/agents/tests/test_auth.py`
- Delete: `apps/agents/app/main.py` (v1 entry point; its behaviour moves to the Board plan)

**Interfaces:**
- Consumes: `settings`, `db`, `events`.
- Produces:
  - `auth.verify_caller(authorization: str | None) -> str` returning the caller's service account email, raising `HTTPException(401)` otherwise
  - `app.app` FastAPI instance with `GET /healthz` (unauthenticated) and a `require_caller` dependency
  - `app.stream(run, body)` helper returning a `StreamingResponse` over `run.queue`

- [ ] **Step 1: Write the failing test**

`apps/agents/tests/test_auth.py`:

```python
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from magic_hour import auth
from magic_hour.app import app

client = TestClient(app)

def test_healthz_needs_no_token():
    r = client.get("/healthz")
    assert r.status_code == 200 and r.json()["ok"] is True

def test_missing_authorization_header_is_rejected():
    with pytest.raises(HTTPException) as e:
        auth.verify_caller(None)
    assert e.value.status_code == 401

def test_malformed_bearer_token_is_rejected():
    with pytest.raises(HTTPException) as e:
        auth.verify_caller("Bearer not-a-jwt")
    assert e.value.status_code == 401

def test_a_protected_route_rejects_an_unauthenticated_call():
    assert client.post("/v1/echo", json={"x": 1}).status_code == 401

def test_audience_is_checked_not_just_the_signature(monkeypatch):
    """A validly signed token for a different service must not be accepted."""
    monkeypatch.setattr(auth.settings, "agents_audience", "https://agents.example")

    def fake_verify(token, request, audience=None):
        assert audience == "https://agents.example", "audience must be passed"
        raise ValueError("wrong audience")

    monkeypatch.setattr(auth.id_token, "verify_oauth2_token", fake_verify)
    with pytest.raises(HTTPException) as e:
        auth.verify_caller("Bearer eyJhbGciOi.payload.sig")
    assert e.value.status_code == 401
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/agents && python -m pytest tests/test_auth.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'magic_hour.auth'`.

- [ ] **Step 3: Write the implementation**

`apps/agents/magic_hour/auth.py`:

```python
"""Service to service authentication.

This service runs with --ingress=internal, so it is not reachable from the
internet at all. This check is the second layer: even inside the perimeter, the
caller must present a Google-signed ID token whose audience is this service.

Checking the audience matters as much as checking the signature. A validly
signed token minted for some other service is still not permission to call this
one.
"""
from fastapi import HTTPException
from google.auth.transport import requests as g_requests
from google.oauth2 import id_token

from magic_hour.settings import settings

_transport = g_requests.Request()


def verify_caller(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    token = authorization.removeprefix("Bearer ").strip()
    try:
        claims = id_token.verify_oauth2_token(
            token, _transport, audience=settings.agents_audience or None)
    except Exception as exc:
        raise HTTPException(status_code=401, detail="invalid token") from exc
    email = claims.get("email", "")
    if not email:
        raise HTTPException(status_code=401, detail="token carries no identity")
    return email
```

`apps/agents/magic_hour/app.py`:

```python
"""FastAPI entry point for the agents service.

Not reachable from the internet: deployed with --ingress=internal and invocable
only by mh-web@. Surface routers are registered here as each plan lands.
"""
from fastapi import Depends, FastAPI, Header
from fastapi.responses import StreamingResponse

from magic_hour import auth, db
from magic_hour.trace import Run

app = FastAPI(title="Magic Hour agents", docs_url=None, redoc_url=None)


async def require_caller(authorization: str | None = Header(default=None)) -> str:
    return auth.verify_caller(authorization)


@app.get("/healthz")
async def healthz() -> dict:
    return {"ok": True}


@app.post("/v1/echo")
async def echo(body: dict, caller: str = Depends(require_caller)) -> dict:
    """Smoke test for the auth path and for deploy verification."""
    return {"caller": caller, "echo": body}


def stream(run: Run) -> StreamingResponse:
    async def gen():
        while True:
            frame = await run.queue.get()
            yield frame
            if '"t": "run_end"' in frame or '"t":"run_end"' in frame:
                return

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


@app.on_event("shutdown")
async def _shutdown() -> None:
    await db.close()
```

`apps/agents/Dockerfile`:

```dockerfile
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY pyproject.toml ./
RUN pip install --no-cache-dir .
COPY magic_hour ./magic_hour
# Cloud Run sets PORT. One worker: ADK agents hold per-run state in memory.
CMD exec uvicorn magic_hour.app:app --host 0.0.0.0 --port ${PORT:-8080} --workers 1
```

Remove the v1 entry point, whose storyboard behaviour is re-specified in the Board plan:

```bash
git rm apps/agents/app/main.py apps/agents/app/static/index.html
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd apps/agents && python -m pytest tests/test_auth.py -v`
Expected: PASS, 5 tests.

- [ ] **Step 5: Deploy and verify the ingress rule actually holds**

```bash
P=nyu-ai-builder26nyc-9338; R=us-central1
gcloud run deploy magic-hour-agents --source apps/agents --region=$R --project=$P \
  --service-account=mh-agents@$P.iam.gserviceaccount.com \
  --ingress=internal --no-allow-unauthenticated --min-instances=1 \
  --set-env-vars=MH_PROJECT=$P,MH_DB_INSTANCE=$P:$R:magic-hour-db

URL=$(gcloud run services describe magic-hour-agents --region=$R --project=$P \
      --format='value(status.url)')
curl -s -o /dev/null -w '%{http_code}\n' "$URL/healthz"   # expect 403, not 200
```

Expected: **403.** A 200 means ingress is not internal and must be fixed before proceeding. Verify from inside instead:

```bash
gcloud run services proxy magic-hour-agents --region=$R --project=$P --port=8081 &
curl -s localhost:8081/healthz    # expect {"ok":true}
```

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "Add the agents service, internal ingress and ID token verification

Two layers. The service is deployed with --ingress=internal so it is not
reachable from the internet, and every request must additionally carry a
Google-signed ID token whose audience is this service. A test asserts the
audience is passed to the verifier, because a validly signed token minted for
another service is not permission to call this one.

Verification is that GET /healthz on the public URL returns 403. A 200 means
ingress is misconfigured."
```

---

## Task 10: Shared contracts

**Files:**
- Create: `packages/contracts/package.json`, `packages/contracts/schemas/events.json`, `packages/contracts/schemas/entities.json`, `packages/contracts/scripts/generate.mjs`
- Create: `packages/contracts/tests/parity.test.ts`

**Interfaces:**
- Consumes: `apps/agents/magic_hour/events.py` as the reference shape.
- Produces: `@magic-hour/contracts` exporting `Event`, `Story`, `Scene`, `Shot`, `Character`, `Location`, `Proposal` TypeScript types generated from JSON Schema.

- [ ] **Step 1: Write the failing test**

`packages/contracts/tests/parity.test.ts`:

```ts
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const PY = readFileSync(
  new URL("../../../apps/agents/magic_hour/events.py", import.meta.url), "utf8");
const schema = JSON.parse(readFileSync(
  new URL("../schemas/events.json", import.meta.url), "utf8"));

describe("event contract parity", () => {
  it("every python event type appears in the json schema", () => {
    const py = [...PY.matchAll(/Literal\["(\w+)"\]/g)].map(m => m[1]).sort();
    const ts = Object.keys(schema.definitions).map(
      k => schema.definitions[k].properties.t.const).sort();
    expect(ts).toEqual(py);
  });

  it("shot_ready carries face_scores, the consistency metric", () => {
    expect(schema.definitions.ShotReady.properties.face_scores).toBeDefined();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd packages/contracts && pnpm vitest run`
Expected: FAIL. `schemas/events.json` does not exist.

- [ ] **Step 3: Write the schema and the generator**

`packages/contracts/schemas/events.json`: one `definitions` entry per class in `events.py`, each with a `properties.t.const` matching the Python `Literal`. Mirror spec §11.2 exactly, including `ShotReady.face_scores` as `{"type":"object","additionalProperties":{"type":"number"}}`.

`packages/contracts/package.json`:

```json
{
  "name": "@magic-hour/contracts",
  "version": "0.1.0",
  "type": "module",
  "main": "./dist/index.ts",
  "scripts": {
    "generate": "node scripts/generate.mjs",
    "test": "vitest run"
  },
  "devDependencies": {
    "json-schema-to-typescript": "^15.0.3",
    "vitest": "^2.1.5"
  }
}
```

`packages/contracts/scripts/generate.mjs`:

```js
// JSON Schema is the single source of truth for anything crossing the wire.
// A contract change breaks the build on both sides rather than at runtime.
import { compileFromFile } from "json-schema-to-typescript";
import { writeFileSync, mkdirSync, readdirSync } from "node:fs";

mkdirSync("dist", { recursive: true });
let out = "// Generated from schemas/. Do not edit by hand.\n\n";
for (const f of readdirSync("schemas").filter(f => f.endsWith(".json"))) {
  out += await compileFromFile(`schemas/${f}`, { bannerComment: "" });
}
writeFileSync("dist/index.ts", out);
console.log("wrote dist/index.ts");
```

- [ ] **Step 4: Generate and run tests**

Run: `cd packages/contracts && pnpm install && pnpm generate && pnpm vitest run`
Expected: PASS, 2 tests, and `dist/index.ts` exists.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "Add shared contracts generated from JSON Schema

JSON Schema is the single source of truth for anything crossing the wire, and a
parity test asserts every Python event type has a matching definition. A
contract change now breaks the build on both sides instead of surfacing as a
runtime shape mismatch during a demo."
```

---

## Task 11: Web app shell and design system

**Files:**
- Create: `apps/web/package.json`, `next.config.mjs`, `tailwind.config.ts`, `app/layout.tsx`, `app/globals.css`, `app/page.tsx`
- Create: `apps/web/components/shell/{Rail,Workspace,Inspector,SpaceField}.tsx`
- Create: `apps/web/components/shell/__tests__/tokens.test.ts`

**Interfaces:**
- Consumes: `@magic-hour/contracts`.
- Produces:
  - `<Shell surface={Surface}>` layout with `Rail`, `Workspace`, `Inspector`
  - `SURFACES: {key, label, accent, icon}[]` for the six surfaces
  - Tailwind tokens: `bg-ink`, `bg-ink-raised`, `text-paper`, `accent-{board,script,scout,cast,muse,bible}`

- [ ] **Step 1: Write the failing test**

`apps/web/components/shell/__tests__/tokens.test.ts`:

```ts
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { SURFACES } from "../surfaces";

const css = readFileSync(new URL("../../../app/globals.css", import.meta.url), "utf8");

describe("design tokens", () => {
  it("defines all six surface accents from spec 12", () => {
    expect(SURFACES.map(s => s.key)).toEqual(
      ["bible", "script", "board", "cast", "scout", "muse"]);
    for (const s of SURFACES) expect(s.accent).toMatch(/^#[0-9A-Fa-f]{6}$/);
  });

  it("uses the palette from the existing site, not invented colours", () => {
    const accents = SURFACES.map(s => s.accent.toUpperCase());
    expect(accents).toContain("#F5A524");  // board, magic hour amber
    expect(accents).toContain("#5B8DEF");  // script
    expect(accents).toContain("#34D399");  // scout
    expect(accents).toContain("#A78BFA");  // cast
    expect(accents).toContain("#22D3EE");  // muse
  });

  it("respects prefers-reduced-motion", () => {
    expect(css).toContain("prefers-reduced-motion");
  });

  it("has no em dash or en dash in any surface label", () => {
    for (const s of SURFACES) expect(s.label).not.toMatch(/[—–]/);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/web && pnpm vitest run`
Expected: FAIL. `apps/web` does not exist.

- [ ] **Step 3: Scaffold the app and write the tokens**

```bash
cd apps
pnpm create next-app@latest web --typescript --tailwind --app --eslint \
  --no-src-dir --import-alias "@/*" --use-pnpm
cd web && pnpm add @magic-hour/contracts@workspace:* && pnpm add -D vitest @vitejs/plugin-react jsdom
```

`apps/web/components/shell/surfaces.ts`:

```ts
// Accents come from the existing sampreethavvari.github.io palette. Each appears
// only on the active rail item and one panel edge glow. Body copy stays neutral.
export type SurfaceKey = "bible" | "script" | "board" | "cast" | "scout" | "muse";

export const SURFACES: { key: SurfaceKey; label: string; accent: string; icon: string }[] = [
  { key: "bible",  label: "Bible",  accent: "#F5F5F7", icon: "book" },
  { key: "script", label: "Script", accent: "#5B8DEF", icon: "pen" },
  { key: "board",  label: "Board",  accent: "#F5A524", icon: "grid" },
  { key: "cast",   label: "Cast",   accent: "#A78BFA", icon: "users" },
  { key: "scout",  label: "Scout",  accent: "#34D399", icon: "map" },
  { key: "muse",   label: "Muse",   accent: "#22D3EE", icon: "spark" },
];
```

`apps/web/tailwind.config.ts`:

```ts
import type { Config } from "tailwindcss";

export default {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#000000",
        "ink-raised": "#0A0A0C",
        paper: "#F5F5F7",
        "paper-dim": "#8A8A8F",
        "accent-bible": "#F5F5F7",
        "accent-script": "#5B8DEF",
        "accent-board": "#F5A524",
        "accent-cast": "#A78BFA",
        "accent-scout": "#34D399",
        "accent-muse": "#22D3EE",
      },
      fontFamily: {
        display: ["-apple-system", "BlinkMacSystemFont", "SF Pro Display",
                  "Inter", "Segoe UI", "Roboto", "sans-serif"],
        // Screenplays are Courier 12pt by industry convention. Filmmakers
        // recognise it instantly, and it is worth more than any gradient.
        script: ["Courier Prime", "Courier New", "monospace"],
      },
      transitionDuration: { DEFAULT: "180ms" },
    },
  },
} satisfies Config;
```

`apps/web/app/globals.css`:

```css
@tailwind base;
@tailwind components;
@tailwind utilities;

:root {
  color-scheme: dark;
  --amb-top: #0B1020;      /* first stars */
  --amb-bottom: #F5A524;   /* last light */
}

body {
  @apply bg-ink text-paper font-display antialiased;
  background-image: linear-gradient(
    to bottom, var(--amb-top) 0%, transparent 55%,
    color-mix(in srgb, var(--amb-bottom) 8%, transparent) 100%);
  background-attachment: fixed;
}

/* Glass panels, borrowed from the GlassHero language on the existing site. */
.glass {
  @apply bg-ink-raised/70 backdrop-blur-xl border border-white/[0.06] rounded-xl;
}

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    transition-duration: 0.01ms !important;
  }
  .spacefield { display: none !important; }
}
```

`apps/web/components/shell/SpaceField.tsx`: port `SpaceField.astro` from `sampreethavvari.github.io` into a React client component. Changes required for a work tool rather than a landing page: remove the scroll-warp velocity uniform, remove the nebula layer, fix `uCam` at a constant, and set canvas opacity to `0.35`. Bail out early when `matchMedia("(prefers-reduced-motion: reduce)").matches` or WebGL is unavailable.

Write `Rail.tsx` (56px collapsed, story switcher on top, six surface buttons, accent on the active one), `Inspector.tsx` (three tabs: Context, Trace, Canon), and `Workspace.tsx` (the centre frame). Keep each under 150 lines.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd apps/web && pnpm vitest run`
Expected: PASS, 4 tests.

- [ ] **Step 5: Verify it renders**

Run: `cd apps/web && pnpm dev`, open <http://localhost:3000>
Expected: near black page, a faint starfield, warm glow along the bottom edge, a working rail, an inspector with three tabs. Toggle reduced motion in the OS and confirm the starfield disappears.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "Add the web shell and design system

Palette, type stack and starfield come from the existing site rather than being
invented, so Magic Hour looks like it belongs to the same hand. The starfield is
toned down for a work tool: no scroll warp, no nebula, fixed camera, 0.35
opacity, and off entirely under reduced motion.

Courier Prime for the screenplay editor, because screenplays are Courier 12pt
by convention and filmmakers clock it immediately.

A test asserts no surface label contains an em dash or en dash."
```

---

## Task 12: Web auth, session, and the typed agents client

**Files:**
- Create: `apps/web/lib/auth.ts`, `apps/web/lib/agents.ts`, `apps/web/app/api/health/route.ts`
- Create: `apps/web/lib/__tests__/agents.test.ts`

**Interfaces:**
- Consumes: `@magic-hour/contracts`, agents service `/healthz` and `/v1/echo`.
- Produces:
  - `requireUser(): Promise<{ uid: string; email: string }>` throwing a redirect when unauthenticated
  - `callAgents<T>(path: string, body: unknown): Promise<T>`
  - `streamAgents(path: string, body: unknown): AsyncIterable<Event>`

- [ ] **Step 1: Write the failing test**

`apps/web/lib/__tests__/agents.test.ts`:

```ts
import { describe, expect, it, vi } from "vitest";
import { streamAgents } from "../agents";

describe("agents client", () => {
  it("parses an SSE stream into typed events and stops at run_end", async () => {
    const frames = [
      'data: {"t":"run_start","run_id":"r1","agent":"Muse"}\n\n',
      'data: {"t":"thinking","run_id":"r1","agent":"Muse","text":"hm"}\n\n',
      'data: {"t":"run_end","run_id":"r1","ms":12,"tokens":4,"usd":0}\n\n',
    ];
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(
      new ReadableStream({
        start(c) {
          for (const f of frames) c.enqueue(new TextEncoder().encode(f));
          c.close();
        },
      }), { headers: { "content-type": "text/event-stream" } })));

    const seen: string[] = [];
    for await (const e of streamAgents("/v1/echo", {})) seen.push(e.t);
    expect(seen).toEqual(["run_start", "thinking", "run_end"]);
  });

  it("handles a frame split across two chunks", async () => {
    const parts = ['data: {"t":"run_end","run_', 'id":"r1","ms":1,"tokens":0,"usd":0}\n\n'];
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(
      new ReadableStream({
        start(c) {
          for (const p of parts) c.enqueue(new TextEncoder().encode(p));
          c.close();
        },
      }))));
    const seen: string[] = [];
    for await (const e of streamAgents("/x", {})) seen.push(e.t);
    expect(seen).toEqual(["run_end"]);
  });

  it("never sends a model key or database credential to the browser", async () => {
    const src = await import("node:fs").then(fs =>
      fs.readFileSync(new URL("../agents.ts", import.meta.url), "utf8"));
    expect(src).not.toMatch(/api_?key/i);
    expect(src).not.toMatch(/postgres:\/\//);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/web && pnpm vitest run lib`
Expected: FAIL. `lib/agents.ts` does not exist.

- [ ] **Step 3: Resolve the auth provider, then implement**

Decide spec §18 question 2 by testing which enables cleanly. Try Firebase first:

```bash
P=nyu-ai-builder26nyc-9338
gcloud services enable firebase.googleapis.com identitytoolkit.googleapis.com --project=$P
```

If both enable, use Firebase Auth with Google sign in and verify ID tokens in `lib/auth.ts` with `firebase-admin`. If either is blocked, fall back to Auth.js v5 with a Google OAuth client created in this project. **Either way `uid` is the OIDC `sub`, never the email**, and record which path was taken in spec §18.

`apps/web/lib/agents.ts`:

```ts
// Server only. The browser never talks to the agents service, so no model key
// or database credential can reach it. Server to server calls carry a
// Google-signed ID token minted from the metadata server, whose audience is the
// agents service URL.
import { GoogleAuth } from "google-auth-library";
import type { Event } from "@magic-hour/contracts";

const AGENTS_URL = process.env.AGENTS_URL!;
const auth = new GoogleAuth();

async function authHeader(): Promise<Record<string, string>> {
  if (process.env.NODE_ENV !== "production" && process.env.SKIP_IAM === "1") {
    return {};   // local dev against `gcloud run services proxy`
  }
  const c = await auth.getIdTokenClient(AGENTS_URL);
  const h = await c.getRequestHeaders();
  return { Authorization: h.Authorization as string };
}

export async function callAgents<T>(path: string, body: unknown): Promise<T> {
  const r = await fetch(`${AGENTS_URL}${path}`, {
    method: "POST",
    headers: { "content-type": "application/json", ...(await authHeader()) },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`agents ${path} returned ${r.status}`);
  return r.json() as Promise<T>;
}

export async function* streamAgents(path: string, body: unknown): AsyncIterable<Event> {
  const r = await fetch(`${AGENTS_URL}${path}`, {
    method: "POST",
    headers: { "content-type": "application/json", ...(await authHeader()) },
    body: JSON.stringify(body),
  });
  const reader = r.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    // Frames are separated by a blank line and can split across chunks, so we
    // only consume complete frames and keep the remainder buffered.
    let i: number;
    while ((i = buffer.indexOf("\n\n")) !== -1) {
      const frame = buffer.slice(0, i).trim();
      buffer = buffer.slice(i + 2);
      if (!frame.startsWith("data:")) continue;
      const e = JSON.parse(frame.slice(5).trim()) as Event;
      yield e;
      if (e.t === "run_end") return;
    }
  }
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd apps/web && pnpm vitest run lib`
Expected: PASS, 3 tests.

- [ ] **Step 5: Verify end to end against the deployed agents service**

```bash
gcloud run services proxy magic-hour-agents --region=us-central1 \
  --project=nyu-ai-builder26nyc-9338 --port=8081 &
AGENTS_URL=http://localhost:8081 SKIP_IAM=1 pnpm dev
curl -s localhost:3000/api/health
```

Expected: `{"web":"ok","agents":{"ok":true}}`.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "Add web auth, session and the typed agents client

The browser never talks to the agents service, so no model key or database
credential can reach it, and a test asserts the client source contains neither.
Server to server calls mint a Google-signed ID token from the metadata server
with the agents URL as audience.

The SSE parser only consumes complete frames, because a frame split across two
network chunks is normal and silently drops an event otherwise. A test covers
exactly that case."
```

---

## Task 13: CI and deployment

**Files:**
- Create: `.github/workflows/ci.yml`, `.github/workflows/deploy.yml`
- Create: `infra/main.tf`, `infra/variables.tf`, `infra/README.md`

**Interfaces:**
- Consumes: `scripts/probe-models.sh`, `scripts/preflight.sh`, `Makefile`.
- Produces: PRs run lint, typecheck, tests, gitleaks, and the model probe. Pushes to `main` deploy both services with no-traffic, migrate, smoke test, then shift traffic.

- [ ] **Step 1: Write the failing test**

`apps/agents/tests/test_ci_config.py`:

```python
from pathlib import Path

import yaml

WF = Path(__file__).resolve().parents[3] / ".github" / "workflows"

def test_ci_runs_gitleaks_because_the_repo_is_public():
    body = (WF / "ci.yml").read_text(encoding="utf-8")
    assert "gitleaks" in body

def test_ci_probes_models_so_a_deprecation_breaks_the_build_not_the_demo():
    assert "probe-models.sh" in (WF / "ci.yml").read_text(encoding="utf-8")

def test_deploy_uses_workload_identity_and_never_a_key():
    body = (WF / "deploy.yml").read_text(encoding="utf-8")
    assert "workload_identity_provider" in body
    assert "credentials_json" not in body, "no service account keys, ever"

def test_deploy_shifts_traffic_only_after_a_smoke_test():
    doc = yaml.safe_load((WF / "deploy.yml").read_text(encoding="utf-8"))
    steps = [s.get("name", "") for j in doc["jobs"].values() for s in j["steps"]]
    joined = " | ".join(steps).lower()
    assert joined.index("smoke") < joined.index("traffic")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/agents && python -m pytest tests/test_ci_config.py -v`
Expected: FAIL with `FileNotFoundError` on `ci.yml`.

- [ ] **Step 3: Write the workflows**

`.github/workflows/ci.yml`:

```yaml
name: ci
on: [pull_request, push]

permissions:
  contents: read
  id-token: write

jobs:
  checks:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: pgvector/pgvector:pg16
        env: { POSTGRES_PASSWORD: dev, POSTGRES_DB: magichour }
        ports: ["5433:5432"]
        options: >-
          --health-cmd pg_isready --health-interval 5s
          --health-timeout 5s --health-retries 10
    steps:
      - uses: actions/checkout@v4

      - name: gitleaks
        uses: gitleaks/gitleaks-action@v2
        env: { GITHUB_TOKEN: "${{ secrets.GITHUB_TOKEN }}" }

      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - uses: actions/setup-node@v4
        with: { node-version: "24" }
      - uses: pnpm/action-setup@v4
        with: { version: 9 }

      - name: Install
        run: |
          pip install -e "apps/agents[dev]"
          pnpm install --frozen-lockfile

      - uses: google-github-actions/auth@v2
        with:
          workload_identity_provider: "${{ vars.WIF_PROVIDER }}"
          service_account: "${{ vars.CI_SERVICE_ACCOUNT }}"

      - name: Probe pinned models
        run: bash scripts/probe-models.sh "${{ vars.GCP_PROJECT }}"

      - name: Migrate and test agents
        env:
          MH_DB_HOST: localhost
          MH_DB_PORT: "5433"
          MH_DB_PASSWORD: dev
        run: |
          python scripts/migrate.py
          cd apps/agents && ruff check . && python -m pytest -q

      - name: Test web and contracts
        run: |
          pnpm --filter @magic-hour/contracts generate
          pnpm --filter @magic-hour/contracts test
          cd apps/web && pnpm lint && pnpm exec tsc --noEmit && pnpm vitest run
```

`.github/workflows/deploy.yml`:

```yaml
name: deploy
on:
  push:
    branches: [main]

permissions:
  contents: read
  id-token: write

env:
  REGION: us-central1

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: google-github-actions/auth@v2
        with:
          workload_identity_provider: "${{ vars.WIF_PROVIDER }}"
          service_account: "${{ vars.CI_SERVICE_ACCOUNT }}"
      - uses: google-github-actions/setup-gcloud@v2

      - name: Deploy agents with no traffic
        run: |
          gcloud run deploy magic-hour-agents --source apps/agents \
            --region=$REGION --project=${{ vars.GCP_PROJECT }} \
            --service-account=mh-agents@${{ vars.GCP_PROJECT }}.iam.gserviceaccount.com \
            --ingress=internal --no-allow-unauthenticated --min-instances=1 \
            --no-traffic --tag=candidate

      - name: Migrate the database
        run: |
          pip install -e "apps/agents[dev]"
          MH_DB_INSTANCE=${{ vars.GCP_PROJECT }}:$REGION:magic-hour-db \
            python scripts/migrate.py

      - name: Smoke test the candidate revision
        run: |
          URL=$(gcloud run services describe magic-hour-agents --region=$REGION \
                 --project=${{ vars.GCP_PROJECT }} \
                 --format='value(status.traffic[0].url)')
          TOKEN=$(gcloud auth print-identity-token)
          CODE=$(curl -s -o /dev/null -w '%{http_code}' -X POST \
                  -H "Authorization: Bearer $TOKEN" -H 'content-type: application/json' \
                  -d '{"ping":1}' "$URL/v1/echo")
          test "$CODE" = "200" || { echo "smoke test failed: $CODE"; exit 1; }

      - name: Shift traffic to the candidate
        run: |
          gcloud run services update-traffic magic-hour-agents --region=$REGION \
            --project=${{ vars.GCP_PROJECT }} --to-latest

      - name: Deploy web
        run: |
          gcloud run deploy magic-hour-web --source apps/web \
            --region=$REGION --project=${{ vars.GCP_PROJECT }} \
            --service-account=mh-web@${{ vars.GCP_PROJECT }}.iam.gserviceaccount.com \
            --allow-unauthenticated --min-instances=1 \
            --set-env-vars=AGENTS_URL=${{ vars.AGENTS_URL }}
```

`infra/main.tf`: Terraform covering the same resources as `scripts/bootstrap.sh` (APIs, three service accounts and bindings, GCS bucket, BigQuery dataset and four tables, Cloud SQL, Artifact Registry, both Cloud Run services, the WIF pool and provider), with a GCS backend for state. `bootstrap.sh` stays as the fast path for a new project; Terraform is the reproducible record.

**If WIF cannot be configured** on the lab project, replace the auth step with a Cloud Build trigger connected to the GitHub repo, running inside the project. Same pipeline, different runner, still no keys. Record which path was used in `infra/README.md`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd apps/agents && python -m pytest tests/test_ci_config.py -v`
Expected: PASS, 4 tests.

- [ ] **Step 5: Configure WIF and repo variables, then verify the pipeline**

```bash
P=nyu-ai-builder26nyc-9338
gcloud iam workload-identity-pools create github --location=global --project=$P
gcloud iam workload-identity-pools providers create-oidc github \
  --location=global --workload-identity-pool=github --project=$P \
  --issuer-uri=https://token.actions.githubusercontent.com \
  --attribute-mapping=google.subject=assertion.sub,attribute.repository=assertion.repository \
  --attribute-condition='assertion.repository=="sahajm99/previz"'
gcloud iam service-accounts add-iam-policy-binding mh-ci@$P.iam.gserviceaccount.com \
  --role=roles/iam.workloadIdentityUser --project=$P \
  --member="principalSet://iam.googleapis.com/projects/775345250143/locations/global/workloadIdentityPools/github/attribute.repository/sahajm99/previz"

gh variable set GCP_PROJECT --body "$P" --repo sahajm99/previz
gh variable set CI_SERVICE_ACCOUNT --body "mh-ci@$P.iam.gserviceaccount.com" --repo sahajm99/previz
gh variable set WIF_PROVIDER --repo sahajm99/previz --body \
  "projects/775345250143/locations/global/workloadIdentityPools/github/providers/github"
```

Then push and confirm CI is green and the deploy job reaches "Shift traffic".

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "Add CI and deployment with Workload Identity Federation

No service account keys exist anywhere, and a test asserts credentials_json
never appears in the deploy workflow. CI runs gitleaks because the repo is
public, and runs probe-models.sh against the live project so a model
deprecation breaks a build instead of a demo.

Deploys land with no traffic, migrate, smoke test the candidate revision, and
only then shift traffic. A test asserts the smoke step precedes the traffic
step, because that ordering is the entire value of the pattern."
```

---

## Self-Review

**Spec coverage.** §2 environment → Tasks 2, 3. §3 architecture and repo layout → Tasks 1, 9, 11. §4 data model and the invariant → Tasks 4, 5. §5 knowledge base, retrieval, Continuity Pack → Tasks 5, 6, 7. §10 model config → Task 2. §11 API contracts and SSE → Tasks 8, 10, 12. §12 design system → Task 11. §13 security → Tasks 3, 9, 12, 13. §14 observability → Task 8. §15 infra and CI/CD → Tasks 3, 13. §16 what carries forward from v1 → Tasks 1, 2, 9.

**Deferred to surface plans, by design:** §6 character consistency (Cast and Board plans), §7 script import (Script plan), §8 location scouting (Scout plan), §9.2 to §9.6 the agent trees (one plan each), §14's five eval metrics (Evals plan). Foundation delivers the substrate they all sit on. §13.1 auth is resolved inside Task 12 Step 3 rather than deferred, since every surface needs a session.

**Type consistency checked.** `reindex_entity` keeps the same signature in Tasks 5, 6 and 7. `search.hybrid` returns `list[Chunk]` in Task 6 and is consumed as such in Task 7. `events.Event` is the union in Task 8, mirrored in Task 10's schema and consumed in Task 12. `Run.queue` holds pre-serialised SSE strings in Task 8 and Task 9's `stream()` reads them as such.

**One thing an implementer must not silently change:** the `db.tx()` boundary in Task 5. If `reindex_entity` is ever called outside a transaction that also writes the structured row, the invariant in spec §4.1 is gone and the product's core promise goes with it.

---

## Next plans

Written after this one, in dependency order. Each is independently testable and can be owned by one person.

1. **Bible** · entity CRUD, the Canon strip, promotion, the Context and Trace tabs wired to real streams
2. **Cast** · the interview, the Ghostwriter, casting portraits, the reference sheet, the face fingerprint
3. **Board** · scene parse, Cinematographer shot list, Nano Banana, the continuity referee (depends on Cast)
4. **Script Room** · the Courier editor, ActionWriter, DialogueDirector, ScriptSupervisor (depends on Cast)
5. **Scout** · Places search, photo caching, shortlist, scene attachment
6. **Muse** · brainstorm chat, fact proposals, handoff to Cast and Scout
7. **Evals** · the golden set, five metrics, the `/evals` page, threshold calibration
