# Example: external-agent journey (synthetic, reproducible)

A self-contained walkthrough of the
[private source-handoff guide](../../docs/howto-source-handoff.md) using
synthetic content only. A maintainer starts from a nonempty Knowledge Base; a
**contributor coding agent in BB + Pi** (the selected initial qualification
target — no real harness run is claimed here) receives one real attached
document, authors two related pages plus one ontology addition, gets a human
review, submits through native Git, and the maintainer imports the private
source and admits the publication. No script ships with this example on
purpose: the harness steps (attachment, readable review, human confirmation)
are manual by design — that is what this example exercises.

Everything below is hand-authored and deterministic: run the blocks of each
role in order, in one shell per role (a terminal on the maintainer machine and
one on the contributor machine; here both may live on one workstation with
separate directories). All private working files — originals, authored pages,
profiles, registries, artifact stores, transfer archives — live at ABSOLUTE
paths OUTSIDE every Git worktree; the two roles never share a registry, store,
or credentials.

## Synthetic identities

| Identity | Value |
|---|---|
| Knowledge Base Namespace | `urn:uuid:9c1f5b2e-0010-4a10-9a10-5f3e8d2c7b31` |
| Baseline source (maintainer-only original) | `aurora-product-notes` |
| Contribution source (the attachment) | `oncall-runbook-2026` |
| Baseline page | `Aurora Helpdesk` → `entities/aurora_helpdesk.md` |
| Contribution page 1 | `On-call Escalation Runbook` → `procedures/on-call_escalation_runbook.md` |
| Contribution page 2 | `Support Ops on-call Rotation` → `concepts/support_ops_on-call_rotation.md` |
| Ontology additions | Entity Type `team`; predicates `escalates-to`/`escalated-by` |
| Source facts kept in the pages | acknowledgement within **5 minutes**; escalation after **10 minutes** |

Title routing preserves hyphens and replaces spaces with underscores — the
expected paths above are what the CLI routes and what the final citation uses.

## 0. Shared scaffold

<!-- j6:shared-env -->
```bash
export JOURNEY="$HOME/lumio-journey-example"          # scratch root; delete to reset
export MAINT_WS="$JOURNEY/maintainer"                 # maintainer workspace (Git repo lives here)
export MAINT_PRIVATE="$JOURNEY/maintainer-private"    # maintainer registry/store/profiles/originals
export CONTRIB_WS="$JOURNEY/contributor"              # contributor workspace (fresh clone lands here)
export CONTRIB_PRIVATE="$JOURNEY/contributor-private" # contributor registry/store/profiles/inbound
# The Git remote the contributor clones. Default: a disposable local bare repo this
# walkthrough creates (no network). Point KB_REMOTE at your approved hosted remote for
# a real two-machine run; the commands are identical.
export KB_REMOTE="${KB_REMOTE:-$JOURNEY/remote/kb.git}"
mkdir -p "$MAINT_WS" "$MAINT_PRIVATE"/{registry,artifacts,originals,authored,outbound,inbound} \
         "$CONTRIB_WS" "$CONTRIB_PRIVATE"/{registry,artifacts,inbound,authored,outbound,extract}
```

## 1. Maintainer: baseline Knowledge Base

### 1.1 Control File, manifest, native Git preparation

<!-- j6:maint-git-init -->
```bash
mkdir -p "$MAINT_WS/kb"
cat > "$MAINT_WS/kb/lumio.yaml" <<'YAML'
version: 2
mode: "categorized"
categories:
  - name: concepts
    description: "Core ideas, definitions, and mental models."
  - name: entities
    description: "Named people, organizations, products, and tools."
  - name: procedures
    description: "Runbooks, methods, and checklists."
ontology:
  entity_types:
    software-system:
      description: "A deployed software product or platform."
    procedure:
      description: "A reviewed runbook or operating procedure."
  predicates: {}
  redirects: {}
YAML
cat > "$MAINT_WS/kb/.lumio-authoring.yaml" <<'YAML'
version: 1
namespace: "urn:uuid:9c1f5b2e-0010-4a10-9a10-5f3e8d2c7b31"
sources: {}
bindings: {}
YAML
# Native Git prepares the authoring repository; setup never initializes Git.
git init -b main "$MAINT_WS/kb"
git -C "$MAINT_WS/kb" config user.name "Aurora Maintainer"
git -C "$MAINT_WS/kb" config user.email "maintainer@lumio-journey.example"
git -C "$MAINT_WS/kb" add lumio.yaml .lumio-authoring.yaml
git -C "$MAINT_WS/kb" commit -m "Adopt the Aurora baseline control files"
# Operator provisioning of this local fixture's clone source (not a contributor
# submission): a disposable bare remote advertising the baseline branch.
git init --bare -b main "$KB_REMOTE"
git -C "$MAINT_WS/kb" remote add origin "$KB_REMOTE"
```

