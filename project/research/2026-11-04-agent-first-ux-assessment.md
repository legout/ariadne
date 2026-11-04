# Ariadne and Lumio: an agent-first usability reassessment

Date: 2026-11-04. Inspected checkout: `34bfe1be`.

**Status: research and recommendations, not an approved specification or implementation plan.** The owner's requirement is the authority for the desired experience: an owner installs/configures the system; other people add business documents and data through prompting; approval is simple. The architectural recommendations below are not owner decisions. Existing ADRs remain binding until explicitly amended.

This is a cross-product assessment, stored in the shared research area. It covers setup, contribution, approval, querying, and the design concepts that shape those journeys. It is not a line-by-line correctness audit or a claim to have evaluated every historical ADR. Sources are linked in §12. The assessment itself changed no product code, configuration, or authoritative design documents.

The owner's subsequent request for written design capture is recorded in [shared ADR-0028](../adr/0028-agent-first-shared-workspaces.md), [shared spec0034](../specs/2026-11-04-0034-agent-first-shared-workspaces.md), [Lumio ADR-0032](../../products/lumio/project/adr/0032-document-first-progressive-enrichment.md), and the expanded [Lumio spec0003](../../products/lumio/project/specs/0003-model-assisted-extraction.md). These written revisions remain proposed; they link the affected existing contracts rather than treating research as execution authority. The confirmed standalone Lumio meaning is captured in its glossary.

## 1. Bottom line

**Both packages are useful foundations, but their current default experience is closer to an engineering workflow than a business-user product.** The problem is not principally a lack of commands or documentation. Too many implementation concepts and operational responsibilities remain part of the journey.

The design currently makes this trade:

> Avoid a shared application/service, and let independent coding agents coordinate Git, local private state, source transfers, validation, and publication.

That reduces centrally operated infrastructure. It increases what each contributor's environment must contain and what each agent must coordinate. Those are different measures of simplicity.

The target should instead be:

> An owner manages one workspace. People provide material, clarify business meaning, and review understandable changes. Agents and deterministic software handle everything else.

Keep the distinction between knowledge and computation. Keep provenance, exact-version publication, source permissions, and safe query compilation. **Remove their implementation vocabulary from the normal experience, and reconsider the defaults that require so much distributed coordination.**

A package split need not imply two user journeys. Git need not imply a Git user interface. Human approval need not imply a human-operated terminal. Agent-first must not mean an agent improvises a complicated shell procedure on every request.

## 2. What is actually present

### Ariadne

The package declares version 0.7.0 and Python ≥3.14. It has a local deterministic CLI, optional MCP, typed authoring operations, source approval, and exact-revision admission. Setup can scaffold and detect filenames, but deliberately does not initialize Git or configure identity. Its interactive source selection exposes JSON objects. The agent skill explicitly prohibits the agent from performing source approval/admission and from directly manipulating the data project's Git state. [A1–A4]

These are deliberate boundaries, not missing documentation. Under the current contract, “the agent will just handle everything after installation” is not true for the complete journey.

Ariadne can admit context-only work and supports ungoverned, bounded exploration. A critique that says every source needs a fully modeled metric before anything useful can happen would be wrong. Those existing capabilities should become the visible progressive-onboarding story. [A4]

### Lumio-wiki

The package declares version 0.5.1 and Python ≥3.14. The base is model-free and cloud-free; the host agent can distill content without a second model service. It supports Git authoring, exact-version publication, source provenance, and optional private original retention. [L1–L3]

The canonical quickstart has **445 lines**. Before the first grounded answer it walks through an ontology, typed pages and Claims, a source manifest, Git setup, a private registry, ingest, review, commit, and publication. This is a deterministic technical demonstration, not an appropriate first-run experience for a nontechnical contributor. The external-contributor guide adds **491 lines** of profile setup, metadata bootstrap, handoff, and maintainer operations. Line counts indicate how much is exposed, not measured task time. [L2, L4]

Recent work already supplies valuable parts of the desired experience:

- A complete multi-page candidate with originals retained before successful application.
- Readable page-body and semantic-change review, rather than approval of YAML alone.
- One informed contributor decision covering the selected submission action and private transfer.
- Verification that the actual resulting commit matches the reviewed candidate.
- Confirmed setup for genuinely empty knowledge bases. [L4–L7]

However, the guide explicitly says real independent BB/Pi harness qualification is pending. The existence of commands and a manual recipe does not prove the intended person can complete the journey. [L4, L8]

### Together

The integrated route already has **one overall human confirmation** for knowledge publication plus Core activation. It is not inherently three separate publication approvals. It also binds one content commit, policies, knowledge, analytics, runtime identities, and visibility. [I1, I2]

The approved managed-source integration follow-up in specification 0033 is not delivered by the inspected publication call path: `lumio_context.publish_and_verify` still calls native publication without the proposed private registry/store/retention inputs. The contributor guide explicitly marks A0–A3 as a separate follow-up. Do not sell the latest standalone Lumio contribution journey as an already qualified combined journey. [I3, I4, L4]

The public foundation is not the separately maintained private Lumio application. That application was not inspected here; its current readiness cannot be inferred from the public glossary's browser, account, and role concepts. [R1, L9]

## 3. Where the experience breaks

### 3.1 Setup configures infrastructure, not an outcome

The first question should be “What does this team want to know?” or “Create a workspace for this team.” Instead, the current paths expose repository identity, locations, profiles, retrieval backend, source-store configuration, and machine-specific paths.

