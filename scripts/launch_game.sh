#!/usr/bin/env bash
# Liar's Duck: the duck deals and judges a bluffing card game; players use their phones.
#   ./scripts/launch_game.sh            # phones: the URL/QR it prints; big screen: http://127.0.0.1:8400/host
# Run it alongside ./scripts/launch_duck.sh --brain (the brain pauses itself during a game).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/brain"
export PATH="$HOME/.local/bin:$PATH"
STT_EXTRA=stt
command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi -L >/dev/null 2>&1 && STT_EXTRA=stt-gpu
(sleep 3; xdg-open "http://127.0.0.1:${PORT:-8400}/host" >/dev/null 2>&1 || true) &
exec uv run -q --extra "$STT_EXTRA" duck-game --port "${PORT:-8400}" "$@"