### 1.2 Private profile and baseline inputs (outside Git)

<!-- j6:maint-private-files -->
```bash
cat > "$MAINT_PRIVATE/profile.json" <<'JSON'
{
  "schema_version": 1,
  "namespace": "urn:uuid:9c1f5b2e-0010-4a10-9a10-5f3e8d2c7b31",
  "source_registry": "REGISTRY_PLACEHOLDER",
  "retention": "required",
  "artifact_store": { "kind": "local", "root": "ARTIFACTS_PLACEHOLDER" }
}
JSON
python3 - "$MAINT_PRIVATE/profile.json" "$MAINT_PRIVATE" <<'PY'
import json, sys
from pathlib import Path
profile_path, private_root = Path(sys.argv[1]), Path(sys.argv[2])
profile = json.loads(profile_path.read_text(encoding="utf-8"))
profile["source_registry"] = str((private_root / "registry").resolve())
profile["artifact_store"]["root"] = str((private_root / "artifacts").resolve())
profile_path.write_text(json.dumps(profile, indent=2) + "\n", encoding="utf-8")
PY
lumio-wiki private-profile inspect "$MAINT_PRIVATE/profile.json" --kb "$MAINT_WS/kb" --json
```

The one-off `python3` substitution writes your actual ABSOLUTE registry/store
paths into the profile — profile paths must be absolute and are validated
against repo containment, so never leave the placeholders in.

<!-- j6:maint-baseline-inputs -->
```bash
cat > "$MAINT_PRIVATE/originals/aurora-product-notes.md" <<'EOF'
# Aurora product notes (internal)

Owner: Support Ops. Last reviewed: 2026-10-01.

Aurora is the support helpdesk this Knowledge Base documents. Aurora
operating procedures live in this Knowledge Base under procedures/.
EOF
cat > "$MAINT_PRIVATE/authored/aurora-helpdesk.md" <<'EOF'
---
title: "Aurora Helpdesk"
id: "entity:aurora-helpdesk"
entity_types: ["software-system"]
tags: ["support", "product"]
summary: "The Aurora helpdesk product this Knowledge Base documents."
category: entities
type: definition
durability_rationale: "Stable product definition maintained by Support Ops."
lifecycle: "approved"
visibility: "internal"
sources:
  - id: "aurora-product-notes"
    title: "Aurora product notes"
claims: []
---

# Aurora Helpdesk

Aurora is the support helpdesk this Knowledge Base documents. Its operating
procedures live in this Knowledge Base under procedures/.
EOF
```

### 1.3 Managed baseline ingestion and baseline commit

<!-- j6:maint-baseline -->
```bash
lumio-wiki ingest "$MAINT_WS/kb" "$MAINT_PRIVATE/originals/aurora-product-notes.md" \
  --compiled-page "$MAINT_PRIVATE/authored/aurora-helpdesk.md" \
  --source-id aurora-product-notes \
  --private-profile "$MAINT_PRIVATE/profile.json"
lumio-wiki validate "$MAINT_WS/kb"
git -C "$MAINT_WS/kb" add -A
git -C "$MAINT_WS/kb" commit -m "Add the Aurora baseline page"
BASE=$(git -C "$MAINT_WS/kb" rev-parse HEAD)
git -C "$MAINT_WS/kb" push -u origin main
echo "baseline revision: $BASE"
```

### 1.4 Baseline snapshot for the fresh contributor

<!-- j6:maint-snapshot -->
```bash
lumio-wiki source-bootstrap export "$MAINT_WS/kb" --revision "$BASE" \
  --output "$MAINT_PRIVATE/outbound/baseline.tar" \
  --private-profile "$MAINT_PRIVATE/profile.json" --json \
  > "$MAINT_PRIVATE/outbound/baseline-export.json"
BASELINE_SHA256=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["snapshot_sha256"])' \
  "$MAINT_PRIVATE/outbound/baseline-export.json")
echo "send the contributor, over your private channel: baseline.tar and $BASELINE_SHA256"
```

