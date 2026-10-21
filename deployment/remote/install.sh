#!/usr/bin/env bash
# Usage: bash install.sh <deployment-directory> [python]
set -euo pipefail
service_dir=$(cd -- "$1" && pwd)
python=${2:-python3}
"$python" -m venv "$service_dir/.venv"
"$service_dir/.venv/bin/python" -m pip install 'mcp>=1.27,<2'
mkdir -p "$service_dir/runtime/incoming" "$service_dir/runtime/jobs"
printf 'Installed. Configure simulation.env, then start the supplied systemd unit.\n'
