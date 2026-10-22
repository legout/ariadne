# Optional task guide: publish immutable versions to S3

This is the optional object-storage half of the onboarding journey. The
canonical local journey ([`docs/quickstart.md`](quickstart.md)) needs none of
it: no object store, no Docker, no model provider. Pick this guide up when you
want to publish **immutable Published Versions** to S3-compatible object
storage and bind read-only Reader projects to them.

Everything here uses the same exact-revision admission gate as local
publication: a commit or passing validation never publishes, and only the
explicit `--confirm` of the displayed review — after operator authorization —
does. The guide continues the quickstart's Maintainer project
(`helpdesk-project` with `./kb`, its adopted `.lumio-authoring.yaml`, and
`LUMIO_SOURCE_REGISTRY` exported).

Install the S3 extra first, plus the adapter's S3 extra when you want remote
LanceDB indexes:

```bash
pip install 'lumio-wiki[s3]'        # S3-native KB Locations
pip install 'lumio-lancedb[s3]'     # optional: LanceDB backend over S3
```

## 1. Local SeaweedFS `weed mini` with a dedicated bucket

Start a throwaway `weed mini`; `S3_BUCKET` creates the journey bucket at
startup. The `admin`/`secret` values below are **labelled local-test
credentials** — fine on localhost, never production credentials.

With the `weed` binary (leave it running in this terminal):

```bash
AWS_ACCESS_KEY_ID=admin AWS_SECRET_ACCESS_KEY=secret \
  S3_BUCKET=lumio-quickstart weed mini
```

Or with Docker:

```bash
docker run -d --name lumio-quickstart-seaweedfs -p 8333:8333 \
  -e AWS_ACCESS_KEY_ID=admin -e AWS_SECRET_ACCESS_KEY=secret \
  -e S3_BUCKET=lumio-quickstart \
  chrislusf/seaweedfs:4.45@sha256:fc9f76fa993ad69966ffeb2f65d0318fcae39c6f8e20cf68ef7b3a5cb97769e5
```

Point Lumio at it — standard AWS credential variables plus the endpoint
override; exported values win, nothing is written to any file:

```bash
export AWS_ACCESS_KEY_ID=admin             # local test credential
export AWS_SECRET_ACCESS_KEY=secret        # local test credential
export AWS_REGION=us-east-1
export LUMIO_S3_ENDPOINT=http://localhost:8333
export LUMIO_S3_ALLOW_HTTP=1               # plain HTTP is localhost-only
```

## 2. Maintainer setup with an S3 destination

Record the publication destination (and, optionally, a private Source
Artifact Store) when you set the project up:

```bash
lumio-wiki setup ./kb --publish-to s3://lumio-quickstart/helpdesk-kb
```

The destination lives in the project `.env` (`LUMIO_PUBLISH_TO`); `publish-s3`
reads it when no destination is passed. Credentials are never written —
standard AWS resolution applies.

**Source Artifact retention is opt-in and not retroactive.** Raw bytes are
retained at managed-ingest time, only when a store is already configured. To
retain originals, configure the store when you set the project up —
`lumio-wiki setup ./kb --publish-to s3://lumio-quickstart/helpdesk-kb
--source-store s3://lumio-private-sources/helpdesk` (a **separate,
non-public** bucket; a local path works too) — and re-ingest; `source fetch
--source-id support-runbook-2026 --output out.md` then returns the byte-exact
original.

## 3. Publish an immutable S3 version (zero-index)

Publication validates, writes canonical content plus the Discovery Graph
under a version prefix, then advances the active pointer
(`current.json`) — compare-and-swap guarded:

```bash
REV1=$(git -C ./kb rev-parse HEAD)
lumio-wiki publish-s3 ./kb --revision "$REV1" --expected-current none \
  --source-registry "$LUMIO_SOURCE_REGISTRY"  # preview only
# Only after operator authorization of the displayed S3 review:
lumio-wiki publish-s3 ./kb --revision "$REV1" --expected-current none \
  --source-registry "$LUMIO_SOURCE_REGISTRY" --confirm <review-digest>
```

The destination comes from `.env` (`LUMIO_PUBLISH_TO`, recorded by `setup`);
pass one explicitly to override. The Published Version identity is the full
commit (`REV1` below), not an operator-chosen `v1` label. The immutable bytes
and private exact bindings identify that captured revision. An identical
confirmed retry returns its receipt without rewriting or reactivating history.

## 4. Reader: read-only project against S3

In a second directory, bind a read-only project to the Location. Pathless
commands resolve the active Published Version — no local copy of the KB:

```bash
mkdir ../helpdesk-reader && cd ../helpdesk-reader
lumio-wiki setup --from s3://lumio-quickstart/helpdesk-kb
lumio-wiki search "password reset" --limit 2     # pathless, reads REV1
lumio-wiki related "Aurora Helpdesk" --scope canonical
lumio-wiki source inspect --source-id support-runbook-2026
```

The pinned Ariadne Context readers also work over S3, with one release
caveat. Published `lumio-wiki` 0.4.1 already supports opening a context
over S3: `open_published_context` accepts a pinned `S3Location` plus the
producer-side `metadata_store` used at publication, and the same shared
exact-admission verifier refuses an unpinned location, a missing store or
foreign private admission records — public objects alone never satisfy
admission. The `metadata_store` keyword on the three scoped navigation
operations (`list_published_context_pages`, `read_published_context_page`,
`search_published_context_pages`) exists only in the unreleased source
candidate: the public `pip install 'lumio-wiki[s3]'` wheel this guide
installs does not carry it, and S3 navigation still refuses there.