The snapshot carries exact baseline Source Version METADATA only — the
contributor never receives `aurora-product-notes.md`.

## 2. Contributor: fresh clone, bootstrap, connection check

<!-- j6:contrib-workspace -->
```bash
export JOURNEY="$HOME/lumio-journey-example"
export MAINT_WS="$JOURNEY/maintainer"
export MAINT_PRIVATE="$JOURNEY/maintainer-private"
export CONTRIB_WS="$JOURNEY/contributor"
export CONTRIB_PRIVATE="$JOURNEY/contributor-private"
export KB_REMOTE="${KB_REMOTE:-$JOURNEY/remote/kb.git}"
# Operator-selected submission settings recorded by journey setup (non-secret):
export LUMIO_SUBMISSION_MODE=commit
export LUMIO_GIT_REMOTE=origin
export LUMIO_GIT_TARGET_BRANCH=main
cat > "$CONTRIB_PRIVATE/profile.json" <<'JSON'
{
  "schema_version": 1,
  "namespace": "urn:uuid:9c1f5b2e-0010-4a10-9a10-5f3e8d2c7b31",
  "source_registry": "REGISTRY_PLACEHOLDER",
  "retention": "required",
  "artifact_store": { "kind": "local", "root": "ARTIFACTS_PLACEHOLDER" }
}
JSON
python3 - "$CONTRIB_PRIVATE/profile.json" "$CONTRIB_PRIVATE" <<'PY'
import json, sys
from pathlib import Path
profile_path, private_root = Path(sys.argv[1]), Path(sys.argv[2])
profile = json.loads(profile_path.read_text(encoding="utf-8"))
profile["source_registry"] = str((private_root / "registry").resolve())
profile["artifact_store"]["root"] = str((private_root / "artifacts").resolve())
profile_path.write_text(json.dumps(profile, indent=2) + "\n", encoding="utf-8")
PY
```

(The profile file itself is validated against a Knowledge Base below, after
the clone exists; `private-profile inspect` without `--kb` needs
`LUMIO_KB_PATH` or a project `.env`, which a fresh contributor terminal
does not have yet.)

<!-- j6:contrib-bootstrap -->
```bash
git clone "$KB_REMOTE" "$CONTRIB_WS/kb-repo"
git -C "$CONTRIB_WS/kb-repo" config user.name "Aurora Contributor"
git -C "$CONTRIB_WS/kb-repo" config user.email "contributor@lumio-journey.example"
lumio-wiki private-profile inspect "$CONTRIB_PRIVATE/profile.json" \
  --kb "$CONTRIB_WS/kb-repo" --json
export BASE=$(git -C "$CONTRIB_WS/kb-repo" rev-parse HEAD)
lumio-wiki git-check "$CONTRIB_WS/kb-repo" --remote origin --json   # read access only
(cd "$CONTRIB_WS" && lumio-wiki setup "$CONTRIB_WS/kb-repo" \
  --journey --private-profile "$CONTRIB_PRIVATE/profile.json")
# The maintainer's snapshot arrives over your private channel (here: a local copy),
# together with its out-of-band digest:
cp "$MAINT_PRIVATE/outbound/baseline.tar" "$CONTRIB_PRIVATE/inbound/baseline.tar"
cp "$MAINT_PRIVATE/outbound/baseline-export.json" "$CONTRIB_PRIVATE/inbound/"
BASELINE_SHA256=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["snapshot_sha256"])' \
  "$CONTRIB_PRIVATE/inbound/baseline-export.json")
lumio-wiki source-bootstrap inspect "$CONTRIB_WS/kb-repo" --snapshot "$CONTRIB_PRIVATE/inbound/baseline.tar" \
  --digest "$BASELINE_SHA256" --revision "$BASE" \
  --private-profile "$CONTRIB_PRIVATE/profile.json" --json \
  > "$CONTRIB_PRIVATE/inbound/baseline-preview.json"
BASELINE_CONFIRM=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["confirmation_digest"])' \
  "$CONTRIB_PRIVATE/inbound/baseline-preview.json")
lumio-wiki source-bootstrap import "$CONTRIB_WS/kb-repo" --snapshot "$CONTRIB_PRIVATE/inbound/baseline.tar" \
  --digest "$BASELINE_SHA256" --revision "$BASE" \
  --private-profile "$CONTRIB_PRIVATE/profile.json" --confirm "$BASELINE_CONFIRM" --json
```

