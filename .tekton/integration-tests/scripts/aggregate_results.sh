#!/usr/bin/env bash
# Emit Konflux-compatible TEST_OUTPUT JSON. Always exits 0 so the Tekton result
# is published even when lanes failed. Use verify_results.sh as the failure gate.
set -euo pipefail
LINUX_STATUS="$(cat "${1:?}")"
WINDOWS_STATUS="$(cat "${2:?}")"
DARWIN_STATUS="$(cat "${3:?}")"
OUT="${4:?}"

successes=0
failures=0
for status in "$LINUX_STATUS" "$WINDOWS_STATUS" "$DARWIN_STATUS"; do
  if [[ "$status" == "PASSED" ]]; then
    successes=$((successes + 1))
  else
    failures=$((failures + 1))
  fi
done

if [[ "$failures" -eq 0 ]]; then
  result="SUCCESS"
else
  result="FAILURE"
fi

timestamp="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
python3 - "$OUT" "$result" "$timestamp" "$successes" "$failures" \
  "$LINUX_STATUS" "$WINDOWS_STATUS" "$DARWIN_STATUS" <<'PY'
import json
import sys

out, result, timestamp, successes, failures, linux, windows, darwin = sys.argv[1:]
payload = {
    "result": result,
    "timestamp": timestamp,
    "successes": int(successes),
    "failures": int(failures),
    "warnings": 0,
    "details": {
        "linux": linux,
        "windows": windows,
        "darwin": darwin,
    },
}
with open(out, "w", encoding="utf-8") as fh:
    json.dump(payload, fh, indent=2)
    fh.write("\n")
print(json.dumps(payload, indent=2))
PY
