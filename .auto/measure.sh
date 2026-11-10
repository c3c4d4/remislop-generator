#!/usr/bin/env bash
# Benchmark: renders the templates with fixtures, screenshots them, scores
# Adwaita fidelity. Emits `METRIC name=value` lines (+ one DETAIL line).
set -euo pipefail
cd "$(dirname "$0")/.."

# Fast pre-check: templates must render (jinja) — measure.py does that, but a
# clear early failure is cheaper than a chromium error.
python3 - <<'PY'
import sys
sys.path.insert(0, ".auto")
import render
render.render_all()
PY

exec python3 .auto/measure.py "$@"
