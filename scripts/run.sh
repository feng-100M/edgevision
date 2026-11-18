#!/bin/sh
set -eu

PROJECT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)
cd "$PROJECT_DIR"

for owned_dir in .tmp output benchmarks benchmarks/results; do
    if [ -L "$owned_dir" ] || { [ -e "$owned_dir" ] && [ ! -d "$owned_dir" ]; }; then
        echo "Refusing unsafe project path: $owned_dir" >&2
        exit 2
    fi
    mkdir -p -- "$owned_dir"
    resolved_dir=$(CDPATH= cd -- "$owned_dir" && pwd -P)
    case "$resolved_dir/" in
        "$PROJECT_DIR/"*) ;;
        *) echo "Refusing path outside project: $owned_dir" >&2; exit 2 ;;
    esac
done

if [ ! -x .venv/bin/python ] || [ ! -f config.local.yaml ] || [ ! -f models/yolox_nano.onnx ]; then
    echo "Project setup is incomplete; see README.md." >&2
    exit 2
fi

export TMPDIR="$PROJECT_DIR/.tmp"
GUI_RUNTIME_DIR=${XDG_RUNTIME_DIR:-/run/user/$(id -u)}
WAYLAND_SOCKET=${WAYLAND_DISPLAY:-wayland-0}
if [ ! -S "$GUI_RUNTIME_DIR/$WAYLAND_SOCKET" ]; then
    echo "No local Wayland display found at $GUI_RUNTIME_DIR/$WAYLAND_SOCKET." >&2
    echo "Log in to the Raspberry Pi desktop session before using this launcher." >&2
    exit 2
fi
CHROMIUM_BIN=$(command -v chromium || command -v chromium-browser || true)
if [ -z "$CHROMIUM_BIN" ]; then
    echo "Chromium is not installed on the Raspberry Pi desktop." >&2
    exit 2
fi

printf 'Starting EdgeVision on the Raspberry Pi screen. Press Ctrl+C to stop.\n'
printf 'The local browser will open http://127.0.0.1:8765 on the Pi.\n'

CHROMIUM_PROFILE="$PROJECT_DIR/.tmp/chromium"

cleanup() {
    status=$?
    trap - INT TERM EXIT
    if [ -n "${BROWSER_PID-}" ] && kill -0 "$BROWSER_PID" 2>/dev/null; then
        kill "$BROWSER_PID" 2>/dev/null || true
        wait "$BROWSER_PID" 2>/dev/null || true
    fi
    # Chromium is multi-process; terminate only processes carrying this
    # launcher's private profile. A second pass handles renderer processes
    # that survive after the browser parent exits.
    stop_browser_profile() {
        signal=$1
        ps -u "$(id -u)" -o pid=,args= 2>/dev/null | while read -r pid args; do
            case "$args" in
                *"$CHROMIUM_PROFILE"*)
                    if [ "$pid" != "$$" ]; then kill "-$signal" "$pid" 2>/dev/null || true; fi
                    ;;
            esac
        done
    }
    stop_browser_profile TERM
    sleep .2
    stop_browser_profile KILL
    if [ -n "${EDGEVISION_PID-}" ] && kill -0 "$EDGEVISION_PID" 2>/dev/null; then
        kill "$EDGEVISION_PID" 2>/dev/null || true
        wait "$EDGEVISION_PID" 2>/dev/null || true
    fi
    exit "$status"
}
trap cleanup INT TERM EXIT

.venv/bin/python -m edgevision.cli run \
    --config config.local.yaml --input uvc --preview "$@" \
    >"$PROJECT_DIR/.tmp/edgevision-run.log" 2>&1 &
EDGEVISION_PID=$!

waited=0
while ! .venv/bin/python -c 'import urllib.request; urllib.request.urlopen("http://127.0.0.1:8765/", timeout=.2).close()' >/dev/null 2>&1; do
    sleep .1
    waited=$((waited + 1))
    if [ "$waited" -ge 100 ]; then
        echo "EdgeVision preview did not start within 10 seconds." >&2
        exit 2
    fi
done

env XDG_RUNTIME_DIR="$GUI_RUNTIME_DIR" WAYLAND_DISPLAY="$WAYLAND_SOCKET" \
    DBUS_SESSION_BUS_ADDRESS="unix:path=$GUI_RUNTIME_DIR/bus" TMPDIR="$PROJECT_DIR/.tmp" \
    "$CHROMIUM_BIN" --ozone-platform=wayland --app=http://127.0.0.1:8765 \
    --user-data-dir="$CHROMIUM_PROFILE" --no-first-run \
    --no-default-browser-check --disable-session-crashed-bubble \
    >"$PROJECT_DIR/.tmp/chromium.log" 2>&1 &
BROWSER_PID=$!
wait "$EDGEVISION_PID"
