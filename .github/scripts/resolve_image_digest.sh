#!/usr/bin/env bash
# Prints the immutable reference of a pushed image, repository@sha256:..., and fails
# when the registry does not return a digest.
#
# Usage: resolve_image_digest.sh <repository:tag>
set -euo pipefail

REF="$1"
DIGEST=$(docker buildx imagetools inspect "$REF" --format '{{.Manifest.Digest}}')

if [[ ! "$DIGEST" =~ ^sha256:[0-9a-f]{64}$ ]]; then
  echo "No digest for $REF: $DIGEST" >&2
  exit 1
fi

echo "${REF%:*}@$DIGEST"
