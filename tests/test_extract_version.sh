#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SCRIPT="$ROOT/.tekton/integration-tests/scripts/extract_version_from_image.sh"
IMG='quay.io/redhat-user-workloads/ocp-art-tenant/art-fbc:v4.21__operator_nvr__mta-operator-container-8.1.3-202607312122.p2.gf5b3f83.assembly.stream.el9'
got="$("$SCRIPT" "$IMG")"
[[ "$got" == "8.1.3" ]] || { echo "expected 8.1.3 got $got"; exit 1; }
echo "OK"
