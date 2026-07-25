#!/usr/bin/env bash
# Deploy Magic Hour to Cloud Run. One command, one service.
#
#   ./scripts/deploy.sh
#
# The design has two services, web public and agents internal only. That split is
# correct and is cancelled for today (docs/NOW.md): with one process there is no
# ID token to verify and no second cold start to pay for.
#
# min-instances 1 because cold starting a container that imports the Vertex SDK is
# four to eight seconds, and on a demo stage that reads as broken.
set -euo pipefail

PROJECT="${GCP_PROJECT:-nyu-ai-builder26nyc-9338}"
REGION="${GCP_REGION:-us-central1}"
SERVICE="${SERVICE:-magic-hour}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "· project $PROJECT · region $REGION · service $SERVICE"
gcloud config set project "$PROJECT" >/dev/null

gcloud services enable run.googleapis.com artifactregistry.googleapis.com >/dev/null

# Built locally and pushed, NOT via `gcloud run deploy --source`.
#
# --source hands the build to Cloud Build, whose default service account is missing
# roles/cloudbuild.builds.builder on this project, and granting it needs
# resourcemanager.projects.setIamPolicy which this account does not have. The
# failure is also misleading: it reports a permission denied on the source bucket
# rather than on the build. Building here and pushing uses only permissions we
# already hold, so it needs no policy change at all.
IMAGE="$REGION-docker.pkg.dev/$PROJECT/cloud-run-source-deploy/$SERVICE"
TAG="$(cd "$ROOT" && git rev-parse --short HEAD 2>/dev/null || echo manual)"

# Tag by commit so a revision can be traced back to a SHA, and :latest so there is
# always something obvious to roll forward to.
echo "· building $IMAGE:$TAG"
gcloud auth configure-docker "$REGION-docker.pkg.dev" --quiet >/dev/null 2>&1

# Context is the repo root, not backend/, because the app reads
# data/seed/character_questions.json. Building from backend/ produces an image that
# boots, serves the UI, and 404s every /api route.
docker build -q -f "$ROOT/backend/Dockerfile" \
  -t "$IMAGE:$TAG" -t "$IMAGE:latest" "$ROOT" >/dev/null
docker push -q "$IMAGE:$TAG" >/dev/null
docker push -q "$IMAGE:latest" >/dev/null
echo "· pushed $TAG"

gcloud run deploy "$SERVICE" \
  --image "$IMAGE:$TAG" \
  --region "$REGION" \
  --allow-unauthenticated \
  --min-instances 1 \
  --memory 2Gi \
  --cpu 2 \
  --timeout 600 \
  --port 8080 \
  --update-env-vars "GCP_PROJECT=$PROJECT,GCP_LOCATION=$REGION${GOOGLE_MAPS_API_KEY:+,GOOGLE_MAPS_API_KEY=$GOOGLE_MAPS_API_KEY}${GOOGLE_OAUTH_CLIENT_ID:+,GOOGLE_OAUTH_CLIENT_ID=$GOOGLE_OAUTH_CLIENT_ID}"

URL="$(gcloud run services describe "$SERVICE" --region "$REGION" \
        --format='value(status.url)')"
echo
echo "  $URL"
echo "  health · $URL/api/health"
echo

# Smoke test the revision rather than trusting that the deploy printed a URL. A
# service that deployed and does not answer is the failure worth catching here,
# not on stage.
if curl -fsS --max-time 30 "$URL/api/health" >/dev/null; then
  echo "  health answered"
else
  echo "  WARNING: health did not answer. Check: gcloud run services logs read $SERVICE --region $REGION"
  exit 1
fi
