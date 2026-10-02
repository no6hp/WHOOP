#!/usr/bin/env bash
# Print the analysis digest for Claude. Usage: scripts/report.sh morning|evening|weekly
# Needs WHOOP_DATA_KEY in the environment. The output contains health data - never commit or post it.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
scripts/data-branch.sh checkout >/dev/null
python3 -m whoop digest --mode "${1:-morning}"