Private source metadata is not public Reader content. In this controlled
same-principal walkthrough, the operator is also authorized to read the private
publication metadata sealed during admission. `source inspect --published-version
<REV1>` can therefore report the exact version, Entity/Source identity and digest
abbreviation with `not retained (no Source Artifact Store configured)`.
Metadata inspection does not grant access to raw bytes: `source fetch` must fail
and create no output when originals were not retained. Unavailable or
unauthorized private metadata remains a bounded refusal; it never falls back to
registry-latest. This lab does not certify cross-role authorization policies.

## 5. LanceDB: expected zero-index fallback, then a healthy index

The **retrieval backend** (`zero-index` | `lancedb`) and the **retrieval
mode** (`lexical` | `semantic` | `hybrid`) are separate settings. Lexical
works on every backend; semantic/hybrid additionally need an embedder.

Request the LanceDB backend while the active version has no remote index
(REV1 was published zero-index) — `status` discloses the **expected zero-index
fallback** instead of hiding it:

```bash
lumio-wiki setup --from s3://lumio-quickstart/helpdesk-kb --retrieval lancedb
lumio-wiki search "password reset" --limit 1    # still answers — zero-index
```

```text
lancedb_requested:           true
lancedb_healthy:             false
lancedb_fallback:            LanceDB index missing ...; zero-index page search over the same Published Version
```

Create a new explicit Git revision (`REV2`) requesting the remote index,
built and health-checked **before** activation (needs `lumio-lancedb`).
Use the exact expected-current guard because `REV1` is active. Keep the
captured `REV1` value from Part 3 in the Maintainer shell:

```bash
cd ../helpdesk-project
git -C ./kb commit --allow-empty -m "Request version-bound LanceDB retrieval"
REV2=$(git -C ./kb rev-parse HEAD)
lumio-wiki publish-s3 ./kb --revision "$REV2" --expected-current "$REV1" \
  --source-registry "$LUMIO_SOURCE_REGISTRY" --retrieval lancedb  # preview
# Only after operator authorization of this new review:
lumio-wiki publish-s3 ./kb --revision "$REV2" --expected-current "$REV1" \
  --source-registry "$LUMIO_SOURCE_REGISTRY" --retrieval lancedb --confirm <review-digest>
cd ../helpdesk-reader
lumio-wiki setup --from s3://lumio-quickstart/helpdesk-kb --retrieval lancedb
```

```text
lancedb_requested:           true
lancedb_healthy:             true
lancedb_fingerprint_matches: true
```

The Reader resolved the new pointer automatically. Lexical mode now ranks
through LanceDB (BM25); the contract — results, `open:` actions — is
identical, only ranking quality changes. Semantic and hybrid stay separate
rungs and demand an embedder; without one the CLI refuses truthfully:

```bash
lumio-wiki search "reset link expiry" --mode semantic
```

```text
error: semantic/hybrid search needs an embedder: install 'lumio-lancedb[embeddings]' (local) or set LUMIO_PROVIDER_BASE_URL + LUMIO_PROVIDER_API_KEY + (LUMIO_EMBEDDING_MODEL or --model) for a remote endpoint.
```

Install `'lumio-lancedb[embeddings]'` (local sentence-transformers) or point
`LUMIO_PROVIDER_*` at an OpenAI-compatible `/embeddings` endpoint to enable
them — `--mode semantic` and `--mode hybrid` are then two separately
demonstrable rungs (the error text is identical until an embedder exists):

```bash
lumio-wiki search "reset link expiry" --mode semantic
lumio-wiki search "reset link expiry" --mode hybrid
```

To revert a bad activation, preview `lumio-wiki rollback-s3
s3://lumio-quickstart/helpdesk-kb --version "$REV1" --expected-current "$REV2"`
in the Maintainer shell, then repeat with `--confirm <review-digest>` only
after operator authorization. Rollback verifies historical bytes/bindings,
never rebuilds them. `lumio-wiki cleanup-s3
s3://lumio-quickstart/helpdesk-kb` reports residue and deletes nothing.

## AWS/S3 variant (production)

The same journey against real S3 drops only Part 1's local-endpoint
variables — credentials resolve through the standard AWS chain (environment,
`~/.aws`, instance role), so **no secrets are committed** and none are needed
in `.env` (setup writes locations, never credentials):

```bash
export AWS_REGION=eu-west-1                    # standard resolution; no keys exported
lumio-wiki setup ./kb --publish-to s3://example-public-kb/team-kb
lumio-wiki publish-s3 ./kb --revision <full-commit-id> --expected-current none \
  --source-registry <private-dir>  # preview; confirm only after operator authorization
lumio-wiki setup --from s3://example-public-kb/team-kb --retrieval lancedb
```

`example-public-kb` is a non-secret placeholder — substitute your bucket.
Keep the private Source Artifact Store (`--source-store`) in a **separate,
non-public** bucket/prefix if you use retention.

## Where to go next

- [`docs/quickstart.md`](quickstart.md) — the canonical local journey this
  guide extends.
- [`docs/usage.md`](usage.md) — full CLI, Python library, and coding-agent
  reference, including S3 reads and the MCP server.
- [`examples/onboarding-journey/`](../examples/onboarding-journey/) — the
  scriptable journey; its S3 half runs this guide's commands in order.