Ariadne's setup source prompt is literally an accept/skip/edited-JSON choice, followed by manual JSON source entry. Lumio's setup wizard asks about zero-index versus LanceDB and source artifact storage. These are useful operator controls; they should not be mandatory concepts for a contributor. [A2, L5]

**Recommendation:** one owner-led setup conversation, with recommended defaults and a concise preview. The program creates the selected private state and versioning layout after authorization. Business users join that configured workspace instead of constructing their own deployment.

### 3.2 Each contributor is effectively a small deployment

Lumio's independent environment requires its own checkout, namespace-compatible manifest, private profile, registry, retained new originals, baseline metadata, and transfer route. The maintainer then imports and publishes independently. The reason for each step is understandable, but the aggregate is expensive. [L4, L10]

The design solves a difficult case—independent local authoring without a central source service—as the default collaboration story. Most employees want to add a document to a team workspace, not operate an offline knowledge supply chain.

**Recommendation:** make the owner-managed workspace the ordinary team path. Retain independent local authoring and private bundles as an advanced/offline path only if users need it. This explicitly revisits ADR-0031's rejection of a shared authoring host; it cannot be implemented as a cosmetic wrapper while pretending that decision is unchanged.

### 3.3 The first document requires too much knowledge modeling

Lumio's version-2 model deliberately makes each Compiled Page an Entity with declared types. Accepted Claims use a controlled ontology and evidence anchors. This supports precise identity and graph semantics, but the quickstart teaches it before answering a simple runbook question. [L2, L11]

A password-reset procedure does not need a user-designed ontology to be useful. A business document may contain several concepts, exceptions, tables, and procedures; neither “one document equals one page” nor “split every noun into an Entity” is a good default.

**Recommendation:** preserve readable, source-backed content first. Let the agent choose a small coherent set of pages, reuse existing identities, and propose structured relationships only when they improve a real task. A system-supplied minimal type can satisfy the existing schema without asking the user. Making Entity typing itself optional would be a separate schema change. Never generate unsupported Claims merely to populate a graph.

### 3.4 Approval has been confused with operating the approval mechanism

Ariadne's walkthrough prints native JSON and exact commands. Its skill says the human must run the approval/admission commands. Lumio's new contribution review is friendlier, but still sits inside a much larger Git and transfer sequence. [A3, A4, L4]

A human should decide whether the proposed business meaning and sharing are right. They should not need to carry digests between commands. A digest identifies what was reviewed; it does not authenticate the reviewer. The existing code itself notes that a terminal is not an identity boundary. [A3]

**Recommendation:** bind a human action in the chosen trusted host to the exact review, actor, workspace, scope, and intended action; software invokes the low-level operation. Do not equate an agent writing `approved=true` with approval. A shared deployment needs enforced roles outside the drafting agent's own unrestricted shell.

The newest approved specification 0033 already allows an external agent to execute an authorized overall operation on the operator's behalf. That is a useful direction, but does not erase the older skill's restrictions or establish deployed behavior. Reconcile these contracts before implementation. [I3]

### 3.5 “Add content” actually hides three different business tasks

1. **Add a document** for people to find and ask about.
2. **Add data** for inspection and analysis.
3. **Approve a business definition** for shared, repeatable calculation.

These should share an intake experience, not be treated as equivalent permissions.

A spreadsheet can contain both narrative and structured data. Ariadne's current source registry lists SQLite, DuckDB, CSV, JSON, Parquet, Delta, Iceberg, DuckLake, and PostgreSQL—not native XLSX. Document conversion is not equivalent to a queryable spreadsheet import with dates, formulas, units, and sheet selection preserved. [A5]

**Recommendation:** show what will become searchable, what will become queryable, and what will become an official metric. Offer an honest supported-input matrix. Do not promise “any database/file” based on a Markdown converter or a DuckDB extension.

### 3.6 Combined use introduces operational coupling ordinary editors cannot explain

One integrated commit includes knowledge and analytics. The contract says a page-only edit cannot skip inherited OSI, ODCS, source, or evidence checks. Actual build identities also participate in admission, and integrated capabilities depend on explicit support revisions. [I1, I2]

That is defensible for reproducibility, but it means apparently ordinary knowledge work shares the analytics release boundary. An unrelated runbook edit can encounter inherited analytics-validation prerequisites; a changed build can require revalidation and admission even without a business-definition change. These are contract consequences, not measured outage reports.

**Recommendation:** initially automate the existing checks without claiming a new safety model. Then reconsider whether all knowledge belongs in one analytics release unit. Keep the exact dependency closure for a governed answer; allow unrelated knowledge to evolve independently if the owner accepts that architectural change. Reuse applicable evidence when inputs and required validity conditions genuinely match. Do not simply skip inherited checks.

### 3.7 A prompt wrapper would move, not remove, much of the complexity

The packaged Ariadne skill has 729 lines; Lumio's skill has 540, plus a 746-line protocol. They cover advanced capabilities as well as ordinary tasks. Size alone is not a defect, but asking a model to reliably coordinate this entire protocol is not a substitute for a coherent runtime workflow. [A4, L3]

**Recommendation:** a small task-oriented skill, capabilities discovered from the installed runtime, deeper instructions loaded only for the operation at hand, and deterministic handling of revisions, paths, validation, retries, and status. Reuse the current APIs. Do not add another autonomous agent runtime merely to wrap them.

### 3.8 Documentation teaches historical compatibility as onboarding

The checkout declares Core 0.7.0 / Lumio 0.5.1. Ariadne's standalone setup tutorial installs 0.6.0; the integrated tutorial deliberately demonstrates 0.6.0 / 0.4.0, with newer behavior separately discussed. The reference also distinguishes capability revisions 1, 2, and 3. This is honest historical evidence, but makes the novice responsible for choosing the right era. [A1, A6, I1, I5]

