# How-to: external-agent authoring with private source handoff

This is the canonical guide for the **external-agent authoring journey**
(spec 0010): a **contributor** coding agent (BB + Pi with the packaged skill
is the selected initial qualification target — real harness qualification is
pending and not claimed by this guide) authors knowledge from a real attached
document, a human reviews it, native Git carries the submission, and a
**maintainer** on a separate machine imports the private sources and admits
the publication. Everything below uses the public `lumio-wiki` CLI only.

Read [`docs/quickstart.md`](quickstart.md) first: it owns the local
single-maintainer loop (setup, ingest, Git review, exact-revision publish).
This guide adds the two-environment split on top of those same gates. A
reproducible synthetic walkthrough with a manual BB + Pi recipe lives in
[`examples/external-agent-journey/`](../examples/external-agent-journey/).

**Paths, cwd, and the private boundary.** Keep every private working file —
originals, extracted material, authored pages, candidate requests, review
reports, profiles, registries, stores, transfer archives — at absolute paths
OUTSIDE every Git worktree; the commands below assume one private root per
role. Ordinary relative paths on the command line resolve from the process
working directory, and path strings inside request JSON are used verbatim
(no `~` expansion, not relative to the JSON file) — generate machine-read
files from expanded variables, as the example does.

## Topology and trust

- **Contributor environment**: a fresh clone of the Knowledge Base Git
  repository, its own private Source Registry and credentials, the packaged
  skill, and a harness session in which a human answers confirmations.
- **Maintainer environment**: the nonempty managed Knowledge Base, its
  canonical private registry/artifact store, and the publication destination.
  The maintainer retains the baseline originals; the contributor never
  receives them.
- **Source Exchange** (optional): one private S3-compatible bucket/prefix used
  only to move transfer archives. It is temporary delivery infrastructure —
  never a registry, never the publication target, and never a dependency
  after import (manual private transfer of the same archive works without
  any S3 dependency).
- Git carries content and exact source references only. Original bytes,
  private registry state, and credentials stay outside the repository, the
  pull request, and every published/Reader artifact.

## 1. Private source profile (v1)

Each machine selects **one explicit profile file** per operation; there is no
discovery by cwd or project name, and the profile selects neither Git
credentials nor a publication destination. Secret values stay in the
environment — the file carries variable *names* only.

```json
{
  "schema_version": 1,
  "namespace": "urn:uuid:9c1f5b2e-0010-4a10-9a10-5f3e8d2c7b31",
  "source_registry": "/home/you/private/lumio-registry",
  "retention": "required",
  "artifact_store": { "kind": "local", "root": "/home/you/private/lumio-artifacts" },
  "exchange": {
    "kind": "s3",
    "bucket": "team-exchange",
    "prefix": "lumio-handoff",
    "endpoint": "https://s3.example.internal",
    "region": "us-east-1",
    "url_style": "path",
    "credentials": {
      "access_key_id_env": "TEAM_EXCHANGE_ACCESS_KEY_ID",
      "secret_access_key_env": "TEAM_EXCHANGE_SECRET_ACCESS_KEY"
    }
  }
}
```

`retention: required` is mandatory for this guided journey (legacy flows may
keep retention disabled and stay on the ordinary quickstart path). The
optional `exchange` may be omitted — manual transfer then covers everything.
Both `artifact_store` and `exchange` accept the same S3 connection shape
(`artifact_store` additionally accepts the local directory form shown);
`bucket` is a bare bucket name, `prefix` a plain object prefix, and
`url_style` is `path` or `vhost`. Relative paths, inline secret values,
credential-bearing URLs, and unknown fields are refused.

Check any profile safely (no registry is opened, nothing is created, and the
output names no private path or credential variable):

```bash
lumio-wiki private-profile inspect "$CONTRIB_PRIVATE/profile.json" --kb "$CONTRIB_WS/kb-repo" --json
```

## 2. Maintainer: prepare the baseline

The journey starts from a **nonempty managed Knowledge Base** at a known full
commit — never from an empty demonstration. The maintainer exports a
metadata-only **Source Baseline Snapshot**: the exact Source Version metadata
referenced by that base revision, with **no original bytes**.

```bash
BASE=$(git -C "$MAINT_WS/kb" rev-parse HEAD)
lumio-wiki source-bootstrap export "$MAINT_WS/kb" --revision "$BASE" \
  --output "$MAINT_PRIVATE/outbound/baseline.tar" \
  --private-profile "$MAINT_PRIVATE/profile.json" --json \
  > "$MAINT_PRIVATE/outbound/baseline-export.json"
BASELINE_SHA256=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["snapshot_sha256"])' \
  "$MAINT_PRIVATE/outbound/baseline-export.json")
# share the archive and this digest with the contributor, out-of-band
```

