#!/usr/bin/env bash
# Runs right after the Service selector moves to the new color. Waits for the
# endpoints to list only the new pods, smokes the public route, and on failure
# returns traffic to the old color and scales the new one down. The old color
# keeps running throughout; the caller scales it down after this exits 0.
#
# A rollback moves traffic and code only. Migrations the new color ran stay
# applied, so the old color's smoke result is printed after a rollback.
#
# Usage: post_switch_verify.sh <namespace> <old-color> <new-color> <base-url>
set -uo pipefail

NS="$1"
OLD="$2"
NEW="$3"
BASE_URL="$4"

SMOKE="$(dirname "$0")/prod_smoke.sh"
ENDPOINT_WAIT_ROUNDS="${ENDPOINT_WAIT_ROUNDS:-30}"
ENDPOINT_WAIT_INTERVAL="${ENDPOINT_WAIT_INTERVAL:-1}"
DRAIN_SECONDS="${DRAIN_SECONDS:-15}"
SMOKE_ROUNDS="${SMOKE_ROUNDS:-6}"
SMOKE_INTERVAL="${SMOKE_INTERVAL:-10}"

sorted_ips() {
  tr ' ' '\n' | grep -v '^$' | sort | tr '\n' ' '
}

# Succeeds once the Service endpoints list exactly the pods of the given color.
wait_for_endpoints() {
  local color="$1" want have i
  for ((i = 0; i < ENDPOINT_WAIT_ROUNDS; i++)); do
    want=$(kubectl get pod -n "$NS" -l "app=github-tamagotchi,version=$color" \
      -o jsonpath='{.items[*].status.podIP}' | sorted_ips)
    have=$(kubectl get endpoints github-tamagotchi -n "$NS" \
      -o jsonpath='{.subsets[*].addresses[*].ip}' | sorted_ips)
    if [ -n "$want" ] && [ "$want" = "$have" ]; then
      echo "Service endpoints: $have($color)"
      return 0
    fi
    sleep "$ENDPOINT_WAIT_INTERVAL"
  done
  echo "Service endpoints: $have, expected $want($color)"
  return 1
}

roll_back() {
  echo "=== POST-SWITCH CHECK FAILED: $1 ==="
  kubectl logs -n "$NS" -l "app=github-tamagotchi,version=$NEW" \
    -c github-tamagotchi --tail=50 2>/dev/null || true

  local ready
  ready=$(kubectl get deployment "github-tamagotchi-$OLD" -n "$NS" \
    -o jsonpath='{.status.readyReplicas}' 2>/dev/null)
  if [ "${ready:-0}" -lt 1 ]; then
    echo "=== $OLD HAS NO READY PODS: no rollback target, traffic stays on $NEW ==="
    exit 1
  fi

  if ! kubectl patch service github-tamagotchi -n "$NS" \
    --type='json' \
    -p="[{\"op\":\"replace\",\"path\":\"/spec/selector/version\",\"value\":\"$OLD\"}]"; then
    echo "=== ROLLBACK FAILED: the Service still selects $NEW ==="
    exit 1
  fi
  echo "Traffic returned to $OLD"

  if ! wait_for_endpoints "$OLD"; then
    echo "=== ROLLBACK INCOMPLETE: endpoints did not return to $OLD, $NEW keeps running ==="
    exit 1
  fi
  sleep "$DRAIN_SECONDS"
  kubectl scale "deployment/github-tamagotchi-$NEW" --replicas=0 -n "$NS"

  if bash "$SMOKE" "$BASE_URL"; then
    echo "=== ROLLED BACK: $OLD passes the smoke ==="
  else
    echo "=== ROLLED BACK, $OLD FAILS THE SMOKE: check migrations the new image applied ==="
  fi
  exit 1
}

if ! wait_for_endpoints "$NEW"; then
  roll_back "endpoints did not move to $NEW"
fi
sleep "$DRAIN_SECONDS"

FAILURES=0
for ((round = 1; round <= SMOKE_ROUNDS; round++)); do
  if bash "$SMOKE" "$BASE_URL"; then
    FAILURES=0
  else
    FAILURES=$((FAILURES + 1))
    if [ "$FAILURES" -ge 2 ]; then
      roll_back "smoke failed twice in a row"
    fi
  fi
  if [ "$round" -lt "$SMOKE_ROUNDS" ]; then
    sleep "$SMOKE_INTERVAL"
  fi
done

if [ "$FAILURES" -gt 0 ]; then
  roll_back "smoke failed on the last round"
fi

echo "Post-switch checks passed on $NEW"
