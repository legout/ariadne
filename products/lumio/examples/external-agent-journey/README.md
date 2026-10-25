# Example: external-agent journey (synthetic, reproducible)

A self-contained walkthrough of the
[private source-handoff guide](../../docs/howto-source-handoff.md) using
synthetic content only. A maintainer starts from a nonempty Knowledge Base; a
**contributor coding agent in BB + Pi** receives one real attached document,
authors two related pages plus one ontology addition, gets a human review,
submits a native Git pull request, and the maintainer imports the private
source and admits the publication. No script is provided on purpose: the
harness steps (attachment, readable review, human confirmation) are manual by
design — that is what this example exercises.

All content below is hand-authored and deterministic: the same inputs produce
the same pages. Copy the blocks verbatim into the named files.

## Synthetic namespace and identities

| Identity | Value |
|---|---|
| Knowledge Base Namespace | `urn:uuid:9c1f5b2e-0010-4a10-9a10-5f3e8d2c7b31` |
| Baseline source (maintainer-only) | `aurora-product-notes` |
| Contribution source (the attachment) | `oncall-runbook-2026` |
| New Entity Types | `team` (ontology addition) |
| New predicate | `escalates-to` (`procedure` → `team`) |

## 1. Maintainer: baseline Knowledge Base

The maintainer Knowledge Base already contains one page bound to the baseline
source. Create it once (any machine; private state stays outside the repo):

```bash
mkdir -p maintainer/kb/entities && cd maintainer/kb
cat > lumio.yaml <<'YAML'
ontology:
  entity_types:
    software-system:
      description: "A deployed software product or platform."
    procedure:
      description: "A reviewed runbook or operating procedure."
  predicates:
    described-as:
      literal_kind: string
  redirects: {}
YAML
cat > .lumio-authoring.yaml <<'YAML'
version: 1
namespace: "urn:uuid:9c1f5b2e-0010-4a10-9a10-5f3e8d2c7b31"
sources: {}
bindings: {}
YAML
```

`kb/entities/aurora-helpdesk.md` (baseline page, bound to the baseline source
the contributor will never receive):

```markdown
---
title: "Aurora Helpdesk"
id: "entity:aurora-helpdesk"
entity_types: ["software-system"]
tags: ["support", "product"]
summary: "The Aurora helpdesk product this Knowledge Base documents."
lifecycle: "approved"
visibility: "internal"
sources:
  - id: "aurora-product-notes"
    title: "Aurora product notes"
claims: []
---

# Aurora Helpdesk

Aurora is the support helpdesk this Knowledge Base documents.
```

Register the baseline original privately (maintainer only), commit, and note
the exact base commit:

```bash
lumio-wiki ingest ./kb aurora-product-notes.md \
  --compiled-page aurora-page.md --source-id aurora-product-notes \
  --private-profile maintainer-profile.json
git -C ./kb add -A && git -C ./kb commit -m "Adopt Aurora baseline"
BASE=$(git -C ./kb rev-parse HEAD)
```

Export and deliver the **Source Baseline Snapshot** (metadata only — the
contributor gets no baseline originals), and share `sha256sum baseline.tar`
out-of-band:

```bash
lumio-wiki source-bootstrap export ./kb --revision "$BASE" \
  --output baseline.tar --private-profile maintainer-profile.json --json
```

## 2. Contributor: fresh clone and bootstrap

On the contributor machine (separate checkout, registry, credentials):

```bash
git clone <the-kb-remote> kb-repo && cd kb-repo
BASE=$(git rev-parse HEAD)
lumio-wiki git-check . --remote origin --json          # read access only
lumio-wiki setup ./kb --journey --private-profile contributor-profile.json
lumio-wiki source-bootstrap inspect ./kb --snapshot baseline.tar \
  --digest <maintainer-sha256> --revision "$BASE" \
  --private-profile contributor-profile.json --json
lumio-wiki source-bootstrap import ./kb --snapshot baseline.tar \
  --digest <maintainer-sha256> --revision "$BASE" \
  --private-profile contributor-profile.json --confirm <preview-digest> --json
```

The baseline original stays inspectable-but-unavailable:
`lumio-wiki source inspect ./kb --source-id aurora-product-notes` reports it
truthfully, and required-retention publication on the contributor refuses.

## 3. The attachment (the only input the contributor receives)

In a BB session with the lumio-wiki skill installed, ask the contributor
agent to author from **this attached file** (`oncall-runbook.md`). Exact
content:

```markdown
# Support runbook: on-call escalation (internal)

Last reviewed: 2026-10-20. Owner: Support Ops.

1. Any Sev-1 incident page Aurora Helpdesk automatically.
2. The on-call engineer acknowledges within 5 minutes.
3. If unacknowledged after 10 minutes, the page escalates to the
   Support Ops on-call rotation lead.
4. Sev-2 incidents follow the same rotation during business hours only.
```

The agent must read these real bytes (`extract`), not guess from the
filename:

```bash
lumio-wiki extract oncall-runbook.md --output ~/private/extract --json
```

## 4. Expected authored output (deterministic)

Two pages from one original, plus the ontology addition. These bodies are
the expected result — assertions during review compare against them.
`~/private/authored/lumio.yaml` (complete Control File candidate; the
`team` type and `escalates-to` predicate are the ontology addition):

