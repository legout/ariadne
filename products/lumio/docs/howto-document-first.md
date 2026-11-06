# How-to: author a document-first candidate with the SDK

Use the document-first profile when a runbook or other document should enter a
Knowledge Base before anyone designs a business ontology. The page represents
the artifact itself; it does not become a person, service, customer, or other
business object mentioned in its text.

The SDK stays model-free. It creates no Claims, manifest writer, page-format
parser, or publication authority. The existing complete-candidate and native
review/admission paths retain those jobs.

## 1. Select the neutral control profile

Before authoring, the Knowledge Base must be in a registered Git worktree
with an explicitly adopted Source Reference Manifest. The selected full
`base_revision` must also contain that manifest in the same namespace;
ordinary setup alone does not establish this candidate-authoring prerequisite.
For a new empty KB, follow the
[confirmed journey setup](howto-source-handoff.md#8-starting-a-genuinely-new-empty-knowledge-base),
then commit its generated controls and manifest before selecting the base.
For an existing KB, preserve its adopted namespace and exact bindings; if the
manifest is missing, complete explicit adoption before continuing rather than
creating an empty manifest over existing source history.

For a new Knowledge Base, `document_first_control_file()` starts with the same
category seed as `seeded_control_file()` and adds only this Entity Type:

```yaml
knowledge-artifact:
  description: "A document, record, or other knowledge artifact. Its referent is the artifact itself, not a person, organization, service, or business object mentioned in it."
```

For an existing Knowledge Base, pass its parsed Control File so categories,
pins, redirects, IDs, and unrelated ontology entries are preserved:

```python
from lumio_wiki import document_first_control_file, load_control_file

control = document_first_control_file(load_control_file(kb_path))
```

The helper returns a value; it does not write it. An existing
`knowledge-artifact` type is reused only when its parsed definition exactly
matches the definition above. A conflicting local definition raises
`ControlFileError` for explicit resolution instead of overwriting or merging
its meaning. Ordinary `seeded_control_file()` and generic setup retain their
empty ontology.

## 2. Author one neutral page and complete candidate

Keep originals, authored pages, candidate controls, registries, and artifact
stores outside the content repository. Give the page a stable artifact Entity
ID, `entity_types: ["knowledge-artifact"]`, valid metadata, an exact Source,
and no inferred Claims. Choose a category already configured in the selected
Control File. The example uses `procedures`, which the new category seed
provides; for an existing KB without that category, replace it with a configured
category (or separately review a control change), rather than assuming that
`document_first_control_file()` adds categories to supplied controls.

For example:

```markdown
---
id: "entity:restart-worker-runbook"
title: "Restart Worker"
entity_types: ["knowledge-artifact"]
category: procedures
type: "runbook"
durability_rationale: "The source runbook permanently supports this procedure."
tags: ["operations"]
summary: "Restart the worker after replacing its configuration."
lifecycle: "draft"
visibility: "internal"
sources:
  - id: "restart-worker-runbook-source"
    title: "Restart worker runbook"
claims: []
synthetic: false
---
# Restart Worker

Restart the worker after replacing its configuration.
```

Serialize the selected control value to a private working location and pass it
through the existing `CandidateRequest` path. This example assumes `kb_path`
and `private_path` are absolute `Path` objects, `base_revision` is the exact
full base commit, and the original and authored page already exist at the
shown private paths:

```python
from hashlib import sha256

from lumio_wiki import (
    CandidateRequest,
    CandidateSourceRecord,
    LocalDirectoryArtifactStore,
    SourceRegistry,
    document_first_control_file,
    ingest_candidate,
    load_control_file,
    write_control_file,
)

original = private_path / "originals" / "restart-worker.md"
authored_page = private_path / "authored" / "restart-worker.md"
control = document_first_control_file(load_control_file(kb_path))
control_path = write_control_file(private_path / "candidate-control", control)

request = CandidateRequest(
    schema_version=1,
    base_revision=base_revision,
    sources=[
        CandidateSourceRecord(
            source_id="restart-worker-runbook-source",
            original_path=str(original),
            expected_digest=sha256(original.read_bytes()).hexdigest(),
            intent="new",
        )
    ],
    pages=[str(authored_page)],
    control=str(control_path),
)
result = ingest_candidate(
    kb_path,
    request,
    source_registry=SourceRegistry(private_path / "registry"),
    artifact_store=LocalDirectoryArtifactStore(private_path / "artifacts"),
)
```

The result binds the stable Entity to the exact source content hash and writes
an uncommitted authoring candidate. Validation and successful ingestion are
not Publication Admission. Review the resulting Git diff, then use the native
exact-revision preview and explicitly authorized confirmation flow in
[`howto-source-handoff.md`](howto-source-handoff.md) or the local flow in
[`quickstart.md`](quickstart.md). A later enrichment may add separately
reviewed business Entities and Claims; it must not silently retype this
artifact Entity.

## 3. Optional bounded enrichment in a managed workspace

After the document is admitted, an explicit request can select its artifact
page and relevant existing business-Entity pages for enrichment. The managed
workspace exposes this MCP call:

```text
prepare_enrichment(
  workspace_id=<configured workspace>,
  page_ids=<1–20 exact admitted Entity IDs>,
  expected_version=<current full admitted Git commit>,
  request_key=<stable request key>,
)
```

The result identifies the exact pages, Source Versions, retention availability,
existing identities, and complete Control File. It also reports the disclosed
character count and the limits: 20 pages, 200,000 characters, and 40 proposed
Claims. An oversized selection fails with a request to narrow or split it; the
service never truncates the corpus silently. Retrying the identical request
resumes the same task. No original passages are added to the selection, and the
service performs no external ontology lookup by default.

The host agent authors a complete candidate through `prepare_contribution`,
passing `enrichment_task_id`, `sources: []`, complete page Markdown, and a
separate stable `retry_key`. Pass a complete modified `control` only when the
candidate changes the ontology. Existing pages outside the selection and
unselected Source IDs are refused. Native candidate ingestion still resolves
identities and validates ontology, Claims, source bindings, and Evidence
coordinates. Coordinate validation is not semantic verification: the browser
review shows the exact quote, attribution, Source Version/availability,
potential conflicts, identity implications, and complete diff for a human to
judge.

Rejection leaves the admitted document and graph unchanged. To correct a draft
or accept only a subset, author another complete candidate with a new draft
`retry_key`; the service creates a fresh exact review. The discarded candidate's
browser action cannot admit the subset. Only the matching browser decision can
publish the corrected candidate. Preserve attributed proposals as proposals,
not adopted Policy, and do not infer a relationship from a mere co-mention.
Enrichment grants no source access, automatic merge, external lookup, Ariadne
join, metric, or publication authority.

## 4. Refresh a supporting source without rewriting accepted meaning

Upload the changed original under the same stable Source ID and prepare a
complete source-update candidate with `intent: "update"`. This registers a new
immutable Source Version; it does not switch admitted page bindings or publish
the update. The ordinary native review and admission path owns that decision.

An enrichment review prepared against the earlier version now shows **Source
refresh impact** to users with review permission. It lists the exact bound and
registry-latest hashes and the admitted pages and Claims/Evidence that may need
review. This is conservative page-level dependence only: it cannot determine
Claim-level or raw-passage impact, prove a Claim false, or retire missing
material. Old originals, published Claims, citations, and historical source
anchors remain unchanged. The browser action issued before the refresh is
stale and refuses with a conflict; do not reuse it.

First obtain the matching native review for the source-update candidate when
the new source version itself should be admitted. Then, at the user's request,
select the affected pages with `prepare_enrichment` at the current admitted
version and author a bounded correction through `prepare_contribution` with a
new draft `retry_key`. Shared native review owns the new admission as well.
There is no automatic redrafting, Claim-to-raw lineage graph, historical-anchor
redirect, or background publication workflow.