<!-- j6:contrib-inspect-original -->
```bash
# Truthful unavailability: the baseline version resolves, its bytes do not exist here.
lumio-wiki source inspect "$CONTRIB_WS/kb-repo" --source-id aurora-product-notes \
  --source-registry "$CONTRIB_PRIVATE/registry"
lumio-wiki source fetch "$CONTRIB_WS/kb-repo" --source-id aurora-product-notes \
  --source-registry "$CONTRIB_PRIVATE/registry" \
  --output "$CONTRIB_PRIVATE/inbound/should-not-exist.md" || echo "fetch refused: no retained original"
```

## 3. The attachment (the only new input the contributor receives)

In a BB session with the lumio-wiki skill installed, the contributor agent
receives `oncall-runbook.md` as a real attachment and saves it (here:
`$CONTRIB_PRIVATE/inbound/oncall-runbook.md`). The agent must read these real
bytes — never guess from the filename:

<!-- j6:contrib-attachment -->
```bash
cat > "$CONTRIB_PRIVATE/inbound/oncall-runbook.md" <<'EOF'
# Support runbook: on-call escalation (internal)

Last reviewed: 2026-10-20. Owner: Support Ops.

1. Any Sev-1 incident pages Aurora Helpdesk automatically.
2. The on-call engineer acknowledges within 5 minutes.
3. If unacknowledged after 10 minutes, the page escalates to the
   Support Ops on-call rotation lead.
4. Sev-2 incidents follow the same rotation during business hours only.
EOF
lumio-wiki extract "$CONTRIB_PRIVATE/inbound/oncall-runbook.md" \
  --output "$CONTRIB_PRIVATE/extract" --json
```

## 4. Expected authored output (deterministic, hand-authored)

Two pages from one original plus the ontology addition. These are the
EXPECTED results an agent must produce from the attachment (assert review
against them); `~/...` never appears inside the machine-read request JSON
below — request paths are absolute, and any relative string would resolve
from the process working directory, not from the request file's location.

<!-- j6:contrib-author -->
```bash
cat > "$CONTRIB_PRIVATE/authored/lumio.yaml" <<'YAML'
version: 2
mode: "categorized"
categories:
  - name: concepts
    description: "Core ideas, definitions, and mental models."
  - name: entities
    description: "Named people, organizations, products, and tools."
  - name: procedures
    description: "Runbooks, methods, and checklists."
ontology:
  entity_types:
    software-system:
      description: "A deployed software product or platform."
    procedure:
      description: "A reviewed runbook or operating procedure."
    team:
      description: "A named group owning procedures and escalation."
  predicates:
    escalates-to:
      subject_types: [procedure]
      object_types: [team]
      inverse: escalated-by
    escalated-by:
      subject_types: [team]
      object_types: [procedure]
      inverse: escalates-to
  redirects: {}
YAML
cat > "$CONTRIB_PRIVATE/authored/oncall-escalation-runbook.md" <<'EOF'
---
title: "On-call Escalation Runbook"
category: procedures
type: runbook
durability_rationale: "Owned runbook; reviewed yearly by Support Ops."
id: "entity:oncall-escalation-runbook"
entity_types: ["procedure"]
tags: ["support", "runbook", "escalation"]
summary: "How Aurora on-call pages are acknowledged and escalated."
lifecycle: "approved"
visibility: "internal"
sources:
  - id: "oncall-runbook-2026"
    title: "Support runbook: on-call escalation"
claims:
  - id: "claim:runbook-escalates-to-rotation"
    predicate: "escalates-to"
    object: "entity:support-ops-rotation"
    status: "accepted"
    evidence:
      - lines: [6, 8]
---

# On-call Escalation Runbook

Aurora Helpdesk automatically pages the on-call engineer for any Sev-1
incident; the engineer acknowledges within 5 minutes. An unacknowledged
page escalates to the [Support Ops on-call rotation](../concepts/support_ops_on-call_rotation.md)
lead after 10 minutes. Sev-2 incidents use the same rotation during
business hours only.
EOF
cat > "$CONTRIB_PRIVATE/authored/support-ops-rotation.md" <<'EOF'
---
title: "Support Ops on-call Rotation"
category: concepts
type: definition
durability_rationale: "Stable team definition maintained by Support Ops."
id: "entity:support-ops-rotation"
entity_types: ["team"]
tags: ["support", "on-call"]
summary: "The Support Ops rotation that owns Aurora escalation."
lifecycle: "approved"
visibility: "internal"
sources:
  - id: "oncall-runbook-2026"
    title: "Support runbook: on-call escalation"
claims: []
---

# Support Ops on-call Rotation

The Support Ops on-call rotation owns Aurora Helpdesk escalation. Its lead
receives pages that the on-call engineer has not acknowledged within the
runbook's 10-minute window.
EOF
```

