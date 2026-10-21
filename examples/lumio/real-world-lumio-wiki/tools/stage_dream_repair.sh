#!/usr/bin/env bash
# Apply up to N Dream Cycle repairs as Git worktree edits.
#
# This is the script the coding agent can run after `run_maintenance.sh` to
# convert the dream's ranked candidates into authored Markdown-link repairs
# in the Git authoring worktree. The agent is expected to review the diff
# with Git, commit what is good, and publish the exact revision.
set -euo pipefail

EXAMPLE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="$EXAMPLE_DIR/.venv"
LUMIO="$VENV/bin/lumio-wiki"
KB="${LUMIO_KB_PATH:-$EXAMPLE_DIR/knowledge-base}"
LIMIT="${DREAM_LIMIT:-3}"

if [[ ! -x "$LUMIO" ]]; then
	echo "error: $LUMIO not found; run ./bootstrap.sh first" >&2
	exit 1
fi

if [[ ! -d "$KB" ]]; then
	echo "error: Knowledge Base not found at $KB; run 'lumio-wiki setup $KB' first" >&2
	exit 1
fi

export LUMIO_KB_PATH="$KB"

printf '\n=== dream --stage --limit %s ===\n' "$LIMIT"
printf '$ %s dream --stage --limit %s %s\n' "$LUMIO" "$LIMIT" "$KB"
"$LUMIO" dream --stage --limit "$LIMIT" "$KB"

printf '\n=== git status (review the repairs) ===\n'
printf '$ git -C %s status --short\n' "$KB"
git -C "$KB" status --short

printf '\nReview the diff with Git; commit what is good and publish the exact\n'
printf 'revision: %s publish %s --revision <full-commit-id> --to <destination> --expected-current <version-or-none>\n' "$LUMIO" "$KB"
printf 'Preview first; add --confirm <review-digest> only after explicit operator authorization.\n'
