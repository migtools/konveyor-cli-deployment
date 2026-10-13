#!/usr/bin/env bash
# Extract MTA X.Y.Z from an image reference or Konflux FBC digest.
#
# Order:
# 1) Parse version from image tag/string (legacy tagged FBC refs).
# 2) For digest-only FBC images:
#    a) related-images.json string match (legacy NVR-in-name)
#    b) rendered-catalog defaultChannel HEAD (mta-operator.vX.Y.Z)
#    c) skopeo Labels.version on stage mta-cli-rhel9 from related-images
set -euo pipefail

IMAGE="${1:?image ref required}"

parse_from_string() {
  local s="$1"
  if [[ "$s" =~ mta-operator-container-([0-9]+\.[0-9]+\.[0-9]+) ]]; then
    echo "${BASH_REMATCH[1]}"
    return 0
  fi
  if [[ "$s" =~ mta-operator\.v([0-9]+\.[0-9]+\.[0-9]+) ]]; then
    echo "${BASH_REMATCH[1]}"
    return 0
  fi
  if [[ "$s" =~ mta-([0-9]+\.[0-9]+\.[0-9]+) ]]; then
    echo "${BASH_REMATCH[1]}"
    return 0
  fi
  # Label values like 8.3.1 or 8.3.1.20261013...
  if [[ "$s" =~ ^([0-9]+\.[0-9]+\.[0-9]+)([.+]|$) ]]; then
    echo "${BASH_REMATCH[1]}"
    return 0
  fi
  return 1
}

if parse_from_string "$IMAGE"; then
  exit 0
fi

if ! command -v curl >/dev/null 2>&1; then
  echo "Could not parse MTA version from image: $IMAGE (curl required)" >&2
  exit 1
fi
if ! command -v python3 >/dev/null 2>&1; then
  echo "Could not parse MTA version from image: $IMAGE (python3 required)" >&2
  exit 1
fi

# ubi9/python images run as non-root; never write to /usr/local/bin.
TOOL_DIR="${TOOL_DIR:-/tmp/mta-cli-e2e-tools}"
mkdir -p "$TOOL_DIR"
export PATH="${TOOL_DIR}:${PATH}"

ensure_oras() {
  if command -v oras >/dev/null 2>&1; then
    return 0
  fi
  echo "Installing oras into ${TOOL_DIR}..." >&2
  ORAS_VERSION="1.2.0"
  curl -fsSL "https://github.com/oras-project/oras/releases/download/v${ORAS_VERSION}/oras_${ORAS_VERSION}_linux_amd64.tar.gz" \
    | tar -xz -C "$TOOL_DIR" oras
  chmod +x "${TOOL_DIR}/oras"
}

ensure_skopeo() {
  if command -v skopeo >/dev/null 2>&1; then
    return 0
  fi
  # Optional fallback only; catalog path usually succeeds first.
  echo "Installing skopeo into ${TOOL_DIR}..." >&2
  # Use the same image's binary via a tiny copy is hard; prefer catalog.
  return 1
}

ensure_oras

echo "Image ref has no embedded version; discovering Konflux artifacts on $IMAGE" >&2
DISCOVER_JSON="$(oras discover --format json "$IMAGE" 2>/dev/null || true)"
if [[ -z "$DISCOVER_JSON" ]]; then
  echo "Could not parse MTA version from image: $IMAGE (oras discover failed)" >&2
  exit 1
fi

artifact_digest() {
  local media_type="$1"
  printf '%s' "$DISCOVER_JSON" | python3 -c '
import json, sys
media = sys.argv[1]
data = json.load(sys.stdin)
for m in data.get("manifests") or []:
    ann = m.get("annotations") or {}
    if ann.get("attachedMediaType") == media:
        print(m.get("digest") or "")
        break
' "$media_type"
}

FBC_REPO="${IMAGE%%@*}"
FBC_REPO="${FBC_REPO%%:*}"
WORK_DIR="$(mktemp -d)"
trap 'rm -rf "$WORK_DIR"' EXIT

# --- related-images: legacy NVR-in-name ---
RELATED_DIGEST="$(artifact_digest "application/vnd.konflux-ci.attached-artifact.related-images+json")"
if [[ -n "$RELATED_DIGEST" ]]; then
  echo "Pulling related-images ${FBC_REPO}@${RELATED_DIGEST}" >&2
  (
    cd "$WORK_DIR"
    rm -f related-images.json
    oras pull "${FBC_REPO}@${RELATED_DIGEST}" >/dev/null
  )
  if [[ -f "$WORK_DIR/related-images.json" ]]; then
    CANDIDATE="$(
      python3 - <<PY
import json, re
with open("$WORK_DIR/related-images.json", encoding="utf-8") as fh:
    data = json.load(fh)