The Claim's `evidence.lines` are 1-based BODY coordinates of the runbook page
itself (the closing `---` delimiter line counts as body line 1): lines 6–8
cover the 5-minute acknowledgement and the 10-minute escalation. The body
link targets the actual routed rotation path
`concepts/support_ops_on-call_rotation.md`, relative from
`procedures/`.

<!-- j6:contrib-request -->
```bash
export ORIG_SHA256=$(sha256sum "$CONTRIB_PRIVATE/inbound/oncall-runbook.md" | cut -d' ' -f1)
python3 - <<'PY'
import json, os
from pathlib import Path
private = Path(os.environ["CONTRIB_PRIVATE"]).resolve()
base = os.environ["BASE"]
request = {
    "schema_version": 1,
    "base_revision": base,
    "sources": [
        {
            "source_id": "oncall-runbook-2026",
            "original_path": str(private / "inbound" / "oncall-runbook.md"),
            "expected_digest": os.environ["ORIG_SHA256"],
            "intent": "new",
        }
    ],
    "pages": [
        str(private / "authored" / "oncall-escalation-runbook.md"),
        str(private / "authored" / "support-ops-rotation.md"),
    ],
    "control": str(private / "authored" / "lumio.yaml"),
}
(private / "candidate.json").write_text(json.dumps(request, indent=2) + "\n", encoding="utf-8")
print((private / "candidate.json").read_text(encoding="utf-8"))
PY
```

Generating the request with the standard library keeps every path an
already-expanded absolute string — no `~/` shorthand and no quoting traps.

## 5. Candidate, review, ONE informed human decision, commit

<!-- j6:contrib-candidate -->
```bash
lumio-wiki ingest-candidate "$CONTRIB_WS/kb-repo" --candidate "$CONTRIB_PRIVATE/candidate.json" \
  --private-profile "$CONTRIB_PRIVATE/profile.json" --json
# Prepare the native contribution branch from the exact baseline; never submit main.
git -C "$CONTRIB_WS/kb-repo" checkout -b oncall-runbook
git -C "$CONTRIB_WS/kb-repo" add -A
lumio-wiki authoring-review "$CONTRIB_WS/kb-repo" --base "$BASE" \
  --private-profile "$CONTRIB_PRIVATE/profile.json" --json \
  > "$CONTRIB_PRIVATE/review.json"
```

**[HUMAN — one decision]** Before any submission step, the agent presents,
together: the displayed candidate (both new page bodies, the new
`team`/`escalates-to` ontology entries, the accepted Claim, validation
outcome) and the SELECTED submission action. The mode is exactly the
configured setting — `commit` (the default here: submission ends at the
verified local commit; the configured `origin`/`main` NEVER authorizes a
push in commit mode) or `github-pr` (selected explicitly BEFORE this
decision, requiring the actual configured repository/remote/head/base).
One explicit human decision covers exactly this candidate and this selected
action set, including the private transfer that follows (a Source Handoff
Bundle through the private channel); a changed candidate, or a different
mode/action, needs a fresh decision.

<!-- j6:contrib-commit -->
```bash
git -C "$CONTRIB_WS/kb-repo" commit -m "Add on-call escalation runbook and Support Ops rotation"
REV=$(git -C "$CONTRIB_WS/kb-repo" rev-parse HEAD)
lumio-wiki authoring-check "$CONTRIB_WS/kb-repo" --review "$CONTRIB_PRIVATE/review.json" \
  --revision "$REV" --json
# commit mode ENDS the submission here — no push happens even though origin exists.
```

