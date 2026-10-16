# Lumio

Deployable chat for trusted knowledge and data. The MVP is a single-tenant, deployable browser agent platform that answers questions over a compiled Markdown knowledge base, with the wiki kept portable outside the web app.

## Language

### Product and knowledge artifacts

**Lumio**:
The product. Deployable chat for trusted knowledge and data.
_Avoid_: llm-wiki-agent, the wiki chatbot, the knowledge-base agent.

**Knowledge Base**:
A portable, versioned tree of Compiled Pages that Lumio loads from a local
filesystem or configured object storage location. It is the source-of-truth
input, not a database and not an index.
_Avoid_: the wiki (ambiguous — use only when "compiled Markdown artifact" is
clearly meant), the corpus, the dataset.

**Knowledge Base Location**:
A deployment or CLI configuration that resolves a Knowledge Base's Published
Versions from a local filesystem or object storage. Its credentials are
deployment configuration, never portable Knowledge Base content.
_Avoid_: Knowledge Source (raw ingest material), working copy, bucket (too
specific).

**Shared-directory Storage**:
A storage mode that copies Published Versions between an app's filesystem
working copy and a directory shared by its consumers. It is neither Git
synchronization nor object storage.
_Avoid_: local storage (ambiguous), S3 storage, shared Knowledge Base.

**Compiled Page**:
A Markdown file with YAML frontmatter (structured metadata) and a body (human-readable knowledge). Source-of-truth content.
_Avoid_: document, article, record.

**Synthetic Page**:
A Compiled Page generated from other compiled knowledge rather than a direct raw source. Must declare itself synthetic and may omit provenance.
_Avoid_: generated page, derived page.

**Knowledge Source**:
A raw input that feeds ingestion (PDF, Office doc, HTML, image, etc.). Distinct from a Compiled Page: sources are not part of the published knowledge base.
_Avoid_: input file, attachment.

### Identity and metadata

**Canonical Page Title**:
The unique title a Compiled Page is known by. A lookup label; semantic identity is the page's Entity ID.
_Avoid_: page name, heading.

**Alias**:
An alternate lookup phrase for a Compiled Page. Optional, and unique across the Knowledge Base.
_Avoid_: nickname, shortcut.

**Tag**:
A controlled organization and retrieval label on a Compiled Page. Required and non-empty.
_Avoid_: keyword, category.

**Lifecycle**:
The publication state of a Compiled Page: `draft`, `review`, `approved`, or `deprecated`.
_Avoid_: status (overloaded).

**Visibility**:
The access class of a Compiled Page: `public`, `internal`, or `restricted`. Lumio records it; the runtime enforces it.
_Avoid_: permission, access level.

**Review After**:
The optional `review_after` date (ISO 8601) on a Compiled Page: the page is due for review once `today >= review_after`. Advisory everywhere, blocking nowhere; changing it is an ordinary reviewed page change.
_Avoid_: stale_after (OKF exchange vocabulary), expiry, TTL.

**Source**:
A provenance reference on a Compiled Page (an identifier, a title, and an optional URL). Non-synthetic pages must have at least one.
_Avoid_: reference, link.

**Claim**:
A proposition owned by an Entity's Compiled Page. It uses a Control File predicate and exactly one Entity object or typed literal, has status `accepted`, `disputed`, or `superseded`, and carries Evidence anchors on the published page. Accepted entity-to-entity Claims form canonical graph edges.
_Avoid_: Relationship (retired vocabulary), connection.

**Extracted Reference**:
A deterministic, non-canonical directed reference derived from an internal Markdown link in a Compiled Page body. It supports navigation and context discovery but does not assert Claim semantics.
_Avoid_: inferred claim, automatic claim, link edge.

### Retrieval

**Evidence**:
A retrievable unit derived from a Compiled Page. Rebuildable from Markdown; never source-of-truth itself.
_Avoid_: chunk, fragment.

**Citation**:
Metadata that lets an answer point back to its source content: page identity, relative path, optional source reference, and optional line range.
_Avoid_: footnote, reference.

**Retrieval Result**:
A citation-ready object the Core SDK returns: evidence identity, citation, snippet, score, reason, and trace.
_Avoid_: hit, match.

