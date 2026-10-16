# Project-specific verification skills: pstack research and proposed adaptation

**Status:** research and recommendation, 2026-10-16; no skill creation, installation, policy change, application execution or test run authorized/performed by this note. The #74 implementation remains paused. Planning-contract v1; installed provenance unknown. Related: [agent-written test value](2026-10-16-agent-written-test-value.md).

## Conclusion

Add a lean, explicitly invoked generator/maintainer for project-specific verification recipes. Do not add another mandatory verification loop, reviewer tier, CI matrix or control framework.

The useful distinction is **independent evidence versus self-confirmation**, not verification versus tests. A meaningful automated test is a verification technique. A browser screenshot, live CLI invocation or another agent's opinion is not intrinsically stronger: each must establish the requested outcome against an independently justified expectation. Pstack's concrete contribution is teaching agents how to operate a real project and observe its outcomes, rather than merely telling them to verify.

## Sources inspected

Official repository: `cursor/plugins`, main at inspected commit **`f713f14203cd6420cec13cd7c55c32d598dbab68`**, committed 2026-10-16T03:18:33Z. Read the complete create/maintain skills, proof principle, worked feature-map examples and verification guide; inspected verification-related excerpts of poteto-mode. Pstack is MIT-licensed, copyright 2026 Lauren Tan. Any later adaptation of substantial text must retain attribution and the required notice. [P1–P6]

The existing skills catalog already owns a general `verification-before-completion` primitive and rejects duplicate generic verification loops. A generator has a different job: producing the project-specific operating knowledge that the general gate can select. Its creation/maintenance mode must not compete with implementation orchestration or integration ownership.

## What pstack actually does

### `/create-verification-skill`

The skill interviews the repository before asking the user: identify the user surface, documented startup, existing driving harness, observable evidence and isolation constraints. It prefers existing harnesses to new control tools. [P1]

It generates `.cursor/skills/verify-<app>/SKILL.md` with:

- **Launch:** reach a usable state, not merely an answering process; include teardown.
- **Doctor:** a read-only instance/readiness check, including relevant build/version, ownership and authorization.
- **Drive:** real, stable commands or selectors for the application's user-facing surface.
- **Evidence:** capture the action and resulting state, including side effects. A dry-run name is not proof that no network, browser or filesystem side effect occurred.
- **Cleanup:** stop only owned resources, remove scratch state, retain proof artifacts.
- **Helpers:** document executable scripts if any are genuinely needed.

It seeds a feature-map index plus approximately three to five initial feature recipes, mapping user entry points and observable end states. Its generation proof is bounded: run the generated instructions once end to end for **ONE** mapped feature, then clean up and confirm the evidence survived. An unexecuted generated skill is a draft, not a demonstrated deliverable. Stand-in environments must disclose what remains unproved on the actual target. [P1, P4]

### `/maintain-verification-skill`

Maintenance is a separate, relatively broad audit: one read-only source reader per feature, followed by one coordinator driving every mapped feature live. It edits only the verification skill and its owned map/harness, never product code. It distinguishes doc drift, harness gaps and product regressions; a regression must be reported, not disguised by rewriting the map. Outcomes are `clean`, `changed` or `blocked`. Run notes are scratch artifacts, not a committed evidence ledger. [P2]

The guide recommends daily scheduled maintenance, verifier swarms for wider passes, fresh per-PR shipping verification, and sometimes rerunning a proof on main. These are pstack workflow choices, not prerequisites for learning its useful mechanism. The creator itself says to suggest a cadence only when asked. We should not import the guide's daily/full-feature/parallel defaults into our deliberately bounded workflow. [P1, P3]

### Concrete proof, not a green badge

The worked Notes example requires reopening a saved note and checking both saved values; a “Note saved” status is insufficient. CLI evidence includes command/output/exit code; mutation evidence includes a second read-only view of stored state. Skipped entry points are not declared verified through another path. [P4]

The proof principle likewise asks for the actual artifact or value rather than a proxy, self-report or compilation result, and favors reproducible scripts over one-time impressions. This is empirical, scoped verification, not a formal proof of all program correctness. [P5]

## General verification guidance

OpenHands separates a code-review agent that reads the diff from a QA agent that actually runs changed CLI/API/UI behavior. That distinction is useful: source inspection and execution establish different claims. Its critic models, automatic multi-round review and `/iterate`-until-green loop are not necessary to adopt the distinction and conflict with our current scope/budget if imported wholesale. Its vendor-reported productivity/quality figures were not independently audited and are not used to justify a bigger verification system here. [G1]

Anthropic similarly recommends deterministic outcome grading where appropriate and warns against grading a rigid sequence of agent actions. It also cautions that model graders require human calibration. An additional model's confidence is not a substitute for an independently grounded expected outcome. [G2]

## What we should adopt, and change

