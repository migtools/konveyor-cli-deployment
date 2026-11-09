#!/usr/bin/env bash
# Pull Konflux related-images.json for an FBC/SNAPSHOT image via oras.
# Usage: fetch_fbc_related_images.sh <FBC_IMAGE> <OUTPUT_JSON_PATH>
set -euo pipefail

IMAGE="${1:?FBC image ref required}"
OUT="${2:?output related-images.json path required}"

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
if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 required" >&2
  exit 1
fi

mkdir -p "$(dirname "$OUT")"
WORK_DIR="$(mktemp -d)"
trap 'rm -rf "$WORK_DIR"' EXIT

echo "Discovering related-images for $IMAGE" >&2
DISCOVER_JSON="$(oras discover --format json "$IMAGE")"

RELATED_DIGEST="$(
  printf '%s' "$DISCOVER_JSON" | python3 -c '
import json, sys
data = json.load(sys.stdin)
want = "application/vnd.konflux-ci.attached-artifact.related-images+json"
for m in data.get("manifests") or []:
    ann = m.get("annotations") or {}
    if ann.get("attachedMediaType") == want:
        print(m.get("digest") or "")
        break
'
)"

if [[ -z "${RELATED_DIGEST}" ]]; then
  echo "No related-images artifact found on $IMAGE" >&2
  exit 1
fi

FBC_REPO="${IMAGE%%@*}"
FBC_REPO="${FBC_REPO%%:*}"
echo "Pulling related-images ${FBC_REPO}@${RELATED_DIGEST}" >&2
(
  cd "$WORK_DIR"
  rm -f related-images.json
  oras pull "${FBC_REPO}@${RELATED_DIGEST}" >/dev/null
)

if [[ ! -f "$WORK_DIR/related-images.json" ]]; then
  found="$(find "$WORK_DIR" -type f -name 'related-images.json' | head -n1 || true)"
  if [[ -z "$found" ]]; then
    echo "oras pull succeeded but related-images.json is missing" >&2
    ls -la "$WORK_DIR" >&2 || true
    exit 1
  fi
  cp "$found" "$WORK_DIR/related-images.json"
fi

python3 - <<PY
import json
from pathlib import Path
src = Path("$WORK_DIR/related-images.json")
dst = Path("$OUT")
data = json.loads(src.read_text(encoding="utf-8"))

def rewrite(item):
    if isinstance(item, str):
        return item.replace("registry.redhat.io", "registry.stage.redhat.io")
    if isinstance(item, dict) and "image" in item:
        item = dict(item)
        item["image"] = str(item["image"]).replace("registry.redhat.io", "registry.stage.redhat.io")
        return item
    return item

if isinstance(data, list):
    data = [rewrite(x) for x in data]
elif isinstance(data, dict):
    data = {k: rewrite(v) for k, v in data.items()}
dst.parent.mkdir(parents=True, exist_ok=True)
dst.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
print(dst)
PY

echo "Wrote $OUT" >&2