**Retrieval Trace**:
A structured explanation of the retrieval stages (validation, lexical search, graph expansion, ranking) that produced a result. Exposed for admin and power-user inspection.
_Avoid_: debug log, explanation.

**Discovery Graph**:
The derived graph used to find context, containing accepted canonical Claims plus Extracted References. Its topology selects Evidence to inspect; an Extracted Reference is never Evidence and cannot support an answer claim by itself.
_Avoid_: knowledge graph (ambiguous), assertion graph, link graph.

**Index Freshness**:
Whether the derived index still reflects the current source Markdown. Lumio detects staleness after a sync or source change and rebuilds from source.
_Avoid_: cache validity, sync state.

### Ingest and publish

_Target vocabulary for owner-approved specification 0008 revision 1 and
[ADR-0029](project/adr/0029-git-native-knowledge-authoring.md), written approval
“Ja Freigabe”, 2026-10-15. Legacy terms identify the proposal-based model during
migration; approval does not assert that the replacement is deployed._

**Source Version**:
An immutable, content-hashed version of a privately identified Knowledge
Source. A new Source Version extends the same source lineage; it is not
automatically a different Knowledge Source.
_Avoid_: source revision, file version, upload.

**Source Artifact**:
The optional, private original bytes retained for one Source Version so an
authorized user can inspect the underlying material. It is excluded from the
Knowledge Base, public exports, retrieval, and canonical fingerprints.
_Avoid_: attachment, published source, evidence file.

**Source Artifact Store**:
The private store that retains Source Artifacts by Source identity and content
hash. It is separate from the Knowledge Base Location.
_Avoid_: attachment bucket, evidence store.

**Source Binding Manifest**:
The private record written to the Source Artifact Store before public
activation, binding one Published Version and each referenced
`(page, source_id)` pair to the exact Source Version content hash used for
that version. Historical manifests keep older Published Versions inspectable
after later Source Versions are registered.
_Avoid_: source index, lineage manifest.

**Source Inspection**:
An authorized action that retrieves the exact Source Artifact bound to a
Published Version. It supports provenance review but does not make the raw file
Evidence or imply claim-level source-span lineage.
_Avoid_: citation, source retrieval, document preview.

**Source Retirement**:
An explicit reviewed Maintainer decision that makes a Knowledge Source
ineligible to support future admitted knowledge without changing historical
Published Versions. A missing or unavailable source is only a retirement
candidate.
_Avoid_: source deletion, missing file.

**Knowledge Source Registry**:
Private provenance history giving each Knowledge Source a stable identity and
immutable content-hashed Source Versions with optional Source Artifact bindings.
It is excluded from Compiled Pages, exports, Reader retrieval, and canonical
fingerprints; it does not confer publication approval.
_Avoid_: lineage database, source index, manifest.

**Authoring Revision**:
An exact committed revision of authored Knowledge Base content and its source
references, scoped to one Knowledge Base. It is reviewable input, not a
Published Version or publication authorization.
_Avoid_: proposal, published commit, latest branch.

**Knowledge Base Namespace**:
The stable identity of a Knowledge Base within which its Entity and Source
identifiers are interpreted. It does not assert equivalence with another
Knowledge Base or confer execution authority.
_Avoid_: page title, storage location, ontology mapping.

**Source Reference Manifest**:
The authored record of a Knowledge Base's namespace, source lifecycle intent,
and exact Source Version bindings for its Entities. It contains safe identities
and digests, not raw source bytes, private storage locations, or credentials.
_Avoid_: Source Binding Manifest, source registry, deployment configuration.

**Publication Review**:
The inspection of one exact Authoring Revision, its validation and impacts,
source references, publication destination, and expected active Published
Version. Reading it does not authorize publication.
_Avoid_: passing validation, Git approval, publication authorization.

**Publication Admission**:
Explicit authorization to publish the exact state identified by a Publication
Review. A commit, merge, page Lifecycle, or passing validation is not admission.
_Avoid_: source approval, commit approval, proposal state.

