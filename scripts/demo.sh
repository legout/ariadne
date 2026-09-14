#!/usr/bin/env bash
# End-to-end demo (ticket #6): seed -> author -> promote -> serve + scripted MCP calls.
# Idempotent: every step rebuilds its artifacts from scratch. Exit 0 = green.
#
#   scripts/demo.sh          # interactive: pauses at the human promotion gate
#   scripts/demo.sh --yes    # auto-promote (CI)
set -euo pipefail
cd "$(dirname "$0")/.."

yes=0
for arg in "$@"; do
  case "$arg" in
    --yes) yes=1 ;;
    *) echo "usage: scripts/demo.sh [--yes]" >&2; exit 2 ;;
  esac
done

PY=.venv/bin/python
if [ ! -x "$PY" ]; then
  echo "== setup: creating .venv (Python 3.12) and installing dependencies"
  uv venv --python 3.12 .venv
  uv pip install --python "$PY" -e .
fi

# The author calls the live LLM endpoint; credentials live outside the repo
# (author.py loads ARIADNE_ENV, default the main checkout's .env). No file, no demo.
ENV_FILE="${ARIADNE_ENV:-/home/volker/coding/ariadne/.env}"
if [ ! -f "$ENV_FILE" ]; then
  echo "error: live LLM credentials not found at $ENV_FILE" >&2
  echo "  the demo runs the real authoring agent; create that file with" >&2
  echo "  OPENAI_API_KEY / OPENAI_BASE_URL / OPENAI_MODEL (or point ARIADNE_ENV at it)" >&2
  exit 1
fi

echo "== 1/4 seed: data/demo.db (deterministic)"
"$PY" scripts/seed_db.py data/demo.db

echo "== 2/4 author: profile + seed notes -> live LLM drafts -> staging/"
rm -rf staging
"$PY" -m ariadne.author --db data/demo.db --notes data/seed_notes.md

echo "== 3/4 promotion gate (spec §6: served artifacts arrive only by human promotion)"
echo "   staged files:"
find staging -type f | sort | sed 's/^/     /'
promote() {
  rm -rf context_layer semantic_layer
  cp -r staging/context_layer context_layer
  cp -r staging/semantic_layer semantic_layer
}
if [ "$yes" = 1 ]; then
  echo "   --yes: promoting automatically"
  promote
elif [ -t 0 ]; then
  echo "   review staging/, then promote with:"
  echo "     rm -rf context_layer semantic_layer"
  echo "     cp -r staging/context_layer context_layer"
  echo "     cp -r staging/semantic_layer semantic_layer"
  printf '   promote now? [y/N] '
  read -r answer
  case "$answer" in
    y | Y) promote ;;
    *) echo "aborted: nothing served (re-run and answer y, or use --yes)" >&2; exit 1 ;;
  esac
else
  echo "error: non-interactive run needs --yes to pass the promotion gate" >&2
  exit 1
fi

echo "== 4/4 serve + scripted MCP client (spawns python -m ariadne.serve over stdio)"
"$PY" scripts/mcp_client.py --db data/demo.db

echo
echo "demo OK — served layers: context_layer/ semantic_layer/ (promoted from staging/)"
