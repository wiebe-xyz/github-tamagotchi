#!/usr/bin/env bash
# One smoke round against the public production route: readiness must report
# healthy and the home page must answer.
#
# Usage: prod_smoke.sh <base-url>
set -uo pipefail

BASE_URL="${1%/}"

if ! READY=$(curl -fsS --max-time 10 "$BASE_URL/api/v1/health/ready"); then
  echo "smoke: readiness request failed"
  exit 1
fi

case "$READY" in
  *'"status":"healthy"'*) ;;
  *)
    echo "smoke: readiness did not report healthy"
    exit 1
    ;;
esac

if ! curl -fsS --max-time 10 -o /dev/null "$BASE_URL/"; then
  echo "smoke: home page request failed"
  exit 1
fi

echo "smoke: ok"
