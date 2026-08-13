#!/usr/bin/env bash
set -euo pipefail
LINUX_STATUS="$(cat "${1:?}")"
WINDOWS_STATUS="$(cat "${2:?}")"
DARWIN_STATUS="$(cat "${3:?}")"
OUT="${4:?}"
{
  echo "linux=$LINUX_STATUS"
  echo "windows=$WINDOWS_STATUS"
  echo "darwin=$DARWIN_STATUS"
} | tee "$OUT"
if [[ "$LINUX_STATUS" != PASSED || "$WINDOWS_STATUS" != PASSED || "$DARWIN_STATUS" != PASSED ]]; then
  echo "One or more OS lanes failed" >&2
  exit 1
fi
