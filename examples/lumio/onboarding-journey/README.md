# Onboarding journey (focused example)

This is the executable companion to the canonical quickstart
([`docs/quickstart.md`](../../docs/lumio/quickstart.md), issue #180). It contains the
one Knowledge Source the journey ingests and a scriptable smoke journey that
runs the quickstart's exact local commands, in order, and fails on any
unexpected outcome — so documentation drift between the quickstart and the
CLI is caught by CI rather than by a reader. When an S3-compatible endpoint
is configured, the same script continues through the optional
[`docs/howto-s3-publish.md`](../../docs/lumio/howto-s3-publish.md) commands.

## Contents

| Path | Role |
|---|---|
| `sources/support-runbook.md` | The raw Knowledge Source the journey ingests (managed ingest input; you never commit raw sources into a Knowledge Base). |
| `smoke-journey.sh` | The scriptable journey: Maintainer setup → ontology starter → seed pages → managed ingest → Git review and exact-revision admission → local publish → retrieval/citation/traversal → Source Artifact inspection → (S3 endpoint configured) S3 publication with and without LanceDB → read-only Reader project → expected zero-index fallback. |

## Run it

Local steps only (no object store needed):

```bash
./smoke-journey.sh
```

Full journey including S3-compatible publication (same environment variables
the CLI and S3-compatible test suites read). Start SeaweedFS `weed mini` with
the bucket and **labelled local-test credentials** shown in the optional S3
guide ([`docs/howto-s3-publish.md`](../../docs/lumio/howto-s3-publish.md)), then run:

```bash
export LUMIO_S3_ENDPOINT=http://localhost:8333
export AWS_ACCESS_KEY_ID=admin              # local test credential
export AWS_SECRET_ACCESS_KEY=secret         # local test credential
export AWS_REGION=us-east-1
./smoke-journey.sh
```

The bucket (`lumio-quickstart` by default, override with
`LUMIO_S3_TEST_BUCKET`) is created at `weed mini` startup with
`S3_BUCKET=lumio-quickstart`. The script verifies the bucket through `obstore`
(the same client the CLI uses) and directs failures back to that startup
configuration. Each run publishes under a unique `helpdesk-kb/run-…` prefix
because Published Versions are immutable and cannot be overwritten.

When `lumio-wiki` is not on `PATH` (for example from a Lumio checkout), point
the script at it:

```bash
LUMIO_WIKI_BIN="uv --project /path/to/lumio run lumio-wiki" ./smoke-journey.sh
```

## What a PASS proves

- The quickstart's command sequence works verbatim in a fresh project: setup,
  ontology starter, seeded Entity pages, managed document ingest, Git review
  and exact-revision publish, retrieval with citation open actions, canonical
  graph traversal, and truthful Source Artifact unavailability (retention is
  disabled by default and the CLI says so).
- Against an S3-compatible endpoint: immutable publication (`publish-s3`) with zero-index and
  LanceDB artifacts, read-only Reader setup (`setup --from`), pathless reads,
  the disclosed zero-index fallback when a LanceDB index is not published,
  health after publishing one, and the truthful embedder requirement for
  `--mode semantic`/`--mode hybrid`.
- Documentation drift: every displayed citation keeps an `open:` action, the
  fallback wording matches, and any CLI change that breaks a documented
  command fails the script (and the CI job that runs it).