**Recommendation:** one recommended supported installation and one happy path per audience. Archive historical qualification instructions as such. Keep compatibility details for operators and diagnostics. Never present an unqualified new pairing as tested merely to simplify the prose.

## 4. Concept-by-concept disposition

These are proposed experience changes, not edits to the canonical glossaries. “Hide” means keep the mechanism but remove the need for an ordinary person to understand or operate it. Everyday labels below are proposed UI wording, not replacement domain definitions.

### Product and installation

| Current concept/choice | Critical assessment | Proposed disposition |
|---|---|---|
| Two independent packages | Useful reuse and ownership boundary; not a reason for two onboarding journeys. | Keep independence; offer one combined workspace setup. |
| Optional integration | Installing libraries should not silently grant authority. Users should not hand-author integration selectors. | Keep explicit owner choice; generate configuration. |
| Python ≥3.14 | A real platform prerequisite, not business value. Lowering it is not a free change. | Owner-managed runtime/bootstrap; revisit support only with dependency evidence. |
| Numerous extras | Lightweight core is good; selecting extras is a developer task. | Owner selects capabilities; install the supported set once. No surprise cloud/model fallback. |
| Separate Ariadne Agent/Tau | Another runtime and compatibility surface for a task the host agent can already perform. | Keep out of the ordinary package/host journey. |
| CLI versus MCP | Transports should not be user-visible workflow choices. Lumio MCP is currently read-only. | Keep CLI locally; design authenticated submission tools if remote prompt-only contribution is selected. |
| Skill installation/scope/drift | Necessary integration mechanics, not recurring user work. | Owner-led, host-specific setup and controlled upgrades. Never install instructions from uploaded content. |
| Multiple package/version names | Internal distribution history does not help the first task. | One product entrypoint, component details in diagnostics. No rename required to improve UX. |

### Authoring, state, and operations

| Current concept/choice | Critical assessment | Proposed disposition |
|---|---|---|
| Content Repository | Valuable export/history container; confusing as the user's workspace identity. | Keep underneath a named workspace. |
| Git branches/worktrees | Good isolation and history; making each contributor operate them is avoidable. | Managed workspace performs mechanics. Preserve native advanced access. |
| Ariadne typed proposals versus Lumio native Git | Legitimate internal differences; incompatible authoring rules for an agent doing one user task. | One task coordinator using each native boundary; no direct-write bypass. |
| Candidate Revision / Authoring Revision | Essential exactness, irrelevant copy/paste burden. | Generate, carry, and check automatically. |
| Preview / review / commit / admission / publish | Different technical events do not each require a separate business decision. | Present one change and one intended action at each real authority boundary. |
| Private profile path per invocation | Prevents accidental retargeting, but creates repetitive machine detail. | Bind an explicitly selected workspace once; runtime passes the exact profile internally. |
| Registry, artifact store, publication location, exchange | Distinct data/authority boundaries; four user configuration concepts are excessive. | Preserve separation behind one owner-managed storage setup. |
| Metadata-only baseline bootstrap | Solves distributed private-history replication without sharing originals. | Advanced independent-host mechanism, absent from ordinary managed contribution. |
| Source Handoff Bundle / exchange | Useful portable transfer; not inherent to adding a team document. | Advanced/offline route; reuse if that topology remains. |
| Required original retention | Auditability has value; storage/privacy costs are real. Quickstart and journey have different defaults. | Owner chooses a clear workspace policy; enforce it without repeated user setup. |
| Import confirmation | Important when trusting a selected external transfer; usually not a business-content judgment. | Automate checks under the owner's configured transfer policy; escalate changed destinations/scope. |
| Publication receipts / hashes / immutable versions | Essential reproducibility and stale-review protection. | Keep internal; expose history and meaningful version labels. |
| Expected-current / concurrency checks | Prevent overwriting others. | Keep deterministic; user sees “another change landed; here is the changed part.” |
| Rollback | Needed for correction; not permission to rewrite history. | “Restore the previous approved version,” with impact preview. |
| Dream Cycle / lint / source drift | Maintenance features, not prerequisite onboarding concepts. | Owner diagnostics; propose repairs without silent publication. |

### Lumio knowledge model

| Current concept/choice | Critical assessment | Proposed disposition |
|---|---|---|
| Compiled Markdown | Portable and inspectable; not something users should format. | Keep; agent authors it. |
| Source versus Compiled Page | Necessary lineage distinction; jargon can disappear. | “Original” and “knowledge created from it” in review. |
| One Entity per page | Helps stable semantic identity, but can force unnatural document decomposition. | Keep for existing schemas; use coherent pages, not mandatory noun expansion. Revisit only with real awkward documents. |
| Entity ID / namespace | Necessary stable identifiers. | System-generated; ask about genuine duplicates, not identifier syntax. |
| Canonical title / alias | Useful for human lookup. | Agent suggests; user corrects ambiguous names only. |
| Category / type / entity types / tags | Overlapping classification dimensions impose authoring work. | Default/minimize; do not ask users to maintain all four. Evaluate redundant requirements separately. |
| Durability rationale | Potentially useful for captured conversation noise, burdensome for an ordinary owned business document. | Derive a truthful default where justified; reconsider making it universal. |
| Ontology / predicates / inverse predicates | Valuable for explicit structured relationships, unnecessary before the first answer. | Advanced; reuse or propose only what the task needs. |
| Claims and typed literals | Useful exact propositions, not required to restate every sentence. | Sparse, evidence-backed, agent-authored. |
| Claim evidence anchors | Support published-page inspection but are not raw-source entailment proof. | Keep; improve reviewer source navigation without overstating lineage. |
| Canonical graph versus Discovery Graph | Important semantic distinction; a browsing implementation detail. | Keep internally; links never become facts automatically. |
| Hot Index / Navigation Index | Useful optional navigation; not a ritual every small question must traverse. | Agent/runtime chooses retrieval route; generated automatically. |
| Zero-index / LanceDB / lexical / semantic / hybrid | Operational retrieval choices, not first-run questions for a contributor. | Default simplest working mode; owner enables enhancements for demonstrated needs. |
| Lifecycle | Page metadata is not publication permission. Multiple “approved” states confuse. | Ordinary status comes from actual workflow; expose metadata separately only when useful. |
| Visibility | A real access boundary, not just a tagging task. | Workspace default and explicit exceptions; service enforces audience before retrieval. |
| Review After / freshness / source drift | These describe different risks; a blanket “verified” badge would lie. | Short actionable notices: what changed, when, and what needs attention. |
| Capture / research / graph exchange / legacy flat mode | Useful specialist routes, not core document onboarding. | Remove from the beginner path, retain specialist access as needed. |
| Citations / Source Inspection | Core trust UX; a shell command is not a convenient link for most people. | Clickable knowledge and authorized original preview, with unavailable originals stated honestly. |

