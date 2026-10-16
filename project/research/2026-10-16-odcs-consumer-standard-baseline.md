# ODCS consumer research: pins, validation limits and authority boundaries

**Status:** research evidence, 2026-10-16; no ODCS version, consumer profile, shared ABI or implementation approved. **Intake:** [Ariadne #75](https://github.com/legout/ariadne/issues/75), updated 2026-10-15T20:22:38Z. **Local source:** `28332db8acadffccca535c1978c2d376441eb675`, containing accepted Core #73 and approved standalone Git-only [specification](../specs/2026-10-16-0027-core-git-only-authoring.md)/[plan](../plans/2026-10-16-0027-core-git-only-authoring.md) 0027r1. **Handoff:** planning-contract v1; installed provenance unknown. The project's `project/research/` artifact contract owns this note; no parallel global-wiki copies are created.

## Summary

ODCS **v3.2.0** is the latest published non-prerelease found in the official release API, published 2026-09-08. The older vault note about v3.1.0 is historical, not a current version decision. Both unversioned and version-named schema URLs can change: pinning `v3.2.0` in a filename is not sufficient for reproducible validation. [S1, S2]

The official schema provides real document validation, not proof of source compliance or complete reference semantics. It accepts older `apiVersion` labels, schema-less documents and duplicate element IDs in the inspected cases. One quality-rule example recommended by the documentation fails that same revision's schema. [S3, S5, S6]

Version 3.2 also introduces AI-context behavior, including a recommendation to return curated answers verbatim. That must not silently replace Ariadne's fresh execution, historical Example meaning, or Lumio's explanatory-knowledge ownership. A limited consumer profile needs explicit approval and honest unsupported behavior; a claim of complete semantic interoperability would be unjustified. [S7; local specification 0027 §§4, 8]

## 1. Reproducible standard inputs

Official tag `v3.2.0` resolves to commit:

```text
f0bdad95346905d500be5ef4b2c2d9b1d95223b7
```

Inspected `schema/odcs-json-schema-v3.2.0.json` at that commit:

```text
JSON Schema dialect: https://json-schema.org/draft/2019-09/schema
Bytes:              110505
Git blob:           f934075459fce0a20a3c8260dd2076872f91e2b9
SHA-256:            edb41f33ec46e84780e99872ab2bd67f074959d2bf3e9c9fc54e61f8982b0d93
```

The fetched bytes' `git hash-object` matched the official GitHub contents API blob. The schema's `$ref` values are internal fragments; its dialect URI is not an external contract reference. This observation does not authorize network resolution or choose a runtime validator. [S3]

Upstream explicitly distinguishes bleeding-edge `latest`, rolling `vX.Y.Z` files that may receive **silent updates**, and dated snapshots. It also notes same-day snapshots can be overwritten while being produced. A commit plus exact bytes avoids relying on a moving filename alone. No schema has been vendored into the Core wheel by this research. [S2]

**Candidate recommendation, not a decision:** consider a single supported v3.2.0 profile with an immutable reviewed schema pin. Compare any later rolling fixes before selecting the actual pin. Keeping older versions is a separate scope choice, not something the broad `apiVersion` enum decides for Ariadne.

## 2. Identity and document shape

The four required top-level properties are `version`, `apiVersion`, `kind` and `id`. `kind` is `DataContract`; `apiVersion` identifies the standard, while `version` identifies the producer's contract revision. `name`, `schema`, ownership/team and server metadata are not required by this inspected schema. Top-level undeclared properties are rejected; `customProperties` is a defined extension surface, not an arbitrary flattened pseudo-ODCS format. Its entries require `property` and `value` in the schema, although the documentation table labels them optional. [S3, S4, S9]

The top-level contract `id` is a string, not a schema-enforced UUID. Nested stable IDs use `StableId`, excluding whitespace and `. # / \ @ ! % & ^`, while allowing colons. Its description requires uniqueness within the containing array. Stable references use IDs and paths such as `schema/<id>/properties/<id>`; shorthand foreign-key references use names and are rename-sensitive. External reference syntax can name another file or URL. Syntax is not permission to fetch it. [S3, S5]

Reference documentation explicitly leaves composite-array length checks to implementations. Structural schema validation therefore cannot replace semantic resolution, duplicate-ID checks or approved source/model binding. Neither ODCS names, physical names, server declarations, relationship hints nor an `authoritativeDefinitions` URL establish an Ariadne Source Approval or a #76 cross-layer identity. [S5; #75; local specification 0027 §§2, 8]

## 3. Bounded schema inspection

A local, source-free probe used **CPython 3.14.0**, `jsonschema 4.26.0`, `validators.validator_for(schema)` selecting `Draft201909Validator`, and `check_schema`. It executed no contract SQL, Ariadne operation or physical-source read. Reproduction artifacts are in the parent-owned ignored directory `.orchestrator/issue75-20261016/`: the pinned JSON and `schema-probe.log` (command exit 0). These are research artifacts, not Core conformance tests.

Each case starts with:

```yaml
apiVersion: v3.2.0
kind: DataContract
id: research-example
version: 1.0.0
```

| Change to that document | Observed structural result | Consequence for shaping |
| --- | --- | --- |
| None; no `schema` or source | Valid | A valid document is not evidence that a dataset was inspected or complies. |
| Change `apiVersion` to `v3.1.0` | Valid under the v3.2.0 schema | Supported-version dispatch needs an explicit consumer decision; using this schema alone does not enforce v3.2-only support. |
| Add top-level `inventedMetric: 1` | Invalid | Keep the real standard, with its defined extension points. |
| Add two schema objects with `id: same`, distinct names | Valid | The described stable-ID uniqueness rule needs semantic validation beyond this schema. |
| Add SQL quality with `mustBeBetween: [0, 100]` | Valid | Structural validation says nothing about actual counts or safe execution. |
| Replace it with both `mustBeGreaterThan: 0` and `mustBeLessThan: 100` | Invalid | There is an upstream documentation/schema discrepancy. |

For the last two cases the enclosing object is `schema: [{name: orders, quality: [...]}]`, with quality fields `type: sql` and `query: SELECT COUNT(*) FROM orders`. Documentation says the two operator forms are equivalent. The pinned `$defs/DataQualityOperators.oneOf` rejects the combined form because both operator alternatives match; an additional `unevaluatedProperties` diagnostic follows. This is not repaired by editing Ariadne's expectations or replacing the official schema with a homemade interpretation. Selecting an upstream correction, following the pinned schema with a documented limitation, or another justified conformance policy remains an owner decision. [S3, S6]

These six observations are not a full ODCS conformance certification. Upstream's CI validates examples and negative scenarios with AJV and checks latest/versioned parity. Its scripts and fixtures are useful independent oracles when an implementation profile is approved; copying every example into Core would not itself establish supported runtime semantics. [S10]

## 4. Behavioral surfaces that need an explicit profile

### AI context and answer authority

ODCS v3.2.0 adds optional string/object `context` at contract and schema-object levels. RFC-0038 describes `instructions` as scoped system-prompt guidance, recommends cascading/merging guidance and constraints, and says answered `verifiedStatements` entries **SHOULD be returned verbatim** for semantically close questions. Property-level context is deferred. [S7]

That recommendation is not Ariadne approval to replay historical numerical answers, infer joins, treat authored claims as measurements, create native Policies, or change a governed query's required-context failure behavior. The approved Core contract retains fresh execution, historical non-authoritative Examples and the current `context_unavailable` fallback. #75 assigns explanatory knowledge to Lumio; #76's external binding/provider/Policy rules remain unapproved. Any supported interpretation or explicit non-implementation of ODCS context needs to be stated in the future profile, without silently claiming full RFC-0038 behavioral conformance. [#75; local specification 0027 §§4, 8]

### Variables, external references and quality execution

ODCS variables may appear in any string. Tooling MUST resolve a token before using its value and MUST preserve unresolved tokens when serializing. Missing variables without defaults must not silently become empty strings. Resolution order is intentionally tool-defined. A consumer that does not support resolution must not use unresolved text as an endpoint, identifier or query. This does not choose Ariadne environment/secret lookup behavior. [S8]

Quality rules include library, text, SQL and custom-engine forms. SQL is dialect-specific; custom implementations can be opaque vendor code. Document validation is not execution permission, engine support, safe source access or evidence of successful checks. Existing operator Source Approval, scoped S3 profiles, secret isolation and SQL/grain protections remain authoritative. Do not install an external execution engine merely because a contract declares one. [S6; #75; local specification 0027 §§2, 7]

Unknown vendor values in `customProperties` must be preserved according to the standard. Extensions or authoritative-definition links must not be mistaken for an already agreed Lumio ontology/Policy identity or a live-service dependency. [S9; #75]

## 5. Handoff questions before #75 coding

Route this evidence to `shape-design`, not directly to an implementer:

1. Which standard version and exact schema snapshot are supported? How is the quality example/schema discrepancy handled and tested?
2. What separates document validity, reference/ID validity, supported evaluation and observed conformance? Which valid-but-unsupported features are preserved and reported without claiming they were evaluated?
3. Which expected constraints/types/quality metrics are evaluated against which explicitly bound, operator-approved sources? Define observation time, source identity, scan bounds and unavailable/unknown outcomes before making CI refusal/freshness claims. Never rewrite producer intent from observations.
4. How are optional context, variables, external references and executable/custom quality handled without expanding authority or claiming unsupported behavior?
5. Which binding/ID decisions require joint #76 approval? Do not infer them from filename equality, Lumio's component manifest or an unaccepted runtime candidate.

The standalone #74 implementation can continue independently; it excludes ODCS and the shared ABI. No changes to its approved sources, glossary, ADRs or implementation are authorized by this note. There is no #75 specification/plan approval, production access, target integration, publication or dependency installation here.

## Sources

All external sources were inspected on 2026-10-16. Search summaries were discovery aids; the claims above use first-party source documents/API data. Two search rounds were sufficient for the bounded version/schema/authority question; optional vault backend configuration was absent. Broad vendor comparisons and claimed LLM-accuracy improvements were not evaluated.

- **S1:** [Official v3.2.0 release](https://github.com/bitol-io/open-data-contract-standard/releases/tag/v3.2.0); GitHub release/tag APIs (`gh api repos/bitol-io/open-data-contract-standard/releases` and `/tags`), showing non-prerelease publication and the tag commit.
- **S2:** [Pinned schema versioning policy](https://github.com/bitol-io/open-data-contract-standard/blob/f0bdad95346905d500be5ef4b2c2d9b1d95223b7/schema/README.md).
- **S3:** [Pinned v3.2.0 JSON Schema](https://github.com/bitol-io/open-data-contract-standard/blob/f0bdad95346905d500be5ef4b2c2d9b1d95223b7/schema/odcs-json-schema-v3.2.0.json), especially `apiVersion`, root `required`, `$defs/StableId`, `$defs/DataQualityOperators` and `$defs/CustomProperty`.
- **S4:** [Official v3.2.0 fundamentals](https://bitol-io.github.io/open-data-contract-standard/v3.2.0/fundamentals/).
- **S5:** [Pinned references and foreign-key rules](https://github.com/bitol-io/open-data-contract-standard/blob/f0bdad95346905d500be5ef4b2c2d9b1d95223b7/docs/references.md).
- **S6:** [Pinned quality documentation](https://github.com/bitol-io/open-data-contract-standard/blob/f0bdad95346905d500be5ef4b2c2d9b1d95223b7/docs/data-quality.md), particularly the final operator-equivalence example, versus S3's `oneOf`.
- **S7:** [Pinned ODCS context documentation](https://github.com/bitol-io/open-data-contract-standard/blob/f0bdad95346905d500be5ef4b2c2d9b1d95223b7/docs/context.md); [approved RFC-0038 at inspected TSC commit](https://github.com/bitol-io/tsc/blob/d100fd653c567899b05de9386ce2dfc02847438b/rfcs/approved/odcs-v3.2.0/0038-context.md), normative cascading and `verifiedStatements` sections.
- **S8:** [Pinned variable semantics](https://github.com/bitol-io/open-data-contract-standard/blob/f0bdad95346905d500be5ef4b2c2d9b1d95223b7/docs/variables.md).
- **S9:** [Pinned custom properties](https://github.com/bitol-io/open-data-contract-standard/blob/f0bdad95346905d500be5ef4b2c2d9b1d95223b7/docs/custom-other-properties.md).
- **S10:** [Pinned official validation workflow](https://github.com/bitol-io/open-data-contract-standard/blob/f0bdad95346905d500be5ef4b2c2d9b1d95223b7/.github/workflows/validate-examples.yaml).
