#!/usr/bin/env bash
# Build mta-{version}-cli-{os}-{arch}.zip from the CLI image in related-images.json.
# Intended for local/Task use when podman is available. Pipeline remote deploy
# prefers in-process extract via utils.fbc_cli_extract on the VM.
#
# Usage:
#   extract_fbc_cli_zip.sh <related-images.json> <MTA_VERSION> <TARGET_OS> <PLATFORM> <OUT_DIR>
set -euo pipefail

RELATED="${1:?related-images.json required}"
VERSION="${2:?MTA version required}"
TARGET_OS="${3:?target OS required}"
PLATFORM="${4:?platform required}"
OUT_DIR="${5:?output directory required}"

ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
export PYTHONPATH="${ROOT}${PYTHONPATH:+:$PYTHONPATH}"

mkdir -p "$OUT_DIR"
python3 - <<PY
import json, os, sys
sys.path.insert(0, "$ROOT")
from utils.fbc_cli_extract import extract_cli_zip
from utils.images import find_cli_image, load_image_list

images = load_image_list("$RELATED")
cli = find_cli_image(images)
path = extract_cli_zip(
    cli_image=cli,
    version="$VERSION",
    platform="$TARGET_OS",
    arch="$PLATFORM",
    output_dir="$OUT_DIR",
    client=None,
)
print(path)
PY
