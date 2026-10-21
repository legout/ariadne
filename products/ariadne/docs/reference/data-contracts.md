# Data Contract reference

**Ariadne 0.6.0 — limited consumer profile, not full ODCS compliance.**
Producer expectations, local bindings, measured observations and human admission
are separate facts. OSI retains calculation, grain and join authority; OKF owns
explanatory knowledge and business Policies. Contract narrative/context is inert
metadata, not instructions merged into prompts or executable Policies.

## Immutable document pin

Only `apiVersion: v3.2.0` and `kind: DataContract` are supported. Core packages the
unmodified official `schema/odcs-json-schema-v3.2.0.json` from
[upstream commit f0bdad95346905d500be5ef4b2c2d9b1d95223b7](https://github.com/bitol-io/open-data-contract-standard/tree/f0bdad95346905d500be5ef4b2c2d9b1d95223b7):

- Git blob: `f934075459fce0a20a3c8260dd2076872f91e2b9`.
- SHA-256: `edb41f33ec46e84780e99872ab2bd67f074959d2bf3e9c9fc54e61f8982b0d93`.
- Size: 110505 bytes; upstream Apache-2.0 LICENSE is packaged beside it.
- Core dependency: `jsonschema>=4.18`, Draft 2019-09 structural assertions.
  JSON Schema `format` is an annotation, not an environment-dependent checker.

Validation uses packaged bytes, never a downloaded or document-selected schema.
Other apiVersion labels refuse even where the pin accepts older labels. Each
file contains one UTF-8 YAML mapping with JSON-compatible values; duplicate keys,
non-JSON values, duplicate scoped IDs and dangling internal references fail.
External references are retained, never fetched. The producer's own `version`
is independent of ODCS/Git versions and need not be SemVer. Ownership/team stays
as declared; missing optional ownership is undeclared, never inferred.

This minimal **unbound** document is valid, but proves nothing about source data:

```yaml
apiVersion: v3.2.0
kind: DataContract
id: order-number-contract
version: producer-release-A
```

`ariadne-validate ARTIFACT_DIR` is source-free static checking. Success is partial
structural evidence; approved-source observations are `not_run`, not compliant.

## Separate Git artifacts and exact bindings

Producer files live in `contracts/*.yaml` / `*.yml`. Consumer configuration lives
in the separate fixed `contract_bindings.yaml`. Both participate in the ordinary
candidate inventory, digest, validation, bounded review and human admission.
Existing typed authoring operations accept:

- Read: `{kind: contract, name}` or `{kind: contract_bindings}`.
- Edit: the same identities plus `content` containing the complete file text.
- Contract names select an existing stem or exact `.yaml`/`.yml` filename; use
  the exact filename when extensions are ambiguous. No arbitrary paths.

Reads select a proposal's current Candidate Revision; edits and validation
require its expected revision and report the resulting revision. Review is
read-only, never sign-off. Loading or measuring never normalizes producer bytes,
injects identifiers, repairs missing IDs or generates expectations from data.

Binding document shape (illustrative identifiers, not a runnable source grant):

```yaml
version: 1
bindings:
  - id: local-orders
    contract_id: order-number-contract
    contract_version: producer-release-A
    object_id: orders-object
    asset: {source: warehouse, catalog: warehouse, schema: main, table: orders}
    model: orders-model
    dataset: orders
    properties: {order-id: order_id}
    server_id: native-duckdb
```

The contract must actually declare the selected object/property/server IDs and
the OSI model/dataset must resolve to those physical rows/columns. `asset` is the
exact case-sensitive native `{source, catalog, schema, table}` selector; file
views use native null-catalog semantics. All physical properties must have stable
IDs and mappings. Declared physical names must agree; no fuzzy matching,
name-derived IDs or omission of unsupported properties. Unknown binding fields,
duplicate local binding IDs, conflicting bindings for one OSI dataset and
ambiguous exact `(contract_id, contract_version)` pairs fail. Different producer
versions may coexist with explicit selection. Unresolvable derived/transformed
OSI identities are unsupported, never guessed equivalent.

`server_id` is required for SQL-quality rules and resolves the producer's
unambiguous server identifier. Neither that server's URL nor a binding creates
a source, supplies credentials, changes an approved endpoint or widens S3 scope.
The host's Source Approval and frozen effective Storage Binding remain required.
These remain repository-local contract identities, not portable OSI/Lumio IDs.
For an integrated project the [Bound Release](../../../../integration/docs/reference/lumio-bound-releases.md) records
these identities alongside its exact knowledge pin; it does not merge their
meaning or make a binding into source permission.

## Small supported field and quality profile

Flat physical properties support presence and these logical scalar families:
string (not binary), integer (not float/decimal), number (integer/decimal/float,
not boolean), boolean, date, time and timestamp (observed variants retained).
Absent types impose no invented constraint. Unknown/lossy types cannot pass.
A declared `physicalType` needs reliably observable original native metadata;
recognized aliases preserve width, precision, scale and time-zone distinctions.
A lossy execution/view projection cannot establish the original physical type.
`required: true` checks NULLs over the entire dataset, never a sample. Extra
observed columns are informational, not automatically drift.

Asserted `unique`, `primaryKey`, `enum`, nested object/collection fields,
transformations and nonempty `logicalTypeOptions` are unsupported. False key
flags impose nothing. Formatting, examples and narrative are not measured rules.

Applicable object/property `type: sql` quality requires a selected DuckDB server
and matching approved **native DuckDB** source. One checked SELECT over the
single bound dataset must return exactly one row/column containing a finite
number or boolean. No joins, other datasets, mutation, multiple statements,
external table functions, environment/secret access or custom engines. The
reviewed SQL-tree authority runs before execution; read-only is not a sandbox.
Only fixed `{object}` and property-rule `{property}` placeholders expand to
checked quoted identifiers. Literal relations must resolve to the same exact
asset without ambient search-path fallback. General `${...}` variables and
unresolved placeholders are unsupported, never environment substitution.

Supported individual operators: `mustBe`, `mustNotBe`, `mustBeGreaterThan`,
`mustBeGreaterOrEqualTo`, `mustBeLessThan`, `mustBeLessOrEqualTo`, `mustBeBetween`,
`mustNotBeBetween`. Numeric precision is retained: no boolean/number conflation,
string coercion or invented tolerance. Boolean equality/inequality is same-type
only. Between uses **open endpoints** (`a < value < b`), with its complement for
not-between, per the pinned upstream quality documentation; bounds must increase.
The upstream combined `mustBeGreaterThan` + `mustBeLessThan` example fails the
pin's `oneOf`: Ariadne retains that diagnostic and never patches the schema or
rewrites operators. NULL, nonfinite/wrong-type values and wrong cardinality are
evaluation errors, not successful comparisons.

Library/text/custom quality, other dialects, unsupported operands and external
references required for evaluation block proof. Severity or selection flags
cannot silently drop an applicable requirement. Vendor metadata stays inert;
scheduling metadata creates no job and no wiki service is contacted.

## Evidence, admission and runtime limits

Document validity, binding validity and evaluation outcomes remain separate.
Requirements report `passed`, `drift`, `unavailable`, `unsupported`, `refused`,
`error` or `not_run` with scoped identity and actionable diagnostics. Only
complete passing evidence for **all** applicable bound requirements can support
human admission. Static success, partial scans, unsupported quality,
missing/forged/stale proof or a successful technical check alone cannot admit.
Valid unbound documents do not invent dependencies for unrelated models.

Existing `.ariadne/validation/` evidence binds the final candidate and artifact
digests, exact producer/binding/asset/column/OSI identities, Source Approval and
non-secret effective storage identity, schema/profile/validator and checks,
observation times, actual full/partial scope and available snapshot identifiers.
The operator's tightening-only `inspection` ceilings apply across the validation's
contract checks: at most 20 execution seconds total, 64 KiB serialized contract
content and 24 hours evidence age. Candidates cannot raise limits or permissions.
Changed dependencies invalidate proof; still-applicable reuse retains the
original observation time, with a new final validation checking its applicability.
No atomic source snapshot or unchanged mutable data is implied.

`discover` / `ariadne search` adds a bounded contracts group from the pinned
admitted snapshot: producer IDs/version, binding/model/dataset where bound,
profile limitations, revision and matching observation as-of/eligibility. An
unbound document has no binding/observation. Before admission the group is
unavailable. Candidate/worktree bytes never replace admitted metadata.

`list_datasets` / `ariadne list-datasets` retains the approved **live catalog**,
actual columns and ordinary approval/admission refusals. Matching contract
annotations use only the pinned snapshot, with no additional source read or
second inspection. Neither operation regenerates evidence or claims current
compliance. Evidence expiry/later drift does not silently unadmit definitions,
start monitoring or introduce a new runtime refusal policy. Existing query,
compile, grain and source gates remain; contract passes grant no join authority,
no governed ad-hoc label and no cached numerical answer.

Existing CLI/MCP/embedded Agent tools expose these native results without new
tool registrations or human operations. Fixture and packaged-resource checks do
not establish production conformance, live-model behavior, remote-source health
or full transport coverage. Source access, integration and publication remain
separate human decisions.
