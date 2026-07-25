#!/usr/bin/env bash
# Magic Hour · GCP preflight
#
# Tells us whether a given GCP project can actually host Magic Hour, before we
# write code against it. Safe to re-run. Reads only, changes nothing.
#
# Usage:
#   bash scripts/preflight.sh <PROJECT_ID>
#
# Run this against the hackathon lab project first, then again against the
# permanent project when we migrate. Any FAIL line is a design decision.

set -uo pipefail

PROJECT="${1:-$(gcloud config get-value project 2>/dev/null)}"
if [[ -z "$PROJECT" || "$PROJECT" == "(unset)" ]]; then
  echo "usage: bash scripts/preflight.sh <PROJECT_ID>" >&2
  exit 2
fi

pass() { printf '  PASS  %s\n' "$*"; }
fail() { printf '  FAIL  %s\n' "$*"; }
warn() { printf '  WARN  %s\n' "$*"; }
head2() { printf '\n=== %s\n' "$*"; }

head2 "Identity and project"
ACCOUNT=$(gcloud config get-value account 2>/dev/null)
echo "  account: ${ACCOUNT}"
echo "  project: ${PROJECT}"
gcloud projects describe "$PROJECT" \
  --format='value[separator="  "](projectNumber,lifecycleState,createTime)' 2>&1 \
  | sed 's/^/  number/'

head2 "Billing"
if gcloud billing projects describe "$PROJECT" --format='value(billingEnabled)' 2>/dev/null | grep -qi true; then
  pass "billing enabled"
  gcloud billing projects describe "$PROJECT" --format='value(billingAccountName)' | sed 's/^/  account: /'
else
  fail "billing NOT enabled or not visible to this account. Vertex, Maps and Cloud SQL will all refuse."
fi

head2 "Roles this account holds on the project"
gcloud projects get-iam-policy "$PROJECT" \
  --flatten='bindings[].members' \
  --filter="bindings.members:${ACCOUNT}" \
  --format='value(bindings.role)' 2>&1 | sed 's/^/  /' \
  || warn "cannot read IAM policy, so this account is probably not an admin"

head2 "APIs already enabled"
gcloud services list --enabled --project="$PROJECT" \
  --format='value(config.name)' 2>&1 | sort | sed 's/^/  /'

head2 "Org policies that would break us"
# A policy object existing is not the same as a policy being enforced. Always
# read --effective and look at the actual value, otherwise you scare yourself
# into building a VPC you did not need.
#
#   listPolicy.allValues: ALLOW   -> permissive, we are fine
#   listPolicy.allValues: DENY    -> blocked
#   listPolicy.allowedValues: [..]-> only those values permitted
#   booleanPolicy: {}             -> NOT enforced
#   booleanPolicy.enforced: true  -> blocked
for C in \
  iam.allowedPolicyMemberDomains \
  iam.disableServiceAccountKeyCreation \
  run.allowedIngress \
  storage.publicAccessPrevention \
  sql.restrictPublicIp \
  compute.vmExternalIpAccess
do
  OUT=$(gcloud resource-manager org-policies describe "$C" --project="$PROJECT" --effective 2>&1)
  if grep -q "PERMISSION_DENIED\|Permission denied" <<<"$OUT"; then
    warn "$C unreadable from this account"
  elif grep -q "NOT_FOUND\|does not exist" <<<"$OUT"; then
    pass "$C not set"
  elif grep -q "allValues: ALLOW" <<<"$OUT"; then
    pass "$C present but permissive (allValues: ALLOW)"
  elif grep -qE "booleanPolicy: \{\}" <<<"$OUT"; then
    pass "$C present but NOT enforced"
  elif grep -q "enforced: true\|allValues: DENY\|allowedValues" <<<"$OUT"; then
    fail "$C ENFORCED:"
    sed 's/^/        /' <<<"$OUT" | head -12
  else
    warn "$C unclear, read it yourself:"
    sed 's/^/        /' <<<"$OUT" | head -12
  fi
done

head2 "Vertex AI regional model availability (us-central1)"
TOKEN=$(gcloud auth print-access-token 2>/dev/null)
if [[ -z "$TOKEN" ]]; then
  fail "no access token, run: gcloud auth login"
else
  for M in \
    publishers/google/models/gemini-2.5-flash \
    publishers/google/models/gemini-2.5-pro \
    publishers/google/models/gemini-2.5-flash-image \
    publishers/google/models/text-embedding-005 \
    publishers/google/models/multimodalembedding@001
  do
    CODE=$(curl -s -o /dev/null -w '%{http_code}' \
      -H "Authorization: Bearer ${TOKEN}" \
      "https://us-central1-aiplatform.googleapis.com/v1/projects/${PROJECT}/locations/us-central1/${M}")
    case "$CODE" in
      200) pass "${M##*/} reachable" ;;
      403) fail "${M##*/} 403 (API disabled, or model not allowlisted for this project)" ;;
      404) fail "${M##*/} 404 (model id wrong for this region, or unavailable)" ;;
      *)   warn "${M##*/} HTTP ${CODE}" ;;
    esac
  done
fi

head2 "Quota headroom worth knowing"
gcloud alpha services quota list \
  --service=aiplatform.googleapis.com \
  --consumer="projects/${PROJECT}" \
  --format='value(metric,displayName)' 2>&1 | head -20 | sed 's/^/  /' \
  || warn "quota listing unavailable, we will discover limits by calling the models"

head2 "Done"
echo "  Every FAIL above is a fallback we need to choose before writing code."
