# Own sqlglot compiler instead of datus-metricflow (AGPL exit)

Status: accepted (owner, 2026-09-17 shape-design round for spec revision 7).

The compile path rendered OSI-envelope models to SQL through `datus-semantic-osi`, which pulls `datus-metricflow` (AGPL-3.0) into the runtime. After evaluating the alternatives (upstream Apache MetricFlow, Cube), we render the envelope ourselves in `ariadne/render.py` via sqlglot AST: base aggregates in one SELECT, derived metrics resolved recursively with cycle detection. This removes both datus packages, the AGPL runtime dependency, the `<3.13` Python cap (kept floor `>=3.12`), and the last startup dependency. The safety net for the swap is the existing executable contract: golden evals, money tests, trap/guard tests, validate and ad-hoc suites must pass verbatim. A side benefit: the compiler becomes ours, making grain-aware compilation (ADR-0006) a native next step instead of an upstream request.

**Considered options:** upstream MetricFlow (Apache) — rejected (new spec-dialect adapter for marginal license gain); Cube — rejected (a whole serving layer to operate); keep datus and accept AGPL — rejected (distribution story stays hostage).
