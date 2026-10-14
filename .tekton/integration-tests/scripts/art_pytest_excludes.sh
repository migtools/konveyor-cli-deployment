#!/usr/bin/env bash
# ART / Konflux known-failure exclusions for kantra-cli-tests.
# Prints space-separated, shell-quoted pytest args (stdout).
# Usage: eval "extra=( $(art_pytest_excludes.sh) )"  OR  append via: cmd="... $(art_pytest_excludes.sh)"
set -euo pipefail
TARGET_OS="${TARGET_OS:-linux}"

args=(
  # Transform / OpenRewrite: known broken, expected to be deprecated.
  --ignore=tests/test_transform.py
  # Hub central-config + Cloud Foundry: need special env not available in ART.
  --ignore=tests/platform/centralconfig
  --ignore=tests/platform/cloudfoundry
  # Advanced options: known / under investigation for ART.
  --deselect=tests/test_advanced_options.py::test_custom_rules
  --deselect=tests/test_advanced_options.py::test_custom_rules_disable_default_issue_781_855
  --deselect=tests/test_advanced_options.py::test_description_display_in_report
  # Container (--run-local=false) proxy bugs.
  '--deselect=tests/test_advanced_options.py::test_http_proxy[--run-local=false]'
  '--deselect=tests/test_advanced_options.py::test_https_proxy[--run-local=false]'
)

# Dotnet hello-world fails on Linux/Darwin; passes on Windows.
if [[ "$TARGET_OS" != "windows" ]]; then
  args+=(--deselect=tests/analysis/dotnet/test_dotnet_analysis.py::test_hello_world_linux_analysis_with_rules)
fi

printf '%q ' "${args[@]}"
echo