**Ingest Proposal (legacy)**:
The former persisted set of proposed Markdown changes or explicit Page Removals
with provenance, affected pages, and validation. Its unreviewed content remains
unadmitted when exported to an Authoring Revision.
_Avoid_: Authoring Revision, admission receipt.

**Capture**:
An explicit, consent-only preparation of declarative Compiled Page knowledge and
a private Capture Manifest bound to the original session/export or manifest
bytes under an explicit source identity. It is preview-first, never publishes,
and never runs in the background.
_Avoid_: session recording, background logging, auto-ingest.

**Capture Manifest**:
The bounded, vendor-neutral YAML record identifying a capture's client,
project, timestamp range, transcript/export location or SHA-256 digest,
included artifact names, and explicit redaction labels. Private ingest
provenance, retained privately — never published; only the reviewed Compiled
Page knowledge is.
_Avoid_: session metadata export, transcript header.

**Page Removal**:
An explicit reviewed deletion of a Compiled Page from the next Published
Version, together with necessary canonical reference repairs. It is not inferred
from omission in a partial set of changes.
_Avoid_: missing page, automatic deletion.

**Published Version**:
An immutable admitted snapshot of the Knowledge Base that Readers and local
agents can resolve. It is distinct from an authored revision and its approval.
_Avoid_: release, commit (too VCS-specific).

**Write Mode (legacy)**:
The former `proposal-first` or `direct-write` choice for ingestion publication.
Neither mode supplies the Publication Admission required by Git authoring.
_Avoid_: edit mode, commit mode.

### Knowledge Base controls and published artifacts

**Knowledge Base Control File**:
A versioned root `lumio.yaml` that declares a categorized Knowledge Base's Content Category catalog and Hot Index pins. It is KB-local content control: portable with the Knowledge Base, validated and fingerprinted by the Core SDK, but neither a Compiled Page nor an OKF concept.
_Avoid_: config file, settings file, kb.json.

**Content Category**:
A broad navigation-routing label declared by the Control File (the seeded catalog is concepts, entities, references, procedures, tables, datasets, synthesis). Distinct from a Compiled Page's free-form `type`, which is specific semantics. No Lumio-wide type taxonomy exists.
_Avoid_: folder, section, classification (too generic).

**Hot Index**:
A regenerated, Maintainer-pinned navigation surface (`hot.md`) listing exactly the Compiled Pages whose Canonical Titles the Control File pins. Curated only; citation/access-frequency ranking is deferred.
_Avoid_: favorites, popular pages, recommendations.

**Legacy Flat Mode**:
The mode a Knowledge Base with no Control File loads in: existing root-level Compiled Pages remain valid with a non-blocking migration warning, and only Navigation Indexes are published until a reviewed migration establishes the Control File.
_Avoid_: old mode, unmanaged mode.

**Reserved Artifact**:
A marked Navigation Index (`index.md`) or Hot Index (`hot.md`) that is excluded
from Compiled Page loading, retrieval, and fingerprinting. Historical marked
`log.md` files are recognized only for compatibility.
_Avoid_: generated file, cache file.

**Lint**:
The read-only cross-page QA report over a Knowledge Base: authoritative validation, Discovery Graph health, and structural diagnostics for BOTH graph scopes (canonical and discovery) with explicit scope disclosure. Model-free; exits non-zero when the Knowledge Base is invalid. Never stages or writes.
_Avoid_: check (too generic), semantic review.

**Link Candidate**:
A deterministic suggestion for a missing authored Markdown link, ranked by
Discovery Graph impact. It is non-canonical and does not enter published graph
topology until the authored repair is reviewed, admitted, and published.
_Avoid_: inferred link, auto-link.

**Dream Cycle**:
The periodic Maintainer reflection with a deterministic model-free core over
validation, health, graph structure, and ranked Link Candidates, plus explicit
opt-in semantic findings. Repairs are reviewable authoring changes, never
automatic publication.
_Avoid_: reflection loop, auto-fix, consolidation.

**Source Drift**:
A Maintainer-only, model-free advisory comparison of declared source references,
private Source Version history, and available historical publication bindings.
It is never a publication gate or public artifact and never replaces exact
admitted bindings, mutates Reader Evidence, or proves Claim lineage.
_Avoid_: source staleness check, lineage audit, drift gate.

