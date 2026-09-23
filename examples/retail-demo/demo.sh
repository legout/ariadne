#!/usr/bin/env bash
# End-to-end demo (ticket #6): seed -> author -> promote -> query locally.
# Idempotent: every step rebuilds its demo artifacts from scratch. Exit 0 = green.
# MCP client remains an optional example, never a success requirement.
#
#   examples/retail-demo/demo.sh          # interactive: pauses at the human promotion gate
#   examples/retail-demo/demo.sh --yes    # auto-promote (CI)
set -euo pipefail
cd "$(dirname "$0")/../.."

yes=0
for arg in "$@"; do
  case "$arg" in
    --yes) yes=1 ;;
    *) echo "usage: examples/retail-demo/demo.sh [--yes]" >&2; exit 2 ;;
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

echo "== 1/4 seed: data/demo.db + the support-tickets parquet fixture (deterministic)"
"$PY" examples/retail-demo/seed_db.py examples/retail-demo/data/demo.db
"$PY" examples/retail-demo/make_parquet_fixture.py examples/retail-demo/data/support_tickets

echo "== 2/4 author: profile + seed notes -> live LLM drafts -> demo staging/"
rm -rf examples/retail-demo/staging
author_rc=0
"$PY" -m ariadne.author --sources examples/retail-demo/ariadne.yaml --notes examples/retail-demo/seed_notes.md --staging examples/retail-demo/staging || author_rc=$?
# Spec §6/§7: review_needed artifacts must never be auto-promoted — the human gate
# holds even under --yes (and even if an older author exited 0 despite review_needed).
if grep -rq 'status: review_needed' examples/retail-demo/staging 2>/dev/null; then
  echo "   staged files carry status: review_needed"
  author_rc=1
fi
if [ "$author_rc" -ne 0 ]; then
  echo "error: authoring ended in review_needed — the human promotion gate applies (spec §6/§7)" >&2
  echo "  review examples/retail-demo/staging/ yourself; --yes does not promote review_needed artifacts" >&2
  exit 1
fi

echo "== 3/4 promotion gate (spec §6: served artifacts arrive only by human promotion)"
echo "   staged files:"
find examples/retail-demo/staging -type f | sort | sed 's/^/     /'
promote() {
  "$PY" ariadne-promote --yes --staging examples/retail-demo/staging --served examples/retail-demo
}
if [ "$yes" = 1 ]; then
  echo "   --yes: promoting automatically"
  promote
elif [ -t 0 ]; then
  echo "   review examples/retail-demo/staging/, then promote with:"
  echo "     python ariadne-promote --staging examples/retail-demo/staging --served examples/retail-demo"
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

echo "== 4/4 query: the local ariadne CLI — governed metric, no server started"
ARIADNE=.venv/bin/ariadne
"$ARIADNE" list-metrics --served examples/retail-demo --sources examples/retail-demo/ariadne.yaml
"$ARIADNE" get-metric gross_margin --dimension region --served examples/retail-demo --sources examples/retail-demo/ariadne.yaml
echo "   governed metric answered locally: gross_margin (governed: true, caveats attached)"

echo "== optional: the MCP example (needs the mcp extra — never a success requirement)"
echo "   uv pip install --python .venv/bin/python -e '.[mcp]'"
echo "   optional client example: examples/retail-demo/mcp_client.py"

# The seed notes define support metrics, so the bundle should carry a model over
# support.tickets. The LLM is not fully deterministic: warn, never fail, here —
# the human promotion gate already reviewed whatever was served.
if grep -rq 'support.tickets' examples/retail-demo/semantic_layer/models 2>/dev/null; then
  echo "   multi-source breadth: served bundle models support.tickets"
else
  echo "   WARNING: no model over support.tickets in the served bundle — the author"
  echo "   ignored the support source; re-run or author it manually"
fi

echo
echo "demo OK — served layers: examples/retail-demo/context_layer/ and examples/retail-demo/semantic_layer/ (promoted from examples/retail-demo/staging/)"