### Ariadne analytics model

| Current concept/choice | Critical assessment | Proposed disposition |
|---|---|---|
| Context Layer versus Semantic Layer | Correct separation of explanation and calculation. | Keep underneath “what it means” and “how it is calculated.” |
| OSI YAML | Machine-readable executable definitions are valuable. | Agent generates; reviewer sees formula, filters, units, examples, and impact. |
| OKF profiles / interchange | Portability benefit, not first-run value. | Keep at storage/integration boundaries. |
| Seed Notes / Policy / Routing Map / term references | Different functions, but users can experience them as multiple places to repeat knowledge. | One clarification flow; avoid copied rule bodies; routing maps remain optional. |
| Source Approval | Necessary permission to access resources; not approval of business meaning. | Bounded owner grants, reused within their scope; new endpoint/privilege requires approval. |
| Storage Profile | Credential/endpoint separation is useful. | Owner connection setup; never credentials pasted into a business chat or shared repository. |
| Dataset / physical table / semantic dataset | Real distinctions, poor novice terminology. | Agent resolves; user sees recognizable data names and row meaning. |
| Schema Observation / filter values | Measurements must not become business rules. | Automatic bounded profiling where permitted; questions only for actual uncertainty. |
| Grain / Fact Branch / Conformed Dimension / fan-out | Essential protection against plausible wrong numbers. | Keep compiler/planner enforcement; ask “What does one row represent?” rather than teach grain theory. |
| Ontology / Identifier Mapping / mapping evidence | Useful cross-system interpretation, not authority to join automatically. | Detect/propose; ask for ambiguous equivalences; preserve reviewed join safety. |
| Governed metric / Ad-hoc metric | Valuable distinction. | “Approved definition” versus “exploratory calculation”; don't require approval to draft an answer. |
| Governed detail / Ad-hoc records | Different contracts, not commands users should choose. | Route the question correctly and disclose the actual status. |
| Data Contracts / bindings / observations / drift | Valuable for producer agreements; heavy for a first CSV. | Optional advanced input; don't fabricate a contract for every upload. |
| Execution attestation versus independent numerical validation | A critical honesty distinction. | Keep; present “checked against an independent reference” only when true. |
| Answer Examples / SQL provenance | Method reuse can help, but repeated save/attestation prompts distract from asking questions. | Prefer explicit “remember this definition/example”; revisit unsolicited save prompts and expose retained SQL only when saving it. |
| Query limits and read-only compilation | Real safeguards for resource use, correctness, and data access. | Keep; agent narrows requests and explains a useful recovery action. |

### Integration and approval

| Current concept/choice | Critical assessment | Proposed disposition |
|---|---|---|
| Direct optional SDK | Good reuse; does not require a microservice between the engines. | Keep even if a shared team-facing boundary is added. |
| Bound Release | Protects knowledge/calculation consistency. | Keep internally; user sees the active approved version and its history. |
| One whole Content Commit | Simple exactness, potentially large validation coupling. | Keep initially; reconsider release granularity using actual dependency closure. |
| Policy Binding / Policy Closure | Required policy context must not be silently lost or treated as executable prose. | Keep deterministic; generate/validate from explicit supported rules. |
| Full required Context in responses | Correct for computation preconditions; costly if every raw policy is repeated to the person/model. | Preserve enforced full context; concise human explanation plus inspectable originals. Do not silently truncate to bypass current limits. |
| Support revisions 1/2/3 | Capability negotiation, not user choice. | Setup selects and reports a compatible supported configuration; no silent authority expansion. |
| Exact code/build identity | Reproducibility benefit, with a real upgrade/admission cost. | Owner-managed upgrades first; separately assess when semantic compatibility could replace byte-exact binding. |
| Project-wide Visibility Scope | Honest current model, insufficient to claim per-user team authorization. | Explicitly design user/role-aware access if shared service is chosen. A query parameter is not permission. |
| Source access, contribution, approval | These are separate powers. A data contributor is not automatically a metric approver. | Separate capabilities, delegated by owner to appropriate domain reviewers. |
| Human-only terminal action | A workflow convention, not proof of identity. | Trusted human interaction bound to exact review; software executes authorized mechanics. |
| No second persisted draft lifecycle | Avoiding duplicate state machines is good. | Reuse Git authoring state; any new queue/status must reference it, not maintain a competing content truth. |

