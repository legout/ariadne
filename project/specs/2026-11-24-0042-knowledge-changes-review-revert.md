# Specification 0042: Knowledge changes, `unreviewed`, `review`/`revert`, workspace tiers (B3)

**Status:** proposed, revision 4, 2026-11-24. Not approved. Review trail: r1 fix-first (six
findings), r2 delta recheck fix-first (six findings), r3 independent full check fix-first
(one P1, two P2, four notes; `~/.local/state/ariadne-runs/s0042-review/review-r3.md`),
r4 incorporates them. No further reviewer round has run. Approval authorizes the joint
B3 + C plan and supervised execution in one isolated candidate; integration and
publication still need the owner. This is the B3 part of sub-spec B of the
[approved umbrella spec 0037 r2](2026-11-18-0037-simple-ariadne.md). It was split out of
[spec 0040 r3](2026-11-22-0040-one-cli-simple-governance.md) ("B3 in eigene spätere
Spec") and lands in the same candidate as
[spec 0041](2026-11-24-0041-automatic-authoring.md) (owner decision 2026-11-24, "B3 mit C
laden", one candidate).

**Owner decisions (Pi conversation 2026-11-24):**

- **Classification by binding.** A change is tier K when it touches only knowledge pages
  that nothing binds as a required Policy or computation, and no other file.
- **Unbound knowledge floats**, read from the Served Knowledge Revision (§3.4).
- **`review` selects or takes all.** `ariadne review [PAGE…]`, TTY, no MCP tool. This
  resolves the open B decision of 0037 §8.
- **Workspace: tier K and review only.** The workspace serves the same tiers and
  markers; its browser review publishes and countersigns knowledge changes. A browser
  approval of calculation drafts stays with the W-track (#89, #90).
- **Publication authority:** one standing, revocable **publication grant** per project,
  given by the operator on a TTY. `publish` and `revert` run under it; agents may run
  them. Every countersignature stays a human act (§4.1.2).
- **Bounded companion deltas:** tier K includes exactly the deltas the native writer
  produces for the pages of the batch, for example a document's registered original
  (§3.3).
- **Served knowledge version:** ordinary pages are read from the version in Ariadne's
  served record, never from Lumio's own `current` (§3.4–3.5).
- **MCP `save_example`:** it publishes immediately only from the operator's local
  `ariadne serve` under the grant; every other deployment and the workspace submit a
  pending contribution (§4.5).
- **First knowledge publication:** in a project without a served record, the first
  `publish` asks on the TTY for exactly what it will serve (§4.1.3).
- **Stale `approved` (r4):** `publish` demotes a changed page without a countersignature
  match to Lifecycle `review`; the file never claims `approved` that the record does not
  hold (§4.1.4).
- **Remote MCP (r4):** only stdio and loopback `--http` of the operator are local;
  `--http-container` and every other deployment submit pending (§4.5).
- **Knowledge-stale drafts (r4):** `validate` and `approve` rebase a knowledge-stale
  draft automatically when its changes are disjoint from the publications since its base;
  an overlap refuses (§5.2).

**Review resolutions (r1 → r2):**

1. A raw Lumio `current` could serve ordinary pages of a failed calculation approval
   → the served record names the knowledge revision; whole-difference rule (§3.4, §3.5).
2. An older calculation draft could roll back published knowledge → knowledge-stale
   drafts, `draft rebase` onto the knowledge head (§5).
3. A "Markdown only" rule excluded documents, Examples and removals → page changes and
   recomputed companion deltas defined separately (§3.3).
4. Publication authority was conflated with countersignature → the publication grant and
   an explicit Lumio ADR amendment (§4.1.2, §9).
5. AC14 contradicted the execution-identity check → the real upgrade path (§8.24).
6. The countersignature was not bound to a unique identity → content without Lifecycle
   plus source bindings (§4.2.6).

**Review resolutions (r2 → r3):**

1. The commit and recovery contract was open → one commit point (the served record), a
   recovery journal bound to an exact candidate, authority and predecessor, and readers
   that see only the committed record (§3.5).
2. The publication scope was contradictory → unnamed `publish` checks the whole working
   tree, a named selection is an exact overlay, producers never carry other pages (§4.1).
3. The knowledge baseline was missing at the approval point → the knowledge revision is
   pinned in validation, consent and activation (§5.3).
4. MCP `save_example` had no unambiguous route → regulated per transport (§4.5).
5. The status rule contradicted the countersignature identity → status is derived from
   the record only; a binding-only change is an edit (§3.3, §4.2.6).
6. A draft pin could hide floating content → classification uses release and draft
   bindings, reading uses the release's only (§3.2).

**Review resolutions (r3 → r4):**

1. (P1) A page left at `approved` after an edit could not be published → `publish`
   demotes instead of refusing; `revert` writes `approved` (§4.1.4, §4.3.1).
2. (P2) "Knowledge head" was undefined → it is the Content Repository revision of the
   record's `knowledge_revision`; commits beyond it are unserved knowledge (§3.4.4–5).
3. (P2) `save_example` without a served record, and `--http-container`, were unassigned
   → pending in both cases (§4.1.2–3, §4.5).
4. Notes: a journal for a candidate the record already names is removed; the first
   publication's journal records "no record"; the order is commit → journal → activation;
   Git-ignored paths are not part of the working tree; stale drafts rebase automatically
   when disjoint (§3.5, §4.1.1, §5.2).

**Evidence:**

- `lumio_context.py`: `open_context(manifest)` opens the Published Version named in the
  Bound Release manifest; `verify_release` compares the pinned association and the
  **execution identity**, which hashes the installed Ariadne and Lumio code
  (`execution_identity`); `publish_and_verify` publishes natively and reports
  `integrated_activated: False` before Core activation.
- `admission.py`: the served record (`.ariadne/current.json`) is published atomically
  after the snapshot; an interrupted transition is reconciled, never guessed.
- `lumio_wiki/git_authoring.py`: `publish_revision` refuses without a confirmed review
  digest (Lumio's separate Publication Admission) and captures a full Git revision;
  `remove_page_in_worktree` repairs dependents, the Control File and the Source
  Reference Manifest.
- `lumio_wiki/okf.py`: Lifecycle `approved` is exported as OKF status `stable`, so a
  stale `approved` in a page would overstate its review state outside Ariadne.
- `knowledge/.lumio-authoring.yaml`: `sources` and `bindings` tie originals to pages.
- Lumio `CONTEXT.md`: Compiled Page **Lifecycle** (`draft`, `review`, `approved`,
  `deprecated`), **Visibility**, immutable **Published Version**, **Page Removal**.
- Lumio [ADR-0029](../../products/lumio/project/adr/0029-git-native-knowledge-authoring.md):
  separate, explicit Publication Admission of the exact revision, source, destination
  and predecessor.
- `serve.py`: `--http` (loopback) and `--http-container` (bind in a private container
  network behind a bearer token).
- `lumio-workspace/app.py`: `/review/{task_id}` with role `review`; `ReviewService.decide`
  takes one digest and one of `approve`, `reject`, `request_changes`.
- Spec 0035 AC6, AC9, AC11, AC12, AC14; shared ADR-0029 ("no moving-latest fallback");
  spec 0040 §2, §3.3, §3.4, §3.5, §3.7, §7 and AC19; spec 0041 §3.4.7, §4.1, §9.

## 1. Goal

A corrected guide is served the moment it validates, and every answer says when it
rests on text no human has countersigned:

```text
ariadne publish --grant               # once per project, on a TTY
$EDITOR knowledge/guides/returns.md   # or: ariadne add notes.md, ariadne save-example
ariadne publish                       # validate, publish, serve as unreviewed
ariadne query retail::orders.sum_amount  # governed:true; unreviewed: [] (bound pages only)
ariadne context "how are returns booked" # the guide, with unreviewed: [<page id>]
ariadne review knowledge/guides/returns.md   # human countersignature (TTY)
ariadne revert knowledge/guides/returns.md   # back to the last countersigned text
```

A change to a required Policy, a metric page, a model, a binding or a source stays what
B1 made it: a draft that is served only through `approve`.

## 2. Non-goals

- **No change to governed calculation.** Tier K cannot add, edit or remove a metric, a
  binding, a source, a contract, the selector, `graph.yml` or a required Policy.
- **No browser approval of calculation drafts.** The workspace approves nothing in this
  spec; its existing source-grant route (0040 §3.7) is unchanged.
- **No second review system.** One countersignature record, in Git, reused by `review`,
  `approve` and the workspace reviewer.
- **No new MCP tools.** Of the existing tools only `save_example` publishes, and only as
  §4.5 says. Nothing reviews or reverts through MCP.
- **No weakening of scope, retention, the execution-identity check or required-Context
  refusal** (0035, ADR-0029, 0040).

## 3. Change tiers and served knowledge

### 3.1 Two kinds of change

| Kind | Served by | Covers |
| --- | --- | --- |
| **Knowledge change** (tier K) | `publish`, immediately after validation, `unreviewed` until countersigned | ordinary knowledge pages: guides, documents, Answer Examples, and the content of Dataset/Table pages |
| **Calculation change** (tier C) | the active draft and a calculation `approve` (0040 §3.3–3.4) | everything else |

### 3.2 Which pages are pinned

**Served pins.** A page is **pinned in the served state** when the served release uses it
under its authority:

1. a Policy page in the Policy Closure of any metric of the served release (a **required
   Policy**);
2. a metric page or Computation page of a metric of the served release;
3. a structured Reference page that the served integration resolves (`resolve_term`,
   shared-scope Evidence), because it belongs to the pinned integrated view (0035 AC14).

**Classification pins.** For classifying a change (§3.3), the same three kinds count for
the **served release and the active draft together**. A draft that starts requiring a page
protects that page from `publish` at once.

**Reading follows served pins only.** An open draft never changes which pages readers get
from the release and which float. Every page under `knowledge/` that is not pinned in the
served state is an **ordinary knowledge page** for readers. A Policy page that no closure
requires is ordinary. The classification is **computed by Ariadne from the same binding
inventories validation uses**; an author never declares a change "knowledge only".

### 3.3 What a knowledge change consists of

A change is a **knowledge change** if and only if it consists only of:

1. **page changes** on pages that are not pinned for classification (§3.2):
   - an **addition**;
   - an **edit** of the page's content **or source bindings** where, on a profile page
     (Dataset, Table, Answer Example), the profile kind, identity, dataset and metric
     links, and Visibility did not change. A new page has no previous state, so this
     applies to edits only;
   - a **removal** whose native repairs (dependent Relationships, exactly-resolved body
     links, the Hot Index pin, the Control File and the Source Reference Manifest binding
     of the removed Entity) touch no page pinned for classification and change no other
     page's content. A dependent page that only loses a reference is a **companion
     change** and is listed;
2. **companion deltas** that the native writer produces for exactly these pages and
   nothing else: the page's Source/Entity binding and original registration in
   `knowledge/.lumio-authoring.yaml` and the Source Reference Manifest, the retained
   original, and the publication manifest entry.

For classification, a page's content is all of it, Lifecycle included; only the
countersignature identity (§4.2.6) leaves the Lifecycle out.

Ariadne **recomputes the writer's deltas from the page batch and compares**. Any
difference, and any change to a control file without a page in the batch
(`knowledge/lumio.yaml`, categories, ontology, visibility defaults), is a **calculation
change**. Hand edits to control files are never tier K.

A calculation change reaches the served state only through `draft edit` and `approve`,
exactly as in B1.

### 3.4 The served record and floating reads

1. **One served record.** `.ariadne/current.json` (project-locked, published atomically,
   local state) is the only place readers look. B3 adds one field to it:
   **`knowledge_revision`**, the Published Version that ordinary pages are served from.
   It is `null` until the first publication that accounts for knowledge.
2. **Pinned pages** are read from the Published Version bound by the served release, as
   today. `verify_release`, the execution-identity check and the refusal before SQL on a
   missing required Context are unchanged.
3. **Ordinary pages** are read from the record's `knowledge_revision`, which every result
   reports as `knowledge_revision`.
4. **Knowledge head.** The **knowledge head** is the Content Repository revision captured
   by the record's `knowledge_revision`. A named overlay (§4.1.1), `draft rebase` (§5.2)
   and the draft's knowledge pin (§5.3) refer to it — never to the Git HEAD or to the
   native `current`.
5. **Unserved knowledge.** Knowledge beyond the knowledge head that no route accounted
   for: a Content Repository commit on the knowledge history beyond the knowledge head
   (for example after a crash between commit and activation), or a native version beyond
   the record's `knowledge_revision` (for example the residue of a failed approval).
   `status` reports it as `knowledge_pending` ("published, not served"). It is never read
   and never a default input. Only an unnamed `publish`, which classifies the whole
   difference, or an `approve`, which displays it, accounts for it. Until then the named
   mode, the producers, `review` and `revert` refuse with `knowledge_pending`.
6. **Unavailable.** If `knowledge_revision` is `null`, or names a version that is neither
   the native current nor in its predecessor chain, ordinary pages are
   `knowledge: unavailable` and `status` names both versions. There is no fallback to
   another destination, to another version, or to a second source.
7. **Whole-difference rule.** Each route accounts for the complete difference between the
   version it publishes and the record's `knowledge_revision`: `publish` classifies it
   under §3.3, `review` and `revert` by construction, `approve` displays all of it in the
   summary the human approves. A version no route accounted for is therefore never
   served.
8. **`unreviewed`** lists the page IDs among the returned or attached pages that have no
   countersignature for their exact published content and source bindings (§4.2.6). It
   appears on `query`, `detail`, `context`, `sql`, `search`, `page` and discovery, and is
   `[]` when nothing unreviewed was used.
9. Governed numbers never depend on ordinary pages (0035 AC9). A governed answer
   therefore normally carries `unreviewed: []`; the list is non-empty only when the
   answer attaches an ordinary page.

### 3.5 One commit point, and recovery

1. **Sequence of every publication route** (`publish`, `review`, `revert`, `approve`):
   1. under the project lock, create the candidate — the Content Repository commit of
      the batch and its companion deltas — and write a **recovery journal**
      (`.ariadne/knowledge_pending.json`) naming the route, the exact candidate, the
      authority it rests on (§4.1.2), the expected native predecessor and the digest of
      the served record it read (`none` for a first publication);
   2. activate natively (compare-and-set on the native current);
   3. rewrite the served record **once**, atomically: `approve` with the new release
      binding and the `knowledge_revision` it published, the other routes with the
      unchanged release binding and the new `knowledge_revision`;
   4. remove the journal.
2. **Readers see the committed record only.** While a journal exists, calculation
   readers get the record's release and knowledge readers the record's
   `knowledge_revision`. No reader ever observes a new release with old knowledge, or
   the reverse.
3. **Outcomes.** A refusal before the journal publishes nothing. A failure after the
   native activation and before the record rewrite is **`recovery pending`**: the version
   is published but not served, and the command reports exactly that. It is not reported
   as "publishes nothing".
4. **Recovery.** The next `publish`, `review`, `revert` or `approve` recovers first, and
   only ever the journal's own candidate. If the served record already names the
   journal's candidate, the journal is simply removed. Otherwise three checks must hold:
   - the served record has the digest the journal read (or is absent, when the journal
     says `none`);
   - the native current is the journal's candidate version;
   - the journal's authority still holds (grant not revoked, approval record present,
     reviewer decision recorded).
   When all hold, the record is rewritten for that candidate and the journal removed.
5. **Stale journal.** If any check fails, the journal is never applied and never replaced
   by another native version. It is set aside under a timestamped name, reported, and its
   candidate stays unserved knowledge (§3.4.5) until an unnamed `publish` or an `approve`
   accounts for it.
6. **Order.** Ariadne never names a version in the record before its native activation
   succeeded.

## 4. Commands

| Command | Meaning |
| --- | --- |
| `publish [PATH…]` | §4.1: publish pending knowledge changes. Unnamed: every change Git reports. Named: exactly those pages. |
| `publish --grant` / `publish --revoke` | §4.1.2: give or revoke the project's publication grant (TTY). |
| `review [PAGE…]` | §4.2: countersign the named pages, or all unreviewed pages (TTY). |
| `revert <PAGE>` | §4.3: republish the last countersigned content of one page. |
| `status` | B1, extended: served release, pinned knowledge version, `knowledge_revision`, unserved knowledge, recovery state, unreviewed page IDs, grant state. |

Text by default, JSON with `--json` (0040 §3.1). All of them are CLI-only.

### 4.1 `ariadne publish`

1. **Scope.**
   - **Unnamed** `publish` examines **every change Git reports in the Content Repository**
     — tracked and untracked, excluding ignored paths such as `.ariadne/`. Anything that
     is not a knowledge change (§3.3) — a model, a binding, a control file, any non-page
     path — refuses the **whole** publication with `calculation_change` and names the
     paths. Nothing is published partially.
   - **Named** `publish PATH…` publishes **exactly** the named pages as an overlay on the
     knowledge head (§3.4.4), with their recomputed companion deltas. Other pending
     changes are neither published nor committed; the report lists them as not selected.
   - `ariadne add <document>` and `ariadne save-example` (0041 §3.4.7, §4.1) always use
     the named mode for the page they produced. They never carry another pending or
     unserved page.
   - While unserved knowledge exists (§3.4.5), only an unnamed `publish` and `approve`
     may publish; everything else refuses with `knowledge_pending` and names it.
2. **Publication grant.** Publishing is an authority of its own, separate from any later
   countersignature. The operator gives it once per project with `ariadne publish --grant`
   on a TTY; it is recorded in the private profile with the resolved Git identity and the
   time, and `--revoke` removes it. Without it, `publish` and `revert` refuse with
   `no_publication_grant` and name the command. The grant alone never publishes a
   project's first knowledge (§4.1.3). In both cases `add <document>` and `save-example`
   leave their page pending in the working tree and say so. No shipped agent interface
   changes the grant. Every publication record names the grant it rests on. This record
   is the Publication Admission of Lumio ADR-0029 for an ordinary page of an integrated
   project — exact revision (the committed batch), source (the Content Repository),
   destination (the configured one) and predecessor (the compare-and-set) — through the
   explicit amendment in §9.
3. **First publication.** In a project without a served record, the first `publish`
   requires a TTY, shows exactly the pages it will serve, and asks once. It creates the
   served record with no release and the first `knowledge_revision`. From then on the
   grant is sufficient. The producers and MCP `save_example` have no TTY for this: they
   leave the page pending and name `ariadne publish`. (Spec 0035 AC11: the first knowledge
   contribution is published only after explicit human approval.)
4. **Lifecycle.** `publish` never rewrites a page's content. It corrects one field to keep
   the file truthful: a changed page that carries Lifecycle `approved` without a
   countersignature match — whether the `approved` was left standing after an edit or
   newly written by the author — is **demoted** to `review`, in the publication commit and
   in the working tree, and the report lists the demotion. Status is derived from the
   record only (§4.2.6), so the field can never forge a countersignature; Lumio exports
   `approved` as `stable`, so it must not overstate.
5. **Validation**, all offline over the Content Repository, in this order:
   - Lumio's native validation of the affected batch, including the companion deltas;
   - for a profile page, the structural checks admission applies to that page kind
     against the served or draft model;
   - authored Visibility within the project's Visibility Scope;
   - for a document, the required original retention (0035: it holds for knowledge-only
     work too).
6. **Publication** follows §3.5: under the project lock the batch commit and the journal,
   native publication with the native current as the compare-and-set, one record rewrite,
   journal removed. A concurrent publication makes the loser refuse as stale and re-read.
7. **Report.** For every published page the **status derived from the countersignature
   record** (§4.2.6): `unreviewed: true` when no record matches, otherwise reviewed. Plus
   demotions, companion changes, removals, pages carried along from unserved knowledge
   (unnamed mode only), the new `knowledge_revision`, the grant used, and the `review`
   command for each unreviewed page.
8. **Effect on the rest.** The served release, its digest, its bindings and every source
   grant are unchanged. The active draft becomes knowledge-stale (§5).
9. **Failure.** §3.5.3–5.

### 4.2 `ariadne review`

1. Requires a TTY on stdin and stdout, like `approve` (0040 §3.5): an operator-consent
   convention, not authentication. With no TTY it refuses and changes nothing.
2. Without `PAGE…`, the candidates are all unreviewed pages of the served knowledge
   version; with `PAGE…`, exactly those pages. An already countersigned page is reported
   as unchanged. No candidates: nothing happens.
3. For each candidate it prints the page ID, the diff of the content against its last
   countersigned content (or `new page`), and the source bindings or their change. Then
   it asks **one** question for the whole list.
4. On "yes" it publishes one new Published Version (§3.5) in which exactly those pages
   carry Lifecycle `approved`, and records for each: page ID, the countersignature
   identity of §4.2.6, the resolved Git identity as attribution label, and the time. If a
   candidate changed between display and "yes", activation refuses and nothing changes
   (0040 §3.3.5).
5. On "no" nothing changes. An interrupt leaves the previous state.
6. **Countersignature identity.** A countersignature covers (a) the page's canonical
   content **without the Lifecycle field**, so the system's own `review → approved`
   transition and the demotion of §4.1.4 do not alter what was reviewed, and (b) the
   page's **source binding identity**: the digest of its Source/Entity bindings as the
   native writer records them. **Reviewed or unreviewed is derived only from a match on
   (page ID, a, b)** — by `publish`, `revert`, `review` and every reader. Identical
   Markdown that points at a different original is not covered.
7. **The record** lives in Git with the publication that carries it. Whether it is a
   commit marker or one small record file is decided in the plan; there is exactly one
   authoritative record and it is never rewritten.
8. `approve` countersigns **only the pages the approved draft changed** (§5.5).

### 4.3 `ariadne revert <PAGE>`

1. Republishes the content **and the source bindings** of the page's last countersigned
   publication with Lifecycle `approved`, through the route of §4.1 and under the same
   grant. Because both equal the countersignature, the page is derived as reviewed. It
   also restores a removed page.
2. The restored page must satisfy the **current** rules: it is not pinned for
   classification, its Visibility is within the Visibility Scope, and its original is
   still retained and available; otherwise `revert` refuses and names the rule (for
   example `original_unavailable`).
3. A page that was never countersigned refuses with `never_reviewed` and names `review`
   (accept the current text) and `publish` (serve a hand-written replacement).
4. It restores only countersigned bytes, so it cannot serve anything a human has not
   seen. The packaged skill lists it as a command agents may run; `review` and `approve`
   are not.
5. A page pinned for classification refuses: its content changes only through the draft.

### 4.4 Removals

Removing a page not pinned for classification is a knowledge change when its native
repairs stay within §3.3.1: `publish` lists it and nothing carries a marker, because no
page remains. `revert` restores the last countersigned version. Removing a pinned page,
or a removal whose repairs touch one, is a calculation change.

### 4.5 MCP `save_example`, per deployment

1. **Local** is the operator's own `ariadne serve` reached over stdio or loopback `--http`,
   running with the project's private profile. In a project with a served record and a
   grant, and without unserved knowledge, `save_example` publishes its page immediately
   through the named mode of §4.1, served `unreviewed`. Without a served record (the
   first publication needs a TTY, §4.1.3), without a grant, or with unserved knowledge,
   it leaves the page pending and returns that outcome, naming `ariadne publish`.
2. **Every other deployment is remote**: `--http-container` (bound in a private container
   network behind a bearer token), any other non-loopback `--http`, and the
   workspace-hosted server. There `save_example` submits a **pending contribution**. It is
   invisible to Readers until the browser review publishes it (§6.2). Token holders are
   configured clients, not processes under the operator's account (0040 §3.5.2).
3. No other MCP tool publishes. Nothing reviews or reverts through MCP.

## 5. Coexistence with calculation drafts

1. **Knowledge-stale drafts.** A knowledge publication advances the knowledge head. An
   active draft based on an earlier knowledge head is **knowledge-stale**. `preview` is
   unaffected: it compiles calculations and reads no ordinary page for its numbers.
2. **Automatic rebase when disjoint.** `validate` and `approve` bring a knowledge-stale
   draft knowledge-current first. When the draft's changes and the knowledge publications
   since its base are disjoint, they rebase the draft onto the knowledge head
   automatically, record the new base, invalidate any earlier validation and continue
   with the rebased candidate: validation runs on it and the consent display shows it.
   When they overlap, both refuse `stale_knowledge` and name the page; `draft rebase`
   aborts the same way, and the draft and its branch stay exactly as before. Conflicts are
   never auto-resolved.
3. **The knowledge revision is pinned like everything else.** The draft slot records the
   `knowledge_revision` it was created or rebased on (0040 §3.3.1). `validate`, the
   consent display and the activation all name it. Once displayed, a change of the served
   record's `knowledge_revision` makes activation refuse, and nothing changes (0040
   §3.3.5). No rebase and no recomputed consent happen after the display.
4. **Approval cannot roll back published knowledge.** `approve` publishes only a
   knowledge-current draft, so the snapshot it publishes contains every published
   knowledge change.
5. **`approve` countersigns only the pages the approved draft changed**, as shown in its
   summary. Ordinary pages carried along keep their status; the summary lists the
   unreviewed ones as information.
6. On success, the approval's single record rewrite (§3.5) carries both the new release
   binding and the `knowledge_revision` it published.

## 6. Workspace

1. **Same tiers, same markers.** The workspace resolves ordinary pages through the
   served record's `knowledge_revision` of the same project and pinned pages through the
   release's version (§3.4), under the workspace audience scope. Its pages and API
   responses show `unreviewed`, `knowledge_revision`, unserved knowledge and recovery
   state. Scope is applied before lookup on floating pages exactly as on pinned ones.
2. **Browser review is the human channel for remote knowledge changes.** A contribution
   is not visible to Readers while it is pending. The existing `/review/{task_id}` route
   (role `review`, one digest, one decision) runs the publication route of §3.5 for
   **exactly the reviewed change** on `approve`, with the reviewer's authenticated
   decision as the per-publication human confirmation (no standing grant is needed), and
   countersigns with the reviewer's identity. The reviewer sees what `ariadne review`
   shows: the content diff and the source bindings. `reject` and `request_changes`
   publish nothing. There is no unreviewed phase for a workspace contribution.
3. **No calculation approval.** The workspace offers no route that approves, discards or
   rebases a calculation draft. Its source-grant route stays as B1 cut it over.
4. **Retrieval caches are version-bound.** A retrieval cache prepared for one knowledge
   version (for example the optional BM25 cache) is keyed by the served record's
   `knowledge_revision` and never used silently for another.

## 7. Invariants

1. **Tier K cannot change a calculation.** A knowledge publication leaves the served
   release, its digest, bindings, sources and grants byte-identical.
2. **Nothing invalid or unclassified is served.** Every version the served record names
   was accounted for as a whole (§3.4.7), and `publish` is atomic.
3. **One commit point.** Readers see exactly one committed record; no reader observes a
   new release with old knowledge or the reverse (§3.5.2).
4. **Recovery is exact.** A journal is applied only to its own candidate, with its
   recorded authority and predecessor, and at most once; a stale journal is set aside,
   never replaced.
5. **Publication authority is the operator's.** It is the standing grant, the first
   publication's TTY confirmation, a per-publication human decision (`review`, `approve`,
   the workspace reviewer), or nothing.
6. **Only humans countersign.** No shipped agent interface produces a countersignature.
7. **`unreviewed` is exact.** It is derived only from a countersignature match on content
   without Lifecycle plus source bindings; any later change to either makes a page
   unreviewed again.
8. **The Lifecycle field never overstates.** A published page carries `approved` only
   when the record holds a matching countersignature.
9. **Bound Context stays pinned and strict.** Required Policies, metric and Computation
   pages and structured References are read from the release's version; refusal before SQL
   and the execution-identity check are unchanged.
10. **Floating reads are disclosed.** Every result names the `knowledge_revision` it read
    ordinary pages from, unserved knowledge, or that none was available.
11. **No draft rolls back knowledge.** Approval publishes only a knowledge-current draft
    and refuses a knowledge revision that changed since display.
12. **Scope and retention are not weakened.** Visibility outside the Visibility Scope
    refuses; hidden pages are indistinguishable from absent ones on every path; document
    originals are retained.
13. **Reproducible.** The served state is reproducible from Git, the recorded approvals,
    the recorded countersignatures and the recorded grants.

## 8. Acceptance examples

Fixture: the 0041 §6.1 project, admitted with `retail::orders.sum_amount`, one required
Policy page `knowledge/policies/recognized-revenue.md`, one ordinary guide
`knowledge/guides/returns.md`.

1. **Publish.** After `publish --grant` (TTY) and editing the guide, `ariadne publish`
   reports it with `unreviewed: true`. `ariadne page knowledge/guides/returns.md` returns
   the new text. `status --json` shows the served revision and release digest unchanged
   and a new `knowledge_revision`. `query retail::orders.sum_amount` returns **200**,
   `governed: true`, `unreviewed: []`. `ariadne context "how are returns booked"`
   returns the guide with `unreviewed: [<id>]`.
2. **Re-marked.** After `review` the file carries `approved`. A second edit and `publish`
   demote it to `review` and serve it unreviewed; the report lists the demotion. A
   changed source binding alone is an edit and does too.
3. **Review one.** `ariadne review knowledge/guides/returns.md` (TTY "yes") removes the
   marker for that page only; a second unreviewed page keeps its marker. The record
   carries the page ID, the countersignature identity and the Git identity. A second run
   reports nothing to review. Without a TTY it refuses and changes nothing.
4. **Review all.** `ariadne review` offers every unreviewed page and countersigns all of
   them on "yes".
5. **Lifecycle-neutral countersignature.** After `review`, a publication that changes
   only the page's Lifecycle leaves it reviewed; one that changes content or bindings
   makes it unreviewed.
6. **Revert.** After a further unreviewed edit, `ariadne revert knowledge/guides/returns.md`
   serves the last countersigned text with Lifecycle `approved` and is reported reviewed.
   On a never-countersigned page it refuses `never_reviewed`; on a page whose original is
   no longer retained it refuses `original_unavailable`.
7. **Pinned page.** Editing the required Policy text: `ariadne publish` refuses
   `calculation_change` and names `draft edit` and `approve`. After the draft route and a
   calculation `approve`, the new text is served with no marker and a changed release
   digest.
8. **Unnamed scope.** A working tree with the edited guide **and** an edited
   `semantic_layer/models/retail.yml`: unnamed `publish` refuses as a whole with
   `calculation_change`, names both paths and publishes nothing. A stray file under the
   ignored `.ariadne/` does not count.
9. **Named scope.** `ariadne publish knowledge/guides/returns.md` in that working tree
   publishes the guide only; the model file stays uncommitted and is listed as not
   selected. With a commit beyond the knowledge head it refuses `knowledge_pending`.
10. **Profile page.** Editing a Dataset page's description publishes. Changing its
    identity, its dataset link or its Visibility refuses `calculation_change`.
11. **Companion deltas.** `ariadne add notes.md` publishes the page together with its
    registered original and binding. A hand edit to `knowledge/.lumio-authoring.yaml`
    that the writer did not produce for a page of the batch refuses
    `calculation_change`. A removal whose repairs touch only unpinned dependents
    publishes and lists them; one that touches a pinned page refuses.
12. **Invalid page.** A guide with a duplicate alias is refused; the previous Published
    Version is still current and `status` is unchanged.
13. **Stale or forged `approved`.** A changed guide that still carries `approved`, or
    whose author wrote `approved` without a record, is demoted to `review`, served
    unreviewed and listed.
14. **No grant, no first publication.** Without the grant, `publish` refuses
    `no_publication_grant` and `save-example` leaves its page pending; `publish --grant`
    without a TTY refuses; `--revoke` makes the next `publish` refuse again. In a project
    without a served record, `save-example` and MCP `save_example` leave their page
    pending even with the grant; the report names `publish`.
15. **First publication.** In a project without a served record, `publish` asks on the
    TTY, lists exactly the pages, and creates the record with no release. Without a TTY
    it refuses. The second `publish` runs under the grant.
16. **Unserved knowledge.** With a Content Repository commit or a native version beyond
    the knowledge head that no route accounted for, `context` serves the record's version
    and `status` reports `knowledge_pending`. The named mode, the producers, `review` and
    `revert` refuse `knowledge_pending`. An unnamed `publish` classifies the whole
    difference: it refuses `calculation_change` when that knowledge contains a
    pinned-page change, and serves its ordinary pages as unreviewed otherwise, listing
    them.
17. **Recovery pending.** When the record rewrite fails after the native activation,
    `publish` reports "published, not served; recovery pending". Readers still get the
    previous record. The next operation rewrites the record for exactly that candidate. A
    journal whose candidate the record already names is removed. With a different native
    current, a changed record or a revoked grant, the journal is set aside and nothing is
    served from it.
18. **Knowledge-stale draft.** With an open draft that changed other files, publishing a
    guide makes it knowledge-stale; `validate` and `approve` rebase it automatically and
    continue with the rebased candidate. A draft that edited the same guide refuses
    `stale_knowledge`, names the page and changes nothing.
19. **Edit during the prompt.** A knowledge publication between the approval display and
    "yes" makes activation refuse; nothing changes, the release stays as before.
20. **After rebase and approve**, the published guide is still served, and only the pages
    the draft changed are countersigned. The record rewrite carries the new release and
    the new `knowledge_revision` together.
21. **Floating read unavailable.** With `knowledge_revision: null` or a version outside
    the native chain, `context` and `search` report `knowledge: unavailable`; `query`
    answers from its bound Context with `knowledge_revision: unavailable`; a missing
    required Policy still refuses before SQL.
22. **Draft pin is not a reader pin.** A draft that binds the guide as a required Policy
    makes `publish` of the guide refuse `calculation_change`, while readers keep getting
    the guide as ordinary until the approval.
23. **MCP `save_example`.** From the operator's local stdio or loopback server with a
    served record and a grant, the Example is served `unreviewed` at once. Without a
    grant, without a served record, or with unserved knowledge it is pending and
    reported. From `--http-container`, any other non-loopback `--http` deployment or the
    workspace it is a pending contribution, invisible until the reviewer's `approve`, then
    served reviewed with the reviewer as attribution.
24. **Upgrade.** A release admitted before B3, on the B3 build: `status` names the
    build-identity refusal and governed queries refuse before SQL, exactly as for any
    build change (0040 AC19). Ordinary knowledge is unavailable until a publication
    accounted for it. The normal path is unchanged: `migrate` if needed, draft,
    `validate`, `approve`; the approval writes the record with its `knowledge_revision`.
    The identity check is not loosened.
25. **Workspace.** A contributor's guide is invisible to Readers while pending. The
    reviewer's `approve` publishes exactly that change with no marker; `reject` publishes
    nothing. A contributor cannot reach the review route. No route approves a calculation
    draft.
26. **Scope.** A page authored with a Visibility outside the Visibility Scope is refused
    at `publish`. A restricted page is not returned to a caller outside that class by any
    path, floating or pinned.
27. **Unchanged.** The existing Policy Closure, `verify_release`, execution-identity,
    exact-revision and redaction tests pass untouched, with their existing independent
    oracles.

## 9. Artifact reconciliation

- **ADR-0034 "Knowledge changes are served unreviewed; the release pins bound pages"**
  is written as proposed
  ([file](../../products/ariadne/project/adr/0034-knowledge-tier-pinned-release.md)).
  It amends ADR-0026 and, for ordinary pages only, shared ADR-0029.
- **Lumio ADR-0029, explicit amendment at approval:** "In an Ariadne-integrated project,
  Publication Admission of ordinary knowledge pages may rest on the operator's standing,
  revocable publication grant recorded in the project's private profile and executed by
  Ariadne's `publish` and `revert`; each publication records the grant. Pinned pages and
  every countersigning publication (`review`, calculation approval, workspace reviewer
  decision) keep their per-publication explicit confirmation."
- **Amended clauses** (one-line headers, history kept):
  - shared ADR-0029 and spec 0035 AC6, AC14: "no moving-latest" and "advancing standalone
    publication does not change an active answer's Context" now hold for pinned pages
    only;
  - spec 0040 §2 ("served state changes only through `approve`"), §3.3 (the draft slot
    also pins the knowledge revision; a draft can be knowledge-stale and is rebased
    automatically when disjoint), §3.4.1 (a calculation approval covers pinned pages and
    every page edited through the draft), §3.4.2 (the approval's single commit point also
    carries the knowledge revision), §3.5 and §3.7 (workspace tiers);
  - spec 0019's `ariadne review` (the retired pre-admission walkthrough) is superseded;
    the name now means countersignature;
  - umbrella 0037 §4 B tier-K paragraph stands; §8's `review` question is resolved.
- **Spec 0041 at approval:** §3.4.7 and §4.1 name the publication grant, the pending
  outcome without it or without a served record, and §4.5's deployment rule for
  `save_example`, and drop their "via B3" wording.
- **At landing:** #89 and #90 get a note that the browser review of knowledge changes is
  delivered here; their remaining scope is the calculation approval and binary formats.
- **CONTEXT.md (Ariadne):** add *Knowledge Change*, *Calculation Change*, *Pinned Page*,
  *Ordinary Knowledge Page*, *Served Knowledge Revision*, *Knowledge Head*, *Publication
  Grant*, *Unreviewed Knowledge*, *Countersignature*; update *Answer Example*, *Git
  Review Admission* (→ Approval) and *Authoring Agent* (may `publish` and `revert` under
  the grant, never `review` or `approve`). **Lumio:** one note on *Published Version*
  (ordinary pages of an integrated project may be served unreviewed and under a standing
  grant).

## 10. Delivery and verification

- One candidate with spec 0041 (0041 §8): one plan, worktree, independent review and full
  CI gate, after B2.
- The workspace journey of §8.25 runs against the real workspace server over HTTPS with
  two identities, as the existing workspace journeys do.
- No Lumio release is required unless §11's first check fails.

## 11. Capture checkpoint

- **Vocabulary:** §9.
- **Decisions:** ADR-0034 and the Lumio ADR-0029 amendment.
- **Behavior:** §3–§7; acceptance examples §8.
- **Uncertainty (checked first in the plan):**
  1. whether native Lumio retrieval returns pages of every published Lifecycle from a
     Published Version; if it excludes some, B3 needs the one bounded Lumio change of
     including them for an integrated project, and a Lumio release before this candidate;
  2. the form of the single countersignature record (§4.2.7) and of the recovery journal
     (§3.5), and whether the approval journal of 0040 §3.4.2.5 can carry the knowledge
     candidate;
  3. exactly which files the native writer and the native removal touch for a page batch,
     so that §3.3.2's recomputed companion deltas are complete;
  4. the storage layout: where the publication commit lands relative to the Git HEAD so
     that a named overlay never includes commits beyond the knowledge head (§3.4.4–5),
     B1's final draft-slot and branch layout for the automatic rebase of §5.2, and where
     the commit of a failed approval ends up;
  5. that the workspace's version-bound retrieval caches are keyed by the served record's
     `knowledge_revision` (§6.4);
  6. what the workspace's `approve` does for a contribution task today (#88/#89), so §6.2
     reuses it rather than building a second path.

Planning Contract version 1; installed provenance `unknown`.
