# How to run a local Git sync on a Lumio-bound project

Use this guide when an integrated project (`context_integration.yaml`, one
shared Content Commit) receives new commits through ordinary local Git. It is
a task guide: for the binding model see the [bound releases reference](
../reference/lumio-bound-releases.md), and for the base authoring flow see
[How to author a Git-managed project](git-authoring.md).

The invariant is: **Git sync never activates a release.** Fetching, merging or
checking out a commit — including the commit an admission was previewed
against — never changes what is served. Only the operator's explicit overall
admission activates a Bound Release, and a served manifest is never mutated.

## First clone

A new machine starts with an ordinary clone of the project repository:

```bash
git clone <remote> project
cd project
```

The clone carries the shared Content Commit, but not any local approval or
admission: source approvals, proposals and the active admission descriptor
live in the project's local `.ariadne` state and do not travel with Git. Where
they are absent, start the native chain first — `ariadne-authoring start`,
source approval, candidate edits, validation and review — as described in
[How to author a Git-managed project](git-authoring.md). Nothing in this
guide replaces that chain.

## Inspect before and after a sync

`ariadne status` is read-only and source-free; it never fetches, merges,
measures or activates anything:

```bash
ariadne status --project .
ariadne status --json --project .
```

For an integrated project the report shows the local HEAD of your checkout
separately from the verified admitted release: the Bound Release digest, its
exact immutable Published Version and its declared supported operations come
only from the verified admission descriptor. An unborn HEAD is `unknown`,
never an invented revision. After a plain sync you will typically see the
local HEAD differ from the admitted revision — that is expected transport
state, not an error: already-admitted serving and already-open sessions stay
pinned to the admitted release.

## Sync the ordinary way

There is no sync wrapper and no second admission command. Use Git itself,
fast-forward only, against your project remote:

```bash
git fetch <remote> <branch>
git merge --ff-only FETCH_HEAD
```

A shared Content Commit moves knowledge and analytics inputs together; do not
hand-edit served artifacts. The active admission descriptor and already-open
sessions are untouched by the sync.

## Admit the synced revision

When the operator decides the new revision should be served, it goes through
the same native chain as any release — review, reconcile, validate, confirm:

1. Fast-forward the proposal worktree to the human-created new HEAD, then
   record that clean HEAD (the command refuses stale revisions, dirty trees
   and automatic merges):

```bash
ariadne-authoring reconcile --project . --proposal ID \
    --expected-revision CURRENT --revision NEW
```

1. If the candidate declares new sources, approve the resolved source
   identity first (human-only):

```bash
ariadne-authoring approve-sources --project . --proposal ID \
    --revision REV --source-digest DIGEST
```

1. Validate and review the current revision, then preview and confirm the
   overall admission. An integrated release needs the exact context flags:
   the final validation-returned revision, the digest `ariadne-authoring
   review` returned, the previous admitted revision (`none` only for the
   very first release), and the local publication target. The first
   invocation previews the composite and displays its overall digest; the
   second activates with exactly that digest. Repeat any `--visibility` and
   `--confirm-mapping` selections on both invocations exactly as reviewed:

```bash
ariadne-authoring validate --project . --proposal ID --expected-revision REV
ariadne-authoring review --project . --proposal ID
ariadne-admit --project . --proposal ID --revision REV \
    --reviewed-digest DIGEST --context-destination PUBLISHED \
    --context-expected-current PREVIOUS
ariadne-admit --project . --proposal ID --revision REV \
    --reviewed-digest DIGEST --context-destination PUBLISHED \
    --context-expected-current PREVIOUS --overall-digest COMPOSITE \
    --confirm
```

A changed SDK/Core build or support set needs this fresh validation and a new
matching admission; public package versions alone never qualify one. Existing
releases are never upgraded in place.

## Verify from the pinned release

After activation, discovery is source-free and reads the newly admitted
release; a session opened before the activation keeps serving the release it
pinned:

```bash
ariadne search-context "<query>" --project .
ariadne list-metrics --project .
```

`get_metric` and `query_metrics` calculate against approved sources through
the admitted binding — the status report is metadata-only and never a
substitute for that governed execution.