## 5. The experience to design for

The following is a proposed interaction, not existing commands or demonstrated behavior.

### Owner: create the workspace once

> “Set up a knowledge and data workspace for our support and finance teams. Keep originals private. Team members can contribute; Finance approves financial definitions.”

The agent asks only unresolved consequential questions: where it may run, who can access what, which model/host may process the content, retention, and who approves. It proposes storage and versioning defaults, installs/configures approved capabilities, creates the selected workspace, and verifies an actual first contribution and answer. Credentials use a secure owner-controlled mechanism, not chat text.

No request to design an ontology, choose a retrieval engine, type a UUID, or understand a private source manifest. Existing repositories/data are never silently adopted or overwritten.

### Contributor: add a document

> “Add this new travel policy for the team.”

1. Receive the actual attachment into the permitted private intake area.
2. Read/convert it, disclose meaningful conversion failures, and compare with existing content.
3. Recognize likely updates and conflicts. Reuse identity only with adequate evidence; ask when uncertain.
4. Prepare the smallest useful source-backed knowledge change.
5. Show what will change and who can see it; submit to the configured reviewer.

The contributor does not pick Lumio, an Entity type, a branch, a registry, or a handoff mechanism. If the audience is already fixed by workspace policy, do not ask about it on every upload. If processing would send data to a new external provider, that is a real permission question.

### Contributor: add a spreadsheet or data file

> “Add these monthly sales figures so we can analyze sales by region.”

Distinguish documentation from data import. Inspect the permitted file and relevant sheets/tables; propose a queryable representation with conversion provenance. Ask, only when not already established, whether rows are orders or order lines, which date is intended, what currency/unit amounts use, and how cancellations/refunds should be treated.

A source may become available for bounded exploration before an official metric exists. An exploratory result remains labeled as such. The system must not convert a persuasive explanation into an approved revenue definition.

### Contributor: connect a database

> “Onboard the orders tables from our sales database.”

If the owner has authorized the connection and requested scope, reuse that permission. Otherwise create a connection/access request for the owner. Do not require every employee to possess database credentials. After authorized access, propose useful tables, measured schema facts, and unresolved meaning. Do not automatically copy a database or grant joins based on matching names.

Adding a connection, adding a table within an authorized scope, and adding a business definition are distinct events under one conversational intake.

### Reviewer: decide on business meaning

> **Travel policy update**
>
> Replaces the 2025 policy with the attached 2026 policy.
> Hotel allowance changes from €120 to €150 per night.
> Audience remains internal. Original retained privately.
> One conflicting FAQ will be updated. No metric definitions change.
>
> **Approve and make available · Request changes · Reject**

For analytics, show the executable consequence:

> **Recognized revenue**
>
> Sum completed-order amounts in EUR, excluding cancelled orders.
> Uses order date. Order lines are aggregated before customer lookup.
> Independent example: €100 + €50 = €150; cancelled €25 excluded.
> No treatment for refunds is established yet: approval is blocked for that scope.

A short summary is navigation, not a replacement for the actual proposed content/diff, deletions, source support, or executable changes. Make these inspectable in the same review surface. Do not claim a reviewer examined material they never saw. Large contributions should be broken into coherent review units, not compressed into a misleading “looks good?” prompt.

### Reader: ask a question

> “How much revenue did we recognize last month, and what is excluded?”

Route automatically to approved knowledge and calculations. Return the number, period, meaningful exclusions, actual governance status, and useful citations. Raw SQL, build fingerprints, graph scope, and receipts are available in details, not dumped into the ordinary answer.

Ordinary readers must resolve approved published content. Editing/previewing a draft is a clearly selected mode. The current Lumio quickstart deliberately queries the authoring tree; that should not become the implicit reader contract for a team. [L2]

## 6. Simplify decisions without weakening governance

**A technical check is not necessarily a human decision.** Hash verification, schema validation, exact-version matching, concurrency checks, source retention verification, and publication preparation can run automatically. A person should intervene when meaning, access, sharing, or destructive intent changes.

| Event | Human decision | Automatic work |
|---|---|---|
| Owner creates workspace | Location, audience, processing/retention policy, reviewer authority | Private directories, versioning, generated identifiers/configuration, capability checks |
| New external data connection | Authorized owner grants bounded access | Connection validation and bounded profiling after permission |
| Upload within authorized workspace | Contributor chooses contribution/audience when not already fixed | Hashing, extraction, retention, identity candidates, drafting, validation |
| New or changed business rule | Authorized domain reviewer accepts exact meaning and impact | Bind reviewed state, prepare publication, activate and report |
| Unchanged exact upload | Normally no new content decision | Report existing source/version instead of duplicate submission |
| Concurrent material change | Review changed impact | Rebase/revalidate safely; preserve prior active content |
| Delete/retire or widen audience | Explicit authorized decision | Dependency checks and historical preservation |

A contributor's “submit this” and a maintainer's “approve this” are different decisions when they are different people. Do not collapse them to meet an arbitrary one-click target. In a single-person workspace one explicit “approve and publish” can cover the disclosed action set.

The approval mechanism must enforce the actor's capability. A model-generated confirmation token is not human identity. Equally, asking the human to copy a token through a terminal adds effort without solving identity.

## 7. Architecture options