Deliver the snapshot through the exchange or any private channel:

```bash
# manual private transfer (any private channel; here a local copy):
cp "$MAINT_PRIVATE/outbound/baseline.tar" "$CONTRIB_PRIVATE/inbound/baseline.tar"
# or, with an exchange connection declared in the maintainer profile:
lumio-wiki source-exchange upload --file "$MAINT_PRIVATE/outbound/baseline.tar" \
  --kb "$MAINT_WS/kb" --private-profile "$MAINT_PRIVATE/profile.json" --json
```

The maintainer keeps its retained originals; the snapshot deliberately cannot
substitute for them.

## 3. Contributor: fresh clone, connection check, guided setup

Clone the repository with your ordinary Git credentials, then check what they
actually prove. `git-check` is read-only: a readable remote proves **read
access only** — push and pull-request capability stay explicitly unverified,
and no test push, branch, or PR is ever attempted.

```bash
lumio-wiki git-check "$CONTRIB_WS/kb-repo" --remote origin --json
```

Run the guided journey setup. It records the submission mode
(`LUMIO_SUBMISSION_MODE=commit|github-pr`) and Git remote/target branch
(`LUMIO_GIT_REMOTE`, `LUMIO_GIT_TARGET_BRANCH`) as non-secret project
settings, reports skill drift and baseline-metadata readiness, and never
persists private paths in tracked content. Set the mode before a
noninteractive setup (export the variables or record them in the project
`.env`):

```bash
export LUMIO_SUBMISSION_MODE=commit
export LUMIO_GIT_REMOTE=origin
export LUMIO_GIT_TARGET_BRANCH=main
git clone "$KB_REMOTE" "$CONTRIB_WS/kb-repo"
BASE=$(git -C "$CONTRIB_WS/kb-repo" rev-parse HEAD)
(cd "$CONTRIB_WS" && lumio-wiki setup "$CONTRIB_WS/kb-repo" \
  --journey --private-profile "$CONTRIB_PRIVATE/profile.json")
```

Import the maintainer's baseline snapshot against the **same exact base
commit**, verifying the out-of-band digest first. Import without `--confirm`
is a read-only preview; the confirm digest binds this snapshot, revision, and
coverage, so a stale or mismatched digest refuses:

```bash
lumio-wiki source-bootstrap inspect "$CONTRIB_WS/kb-repo" \
  --snapshot "$CONTRIB_PRIVATE/inbound/baseline.tar" \
  --digest "$BASELINE_SHA256" --revision "$BASE" \
  --private-profile "$CONTRIB_PRIVATE/profile.json" --json \
  > "$CONTRIB_PRIVATE/inbound/baseline-preview.json"
BASELINE_CONFIRM=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["preview_digest"])' \
  "$CONTRIB_PRIVATE/inbound/baseline-preview.json")
lumio-wiki source-bootstrap import "$CONTRIB_WS/kb-repo" \
  --snapshot "$CONTRIB_PRIVATE/inbound/baseline.tar" \
  --digest "$BASELINE_SHA256" --revision "$BASE" \
  --private-profile "$CONTRIB_PRIVATE/profile.json" --confirm "$BASELINE_CONFIRM" --json
```

The contributor can now resolve every **unchanged** baseline binding while
`source inspect` truthfully reports the baseline originals as unavailable
(select the registry explicitly: `lumio-wiki source inspect <kb> --source-id
<id> --source-registry "$CONTRIB_PRIVATE/registry"`).
Required-retention publication on the contributor still refuses until the
missing originals are actually retained — the snapshot confers no publication
permission. A genuinely **new empty** Knowledge Base uses the confirmed
creation route instead of a baseline (see §8); a fresh clone of nonempty
content is never "an empty KB".

## 4. Contributor: read the attachment, author the candidate

The harness supplies the original as a real attachment. **Read the actual
file bytes** — never invent content from its filename. Extract it into
private working material outside every Git worktree; the record discloses the
real processor identity and any conversion limits, and PDF/Office/image
formats need `lumio-wiki[documents]`:

```bash
lumio-wiki extract "$CONTRIB_PRIVATE/inbound/oncall-runbook.md" \
  --output "$CONTRIB_PRIVATE/extract" --json
```