## 6. Contributor: private handoff

<!-- j6:contrib-handoff -->
```bash
lumio-wiki source-handoff export "$CONTRIB_WS/kb-repo" --base "$BASE" --revision "$REV" \
  --output "$CONTRIB_PRIVATE/outbound/handoff.tar" \
  --private-profile "$CONTRIB_PRIVATE/profile.json" --json \
  > "$CONTRIB_PRIVATE/outbound/handoff-export.json"
HANDOFF_SHA256=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["bundle_sha256"])' \
  "$CONTRIB_PRIVATE/outbound/handoff-export.json")
HANDOFF_ID=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["transfer_id"])' \
  "$CONTRIB_PRIVATE/outbound/handoff-export.json")
echo "send the maintainer, over your private channel: handoff.tar ($HANDOFF_ID / $HANDOFF_SHA256)"
# Manual private transfer (no S3 dependency). For the S3 exchange variant, see
# docs/howto-source-handoff.md §1 and §6: same archive, upload/download instead of cp.
cp "$CONTRIB_PRIVATE/outbound/handoff.tar" "$MAINT_PRIVATE/inbound/handoff.tar"
cp "$CONTRIB_PRIVATE/outbound/handoff-export.json" "$MAINT_PRIVATE/inbound/"
```

The bundle (outside every Git worktree) carries the exact new Source Version
and its original bytes for the reviewed contribution range only.

**GitHub pull-request mode (alternative; requires your approved hosted
repository).** PR mode is selected explicitly BEFORE the human decision (§5)
with the actual configured repository/remote/head/base. Its ordering is
fixed: exact commit verification (§5) → private handoff FIRST, obtaining the
ACTUAL `HANDOFF_ID`/`HANDOFF_SHA256` (above) → then the public-safe body
carrying those actual values, the exact revision, the validation outcome and
the summary → then exact-target retry inspection → only then the push/PR
mutation. An existing matching PR is reported and reused, never duplicated.
`gh` is one native-tool example, not a requirement; nothing here runs as part
of this local walkthrough:

```bash
cat > "$CONTRIB_PRIVATE/pr-body.md" <<EOF
Adds two pages and one ontology addition from the on-call runbook.

- Validation: complete candidate passed (authoring-check green)
- Exact revision: $REV
- Private source transfer id: $HANDOFF_ID
- Private source transfer sha256: $HANDOFF_SHA256
EOF
# Inspect BOTH the remote branch and the exact-target PR list BEFORE any
# push/create mutation:
git ls-remote "$KB_REMOTE" oncall-runbook
EXISTING=$(gh pr list --repo <owner/repo> --head oncall-runbook --base main \
  --json number,url --jq 'length')
if [ "$EXISTING" != "0" ]; then
  echo "Matching pull request already exists — report/reuse it; no push, no create:"
  gh pr list --repo <owner/repo> --head oncall-runbook --base main --json number,url
else
  git -C "$CONTRIB_WS/kb-repo" push -u origin oncall-runbook
  gh pr create --repo <owner/repo> --head oncall-runbook --base main \
    --title "Add on-call escalation runbook" --body-file "$CONTRIB_PRIVATE/pr-body.md"
fi
```

The body carries the actual transfer id/digest, exact revision, validation
outcome and summary ONLY — never private paths, originals, or signed URLs.
`<owner/repo>` is an explicit operator substitution for YOUR approved
disposable repository.

## 7. Maintainer: integrate, import, fresh admission, cited read

