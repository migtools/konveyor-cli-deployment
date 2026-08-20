#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SCRIPT="$ROOT/.tekton/integration-tests/scripts/aggregate_results.sh"
VERIFY="$ROOT/.tekton/integration-tests/scripts/verify_results.sh"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

printf 'PASSED' > "$TMP/linux"
printf 'FAILED' > "$TMP/windows"
printf 'PASSED' > "$TMP/darwin"

"$SCRIPT" "$TMP/linux" "$TMP/windows" "$TMP/darwin" "$TMP/out.json"
python3 - <<PY
import json
with open("$TMP/out.json") as f:
    data = json.load(f)
assert data["result"] == "FAILURE"
assert data["successes"] == 2
assert data["failures"] == 1
assert data["details"]["windows"] == "FAILED"
print("aggregate OK")
PY

if "$VERIFY" "$TMP/linux" "$TMP/windows" "$TMP/darwin"; then
  echo "verify should have failed" >&2
  exit 1
fi

printf 'PASSED' > "$TMP/windows"
"$VERIFY" "$TMP/linux" "$TMP/windows" "$TMP/darwin"
echo "OK"