(Shell variables here stand for your role's ABSOLUTE private paths, as in the
[runnable example](../examples/external-agent-journey/README.md).)

Read the existing vocabulary and relevant pages first
(`hot`, `index`, `search`, `page`), then author the candidate **outside the
repository**: one or more Compiled Pages plus, when needed, ontology
additions. One original may legitimately produce several pages. Reuse stable
Entity/source identities when the source is an explicit update (`intent:
"update"`); choose a new collision-resistant `source_id` otherwise
(`intent: "new"`). A matching filename never establishes identity.

Describe the candidate in a v1 request JSON (also outside the repository).
Path strings inside the JSON are used verbatim — no `~` expansion, and a
relative string would resolve from the process working directory, not from
the JSON file's location — so generate the request from expanded variables
with the standard library instead of hand-typing paths:

```bash
ORIG_SHA256=$(sha256sum "$CONTRIB_PRIVATE/inbound/oncall-runbook.md" | cut -d' ' -f1)
python3 - <<'PY'
import json, os
from pathlib import Path
private = Path(os.environ["CONTRIB_PRIVATE"]).resolve()
request = {
    "schema_version": 1,
    "base_revision": os.environ["BASE"],
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
PY
```

`pages` lists the authored page files; `control` is the optional complete
`lumio.yaml` candidate carrying ontology additions. Apply the **complete**
candidate — cross-page references are validated as a whole, new originals are
registered, retained, and byte-verified before success, and a failure rolls
the authored tree back (reusable private registration may remain; nothing is
committed):

```bash
lumio-wiki ingest-candidate "$CONTRIB_WS/kb-repo" --candidate "$CONTRIB_PRIVATE/candidate.json" \
  --private-profile "$CONTRIB_PRIVATE/profile.json" --json
```

## 5. Contributor: readable review, ONE informed human decision, native Git

Prepare the native contribution branch from the exact baseline (never
submit the default branch), stage exactly the intended paths, and produce
the readable review against the exact full base commit. The review captures
the complete staged tree, displays page bodies/diffs and semantic changes
(Claims, Entity types, ontology, lifecycle, visibility, source support),
discloses excluded unstaged/untracked work, and refuses any submitted change
outside the Knowledge Base. It is stateless evidence: it approves nothing and
authenticates no one.

```bash
git -C "$CONTRIB_WS/kb-repo" checkout -b oncall-runbook
git -C "$CONTRIB_WS/kb-repo" add -A
lumio-wiki authoring-review "$CONTRIB_WS/kb-repo" --base "$BASE" \
  --private-profile "$CONTRIB_PRIVATE/profile.json" --json \
  > "$CONTRIB_PRIVATE/review.json"
```

**Ask ONE informed human decision.** Present, together: the displayed
candidate (new page bodies, before/after diffs with explicit deletions, the
plain-language summary of semantic changes, validation outcome), the
CONFIGURED submission action — commit-only (submission ends at the local
commit), or branch push of `oncall-runbook` to the configured
remote/base — and the private transfer that follows (a Source Handoff
Bundle through the private channel or exchange). One explicit decision
authorizes exactly this candidate and this selected action set; a changed
candidate or a different action needs a fresh decision. YAML is not shown;
large reviews are paginated and never imply review of undisplayed content.

Only after that decision, commit with native Git and verify the whole
resulting commit against the reviewed candidate — a post-commit hook or
concurrent edit produces a named mismatch and stops the submission:

```bash
git -C "$CONTRIB_WS/kb-repo" commit -m "Add on-call escalation runbook"
REV=$(git -C "$CONTRIB_WS/kb-repo" rev-parse HEAD)
lumio-wiki authoring-check "$CONTRIB_WS/kb-repo" --review "$CONTRIB_PRIVATE/review.json" \
  --revision "$REV" --json
# branch-push mode only (part of the authorized action), never in commit-only mode:
git -C "$CONTRIB_WS/kb-repo" push -u origin oncall-runbook
```

If anything changed after confirmation, do not carry the approval forward:
re-review the changed candidate and ask again.

### GitHub pull-request mode (requires your approved hosted repository)

Prepare a public-safe PR body first, INSPECT for an existing PR by exact
repository/head/base BEFORE creating anything, then create with explicit
targets — never `--fill`, never a duplicate, never a force-push, never an
auto-merge:

```bash
cat > "$CONTRIB_PRIVATE/pr-body.md" <<EOF
Adds two pages and one ontology addition from the on-call runbook.

- Validation: complete candidate passed (authoring-check green)
- Exact revision: $REV
- Private source transfer id/digest: see handoff receipt exchanged separately
EOF
git ls-remote "$KB_REMOTE" oncall-runbook
gh pr list --repo <owner/repo> --head oncall-runbook --base main
gh pr create --repo <owner/repo> --head oncall-runbook --base main \
  --title "Add on-call escalation runbook" --body-file "$CONTRIB_PRIVATE/pr-body.md"
```

The PR body carries a readable summary, the validation outcome, the exact
revision, and the transfer id/digest pointer only: never original documents,
signed URLs, private paths, or bucket names. `<owner/repo>` is an explicit
operator substitution for YOUR approved disposable repository — not a
placeholder a script may silently fill.

## 6. Contributor: private handoff

Export the **Source Handoff Bundle**: the exact Source Versions and original
bytes selected by new/changed bindings between the base and the contribution
commit. The bundle digest travels out-of-band (it is what the maintainer will
verify); a supplementary `--references` selection can carry additional exact
versions a maintainer is missing. Keep the archive outside every Git
worktree:

```bash
lumio-wiki source-handoff export "$CONTRIB_WS/kb-repo" --base "$BASE" --revision "$REV" \
  --output "$CONTRIB_PRIVATE/outbound/handoff.tar" \
  --private-profile "$CONTRIB_PRIVATE/profile.json" --json \
  > "$CONTRIB_PRIVATE/outbound/handoff-export.json"
HANDOFF_SHA256=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["bundle_sha256"])' \
  "$CONTRIB_PRIVATE/outbound/handoff-export.json")
```

Deliver it through the configured private route — manual transfer of the same
archive, or the S3 exchange:

```bash
# manual private transfer (no S3 dependency):
cp "$CONTRIB_PRIVATE/outbound/handoff.tar" "$MAINT_PRIVATE/inbound/handoff.tar"
# or, with an exchange connection declared in the profile:
lumio-wiki source-exchange upload --file "$CONTRIB_PRIVATE/outbound/handoff.tar" \
  --kb "$CONTRIB_WS/kb-repo" --private-profile "$CONTRIB_PRIVATE/profile.json" --json
```

**Retries inspect before creating or mutating.** Before pushing or opening
another PR, look up the existing remote branch/PR by exact
repository/head/base; never force-push or auto-merge to recover, and never
create a duplicate of an already-completed submission.

## 7. Maintainer: import, final review, admission

Fetch the contribution, integrate it, and import the bundle against the
selected revision (preview first; the confirm digest binds bundle, range,
and selection). `$HANDOFF_SHA256` and the transfer id arrive over the
private channel with the archive — never from the archive alone:

```bash
git -C "$MAINT_WS/kb" fetch origin oncall-runbook
CONTRIB_REV=$(git -C "$MAINT_WS/kb" rev-parse FETCH_HEAD)
git -C "$MAINT_WS/kb" merge --no-ff "$CONTRIB_REV" -m "Merge the contribution"
FINAL_REV=$(git -C "$MAINT_WS/kb" rev-parse HEAD)
lumio-wiki validate "$MAINT_WS/kb"
# with the exchange route, first:
#   lumio-wiki source-exchange download --id "$HANDOFF_ID" --digest "$HANDOFF_SHA256" \
#     --output "$MAINT_PRIVATE/inbound/handoff.tar" --kb "$MAINT_WS/kb" \
#     --private-profile "$MAINT_PRIVATE/profile.json" --json
lumio-wiki source-handoff inspect "$MAINT_WS/kb" \
  --bundle "$MAINT_PRIVATE/inbound/handoff.tar" --digest "$HANDOFF_SHA256" \
  --revision "$CONTRIB_REV" --private-profile "$MAINT_PRIVATE/profile.json" --json \
  > "$MAINT_PRIVATE/inbound/handoff-preview.json"
HANDOFF_CONFIRM=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["preview_digest"])' \
  "$MAINT_PRIVATE/inbound/handoff-preview.json")
lumio-wiki source-handoff import "$MAINT_WS/kb" \
  --bundle "$MAINT_PRIVATE/inbound/handoff.tar" --digest "$HANDOFF_SHA256" \
  --revision "$CONTRIB_REV" --private-profile "$MAINT_PRIVATE/profile.json" \
  --confirm "$HANDOFF_CONFIRM" --json
```