1. **Match evidence to the claim.** UI appearance needs rendered evidence; persistence needs read-back, and restart when the claim includes restart survival; a CLI contract needs the actual command; a package claim needs the relevant installed artifact. Tests may already provide exactly that proof—do not execute an equivalent second stage just to call it verification.
2. **Separate expected from observed.** Requirements, approved examples or an independent oracle define correctness. Code exploration identifies entry points; running the app records observations. Neither may silently rewrite an expected outcome to match a bug. This is especially important because an agent-written feature map can reproduce the same oracle problem as agent-written tests.
3. **Bind evidence to its scope and target.** Name the surface, scenario, source/artifact identity, relevant environment and outcome. A version string alone may not identify an editable or installed build. A CLI proof does not automatically prove MCP, a deployed service or every feature-map entry.
4. **Reuse still-applicable evidence.** A new parent/reviewer, handoff or identical merge is not a reason to rerun. Conversely, a claim about a service running *now* needs current service observation: a prior regression result or screenshot cannot establish present liveness. Recheck only what relevant changes or the new claim invalidate.
5. **A feature map is a menu, not a mandatory checklist.** Default execution selects the smallest recipe for the changed behavior. A full-feature audit is explicitly requested work, not an automatic consequence of possessing a verifier.
6. **Keep budgets and stop conditions.** One necessary bounded proof, a concrete blocker on failure, no repeat-until-green or automatic wider matrix. One proof may need several actions, such as write/reopen/read; it is not limited to one shell command. Distinct required risks need explicit justification.
7. **Preserve authority.** Skill creation does not authorize startup repairs, dependency installation, production data access, source grants, admission, user-browser access, service restarts, PR creation or publication. Reuse an existing authorization when it genuinely covers the selected action; otherwise report the missing prerequisite. Do not inherit pstack's “fix startup first” as repair authority.
8. **Maintain only demonstrated drift.** Update changed commands/selectors and related recipes when needed. Keep product regressions separate from documentation changes. Never change an oracle solely because the current app behaves differently.

## Recommended skill structure

Use **one new general skill**, provisionally `project-verification`, with explicit **create** and **update** modes instead of immediately introducing two new skills. Creation/maintenance is an explicit user operation; automatic discovery of a project verifier is not permission to rewrite it.

Its output uses the portable project location supported by our current Pi installation:

```text
.agents/skills/verify-<project>/
  SKILL.md
  features/          # only when separate recipes earn their files
```

The generated skill is a cold-start operating recipe: target identity, prerequisites/permissions, launch/readiness, scenario selection, independent expected outcomes, concrete drive/read-back, evidence and owned-resource cleanup. Start with one high-value journey; reuse existing controls and fixtures. Do not automatically build a custom control CLI, install a test framework or inventory the entire product. Prove one journey only within approved execution scope; otherwise clearly label the generated instructions as unproved/draft.

Responsibilities remain separate:

| Owner | Responsibility |
| --- | --- |
| `agent-guardrails` | Whether a check is justified; oracle, safety, scope and repetition limits. |
| `write-implementation-plan` | Which acceptance outcome needs which minimal evidence, or applicable evidence reuse. |
| `orchestrate-implementation` | Who obtains/inspects evidence, and the assigned scope/budget; no duplicate parent reruns. |
| `verification-before-completion` | Whether evidence supports the completion claim and what remains unverified. |
| Project-local `verify-<project>` | How to obtain the selected proof safely in this repository. |
| New generator/update mode | Create and maintain that operating knowledge, not orchestrate product work. |

AGENTS instructions should route to the relevant project recipe only when a justified claim needs it, not demand a full app pass on every task. Project recipes inherit the global guardrails rather than defining competing test policies.

For Ariadne, useful proofs involve the actual supported CLI/MCP surface, a small independently specified synthetic data fixture, admitted/candidate identity, observable writes or refusals and permission boundaries—not screenshots of a green terminal. Choose a stable target: current main and the unfinished #74 worktree have different contracts. Do not generate a supposedly authoritative verifier from that incomplete worktree or use real company data to make it runnable.

## Limits and handoff

This is source-based research and a proposed design, not empirical validation of pstack's productivity claims. No pstack code, harness or generated skill was installed or executed; no application was launched. No repository test cleanup or skills-policy edit occurred. The OpenAI SWE-bench article found during discovery returned HTTP 403 and was excluded rather than cited from a search summary. The project artifact contract owns this capture; no duplicate global-wiki pages are created.

Next: approve the lean generator design together with the pending shared guardrails changes. Pin and attribute the adopted upstream material, reconcile contradictory fresh-rerun instructions, and avoid creating another verification framework.

## Sources

All pstack links below use the inspected immutable commit, not floating main.

- **P1:** [create-verification-skill](https://github.com/cursor/plugins/blob/f713f14203cd6420cec13cd7c55c32d598dbab68/pstack/skills/create-verification-skill/SKILL.md).
- **P2:** [maintain-verification-skill](https://github.com/cursor/plugins/blob/f713f14203cd6420cec13cd7c55c32d598dbab68/pstack/skills/maintain-verification-skill/SKILL.md).
- **P3:** [Verify the result and open a PR guide](https://github.com/cursor/plugins/blob/f713f14203cd6420cec13cd7c55c32d598dbab68/pstack/docs/guide/06-verify-and-ship.md).
- **P4:** [Feature-map index](https://github.com/cursor/plugins/blob/f713f14203cd6420cec13cd7c55c32d598dbab68/pstack/skills/create-verification-skill/references/feature-map-example/README.md), [create-note example](https://github.com/cursor/plugins/blob/f713f14203cd6420cec13cd7c55c32d598dbab68/pstack/skills/create-verification-skill/references/feature-map-example/create-note.md), [search example](https://github.com/cursor/plugins/blob/f713f14203cd6420cec13cd7c55c32d598dbab68/pstack/skills/create-verification-skill/references/feature-map-example/search.md).
- **P5:** [Prove It Works principle](https://github.com/cursor/plugins/blob/f713f14203cd6420cec13cd7c55c32d598dbab68/pstack/skills/principle-prove-it-works/SKILL.md).
- **P6:** [Pstack MIT license](https://github.com/cursor/plugins/blob/f713f14203cd6420cec13cd7c55c32d598dbab68/pstack/LICENSE).
- **G1:** [OpenHands: The Verification Stack](https://www.openhands.dev/blog/20260506-the-verification-stack), page date 2026-06-22; complete article inspected.
- **G2:** [Anthropic: Demystifying evals for AI agents](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents), relevant deterministic/outcome-grading passages inspected in the preceding research.
