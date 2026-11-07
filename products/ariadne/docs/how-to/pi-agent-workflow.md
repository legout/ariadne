# Use Ariadne from a Pi coding agent

Ariadne ships a packaged Agent Skill so a coding agent such as
[Pi](https://github.com/earendil-works/pi-coding-agent) can work inside a
data project without ever bypassing the governance gates. This guide walks
the concrete Pi workflow; the full contract is the packaged
[SKILL.md](../../packages/ariadne-data/src/ariadne/skill_assets/SKILL.md),
and every command is documented in the [CLI reference](../reference/cli.md).

Everything here is the local Git-project route: no server, no model key,
and no computation outside the deterministic compile gate.

## 1. Install the packaged skill

Inside the data project (with `ariadne-data` providing the CLI):

```bash
ariadne-skill install --scope project --agent pi
```

The install is an idempotent refresh; it copies the packaged skill to
`.pi/skills/ariadne` under the selected project (`--scope user` installs it
shared-scope instead). `ariadne-skill status` reports per-target drift
against the packaged skill. Pi loads the skill on its next start.

## 2. Start every question with discovery

From the project root (or pass `--project DIR`):

```bash
ariadne status --project .          # offline readiness; never opens sources
ariadne list-metrics --project .    # if a governed metric answers it, query it governed
ariadne search-context "cancelled orders" --project .
ariadne resolve-term "order number" --project .   # ambiguity and claim status included
```

Discovery groups metrics, pages, terms and examples without opening
sources, executing an answer, or authorizing a join. A matching term or
identifier never grants join authority.

## 3. Query governed, or explicitly ad hoc

```bash
# governed: carries governed: true, compiled SQL, and the full Policy context
ariadne get-metric gross_margin --dimension region --start 2024-01-01 --project .

# ad hoc: explicitly ungoverned, never saved
ariadne define-metric --file request.json --project .
```

An ad-hoc `define_metric` result carries `governed: false` and
`persistence: {status: not_saved}` — present it as a draft, never as a
governed number. To keep a definition, move it through a reviewed proposal
(next step); there is no silent save.

## 4. Author through proposals, stop at human admission

```bash
ariadne-authoring start --project .              # revision-checked proposal
ariadne-authoring edit --project . --proposal ID \
    --expected-revision CURRENT --file edit.json # typed edit; returns the new revision
ariadne-authoring validate --project . --proposal ID \
    --expected-revision CURRENT                   # the revision from the preceding edit
ariadne-authoring review --project . --proposal ID   # read-only; return its exact payload
```

`--expected-revision` is required and always names the current candidate
revision returned by the preceding edit or validation. The full sequence —
approved inputs, the finalize commit, human admission — is the
[Git-backed authoring guide](git-authoring.md).

The agent makes the candidate and reports the review payload and digest.
**Admission is a human Git decision** — the agent stops there, never runs
`git commit`/`push` or arbitrary shell commands against the data project,
and never edits served layers or `.ariadne/` state by hand. The one
documented exception is native `git add` of intended paths inside the
explicit external whole-contribution workflow; its commit, export and push
decisions remain human and separately authorized.

## 5. Honest boundaries

- `ariadne setup` is operator-facing; agents pass operator commands and
  blockers to the human instead of running them.
- Missing or corrupt admission refuses; there is no candidate-worktree or
  mutable-root fallback, and no server is started just to answer a question.
- Observed `value_evidence` and the optional Context Routing Map are
  guidance, never enums, validation, or permission to calculate.
- The optional MCP transport exposes the same operations; the local CLI
  above remains the default workflow.
