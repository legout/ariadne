# Example: shared workspace journey (one real Pi, two real humans)

This is the W6 milestone journey for the shared workspace: the operator
recipe, the required fixture inputs, the expected statements and numbers,
and the refusal/recovery observations a run must produce. It complements the
canonical configuration guide ([`docs/howto-shared-workspace.md`](../../docs/howto-shared-workspace.md))
and the operations guide ([`docs/howto-workspace-operations.md`](../../docs/howto-workspace-operations.md));
this document owns the journey and its independently derived expectations.

**Status — honestly open.** The *real* journey legs that need owner-supplied
prerequisites have NOT passed and are not simulated as passed:

| Open leg | Owner-bound prerequisite |
|---|---|
| Two human participants (contributor + reviewer, separately delivered credentials) | Two local humans; one agent acting as both people proves nothing about human approval |
| Installed Pi with the workspace extension | Installed Pi on the contributor machine, `/workspace` + `/mcp` connection, owner model allowlist (`LUMIO_WORKSPACE_ALLOWED_MODES`) |
| Private HTTPS boundary | Operator-provided private HTTPS for the workspace host |
| Live Entra leg | Deferred (spec0034 r4); no tenant fixture exists — never report a pass |
| Live S3 / live spreadsheet run-legs | Reuse the D2/D3 lane evidence below instead of fabricating a live pass |

What HAS run is the synthetic installed-distribution verification recorded in
the last section: the document journey and both oracles below were executed
2026-11-07 against built wheels in isolated environments (Lumio-only without
Core, and the analytics pair), with one agent driving every identity — which
proves the installed surfaces and the expectations, and deliberately does not
prove the two-human or private-HTTPS legs.

## 1. Fixtures and identities (synthetic, embedded)

All expected values in this journey come from these fixture texts — never
from service output.

### 1.1 The operations-notes corpus (v1, the baseline source)

```markdown
# Operations notes

## Ownership

Team A operates Service B.

Team C is mentioned in the escalation roster.

## Meeting notes

Alex proposed retaining logs for 30 days.

## Escalation

During a SEV-1 incident the on-call engineer pages the secondary responder
within 15 minutes and records the page in the incident log.
```

The baseline Knowledge Base binds four pages to this source digest:
Operations Runbook (`entity:operations-runbook`, procedures), Team A
(`entity:team-a`), Service B (`entity:service-b`), Team C (`entity:team-c`).
The ontology defines `operates` (team → service), the literal predicate
`proposed-log-retention-days` on services — described as *"A
source-attributed proposal, not an adopted retention Policy."* — and note
predicates for artifacts and teams. The `knowledge-artifact` entity type must
keep the exact neutral document-first description (a local variant reads as a
conflict, by design).

### 1.2 The corpus update (v2, uploaded during the journey)

v1 plus:

```markdown
## Paging drill

After a SEV-1 page, the secondary responder confirms handover within 5 minutes.
```

### 1.3 People and capabilities (provisioned by the operator CLI)

| User | Capabilities | Credentials |
|---|---|---|
| `owner` | read, setup | api + browser |
| `contributor` | read, contribute | api (+ browser for the refusal probe) |
| `reviewer` | read, review, inspect_source | browser |
| `reader` | read | api |
| `outsider` | *(no membership)* | api |

Every member first receives the default `read` grant; authoring capabilities
are additional explicit grants. Credentials are purpose-separated
(`local-token issue --purpose api|browser`) and delivered by the operator,
never through Pi.

### 1.4 The analytics fixture (pair journey)

A synthetic native retail baseline (`urn:demo:w6retail`) with an orders
model over a baseline SQLite table. The journey adds the operator-bound
source `orders2` whose `entries` table holds exactly:

| id | amount | status |
|---|---|---|
| 1 | 12 | completed |
| 2 | 8 | completed |
| 3 | 99 | cancelled |

**Hand-worked expectation (derived here, before any query):** completed
revenue = 12 + 8 = **20**; the cancelled 99 never counts. The governing
policy page states the same rule in prose, and the reviewed model edit
switches the metric to `SUM(amount) FILTER (WHERE status = 'completed')`
over `orders2.main.entries`.

### 1.5 PDF/DOCX route fixtures

Small real documents that convert inside the native 20-second bound:
`text.pdf` (sha256 `7d1fd093…`, converts via LiteParse; contains "Fixture
Document") and `text.docx` (sha256 `6b674297…`, converts via AnyDoc; contains
"First numbered"), both from
`products/lumio/experiments/anydoc/fixtures/anydoc-fixtures/`. The large
real-world example sources honestly exceed the conversion bound and are not
used.

## 2. The journey

