# Ad-hoc metrics: from governed-only to no-unvalidated-execution

Status: accepted (owner, 2026-09-14 shape-design round for spec revision 3).

The MVP's original invariant was "get_metric accepts only named governed metrics — never raw SQL" (spec rev 1/2 §6). The owner requirement that any data in the attached database be queryable — with the LLM generating new metrics on the fly and the semantic/context layers as helpers rather than gatekeepers — broke that invariant. Revision 3 replaces it with **no unvalidated execution**: agents may author dataset sources and metric expressions as structured `define_metric` params, but the facade expands them into an ephemeral OSI model and every computation still passes the deterministic Datus compile gate; there is no code path from tool arguments to `duckdb.execute` that bypasses the compiler. Governed state still changes only by human promotion; successful ad-hoc definitions are auto-staged as proposals, never auto-promoted (ADR-0003 logic extended). Agent-authored SQL fragments remain a named, accepted trust boundary until the deferred governance work.

**Considered options:** LLM drafting inside the facade (rejected — nondeterminism and LLM dependency inside the server; the consuming agent already is one); raw SQL tool (rejected — reintroduces ungoverned text-to-SQL, the failure mode the architecture exists to prevent).
