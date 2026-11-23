#!/bin/bash
# Installed in the isolated controller's bin directory.
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd -P)
. "$root/environment.sh"
case "${1:-}" in
  --dump-config)
    cd "$root/runs/config-probe"
    exec "$root/bin/node" "$root/source/apps/cli/lib/bin.js" --profile headless --dump-config
    ;;
  --offline-test)
    shift
    exec "$npm_config_python" "$root/accept_linux_controller.py" "$@"
    ;;
  --cli)
    shift
    exec "$root/bin/node" "$root/source/apps/cli/lib/bin.js" "$@"
    ;;
  *)
    echo 'Use --dump-config or --offline-test offline-acceptance-NN for maintenance checks.' >&2
    echo 'Use --cli from a task directory for normal DSH commands with the selected model, protocol and budget configuration.' >&2
    exit 78
    ;;
esac