Configuration (mode, published path, state, authoring, private profile) is
the canonical guide's §§1–3; provisioning is its §3. The steps below name
what each participant does and what must be observed.

### 2.1 Operator: baseline and service

1. Author the §1.1 corpus and the four-page KB; register the source in the
   private Source Registry and artifact store; publish the baseline natively
   (`lumio-wiki` authoring admission; the published destination is what the
   service reads).
2. Provision the §1.3 people through the installed CLI. Record each
   credential ID; the raw token prints exactly once.
3. Start `lumio-workspace serve` behind the private HTTPS boundary.

### 2.2 Pi (owner-bound leg; synthetic run used direct MCP over HTTP)

The contributor's installed Pi connects with their API token in the
operator-controlled environment and the owner's model allowlist. Via `/mcp`:

- `workspace_status` → `ready: true`, the caller's capabilities, the current
  `published_version` (record it as **V1**).
- **Cited answer (oracle 1).** `read_knowledge("Operations Runbook")` must
  return the SEV-1 sentence — *"pages the secondary responder within 15
  minutes"* — with a citation carrying the page path and **V1**.
  `search_knowledge("SEV-1")` must return that page with a passage
  containing *"within 15 minutes"*.

### 2.3 Contributor: exact bytes, retry discipline, normalized material

1. `POST /uploads` the §1.2 corpus update (source id `operations-notes`,
   `application/octet-stream`, a chosen stable retry key). Expect an
   `upload_id` and the v2 sha256.
2. **Recovery observation:** repeat the identical upload (same key, same
   bytes) → the *same* `upload_id`, no duplicate.
3. **Refusal observation:** same key with *changed* bytes → HTTP 409
   `retry_conflict`; the original is never silently replaced.
4. `read_source_material` → normalized text containing *"confirms handover
   within 5 minutes"*, `incomplete: false`, processor `markdown`.
5. PDF and DOCX: upload each and read the material — processor `liteparse`
   (PDF, page-addressable) and `anydoc` (DOCX, heading sections), non-empty
   text, `incomplete: false`. Uploads are retained only; retention is not
   admission.
6. `prepare_contribution` with the uploaded source (intent `update`) and the
   updated runbook page → `pending_review` plus the opaque `review_url`.

### 2.4 Reviewer (a different human, browser only)

1. Sign in at `/auth/login` with the *browser* credential over HTTPS.
   **Refusal observations:** an API-purpose token is refused here (401), a
   browser-purpose token on `/mcp` is refused (401), an anonymous review GET
   redirects to login, and a contributor without `review` is refused.
2. Open the `review_url`: the GET is inert and shows the complete effective
   change — the new *handover within 5 minutes* sentence must be visible —
   plus native submission ancestry. Each GET issues a fresh one-use action.
3. Approve via the same-origin form POST → `published` / `activated`.
4. **Refusal observation:** replaying the same action digest → HTTP 409.

After publication, `read_knowledge("Operations Runbook")` must show the
handover sentence under a **new** `published_version` (**V2** ≠ V1).

### 2.5 Optional enrichment: the attributed meeting proposal (oracle 2)

1. `prepare_enrichment` selecting `entity:service-b` and `entity:team-a`
   against **V2** → bounded selection (limits: 20 pages, 200,000 characters,
   40 proposed Claims; external lookup disabled), sources report the corpus
   digest with originals available.
2. The contributor authors complete pages through `prepare_contribution`
   (`enrichment_task_id`, no new sources): Service B gains the claim
   `proposed-log-retention-days = 30` (status accepted, evidence section
   *"Meeting notes"*), and its body states the proposal explicitly; Team A
   gains `operates → entity:service-b` (evidence *"Ownership"*).
3. The reviewer approves; the pages publish under **V3**.

**Expectations:** `read_knowledge("Service B")` shows the proposal sentence;
the published Service B page carries exactly one
`proposed-log-retention-days` claim, value **30**, attributed to the
*Meeting notes* evidence of the bound source; Team A carries exactly one
`operates` claim. The proposal stays a proposal — no page, category, or
policy adopts a log-retention rule (the predicate description governs this).

### 2.6 The analytics pair (explicit enablement; oracle 3)

Prerequisites: the service runs with `LUMIO_WORKSPACE_ANALYTICS_*` fully
configured (exact project handle, project path, operator source bindings)
and the `analytics` extra installed — the same-candidate Core producer.

**Lumio-only truth first:** on the base service (no Core), a
`query_data` call must be refused honestly — *"analytics is not enabled…"*
when unconfigured, and *"analytics Core is unavailable or incompatible;
install the same-candidate analytics producer rather than using the base
service as a query fallback"* when configured but Core is absent. Never a
fallback, never silence.

1. Owner setup: browser GET `/setup` shows the adopted-KB preview; the
   same-origin POST applies it.