Then review the **final integrated commit** freshly — merge/rebase may change
the commit identity, and the contributor's confirmations never carry over.
Compare the final Source Reference Manifest against imported and existing
versions; changed bindings or missing originals need a supplementary handoff,
never a guessed latest version. Validate the whole candidate, not just the
delta.

Publication is the maintainer's own explicit admission (the ordinary
`publish` preview/confirm gate from the quickstart). Under required
retention it verifies **all** referenced non-synthetic originals in the
maintainer's canonical store — the retained baseline originals plus this
contribution's imported bytes. A PR approval, a source import, and a Git
merge none of them grant Publication Admission. The contributor needs no
publication credentials at all.

```bash
lumio-wiki publish "$MAINT_WS/kb" --revision "$FINAL_REV" --to "$MAINT_WS/published" \
  --expected-current none --private-profile "$MAINT_PRIVATE/profile.json" --json \
  > "$MAINT_PRIVATE/publish-preview.json"
REVIEW_DIGEST=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["review_digest"])' \
  "$MAINT_PRIVATE/publish-preview.json")
# only after the maintainer authorizes the displayed review:
lumio-wiki publish "$MAINT_WS/kb" --revision "$FINAL_REV" --to "$MAINT_WS/published" \
  --expected-current none --private-profile "$MAINT_PRIVATE/profile.json" \
  --confirm "$REVIEW_DIGEST" --json
```

After admission, cite from the published snapshot as always: Compiled Page
title, the path the CLI prints, and the exact supporting passage.

## 8. Starting a genuinely new empty Knowledge Base

`--create-empty` is an additional onboarding route for a **new** KB, not a
shortcut around the baseline above. The authoring location must already be a
registered native Git worktree (setup never initializes Git, switches
branches, or commits). Noninteractive calls validate and return a read-only
preview; `--confirm` authorizes exactly the freshly revalidated preview, and
a changed target or stale digest refuses before any write:

```bash
lumio-wiki setup "$MAINT_WS/repo/new-kb" --journey --create-empty \
  --namespace "urn:uuid:9c1f5b2e-0010-4a10-9a10-5f3e8d2c7b31" \
  --private-profile "$MAINT_PRIVATE/profile.json"            # preview only
lumio-wiki setup "$MAINT_WS/repo/new-kb" --journey --create-empty \
  --namespace "urn:uuid:9c1f5b2e-0010-4a10-9a10-5f3e8d2c7b31" \
  --private-profile "$MAINT_PRIVATE/profile.json" --confirm "$SETUP_DIGEST" --json
```

Confirmed creation writes the seeded Control File and an empty v1 Source
Reference Manifest under the selected namespace — no invented pages or
source history. Already-adopted nonempty Knowledge Bases keep their exact
namespace/bindings; nonempty content without a valid manifest is refused
with adoption guidance instead of being reinterpreted.

## Exchange notes, residue, and fallback

The upload path captures and validates the local bytes once, streams them
through multipart upload to a unique private
`_staging/<random-attempt-id>/transfer.tar` key, promotes them with an
**atomic copy-if-absent** to the immutable final `<id>/transfer.tar`,
verifies the complete final object, and only then publishes a create-only
`ready.json` completion record. Downloads verify the completion record and
the complete artifact before exposing output; a same-id/different-bytes
object is a conflict, never an overwrite.

The exchange service must support multipart upload and atomic conditional
server-side copy. SeaweedFS 4.45 is the proven-compatible reference service;
an unsupported operation produces a distinct `exchange_unsupported` refusal
and **manual transfer stays available** — carry the same archive privately
and feed the identical import commands. Temporary staging objects and
abandoned multipart uploads are operator-managed residue (lifecycle rules on
the staging prefix / incomplete uploads); Lumio adds no cleanup command and
never deletes remote objects. Local operation-owned temporary files are
removed when the operation finishes, and admitted knowledge never depends on
the exchange surviving.

## Ariadne boundary

This guide describes the **standalone Lumio** journey only. The integrated
Ariadne + Lumio Content-Repository journey — Core Git diagnostics,
managed-source admission within overall review, composed whole-contribution
review, and integrated qualification — is separately specified and planned in
[Ariadne spec 0033](../../ariadne/project/specs/2026-10-23-0033-managed-knowledge-authoring.md)
and
[plan 0033](../../ariadne/project/plans/2026-10-23-0033-managed-knowledge-authoring.md)
(slices A0–A3). Configuring the CLI above does not qualify that integrated
journey, and the existing paired standalone/integrated checks do not certify
it.
