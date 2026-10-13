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
if ! command -v python3 >/dev/null 2>&1; then
  echo "Could not parse MTA version from image: $IMAGE (python3 required for related-images fallback)" >&2
  exit 1
fi

# ubi9/python images run as non-root; never write to /usr/local/bin.
TOOL_DIR="${TOOL_DIR:-/tmp/mta-cli-e2e-tools}"
mkdir -p "$TOOL_DIR"
export PATH="${TOOL_DIR}:${PATH}"

if ! command -v oras >/dev/null 2>&1; then
  echo "Installing oras into ${TOOL_DIR}..." >&2
  ORAS_VERSION="1.2.0"
  curl -fsSL "https://github.com/oras-project/oras/releases/download/v${ORAS_VERSION}/oras_${ORAS_VERSION}_linux_amd64.tar.gz" \
    | tar -xz -C "$TOOL_DIR" oras
  chmod +x "${TOOL_DIR}/oras"
fi

echo "Image ref has no embedded version; trying related-images on $IMAGE" >&2
RELATED_IMAGES_DIGEST="$(
  oras discover --format json "$IMAGE" 2>/dev/null \
    | python3 -c '
import json, sys
data = json.load(sys.stdin)
for m in data.get("manifests") or []:
    ann = m.get("annotations") or {}
    if ann.get("attachedMediaType") == "application/vnd.konflux-ci.attached-artifact.related-images+json":
        print(m.get("digest") or "")
        break
' || true
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

CANDIDATE="$(
  python3 - <<'PY'
import json, re
with open("related-images.json", encoding="utf-8") as fh:
    data = json.load(fh)
entries = data if isinstance(data, list) else list(data.values()) if isinstance(data, dict) else []
text_entries = []
for item in entries:
    if isinstance(item, str):
        text_entries.append(item)
    elif isinstance(item, dict):
        text_entries.extend(str(v) for v in item.values())
joined = "\n".join(text_entries)
m = re.search(r"mta-operator-container-([0-9]+\.[0-9]+\.[0-9]+)", joined)
if m:
    print(f"mta-operator-container-{m.group(1)}")
else:
    m = re.search(r"mta-[A-Za-z0-9._-]*-([0-9]+\.[0-9]+\.[0-9]+)", joined)
    if m:
        print(m.group(0))
PY
)"

if ! parse_from_string "${CANDIDATE:-}"; then
  echo "Could not parse MTA version from image: $IMAGE (no mta version in related-images)" >&2
  exit 1
fi
