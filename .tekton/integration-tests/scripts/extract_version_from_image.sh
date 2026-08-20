#!/usr/bin/env bash
set -euo pipefail
IMAGE="${1:?image ref required}"
if [[ "$IMAGE" =~ mta-operator-container-([0-9]+\.[0-9]+\.[0-9]+) ]]; then
  echo "${BASH_REMATCH[1]}"
  exit 0
fi
if [[ "$IMAGE" =~ mta-([0-9]+\.[0-9]+\.[0-9]+) ]]; then
  echo "${BASH_REMATCH[1]}"
  exit 0
fi
echo "Could not parse MTA version from image: $IMAGE" >&2
exit 1
