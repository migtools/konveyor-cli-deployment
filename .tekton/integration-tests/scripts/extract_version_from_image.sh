#!/usr/bin/env bash
# Extract MTA X.Y.Z from an image reference or Konflux FBC digest.
# 1) Parse version from image tag/string (legacy tagged FBC refs).
# 2) For digest-only quay FBC images, discover related-images and find
#    mta-operator-container-X.Y.Z (same artifact Konflux attaches for FBC E2E).
set -euo pipefail

IMAGE="${1:?image ref required}"

parse_from_string() {
  local s="$1"
  if [[ "$s" =~ mta-operator-container-([0-9]+\.[0-9]+\.[0-9]+) ]]; then
    echo "${BASH_REMATCH[1]}"
    return 0
  fi
  if [[ "$s" =~ mta-([0-9]+\.[0-9]+\.[0-9]+) ]]; then
    echo "${BASH_REMATCH[1]}"
    return 0
  fi
  return 1
}

if parse_from_string "$IMAGE"; then
  exit 0
fi

# Digest-only (or otherwise unparseable) refs: try Konflux related-images.
if ! command -v curl >/dev/null 2>&1; then
  echo "Could not parse MTA version from image: $IMAGE (curl required for related-images fallback)" >&2
  exit 1
fi

if ! command -v jq >/dev/null 2>&1; then
  echo "Installing jq for related-images parse..." >&2
  curl -fsSL https://github.com/jqlang/jq/releases/download/jq-1.7.1/jq-linux-amd64 -o /usr/local/bin/jq
  chmod +x /usr/local/bin/jq
fi

if ! command -v oras >/dev/null 2>&1; then
  echo "Installing oras for related-images discover..." >&2
  ORAS_VERSION="1.2.0"
  curl -fsSL "https://github.com/oras-project/oras/releases/download/v${ORAS_VERSION}/oras_${ORAS_VERSION}_linux_amd64.tar.gz" \
    | tar -xz -C /usr/local/bin oras
  chmod +x /usr/local/bin/oras
fi

echo "Image ref has no embedded version; trying related-images on $IMAGE" >&2
RELATED_IMAGES_DIGEST="$(
  oras discover --format json "$IMAGE" 2>/dev/null \
    | jq -r '.manifests[]? | select(.annotations.attachedMediaType == "application/vnd.konflux-ci.attached-artifact.related-images+json") | .digest' \
    | head -1 || true
)"

if [[ -z "${RELATED_IMAGES_DIGEST}" || "${RELATED_IMAGES_DIGEST}" == "null" ]]; then
  echo "Could not parse MTA version from image: $IMAGE (no related-images artifact)" >&2
  exit 1
fi

WORK_DIR="$(mktemp -d)"
trap 'rm -rf "$WORK_DIR"' EXIT
cd "$WORK_DIR"

FBC_REPO="${IMAGE%%@*}"
FBC_REPO="${FBC_REPO%%:*}"
echo "Pulling related-images ${FBC_REPO}@${RELATED_IMAGES_DIGEST}" >&2
oras pull "${FBC_REPO}@${RELATED_IMAGES_DIGEST}" >/dev/null

if [[ ! -f related-images.json ]]; then
  echo "Could not parse MTA version from image: $IMAGE (related-images.json missing)" >&2
  exit 1
fi

# Prefer operator container NVR; fall back to any mta-*-X.Y.Z in the list.
CANDIDATE="$(
  jq -r '.[]?' related-images.json 2>/dev/null \
    | grep -oE 'mta-operator-container-[0-9]+\.[0-9]+\.[0-9]+' \
    | head -1 || true
)"
if [[ -z "$CANDIDATE" ]]; then
  CANDIDATE="$(
    jq -r '.[]?' related-images.json 2>/dev/null \
      | grep -oE 'mta-[A-Za-z0-9._-]*-[0-9]+\.[0-9]+\.[0-9]+' \
      | head -1 || true
  )"
fi

if ! parse_from_string "${CANDIDATE:-}"; then
  echo "Could not parse MTA version from image: $IMAGE (no mta version in related-images)" >&2
  exit 1
fi