| Option | What becomes simpler | What remains difficult |
|---|---|---|
| **A. Better skills over today's distributed CLI/Git model** | Lowest product change; more commands hidden by prompting | Every contributor still needs local setup, private-state bootstrap, transfer, credentials, and reliable recovery. Not the strongest default for nontechnical teams. |
| **B. One owner-managed workspace, existing agents as clients** | Contributors join once; one canonical private source history; centralized credential handling; one review surface | Adds a real authenticated boundary, managed jobs, permission enforcement, backup, and availability responsibilities. |
| **C. Dedicated end-user application with its own chat runtime** | Potentially simplest browser experience | Largest product/runtime/operations scope; risks rebuilding the separately maintained Lumio application and duplicating agent infrastructure. |

**Recommend B for the stated team workflow; retain A for advanced local/offline use.** First check whether an already selected host/private application can supply identity, attachments, durable job status, and review interaction. Do not assume it can, and do not build a new app before checking. The public package code inspected here does not establish that capability.

Keep the engines in one ordinary deployment and call their SDKs; a shared user-facing service does not require turning Ariadne and Lumio into separate microservices. Host-provided agents can remain the distillers and analysts.

The shared workspace owns private originals and connections. Each contribution uses isolated authoring state; publication is serialized/conditional. Contributors do not share one writable Git worktree or receive maintainer credentials. Persist enough task status to survive an interrupted agent, referencing native revisions and receipts rather than creating a second independent draft database. A retry should resume/report the same work, not create another PR or duplicate source.

This is **less distributed operational complexity, not zero backend work**. Authentication, role-aware retrieval, upload limits, processing permissions, source privacy, and recovery become explicit design obligations. They must be enforced by software, not only described in a skill. This report identifies the new boundary; it does not claim a vulnerability in the current trusted-local model.

## 8. What I would remove from the default journey

- User-operated Git and exact-revision command copying.
- Per-contributor private registries, baseline archives, and source-exchange setup.
- Ontology design and graph demonstrations before the first useful answer.
- Selecting retrieval backend/mode or component-level integration profiles.
- Choosing whether an input belongs to “context,” “semantic,” or “knowledge” layers.
- Repeated saving/attestation prompts after ordinary analytics questions.
- A requirement to define metrics when someone only wants to add documentation or inspect data.
- Raw JSON/YAML and hashes as the primary review surface.
- Historical package pairings and advanced migration routes in the beginner tutorial.

**I would not remove:** source permissions, authentic reviewer authorization, exact source provenance, explicit data-loss decisions, stale-review protection, compile/grain/read-only checks, truthful exploratory labels, required policy enforcement, or immutable published history.

## 9. A sensible order of work

This is prioritization, not an approved execution plan.

1. **Choose the collaboration/host model.** Decide where shared authority and private source history live. Otherwise more onboarding work will polish the wrong topology.
2. **Deliver one real document journey.** Nonempty workspace, fresh contributor identity, actual attachment, understandable review by another person, published answer with an accessible citation. No YAML, shell, Git, or copied digest for either ordinary participant.
3. **Add data-file onboarding.** Start with a deliberately chosen supported format; if business users primarily use Excel, address that explicitly rather than calling Markdown conversion spreadsheet analytics.
4. **Add shared database connection requests and reuse.** Owner provisions credentials/access; contributors request authorized tables and meaning clarification.
5. **Unify metric/policy review.** One change summary with actual executable impact; preserve the existing deterministic gates.
6. **Then reduce optional modeling and release coupling.** Use real friction evidence to decide which metadata requirements and whole-KB/build bindings need redesign.

Do not mechanically continue every pending authoring slice before this choice. Some spec0033 work remains useful under either topology, but independently replicated source workflows may no longer be the default priority. Preserve existing work; reassess against the selected experience.

## 10. Acceptance should be about people completing tasks

Proposed acceptance scenarios for a future specification:

- An owner sets up a new workspace through the chosen host, without editing configuration files; requested access and storage choices are visible before activation.
- A new contributor joins an existing nonempty workspace and adds a real document without receiving unrelated originals, publication credentials, or Git/storage instructions.
- A reviewer sees changed meaning, deletions, source support, audience, and analytics impact, and approves or requests changes without a shell.
- An unapproved or rejected candidate never changes ordinary reader answers.
- Re-uploading identical material does not create duplicate knowledge; an actual revision shows what changes.
- Interrupting extraction, review, or publication can be resumed without duplicates or exposing half-published content.
- An ambiguous spreadsheet date, unit, grain, or policy produces a targeted question, not a plausible guess.
- A contributor without a database grant requests access; the system does not borrow an administrator's privileges implicitly.
- A computed answer uses an approved definition or clearly identifies exploration; a policy summary never changes SQL by itself.
- A confidential document remains confidential during extraction, drafting, review, indexing, citations, and original inspection—not just at final publication.
- A new software build follows the selected upgrade policy without silently weakening the admitted calculation contract.

These are proposed real-user checks, not authorization to run tests, access data, deploy infrastructure, or redesign every subsystem now. Test the selected host and fresh user state, not just a prepared fixture or an agent simulating both people.

## 11. Decisions still owned by the user

Follow-up: the owner endorsed the simplification direction and explicitly required standalone shared Lumio use; see §13. The precise host, authority model, and detailed replacement design still need decisions.

1. **Shared team workspace or independent local environments?** I recommend a shared owner-managed workspace as the ordinary path. Independent/offline contribution can remain advanced.
2. **What host do ordinary people actually use?** A browser/app with attachments and trusted review controls, an existing desktop agent, or a coding terminal? Nontechnical browser use cannot be established by a CLI skill alone.
3. **Who approves which changes?** I recommend owner-delegated domain reviewers, with content contribution available more broadly. Installing the system and deciding a finance definition need not be the same person's job.
4. **What input formats and privacy conditions define the first release?** Pick the actual document/spreadsheet/database mix; decide permitted model processing and original retention. “And so on” is not a support contract.

