#!/usr/bin/env bash
# Magic Hour · Vertex AI model probe
#
# Model IDs and regional availability move faster than any doc we could write,
# so we do not guess. This makes a real (tiny) call to every model Magic Hour
# depends on and reports what actually answers. Whatever passes here is what
# goes into the model config. Re-run after any project migration.
#
# Usage: bash scripts/probe-models.sh [PROJECT_ID]

set -uo pipefail
P="${1:-$(gcloud config get-value project 2>/dev/null)}"
TOKEN=$(gcloud auth print-access-token 2>/dev/null) || { echo "run: gcloud auth login" >&2; exit 2; }

probe_gen() { # model, location
  local M="$1" L="$2" HOST BODY CODE
  if [[ "$L" == "global" ]]; then HOST="aiplatform.googleapis.com"; else HOST="${L}-aiplatform.googleapis.com"; fi
  BODY='{"contents":[{"role":"user","parts":[{"text":"ok"}]}],"generationConfig":{"maxOutputTokens":8}}'
  CODE=$(curl -s -o /tmp/mh_probe.json -w '%{http_code}' -X POST \
    -H "Authorization: Bearer ${TOKEN}" -H "Content-Type: application/json" \
    "https://${HOST}/v1/projects/${P}/locations/${L}/publishers/google/models/${M}:generateContent" \
    -d "$BODY")
  printf '  %-34s %-11s %s' "$M" "$L" "$CODE"
  [[ "$CODE" != "200" ]] && printf '  %s' "$(head -c 150 /tmp/mh_probe.json | tr -d '\n')"
  printf '\n'
}

probe_embed() { # model, location, payload
  local M="$1" L="$2" BODY="$3" CODE
  CODE=$(curl -s -o /tmp/mh_probe.json -w '%{http_code}' -X POST \
    -H "Authorization: Bearer ${TOKEN}" -H "Content-Type: application/json" \
    "https://${L}-aiplatform.googleapis.com/v1/projects/${P}/locations/${L}/publishers/google/models/${M}:predict" \
    -d "$BODY")
  printf '  %-34s %-11s %s' "$M" "$L" "$CODE"
  if [[ "$CODE" == "200" ]]; then
    printf '  dims=%s' "$(python -c 'import json,sys;d=json.load(open("/tmp/mh_probe.json"))["predictions"][0];v=d.get("embeddings",{});v=v.get("values") if isinstance(v,dict) else d.get("imageEmbedding") or d.get("textEmbedding");print(len(v) if v else "?")' 2>/dev/null || echo '?')"
  else
    printf '  %s' "$(head -c 150 /tmp/mh_probe.json | tr -d '\n')"
  fi
  printf '\n'
}

echo "project: ${P}"
echo
echo "TEXT / REASONING  (model, location, http)"
for M in gemini-3-pro-preview gemini-3-flash-preview gemini-2.5-pro gemini-2.5-flash gemini-2.5-flash-lite gemini-flash-latest gemini-pro-latest; do
  probe_gen "$M" us-central1
done
echo
echo "TEXT / REASONING on global endpoint"
for M in gemini-3-pro-preview gemini-2.5-pro gemini-2.5-flash; do
  probe_gen "$M" global
done
echo
echo "IMAGE GENERATION  (Nano Banana family)"
for M in gemini-3-pro-image-preview gemini-2.5-flash-image gemini-2.5-flash-image-preview; do
  probe_gen "$M" us-central1
done
echo
echo "EMBEDDINGS"
probe_embed gemini-embedding-001 us-central1 '{"instances":[{"content":"a test sentence"}]}'
probe_embed text-embedding-005     us-central1 '{"instances":[{"content":"a test sentence"}]}'
probe_embed text-embedding-004     us-central1 '{"instances":[{"content":"a test sentence"}]}'
probe_embed multimodalembedding@001 us-central1 '{"instances":[{"text":"a test sentence"}]}'
echo
echo "Anything returning 200 is safe to pin in the model config."
