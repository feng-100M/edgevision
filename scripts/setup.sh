#!/bin/sh
# Operates only in this project directory; OS dependencies are a separate step.
set -eu
PROJECT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)
cd "$PROJECT_DIR"
mkdir -p .cache/pip .tmp
export PIP_CACHE_DIR="$PROJECT_DIR/.cache/pip"
export TMPDIR="$PROJECT_DIR/.tmp"
export PIP_CONFIG_FILE=/dev/null
if [ ! -x .venv/bin/python ]; then
    python3 -m venv .venv
fi
if [ -d .wheelhouse ]; then
    .venv/bin/python -m pip install --no-index --find-links .wheelhouse setuptools==75.8.2 wheel==0.45.1 numpy==1.26.4 opencv-python-headless==4.11.0.86 onnxruntime==1.20.1 PyYAML==6.0.2 paho-mqtt==2.1.0 psutil==6.1.1 pytest==8.3.5
    .venv/bin/python -m pip install --no-index --no-build-isolation --no-deps -e .
else
    .venv/bin/python -m pip install -e '.[dev]'
fi
.venv/bin/python -m pip check