<!-- j6:maint-integrate -->
```bash
export JOURNEY="$HOME/lumio-journey-example"
export MAINT_WS="$JOURNEY/maintainer"
export MAINT_PRIVATE="$JOURNEY/maintainer-private"
export CONTRIB_WS="$JOURNEY/contributor"
export CONTRIB_PRIVATE="$JOURNEY/contributor-private"
export KB_REMOTE="${KB_REMOTE:-$JOURNEY/remote/kb.git}"
# OPERATOR-OWNED LOCAL FIXTURE TRANSFER (not a contributor submission step):
# commit mode ended the contributor's submission at the verified local commit,
# so the operator running this two-directory fixture bridges the contribution
# to the maintainer with ordinary native Git — fetching the branch directly
# from the contributor checkout. On a real two-machine journey the
# contribution arrives through the hosted remote/PR instead.
git -C "$MAINT_WS/kb" fetch "$CONTRIB_WS/kb-repo" oncall-runbook
CONTRIB_REV=$(git -C "$MAINT_WS/kb" rev-parse FETCH_HEAD)
git -C "$MAINT_WS/kb" merge --no-ff "$CONTRIB_REV" -m "Merge on-call escalation runbook"
FINAL_REV=$(git -C "$MAINT_WS/kb" rev-parse HEAD)
lumio-wiki validate "$MAINT_WS/kb"
echo "contribution: $CONTRIB_REV  final: $FINAL_REV"
```

<!-- j6:maint-import -->
```bash
HANDOFF_SHA256=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["bundle_sha256"])' \
  "$MAINT_PRIVATE/inbound/handoff-export.json")
lumio-wiki source-handoff inspect "$MAINT_WS/kb" --bundle "$MAINT_PRIVATE/inbound/handoff.tar" \
  --digest "$HANDOFF_SHA256" --revision "$CONTRIB_REV" \
  --private-profile "$MAINT_PRIVATE/profile.json" --json \
  > "$MAINT_PRIVATE/inbound/handoff-preview.json"
HANDOFF_CONFIRM=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["confirmation_digest"])' \
  "$MAINT_PRIVATE/inbound/handoff-preview.json")
lumio-wiki source-handoff import "$MAINT_WS/kb" --bundle "$MAINT_PRIVATE/inbound/handoff.tar" \
  --digest "$HANDOFF_SHA256" --revision "$CONTRIB_REV" \
  --private-profile "$MAINT_PRIVATE/profile.json" --confirm "$HANDOFF_CONFIRM" --json
```

The maintainer imports against the selected contribution revision; the
digest comes over the private channel with the bundle, never from the bundle
alone.

**[HUMAN — maintainer admission]** The maintainer reviews the FINAL
integrated commit freshly (the merge changed the commit identity; the
contributor's confirmations never carry over) and gives their own explicit
publication decision on the displayed preview below. PR approval, source
import, and the Git merge are NOT Publication Admission.

<!-- j6:maint-publish -->
```bash
lumio-wiki publish "$MAINT_WS/kb" --revision "$FINAL_REV" --to "$MAINT_WS/published" \
  --expected-current none --private-profile "$MAINT_PRIVATE/profile.json" --json \
  > "$MAINT_PRIVATE/publish-preview.json"
REVIEW_DIGEST=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["review_digest"])' \
  "$MAINT_PRIVATE/publish-preview.json")
# Only after the maintainer authorizes the displayed review:
lumio-wiki publish "$MAINT_WS/kb" --revision "$FINAL_REV" --to "$MAINT_WS/published" \
  --expected-current none --private-profile "$MAINT_PRIVATE/profile.json" \
  --confirm "$REVIEW_DIGEST" --json
```

<!-- j6:cited-read -->
```bash
lumio-wiki search "$MAINT_WS/published" escalation --limit 2
lumio-wiki page "$MAINT_WS/published" "On-call Escalation Runbook"
```

Expected cited read (exact routed path, hyphen preserved):

> The on-call engineer acknowledges within **5 minutes**; an unacknowledged
> Sev-1 page escalates to the Support Ops rotation lead after **10 minutes**.
> — On-call Escalation Runbook (`procedures/on-call_escalation_runbook.md`)

## What this example does and does not prove

Run end-to-end, it demonstrates the standalone CLI journey deterministically:
metadata-only bootstrap from a nonempty baseline, truthful baseline-original
unavailability, one complete two-page/ontology candidate, readable review
with whole-commit verification, branch submission, manual private handoff
with independent registries/stores, maintainer import, independent admission
and a cited read. It does NOT constitute the real BB + Pi harness
qualification (actual attachment handling in BB, real human decisions,
hosted PR, S3 exchange, independent machines) — that remains pending
qualification work — and it does not cover the separately planned integrated
Ariadne journey
([spec 0033](../../../ariadne/project/specs/2026-10-23-0033-managed-knowledge-authoring.md)).