entries = data if isinstance(data, list) else list(data.values()) if isinstance(data, dict) else []
joined = "\\n".join(str(x) for x in entries)
m = re.search(r"mta-operator-container-([0-9]+\\.[0-9]+\\.[0-9]+)", joined)
if m:
    print(f"mta-operator-container-{m.group(1)}")
PY
    )"
    if parse_from_string "${CANDIDATE:-}"; then
      exit 0
    fi
  fi
fi

# --- rendered-catalog: defaultChannel HEAD (works without registry.stage auth) ---
CATALOG_DIGEST="$(artifact_digest "application/vnd.konflux-ci.attached-artifact.rendered-catalog+json")"
if [[ -n "$CATALOG_DIGEST" ]]; then
  echo "Pulling rendered-catalog ${FBC_REPO}@${CATALOG_DIGEST}" >&2
  (
    cd "$WORK_DIR"
    rm -f catalog.json
    oras pull "${FBC_REPO}@${CATALOG_DIGEST}" >/dev/null
  )
  if [[ -f "$WORK_DIR/catalog.json" ]]; then
    CATALOG_VERSION="$(
      python3 - <<PY
import json, re
from pathlib import Path
text = Path("$WORK_DIR/catalog.json").read_text(encoding="utf-8")
default_channel = None
channels = {}
for line in text.splitlines():
    line = line.strip()
    if not line:
        continue
    try:
        obj = json.loads(line)
    except json.JSONDecodeError:
        # Some catalogs are a single JSON object / pretty blob.
        continue
    if not isinstance(obj, dict):
        continue
    schema = obj.get("schema")
    if schema == "olm.package":
        default_channel = obj.get("defaultChannel") or default_channel
    elif schema == "olm.channel":
        channels[obj.get("name")] = obj.get("entries") or []

# Fallback if file is one JSON document rather than NDJSON.
if default_channel is None and not channels:
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        obj = None
    if isinstance(obj, dict):
        default_channel = obj.get("defaultChannel")
    elif isinstance(obj, list):
        for item in obj:
            if isinstance(item, dict) and item.get("schema") == "olm.package":
                default_channel = item.get("defaultChannel")
            if isinstance(item, dict) and item.get("schema") == "olm.channel":
                channels[item.get("name")] = item.get("entries") or []

# Also recover package header from leading pretty-printed object if present.
if default_channel is None:
    m = re.search(r'"defaultChannel"\\s*:\\s*"(stable-v[0-9.]+)"', text)
    if m:
        default_channel = m.group(1)

if not default_channel:
    # Pick highest stable-vX.Y channel found in text.
    found = sorted(set(re.findall(r"stable-v[0-9]+\\.[0-9]+", text)))
    default_channel = found[-1] if found else None

head_name = None
entries = channels.get(default_channel) or []
if entries and isinstance(entries[-1], dict):
    head_name = entries[-1].get("name")
if not head_name:
    # Grep channel head from text near default channel.
    vers = re.findall(r"mta-operator\\.v([0-9]+\\.[0-9]+\\.[0-9]+)", text)
    if vers:
        # Prefer versions matching defaultChannel minor (stable-v8.3 -> 8.3.x)
        minor = None
        if default_channel and default_channel.startswith("stable-v"):
            minor = default_channel[len("stable-v"):]
        if minor:
            matched = [v for v in vers if v.startswith(minor + ".")]
            head_name = f"mta-operator.v{matched[-1]}" if matched else f"mta-operator.v{vers[-1]}"
        else:
            head_name = f"mta-operator.v{vers[-1]}"

if head_name:
    m = re.search(r"([0-9]+\\.[0-9]+\\.[0-9]+)", head_name)
    if m:
        print(m.group(1))
PY
    )"
    if parse_from_string "${CATALOG_VERSION:-}"; then
      exit 0
    fi
  fi
fi

# --- skopeo Labels.version on stage CLI image from related-images ---
if [[ -f "$WORK_DIR/related-images.json" ]] && ensure_skopeo; then
  CLI_IMG="$(
    python3 - <<PY
import json
with open("$WORK_DIR/related-images.json", encoding="utf-8") as fh:
    data = json.load(fh)
entries = data if isinstance(data, list) else []
for item in entries:
    if isinstance(item, str) and "mta-cli-rhel9@" in item:
        print(item.replace("registry.redhat.io", "registry.stage.redhat.io"))
        break
PY
  )"
  if [[ -n "${CLI_IMG}" ]]; then
    echo "Inspecting CLI image labels: $CLI_IMG" >&2
    LABEL_VERSION="$(
      skopeo inspect --override-os linux --override-arch amd64 --format '{{index .Labels "version"}}' \
        "docker://${CLI_IMG}" 2>/dev/null || true
    )"
    if parse_from_string "${LABEL_VERSION:-}"; then
      exit 0
    fi
  fi
fi

echo "Could not parse MTA version from image: $IMAGE (no version in related-images/catalog/labels)" >&2
exit 1