### Platform roles and guardrails

**Reader / Maintainer / Owner**:
The three Lumio roles. Reader asks questions and views citations. Maintainer runs ingest, reviews staged changes, and administers Reader accounts only (cannot see or target Owner/Maintainer accounts, themselves, or any role assignment). Owner configures storage, auth, model provider, write mode, secrets, and all accounts and roles. Owner is a first-run role created only through setup; the account-administration surface can never create, promote to, update, or delete an Owner.
_Avoid_: user/admin/superuser (use the canonical role names).

**Guardrails**:
The rules the Chat Gateway enforces: domain claims require citation; unsupported questions return "not covered"; out-of-scope questions are rejected or narrowed; external clients cannot bypass retrieval and citation; raw sources stay out of public exports.
_Avoid_: rules, policies.

### Web UI interaction model

**Chat + Citation Workspace**:
The Reader's default surface: a chat-first workspace that keeps Citations,
Compiled Pages, and Retrieval Trace access close to the conversation. Chat is
the entrypoint; evidence remains first-class.
_Avoid_: chatbot screen, ask page, Q&A panel.

**Chat Context**:
A temporary, Reader-owned conversation scope retained for the active retention
window. It carries chat state and any attached Conversation Source; it is not a
published Knowledge Base artifact.

**Conversation Source**:
A temporary private text or Markdown source attached to one Chat Context. Its
converted text and stable sections are retrievable only by its owning Reader
within that context and are removed independently of the published Knowledge
Base. It is distinct from both a raw Knowledge Source used by ingest and a
published Compiled Page.

**Reading Room**:
The Reader surface for browsing, searching, and reading published Compiled
Pages, either beside a conversation or as a standalone destination.
_Avoid_: document viewer, article view, citation popup, Library.

**Constellation**:
A contextual lens seeded from an answer, Citation, Compiled Page, or
Maintainer/Owner diagnostic task. It explains how Compiled Pages connect; it
is not the Reader home.
_Avoid_: graph homepage, mind map, knowledge graph app.

**Workshop**:
The Maintainer surface for ingest, validation, knowledge-change review, and
publication decisions.
_Avoid_: admin panel, CMS, moderation queue.

**Progressive Console**:
The Maintainer interaction model where ordinary Workshop tasks remain readable
and approachable, while ingest, validation, sync, proposal review, and power
navigation reveal Console affordances such as panes, operation logs, status
lines, and a command palette.
_Avoid_: terminal mode, developer console, power-user-only UI.

**Operational Disclosure**:
The Owner interaction model where settings and administration remain calm by
default, while audit, diagnostics, risky changes, and troubleshooting reveal
deeper operational detail only when needed.
_Avoid_: operations cockpit, control center, debug dashboard.

### Platform capabilities

These named capabilities are part of Lumio's ubiquitous language. Each is a seam, not a module dictate.

**Core SDK**:
The framework-independent boundary that owns loading, validating, indexing, and retrieving over a Knowledge Base. Every client (web, API, future CLI, local coding-agent adapter) calls the same Core SDK behavior.
_Avoid_: the engine, the backend.

**Agent Runtime**:
The Lumio-owned loop that classifies a question, retrieves evidence via the Core SDK, calls the model, synthesizes a cited answer, exposes a trace, and refuses unsupported claims.
_Avoid_: the LLM layer, the brain.

**Chat Gateway**:
The boundary that exposes chat to clients (native web API and a future OpenAI-compatible endpoint), enforcing auth, roles, and guardrails so no client bypasses the Agent Runtime.
_Avoid_: the API, the endpoint.

## Future extension

**Connector**:
A future adapter exposing knowledge or data from a non-Markdown source (table, database, data lake). Not part of the MVP. Retrieval results already allow non-Markdown evidence so connectors can be added without changing client contracts.
_Avoid_: integration, plugin.

**Dataset**:
A future structured data source exposed through a Connector (tables, extracts, Parquet, data-lake artifacts). Query execution is post-MVP.
_Avoid_: database (too narrow), table.
