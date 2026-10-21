# Lumio agent onboarding quickstart (canonical)

This is the **one canonical onboarding journey** (issue #180): a single linear
path from an empty project to a grounded, citation-backed agent answer —
entirely on your local machine. No object storage, no Docker, and no model
provider are required: the base `lumio-wiki` wheel, plain Git, and you (the
host coding agent) as the Distiller are enough. Publishing immutable versions
to S3-compatible object storage — and read-only Reader projects against them
— is a separate optional guide:
[`docs/howto-s3-publish.md`](howto-s3-publish.md).

Time: ~15 minutes. You end with a Maintainer project that admits one exact
reviewed Git revision to a visible local Published Version, then answers
questions from the Knowledge Base with citations.

> The journey is scriptable: [`examples/onboarding-journey/smoke-journey.sh`](../examples/onboarding-journey/smoke-journey.sh)
> executes exactly the commands below and fails on drift. Run it with no S3
> environment for this local journey; CI additionally runs its S3 half
> against SeaweedFS `weed mini` on every push to main.

## What you are building

Lumio compiles trusted knowledge into a **Knowledge Base**: a directory of
Compiled Markdown pages plus a root `lumio.yaml` Control File. A **Maintainer**
authors and reviews locally in a selected Git worktree; `publish` admits one
exact commit as a **Published Version** only after the operator authorizes
the displayed review. One loop:

```text
setup → ontology starter → seed pages → managed ingest → Git review
      → exact-revision publish (preview → operator-authorized confirm)
      → search / page / related → open citation → grounded answer
```

## 0. Prerequisites

- Python **≥ 3.14**, a shell, and Git (authoring and admission only — plain
  reads, queries and validation never need Git).

Install the portable foundation. The base wheel carries the whole local
journey — no S3 extra, no retrieval adapter, no model provider:

```bash
pip install lumio-wiki
```

Verify:

```bash
lumio-wiki --version                # e.g. lumio-wiki 0.4.1
lumio-wiki doctor                   # version, detected extras, skill location
```

The optional capabilities — `lumio-lancedb` for enhanced retrieval,
`lumio-wiki[s3]` for object storage — are not needed below; see
[`docs/usage.md`](usage.md) and the [S3 guide](howto-s3-publish.md).

## 1. Maintainer: local project setup

Create a fresh project directory and run the canonical bootstrap. It creates
the Knowledge Base (seeded `lumio.yaml` + derived-index directory), writes project
`.env`, and writes the `AGENTS.md` protocol section:

```bash
mkdir helpdesk-project && cd helpdesk-project
lumio-wiki setup ./kb
```

`setup` ends with a status summary — role, location, retrieval backend/mode,
graph state, artifact retention, validation, and one next action. Re-run it
any time with `lumio-wiki status`. With `--publish-to <s3-uri>` the same
command additionally records an S3 publication destination
([S3 guide](howto-s3-publish.md)).

## 2. Ontology starter

A fresh Knowledge Base seeds a **valid-empty ontology**: `lumio.yaml` carries
the version-2 Control File, but `ontology.entity_types` and
`ontology.predicates` are empty. That is sufficient until the first page
declares `entity_types` or `claims` — validation then fails with "declare it
under `ontology.entity_types`/`ontology.predicates` in `lumio.yaml`", because
the vocabulary is KB-local content you declare deliberately.

Open `kb/lumio.yaml` and replace the empty ontology block

```yaml
ontology:
  entity_types:
  predicates:
  redirects:
```

with this starter (small but real: two Entity Types for the graph, a literal
predicate, and an inverse pair — an inverse must itself be a declared
predicate):

```yaml
ontology:
  entity_types:
    software-system:
      description: "A deployed software product or platform."
    database:
      description: "A persistent storage service backing an application."
    procedure:
      description: "A reviewed runbook or operating procedure."
  predicates:
    uses:
      subject_types: [software-system]
      object_types: [database, software-system]
      inverse: used-by
    used-by:
      subject_types: [database, software-system]
      object_types: [software-system]
      inverse: uses
    described-as:
      literal_kind: string
  redirects: {}
```

## 3. Seed pages with one accepted Claim

In a version-2 Knowledge Base every page declares a stable Entity ID and at
least one entity type, and lives under a configured Content Category. Create
two pages — the second page is the object of the first page's accepted Claim,
which is what makes graph traversal real:

```bash
mkdir -p kb/entities
cat > kb/entities/aurora-helpdesk.md <<'EOF'
---
title: "Aurora Helpdesk"
id: "entity:aurora-helpdesk"
entity_types: ["software-system"]
aliases: ["Aurora"]
tags: ["support", "product"]
summary: "The Aurora helpdesk product this Knowledge Base documents."
lifecycle: "approved"
visibility: "internal"
sources:
  - id: "aurora-product-notes"
    title: "Aurora product notes"
claims:
  - id: "claim:aurora-uses-starlight"
    predicate: "uses"
    object: "entity:starlight-db"
    status: "accepted"
    evidence:
      - lines: [6, 6]
---

# Aurora Helpdesk

Aurora is the support helpdesk this Knowledge Base documents. It stores
tickets and attachments in [Starlight DB](starlight-db.md).
EOF

cat > kb/entities/starlight-db.md <<'EOF'
---
title: "Starlight DB"
id: "entity:starlight-db"
entity_types: ["database"]
tags: ["storage"]
summary: "The persistent database behind Aurora Helpdesk."
lifecycle: "approved"
visibility: "internal"
sources:
  - id: "aurora-product-notes"
    title: "Aurora product notes"
claims:
  - id: "claim:starlight-described-as"
    predicate: "described-as"
    value: "managed PostgreSQL, region eu-west-1"
    value_type: "string"
    status: "accepted"
    evidence:
      - lines: [3, 4]
---

# Starlight DB

Starlight DB is the managed PostgreSQL (region eu-west-1) that stores Aurora
tickets and attachments.
EOF

lumio-wiki validate ./kb
```

A Claim needs `id`, `predicate`, exactly one object (`object` **or**
`value`+`value_type`), `status: accepted`, and at least one `evidence` anchor
(`lines` and/or `section`) into the page body — a Claim is a graph edge, never
answer Evidence by itself.

## 4. Managed document ingest (you are the Distiller)

Take a raw document — any file your team actually owns, here a support runbook
— and author its Compiled Page yourself. Lumio never generates content for
you: the **Distiller** is whoever writes the page — you at the keyboard or a
coding agent. No model provider, no coding-agent host, and no `[documents]`
extra is required; the supplied page below can be copied verbatim. The
managed mode binds the ORIGINAL bytes and your authored page under one stable
source identity, so provenance records the real file:

```bash
cat > support-runbook.md <<'EOF'
# Support runbook: password reset (internal)

Last reviewed: 2026-07-10. Owner: Support Ops.

1. Verify the requester through the secondary email on file.
2. In Aurora Helpdesk, open the requester's profile and click
   "Force password reset".
3. The reset link expires after 30 minutes; tell the requester.
4. Escalate to Support Ops on-call if the profile has no secondary email.

Reset volume is tracked in Starlight DB table `reset_audit`.
EOF

cat > password-reset-page.md <<'EOF'
---
title: "Password Reset Runbook"
category: procedures
type: runbook
durability_rationale: "Owned runbook; reviewed yearly by Support Ops."
id: "entity:password-reset-runbook"
entity_types: ["procedure"]
tags: ["support", "runbook"]
summary: "How Aurora support verifies a requester and forces a password reset."
lifecycle: "approved"
visibility: "internal"
sources:
  - id: "support-runbook-2026"
    title: "Support runbook: password reset"
---

# Password Reset Runbook

Verified steps from the 2026 support runbook. Aurora Helpdesk support
verifies the requester through the secondary email on file, then forces the
reset from the requester's profile. The reset link expires after 30 minutes.
Requests without a secondary email escalate to Support Ops on-call; reset
volume is tracked in [Starlight DB](../entities/starlight-db.md).
EOF

# Adopt an explicitly selected Git authoring tree; private state stays OUTSIDE it.
# Configure your own Git author identity before committing.
cat > kb/.lumio-authoring.yaml <<'YAML'
version: 1
namespace: "urn:uuid:4ba0be10-04a1-4d36-bbe6-54bf7d0b0320"
sources: {}
bindings: {}
YAML
git -C ./kb init -q
git -C ./kb add lumio.yaml entities .lumio-authoring.yaml
git -C ./kb commit -m "Adopt the helpdesk Knowledge Base"
export LUMIO_SOURCE_REGISTRY="$PWD/private-source-registry"

lumio-wiki ingest ./kb support-runbook.md \
  --compiled-page password-reset-page.md --source-id support-runbook-2026 \
  --source-registry "$LUMIO_SOURCE_REGISTRY"
```

The authored page declares `category`, a free-form `type`, and a
`durability_rationale` (categorized pages need all three), plus the same
`support-runbook-2026` id in `sources[].id` — that is the binding. Raw bytes
never enter the Knowledge Base; they are registered privately.

## 5. Git review: diff → commit → exact-revision publish

Git owns the review; publication is a separate explicit admission of one
exact commit:

```bash
git -C ./kb diff                          # the worktree changes from ingest
git -C ./kb add procedures/password_reset_runbook.md .lumio-authoring.yaml
git -C ./kb commit -m "Add password-reset runbook"
REV=$(git -C ./kb rev-parse HEAD)
lumio-wiki validate ./kb
lumio-wiki publish ./kb --revision "$REV" --to ./published \
  --expected-current none --source-registry "$LUMIO_SOURCE_REGISTRY"  # preview only
# Only after the operator authorizes that displayed review:
lumio-wiki publish ./kb --revision "$REV" --to ./published \
  --expected-current none --source-registry "$LUMIO_SOURCE_REGISTRY" \
  --confirm <review-digest>
```

A commit alone never publishes. After the confirm, `./published` holds the
admitted Published Version — visible, reviewed, and reproducible from that
exact commit. Legacy stores from the retired proposal pipeline migrate with
`lumio-wiki legacy-proposals inventory` and `legacy-proposals export` (never
publication). Preview can resolve an explicit ref; confirm using the captured
full baseline commit printed by preview, not the floating ref. The baseline
must carry the operator-adopted namespace; unknown exact history or stale
original assumptions block conversion.

## 6. Retrieval, citations with open actions, traversal

Every retrieval result and page read labels how to **open** what it cites —
reuse the labels verbatim when you answer:

```bash
lumio-wiki search "password reset" --limit 2
```

```text
## Password Reset Runbook
summary: How Aurora support verifies a requester and forces a password reset.
path:    procedures/password_reset_runbook.md
...
open:            lumio-wiki page ./kb "Password Reset Runbook"
```

Read the page (ladder step 3) to copy the exact passage before citing it:

```bash
lumio-wiki page "Password Reset Runbook"
```

The page read adds the private-Source action — an explicit, authorized
inspection command, never an implicit URL:

```text
source-artifact: lumio-wiki source inspect ./kb --source-id support-runbook-2026
```

Traverse the Discovery Graph over the accepted Claim you seeded (add
`--scope discovery` to include deterministic body-link Extracted References —
topology only, never Evidence):

```bash
lumio-wiki related "Aurora Helpdesk" --scope canonical --trace
lumio-wiki paths "Aurora Helpdesk" "Starlight DB" --scope canonical --trace
```

```text
Aurora Helpdesk (entity:aurora-helpdesk) -> Starlight DB (entity:starlight-db)
# trace: scope=canonical direction=outgoing max_depth=5 max_edges=1000 found=true hops=1
```

These reads run against the **authoring tree** (`./kb`) — the Maintainer's
current worktree view, resolved through the `LUMIO_KB_PATH` that `setup`
recorded in `.env`. The immutable admitted copy sits separately under
`./published`; nothing in this section claims to read it.

## 7. Source Artifact inspection — truthful unavailability

Retention of raw Source Artifacts is **disabled by default**; nothing was
configured in `setup`, so inspection says exactly that (secret-free metadata,
no raw bytes):

```bash
lumio-wiki source inspect ./kb --source-id support-runbook-2026
```

```text
source_id:       support-runbook-2026
...
bound_to:        current registry version (local worktree)
availability:    not retained (no Source Artifact Store configured)
authorization:   granted (private registry view)
```

`lumio-wiki source fetch ./kb --source-id support-runbook-2026` fails with an
equally actionable message (naming `--source-store`) rather than substituting
something else. Retention is **not retroactive**: raw bytes are retained at
managed-ingest time, only when a store is already configured. To retain
originals, configure a private store when you set the project up and
re-ingest — see the [S3 guide](howto-s3-publish.md) (`--source-store` accepts
an S3 URI or a local path; the store is always separate from public content,
and retention is opt-in).

## 8. A grounded agent answer

This is what the journey was for. A coding agent in the project — or you at
the keyboard, with `LUMIO_KB_PATH` from `setup`'s `.env` — follows the
retrieval ladder — hot index, navigation index, search, page read — over the
**authoring tree** (`./kb`, here identical to the admitted revision because
the worktree is clean) and answers **citing pages, not memory**:

> **Q: How long is an Aurora password reset link valid?**
>
> The reset link expires after **30 minutes**.
>
> — Password Reset Runbook (`procedures/password_reset_runbook.md`):
> "The reset link expires after 30 minutes."
> Open: `lumio-wiki page ./kb "Password Reset Runbook"`
> Source artifact: `lumio-wiki source inspect ./kb --source-id support-runbook-2026`

Every domain claim carries a citation with an open action; a question the
Knowledge Base cannot support returns **"not covered by this knowledge
base"** — never a fabricated answer.

## Optional next rung: immutable versions on S3

When the local journey works, the same admission gate publishes immutable
versions to S3-compatible object storage (a local SeaweedFS `weed mini` works
for testing) and binds read-only Reader projects to them — including optional
LanceDB retrieval with its truthful zero-index fallback. That path needs the
`[s3]` extra and is documented step by step in
[`docs/howto-s3-publish.md`](howto-s3-publish.md).

## Operating model notes

**Three states of `lumio.yaml`.** *Missing* → the Knowledge Base loads in
Legacy Flat Mode (Entity contract optional, no ontology validation, warning
emitted). *Empty file or empty mapping* → treated the same as missing for
content; establish the Control File deliberately. *Valid-empty* (what `setup`
seeds) → version 2 with the category catalog and an **empty ontology**: fully
valid, and sufficient until the first `entity_types`/`claims` declaration —
from then on the vocabulary must be declared (Part 2).

**Backend vs mode.** `LUMIO_RETRIEVAL_BACKEND` = `zero-index` (deterministic,
in-memory, always available) or `lancedb` (BM25/vector/hybrid ranking; needs
the adapter and, for remote indexes, a published `derived/lance/`). The
retrieval *mode* (`--mode lexical|semantic|hybrid`) picks how a query runs;
`semantic`/`hybrid` require the LanceDB backend **and** an embedder. A missing
or unhealthy LanceDB index never breaks reads — `status` discloses the
zero-index fallback and the exact repair command.

**Local authoring vs immutable S3 reading.** Maintainers author, ingest, and
publish **in a local worktree**; `publish-s3` writes one immutable version
prefix and advances a tiny pointer. Readers never write: `setup --from` binds
read-only and every pathless read resolves the active Published Version once.
Never point a Maintainer worktree at the S3 prefix as if it were a filesystem.

## Where to go next

- [`docs/usage.md`](usage.md) — full CLI, Python library, and coding-agent
  reference.
- [`docs/kb-format.md`](kb-format.md) — every frontmatter field and validation
  rule.
- [`docs/howto-s3-publish.md`](howto-s3-publish.md) — the optional S3 journey:
  `weed mini` locally, immutable Published Versions, Reader projects, LanceDB.
- The canonical joint local tutorial (Lumio + Ariadne in one walkthrough) in
  the Ariadne repository:
  [`docs/tutorials/lumio-ariadne-local.md`](https://github.com/legout/ariadne/blob/main/integration/docs/tutorials/lumio-ariadne-local.md).
- [`examples/onboarding-journey/`](../examples/onboarding-journey/) — the
  scriptable journey CI runs.
