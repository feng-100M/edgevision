#!/bin/sh
# Transient user service: no files are installed under /etc or ~/.config.
set -eu
PROJECT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)
cd "$PROJECT_DIR"
if [ "$(id -u)" -eq 0 ]; then
    echo "Run as the regular project user, not root." >&2
    exit 1
fi
test -f config.local.yaml
mkdir -p output benchmarks/results .tmp
exec systemd-run --user --unit=edgevision-reproduction --collect \
    --property=Restart=on-failure --property=RestartSec=3 \
    --property=MemoryMax=2G --property=TasksMax=96 \
    --property=NoNewPrivileges=yes \
    --setenv="TMPDIR=$PROJECT_DIR/.tmp" \
    --working-directory="$PROJECT_DIR" \
    "$PROJECT_DIR/.venv/bin/edgevision" run \
    --config "$PROJECT_DIR/config.local.yaml" --input uvc \
    --json-out benchmarks/results/service-last-run.json "$@"