There is no approved new vocabulary, ADR, or behavioral specification from this analysis. If this direction is selected, reconcile at least Ariadne ADR-0024/0026 and skill authority rules, Lumio ADR-0021/0028/0029/0031, and the relevant integration/authoring specs before dependent implementation. Not every choice requires changing all of them: model defaults can initially be hidden without schema changes; adding remote write/approval authority cannot.

Planning contract: version 1; installed skill provenance revision unknown. Disposition: **ask** for the collaboration/host decision before turning this into an approved design. No implementation handoff is ready.

## 12. Evidence and limits

### Primary sources

Paths are relative to this research note. Section names and symbols identify the inspected behavior; the checkout identity above bounds these observations.

- **R1:** [Repository README](../../README.md) — independent products, installation, public/private application boundary.
- **A1:** [Ariadne package metadata](../../products/ariadne/packages/ariadne-data/pyproject.toml) — version, Python, dependencies, entrypoints, extras.
- **A2:** [Ariadne setup implementation](../../products/ariadne/packages/ariadne-data/src/ariadne/setup.py) — `_select_entries`, `_managed_declare`, `run`.
- **A3:** [Ariadne review implementation](../../products/ariadne/packages/ariadne-data/src/ariadne/review.py) — module boundary, `_managed`, human/operator walkthrough.
- **A4:** [Packaged Ariadne skill](../../products/ariadne/packages/ariadne-data/src/ariadne/skill_assets/SKILL.md) — authoring rules, context-only work, query routing, onboarding, feedback, integrated operations.
- **A5:** [Source reference](../../products/ariadne/docs/reference/data-sources.md) and [source registry implementation](../../products/ariadne/packages/ariadne-data/src/ariadne/sources.py) — supported types, credentials, trusted catalogs; `SOURCE_TYPES`.
- **A6:** [Ariadne getting started](../../products/ariadne/docs/tutorials/getting-started.md) and [Git authoring](../../products/ariadne/docs/how-to/git-authoring.md).
- **A7:** [Ariadne glossary](../../products/ariadne/CONTEXT.md) and [Git-only ADR-0024](../../products/ariadne/project/adr/0024-git-only-durable-authored-state.md).
- **L1:** [Lumio package metadata](../../products/lumio/packages/lumio-wiki/pyproject.toml).
- **L2:** [Canonical Lumio quickstart](../../products/lumio/docs/quickstart.md) — ontology, publication, authoring-tree retrieval, retention defaults.
- **L3:** [Packaged Lumio skill](../../products/lumio/packages/lumio-wiki/src/lumio_wiki/data/skill/SKILL.md) and [protocol](../../products/lumio/packages/lumio-wiki/src/lumio_wiki/data/skill/PROTOCOL.md) — protocol line count only for the latter, not a full protocol audit.
- **L4:** [External-agent source-handoff guide](../../products/lumio/docs/howto-source-handoff.md) — independent environments, review, private profiles, transfer, pending qualification and integration.
- **L5:** [Lumio CLI](../../products/lumio/packages/lumio-wiki/src/lumio_wiki/cli.py) — `_run_setup_wizard`; [private profile](../../products/lumio/packages/lumio-wiki/src/lumio_wiki/private_profile.py) — `load_private_profile`, `resolve_private_profile`.
- **L6:** [Candidate ingestion](../../products/lumio/packages/lumio-wiki/src/lumio_wiki/authoring_journey.py) — `ingest_candidate` contract and initial validation path.
- **L7:** [Readable authoring review](../../products/lumio/packages/lumio-wiki/src/lumio_wiki/authoring_review.py) — captured staged-tree review and exact-commit contract; behavior also documented in L4.
- **L8:** [External-agent example](../../products/lumio/examples/external-agent-journey/README.md) — manual qualification recipe, explicitly no real harness-run claim.
- **L9:** [Lumio glossary](../../products/lumio/CONTEXT.md), [Git-native ADR-0029](../../products/lumio/project/adr/0029-git-native-knowledge-authoring.md), [read-only MCP ADR-0028](../../products/lumio/project/adr/0028-read-only-mcp-distribution.md).
- **L10:** [Private source handoff ADR-0031](../../products/lumio/project/adr/0031-private-source-handoff-for-external-agents.md) — reasons for independent environments, rejected shared-host/service alternatives, metadata baseline and exchange.
- **L11:** [Entity/Claim/ontology ADR-0021](../../products/lumio/project/adr/0021-entity-claim-ontology-and-progressive-graph-materialization.md).
- **L12:** [Document processing](../../products/lumio/packages/lumio-wiki/src/lumio_wiki/source_processor.py) — normalized-source, conversion, provenance and optional dependency boundaries.
- **I1:** [Bound releases reference](../../integration/docs/reference/lumio-bound-releases.md) — whole-commit validation, one overall confirmation, operation revisions, build identity, project-wide visibility.
- **I2:** [Ariadne integration ADR-0026](../../products/ariadne/project/adr/0026-lumio-sdk-bound-governed-releases.md).
- **I3:** [Approved managed-authoring specification 0033](../../products/ariadne/project/specs/2026-10-23-0033-managed-knowledge-authoring.md) — private profile, composed review, authorized agent execution, integrated qualification target.
- **I4:** [Integrated publication implementation](../../products/ariadne/packages/ariadne-data/src/ariadne/lumio_context.py) — `publish_and_verify`, inspected direct native publication calls.
- **I5:** [Combined local tutorial](../../integration/docs/tutorials/lumio-ariadne-local.md) — historical tested pairing, explicit operator commands, authoring versus admitted state.