2. `prepare_data_source` (contributor; project `retail`, source `orders2`,
   table `entries`, the business question) → `pending_source_approval`.
   **Refusal:** profiling before approval is refused.
3. The reviewer approves twice through the browser — source approval, then
   the explicit data grant → `data_granted`.
4. `profile_data_source` → exactly the `orders2` source, `entries` with
   row count 3 (bounded profiling, no data in the response).
5. Upload the policy note (source `human-cancellation-rule`, intent `new`)
   and `prepare_contribution` with the source task, the updated policy page,
   and the reviewed model edit (the `SUM(amount) FILTER …` expression over
   `orders2.main.entries`) → `pending_submission`.
6. The reviewer submits (approve → `pending_publication`, validation ok),
   then reviews — **the filter expression and the policy sentence must be
   visible in the review HTML** — and approves → `published` / `activated`.
7. `query_data` (`get_metric` `revenue`) → **rows exactly
   `[{"revenue": 20}]`** (the §1.4 hand-worked value), `governed: true`,
   `complete: true`, citations to the revenue metric and both governing
   policies, and the pinned commit equal to the published native candidate.
   `get_task` reconciles the published state.
8. **Refusal:** an unauthorized reader's `query_data` → *"not available for
   this caller"*.

## 3. Input-family coverage

| Family | Status | Evidence |
|---|---|---|
| Text / Markdown | Run in §2.3 (upload → material → contribution) | this journey |
| PDF | Run in §2.3 (LiteParse) | this journey |
| DOCX | Run in §2.3 (AnyDoc) | this journey |
| CSV / XLSX | Stored-value behavior proven at source level by the D2 lane; spreadsheets enter through `prepare_data_source` sheet selection (`structured_requires_analytics` refusal otherwise) | `products/ariadne/packages/ariadne-data/tests/test_spreadsheet_import.py` et al. |
| Database table | Run in §2.6 (SQLite `orders2.entries`) | this journey |
| S3 file/table routes | D3 adapter evidence; the required CI job runs the onboarding + S3-compatible suites against a real S3-compatible service | `integration/tests/lumio_s3_context.py`, `integration/tests/workspace_data_sources.py`, `docs/howto-s3-publish.md` |

No live S3 endpoint, live spreadsheet upload, or Entra tenant is exercised by
this journey; those rows are reuse and remain owner-bound where live.

## 4. What the W6 synthetic run proved (2026-11-07)

Built from the delivered base `61ec59bb` (`uv build` per package), installed
into isolated venvs (Python 3.14):

| Distribution | sha256 |
|---|---|
| `lumio_workspace-0.1.0` | `06bea9fec404af430d50d7c1860557310eef3d0c14b917566e06a32bf20a08a4` |
| `lumio_wiki-0.5.1` | `0ed867bfbb4821609d364edd2a715cc10e6db4e3e8a8ae94871924ff4dfc8caa` |
| `ariadne_data-0.7.0` | `66d9fa80083528c801cb817740cf7aeb0973ea6deac87967b48cd111aa5879bc` |

- **Packaging** (`scripts/verify_workspace_wheel.py`, base venv): wheel
  bound byte-for-byte to source and installation; both service templates
  shipped; base dependency set exact with Core gated behind the `analytics`
  extra; the analytics import boundary stays lazy without Core; the
  `lumio-workspace` entry point intact.
- **Lumio-only service without Core** (base venv; console-script boot on
  loopback plus a synthetic local TLS boundary — self-signed uvicorn TLS, a
  harness stand-in, **not** the owner private-HTTPS qualification): §2.2–§2.5
  complete, 37 recorded steps — oracles 1 and 2, the retry recovery and all
  listed refusals, including both honest analytics refusals.
- **Analytics pair** (pair venv; same TLS harness): §2.6 complete, 18
  recorded steps — both browser approvals, bounded profiling, combined
  review with visible filter expression, publication, and the governed
  pinned query returning exactly the hand-worked 20.
- Client build for the disclosure guard is covered by the required
  `workspace` CI job (installed Pi runtime + `bun test`); the client itself
  is unchanged by W6.

The orchestration transcripts and per-step evidence JSON live in the W6 run
record (thread storage), not in this repository.

## 5. Reproducing

Follow [`docs/howto-shared-workspace.md`](../../docs/howto-shared-workspace.md)
§§1–8 with the §1 fixtures above; the wheel-packaging half is
`uv build --package lumio-workspace --wheel` plus
`packages/lumio-workspace/scripts/verify_workspace_wheel.py` in a fresh venv
containing only the built workspace and SDK wheels. The two-human legs need
the owner-bound prerequisites in the status table — do not substitute one
agent for the two people and report a pass.