```yaml
ontology:
  entity_types:
    software-system:
      description: "A deployed software product or platform."
    procedure:
      description: "A reviewed runbook or operating procedure."
    team:
      description: "A named group owning procedures and escalation."
  predicates:
    described-as:
      literal_kind: string
    escalates-to:
      subject_types: [procedure]
      object_types: [team]
      inverse: escalated-by
    escalated-by:
      subject_types: [team]
      object_types: [procedure]
      inverse: escalates-to
  redirects: {}
```

`~/private/authored/oncall-escalation-runbook.md`:

```markdown
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
      - lines: [9, 11]
---

# On-call Escalation Runbook

Aurora Helpdesk automatically pages the on-call engineer for any Sev-1
incident; the engineer acknowledges within 5 minutes. An unacknowledged page
escalates to the [Support Ops on-call rotation](support-ops-rotation.md)
lead after 10 minutes. Sev-2 incidents use the same rotation during business
hours only.
```

`~/private/authored/support-ops-rotation.md`:

```markdown
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
```

## 5. Candidate, review, confirmation, commit

`~/private/candidate.json` (compute the digest from the real attachment:

`sha256sum oncall-runbook.md`):

```json
{
  "schema_version": 1,
  "base_revision": "<BASE: full 40-hex commit>",
  "sources": [
    { "source_id": "oncall-runbook-2026", "original_path": "oncall-runbook.md",
      "expected_digest": "<sha256 of oncall-runbook.md>", "intent": "new" }
  ],
  "pages": ["~/private/authored/oncall-escalation-runbook.md",
            "~/private/authored/support-ops-rotation.md"],
  "control": "~/private/authored/lumio.yaml"
}
```

Apply the complete candidate, stage, and review:

```bash
lumio-wiki ingest-candidate ./kb --candidate ~/private/candidate.json \
  --private-profile contributor-profile.json --json
git -C . add kb/
lumio-wiki authoring-review ./kb --base "$BASE" \
  --private-profile contributor-profile.json --json > review.json
```

**[HUMAN]** The agent shows both new page bodies, the new
`team`/`escalates-to` ontology entries, and the accepted Claim, then asks for
an explicit decision. Only after the human confirms the displayed candidate:

```bash
git commit -m "Add on-call escalation runbook and Support Ops rotation"
REV=$(git rev-parse HEAD)
lumio-wiki authoring-check ./kb --review review.json --revision "$REV" --json
```

## 6. Handoff, exchange, pull request

```bash
lumio-wiki source-handoff export ./kb --base "$BASE" --revision "$REV" \
  --output handoff.tar --private-profile contributor-profile.json --json
sha256sum handoff.tar
lumio-wiki source-exchange upload --file handoff.tar \
  --kb ./kb --private-profile contributor-profile.json --json
git push -u origin HEAD && gh pr create --fill
```

The PR text names the exact revision, the validation outcome, and the
transfer id/digest from the upload result — nothing private. If the push or
PR may already have succeeded (for example after an interrupted run), look up
the existing branch/PR by exact repository/head/base before retrying; never
open a duplicate and never force-push.

## 7. Maintainer: import, final review, admission, cited read

```bash
lumio-wiki source-exchange download --id <transfer-id> --digest <sha256> \
  --output handoff.tar --kb ./kb --private-profile maintainer-profile.json --json
lumio-wiki source-handoff inspect ./kb --bundle handoff.tar --digest <sha256> \
  --revision "$REV" --private-profile maintainer-profile.json --json
lumio-wiki source-handoff import ./kb --bundle handoff.tar --digest <sha256> \
  --revision "$REV" --private-profile maintainer-profile.json \
  --confirm <preview-digest> --json
```

**[HUMAN]** The maintainer reviews the final integrated commit freshly
(`authoring-review` against its own base after merge/rebase — the
contributor's confirmation never carries over), then confirms the ordinary
`publish` preview against the maintainer's retained originals:

```bash
lumio-wiki publish ./kb --revision "$FINAL_REV" --to ./published \
  --expected-current none --private-profile maintainer-profile.json
# only after the maintainer authorizes the displayed review:
lumio-wiki publish ./kb --revision "$FINAL_REV" --to ./published \
  --expected-current none --private-profile maintainer-profile.json \
  --confirm <review-digest>
```

Finally, a cited read from the admitted snapshot:

```bash
lumio-wiki search ./published "escalation" --limit 2
lumio-wiki page ./published "On-call Escalation Runbook"
```

> The on-call engineer acknowledges within **5 minutes**; an unacknowledged
> Sev-1 page escalates to the Support Ops rotation lead after **10 minutes**.
> — On-call Escalation Runbook (`procedures/oncall_escalation_runbook.md`)

## What this example does and does not prove

Running it end-to-end through real BB + Pi sessions exercises attachment
reading, readable review, human confirmation, native Git submission, private
transfer, independent import, and maintainer admission. It does not prove
universal harness support, factual correctness of distilled content, or the
separately planned integrated Ariadne journey
([spec 0033](../../../ariadne/project/specs/2026-10-23-0033-managed-knowledge-authoring.md)).