### What was and was not established

- Read current source, package metadata, packaged agent instructions, glossaries, selected ADRs/specs, and the onboarding/contribution guides. The working tree was clean before this note.
- Consulted shared memory and the wiki first. The retrieved Lumio wiki overview describes the older full application, not today's public package boundary; it was not used as current implementation evidence. A QMD search returned no result. The available code graph was stale; direct file reads, not graph claims, underpin the findings.
- No installation, product journey, database query, source access, deployment, browser session, benchmark, or test suite was run. The repository's existing `.venv` exposes Python 3.12 while these packages require 3.14; no environment repair was attempted.
- No observed user study or measured failure/time rates exist in this assessment. Statements about novice friction and preferred architecture are reasoned recommendations grounded in the exposed workflow, not empirical usability results.
- No external competitor research was needed for this repository-based question. The private Lumio app and arbitrary agent-host capabilities remain unverified.
- This is not a security vulnerability report. The proposed multi-user model introduces authority and data-processing boundaries that need design; the inspected trusted-local tools should not be represented as already providing that model.

## 13. Owner follow-up: standalone Lumio and enrichment after intake

The owner endorsed the simplification direction in the next conversation turn and explicitly required **Lumio to work as a standalone shared knowledge base for internal documentation, runbooks, meeting notes, and similar team material**. Ariadne is optional analytics, not a prerequisite for Lumio contribution, review, publication, or retrieval. This confirms product direction, not the detailed architecture, deployment host, or implementation authority.

The owner subsequently selected **existing agent apps as the primary contributor/reviewer interface**, rather than extending the private Lumio application or building a new browser frontend. The next design should reuse those clients for interaction and provide shared workspace tools; the initial supported clients and their actual attachment, authentication, and trusted-confirmation capabilities still need selection and verification. This choice does not establish that arbitrary clients already support the full workflow.

The owner also asked whether agents could discover ontology definitions, typed Entities, Claims, evidence anchors, and manifests after basic onboarding, potentially with human review. **Yes, with an important distinction between semantic enrichment and accurate bookkeeping.** The following is a recommendation, not yet an approved behavioral specification.

### Intake records facts; enrichment proposes meaning

At intake, software should assign stable source identities, hash/version the actual input, preserve its access/retention policy, and retain the original or accurately record its absence. Conversion should preserve available source locations and disclose loss. Generate initial source manifests deterministically from those actual records. Publication manifests are generated from the actual publication; later enrichment updates exact bindings through the normal reviewed path. Manifests are not ontologies, and an LLM should never invent missing source history, approval, or retention evidence later.

After ordinary content review/publication, documents should be searchable and answerable with citations without a domain ontology or a complete analytics model. Data can be documented and, where the access/execution contract permits, explored before canonical metrics exist. This is a proposed progressive experience: existing Ariadne admission and query preconditions do not disappear.

An agent can subsequently inspect the authorized material and current vocabulary to propose:

- Entity candidates, types, aliases, and possible duplicate identities.
- A small vocabulary of relationships needed by real questions, reusing existing reviewed definitions before inventing new ones.
- Claims supported by exact passages, with their date, scope, attribution, and unresolved ambiguity.
- Evidence anchor candidates into exact page/source versions. Software verifies that anchors resolve and quoted text matches; this does not prove the passage entails the Claim.
- Contradictions, superseded statements, and questions for a domain reviewer.
- For Ariadne only, proposed metric meanings and mappings; neither a knowledge relationship nor a matching identifier grants source or join authority.

External ontology standards may be considered when relevant, but are suggestions, not proof of local business meaning. No automatic external lookup, document disclosure, new model provider, or imported operational instruction follows from enrichment.

### Human attention belongs on meaning

A reviewer should see a coherent business summary, source passages, and consequential changes—not be asked to approve every generated ID, hash, or line number. Ask particularly about entity merges, conflicting sources, changes to accepted definitions, important ambiguous types, and policies/metrics. Model confidence alone is not permission to accept a fact.

Meeting notes require special care: “Alex suggested a 30-day retention period” is not “company policy is 30-day retention.” Publishing the notes does not endorse the suggestion as policy. Enrichment must retain attribution and distinguish proposals, decisions, and normative rules where the evidence supports those distinctions.

Keep drafted enrichment out of accepted graph semantics until its applicable approval. Failure or rejection of optional enrichment must not make otherwise valid published documents unusable. A source update triggers dependency-aware re-evaluation, not silent mutation of previously accepted history. Enrichment inherits the source audience; a graph edge must not disclose confidential entities to a wider audience.

### Small first version

Start with an explicit request such as “organize the knowledge we have added and suggest useful relationships.” Reuse the host agent and native validation/review seams. Owner-enabled automatic draft preparation after intake is a possible later/default policy to decide; do not introduce a scheduler, agent swarm, or automatic semantic publication merely to answer this feasibility question.

At the inspected baseline, [extraction specification 0003](../../products/lumio/project/specs/0003-model-assisted-extraction.md) was a deferred placeholder for extraction, evidence grounding, contradiction detection, and consensus, with proposal terminology predating Git authoring. The owner's later capture request expanded it into a proposed document-first/enrichment specification; this is not implementation or execution approval. [ADR-0021](../../products/lumio/project/adr/0021-entity-claim-ontology-and-progressive-graph-materialization.md) still requires each version-2 Compiled Page to be a typed Entity. The written proposal recommends a minimal neutral artifact vocabulary first, not a new untyped format; its exact defaults still need approval. A staged enrichment feature is not already delivered merely because a host agent can author the existing structured format.
