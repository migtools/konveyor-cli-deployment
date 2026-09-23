#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TASKS="$ROOT/.tekton/tasks"

for f in "$TASKS"/*.yaml; do
  test -f "$f"
  grep -q 'apiVersion: tekton.dev/v1' "$f"
  grep -q 'kind: Task' "$f"
  grep -q 'metadata:' "$f"
  grep -q 'spec:' "$f"
done

# Expected result names used by the pipeline
grep -q 'name: verificationStatus' "$TASKS/verify-image-pullable.yaml"
grep -q 'name: imageDigest' "$TASKS/verify-image-pullable.yaml"
grep -q 'name: prepareStatus' "$TASKS/prepare-workspace.yaml"
grep -q 'name: testStatus' "$TASKS/run-os-e2e.yaml"
grep -q 'name: summary' "$TASKS/aggregate-results.yaml"

echo "OK"
