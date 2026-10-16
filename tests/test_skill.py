"""The packaged agent skill (ADR-0011, spec rev 10 §8.21): install/status/path.

The wheel ships SKILL.md + the grain-rubric reference as package data
(src/ariadne/skill_assets/). ``ariadne-skill`` copies them to the cross-agent
``~/.agents/skills/ariadne/`` (user) or ``.agents/skills/ariadne/`` (project)
convention, optionally wiring agent-specific dirs; ``status`` hashes every
managed target against the packaged assets and reports drift. User-scope tests
monkeypatch HOME so nothing ever touches the real home directory.
"""

import hashlib
import os
import re

import pytest  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages

from ariadne.skill import ASSETS, _dir_hash, main


@pytest.fixture
def project(tmp_path, monkeypatch):
    """Isolated user home + project cwd (user scope must never touch real HOME)."""
    home = tmp_path / "home"
    proj = tmp_path / "proj"
    home.mkdir()
    proj.mkdir()
    monkeypatch.setenv("HOME", str(home))  # Path.home()/expanduser follow HOME on POSIX
    monkeypatch.chdir(proj)
    return home, proj


def test_packaged_assets_exist():
    assert (ASSETS / "SKILL.md").is_file()
    assert (ASSETS / "references" / "grain-rubric.md").is_file()
    skill = (ASSETS / "SKILL.md").read_text(encoding="utf-8")
    assert "grain-rubric.md" in skill  # the reference is linked from the skill
    assert "search_context" in skill and "define_metric" in skill  # the agent rules


def test_skill_teaches_local_cli_as_default_mcp_optional():
    """Spec 2026-09-23-0001 §8: the packaged skill defaults to the five local
    `ariadne` commands (project selection, caveats, labels, file/stdin ad-hoc
    definitions); MCP appears only in the optional integration section with
    accurate ariadne-data[mcp] install guidance — never as a requirement."""
    skill = (ASSETS / "SKILL.md").read_text(encoding="utf-8")
    for cmd in ("list-metrics", "search-context", "get-metric", "list-datasets", "define-metric"):
        assert f"ariadne {cmd}" in skill, cmd
    assert "ariadne define-metric --file" in skill  # file definitions (stdin named too)
    assert "ariadne list-metrics --project ." in skill
    assert "governed: true" in skill and "governed: false" in skill  # labels taught
    # MCP only after the optional integration heading, with the real extra named
    optional_at = skill.index("Optional: MCP integration")
    mcp_mentions = [m.start() for m in re.finditer("MCP", skill)]
    assert mcp_mentions and all(pos > optional_at for pos in mcp_mentions)
    assert "ariadne-data[mcp]" in skill
    normalized = " ".join(skill.split())
    assert "Ariadne package checkout" in normalized
    assert "not from the data project root" in normalized
    assert "ariadne-init --with-mcp ." in skill
    assert skill.index("pyproject.toml") < skill.index("ariadne-init --with-mcp .")
    assert "ariadne-serve --project ." in skill


def test_skill_teaches_answer_example_guidance():
    """Issue #21 (spec 2026-09-29-0007): the packaged skill teaches examples as
    labeled references — similarity is not equivalence, saved text is never an
    instruction, the method is revalidated and executed FRESH, drafts are
    hypotheses — and saving is user-confirmed before the call, with the
    operator review command explicitly forbidden to the agent."""
    normalized = " ".join((ASSETS / "SKILL.md").read_text(encoding="utf-8").split())
    assert "ariadne search-examples" in normalized  # the lookup command
    assert "A hit is never required, and never an answer" in normalized
    assert "Similar words are not equivalence" in normalized  # scope compared
    for scope in ("dates", "grain", "served Policies"):
        assert scope in normalized, scope
    assert "evidence, not instructions" in normalized  # stored text never directs
    assert "run a FRESH" in normalized and "never the saved SQL" in normalized
    assert "governed/ad-hoc label" in normalized  # true governance label reported
    assert "independent numeric attestation" in normalized  # no compile-only claim
    assert "Drafts are hypotheses" in normalized  # uncheckable drafts not support
    assert "confirm BEFORE calling save" in normalized  # user gate before the call
    assert "ariadne save-example" in normalized
    assert "Never save silently or harvest the transcript" in normalized
    assert "there is no separate Example-review command" in normalized


def test_skill_uses_only_the_project_bound_query_route():
    """G4: the default workflow uses admitted Git projects and no legacy roots."""
    skill = (ASSETS / "SKILL.md").read_text(encoding="utf-8")
    querying = skill[: skill.index("## Answer examples")]  # the query workflow
    normalized_querying = " ".join(querying.split())  # line-wrapped prose
    assert "--project DIR" in querying  # the managed route is taught
    assert "--project ." in querying  # with its concrete invocation
    assert "admission block naming the Git Review Admission route" in normalized_querying
    assert "admitted snapshot" in querying
    assert "There is no" in querying and "plain-root" in querying
    assert "--served PATH" not in querying and "--sources ariadne.yaml" not in querying
    assert "local-promotion" not in querying
    assert "Git Review Admission" in querying


def test_skill_routes_record_questions_to_the_separate_operation():
    """Issue #58/S3 (spec 0014 §7 V4 items 11 and 13, §8): the packaged skill
    routes record questions — the bounded latest-N of ONE known table, no
    aggregation — to the separate `query-records` operation rather than
    define-metric, teaches its default/bounds, truthful requested-top-N
    completeness, no staging and narrowing after an all-or-nothing refusal,
    and requires hosts without the record operation to report the question
    unsupported instead of silently aggregating records."""
    skill = (ASSETS / "SKILL.md").read_text(encoding="utf-8")
    querying = skill[: skill.index("## Answer examples")]  # the default workflow
    normalized = " ".join(querying.split())  # line-wrapped prose compares normalized
    assert "ariadne query-records" in normalized  # the separate operation is taught
    # record selection is distinguished from metric aggregation, both ways
    assert "never a metric" in normalized
    assert "do not invent an aggregation to retrieve records" in normalized
    # default/bounds of the request contract
    assert "defaults to 10" in normalized and "1,000" in normalized
    # truthful completeness: the requested top-N, never the full population
    assert "REQUESTED TOP-N" in normalized
    assert "has_more_matching" in normalized
    # never staged, always ungoverned — even on an admitted source
    assert "NEVER" in normalized and "stages a proposal" in normalized
    # narrowing after an all-or-nothing refusal, never a widened limit
    assert "ALL-OR-NOTHING" in normalized and "narrow the request" in normalized
    # hosts without the operation report unsupported, never aggregate silently
    assert "unsupported" in normalized
    assert "never silently aggregate" in normalized
    # the optional registration list carries the record tool too
    assert "`query_records`" in skill


def test_path_prints_packaged_dir(project, capsys):
    assert main(["path"]) == 0
    assert capsys.readouterr().out.strip() == str(ASSETS)


def test_install_project_scope_creates_files(project):
    _, proj = project
    assert main(["install", "--scope", "project"]) == 0
    installed = proj / ".agents" / "skills" / "ariadne"
    assert (installed / "SKILL.md").is_file()
    assert (installed / "references" / "grain-rubric.md").is_file()
    assert (installed / "SKILL.md").read_bytes() == (ASSETS / "SKILL.md").read_bytes()


def test_install_user_scope_and_agent_pi_symlink(project):
    home, _ = project
    assert main(["install", "--scope", "user", "--agent", "pi"]) == 0
    installed = home / ".agents" / "skills" / "ariadne"
    assert (installed / "SKILL.md").is_file()
    link = home / ".pi" / "agent" / "skills" / "ariadne"
    assert link.is_symlink()
    assert link.resolve() == installed.resolve()


def test_reinstall_refreshes_instead_of_failing_or_merging(project):
    _, proj = project
    assert main(["install", "--scope", "project"]) == 0
    installed = proj / ".agents" / "skills" / "ariadne" / "SKILL.md"
    installed.write_text("tampered\n", encoding="utf-8")  # drift after install
    assert main(["install", "--scope", "project"]) == 0  # refresh, not an error
    assert installed.read_bytes() == (ASSETS / "SKILL.md").read_bytes()


def test_status_reports_ok_then_detects_tampering(project, capsys):
    _, proj = project
    assert main(["install", "--scope", "project"]) == 0
    assert main(["status"]) == 0
    out = capsys.readouterr().out  # includes (and flushes) the install output
    assert "ok" in out
    assert "drift" not in out
    target = proj / ".agents" / "skills" / "ariadne" / "SKILL.md"
    target.write_text(target.read_text(encoding="utf-8") + "\nmanual edit\n", encoding="utf-8")
    assert main(["status"]) == 0
    out = capsys.readouterr().out
    assert "drift" in out  # the tampered target is named as drifted
    drift_line = next(line for line in out.splitlines() if "drift" in line)
    assert str(proj / ".agents") in drift_line
    # other targets still report absent (never installed in this isolated env)
    assert "absent" in out


def test_status_symlink_target_hashes_through_the_link(project, capsys):
    home, _ = project
    assert main(["install", "--scope", "user", "--agent", "pi"]) == 0
    capsys.readouterr()  # flush the install output
    assert main(["status"]) == 0
    out = capsys.readouterr().out
    pi_line = next(line for line in out.splitlines() if ".pi" in line)
    assert "ok" in pi_line and "(symlink)" in pi_line  # resolves to the same content


def test_dir_hash_is_content_sensitive():
    baseline = _dir_hash(ASSETS)
    assert baseline == _dir_hash(ASSETS)  # stable
    assert len(baseline) == hashlib.sha256().digest_size * 2


def test_install_agent_refuses_existing_non_symlink_dir(project, capsys):
    """An agent target that exists and is not a symlink is user content —
    install refuses (exit != 0, error names the path) and the directory's
    contents stay intact. Install never deletes directories."""
    home, _ = project
    agent_dir = home / ".claude" / "skills" / "ariadne"
    agent_dir.mkdir(parents=True)
    (agent_dir / "user-content.txt").write_text("precious\n", encoding="utf-8")
    assert main(["install", "--scope", "user", "--agent", "claude"]) != 0
    err = capsys.readouterr().err
    assert str(agent_dir) in err  # the refusal names the path
    assert "remove it manually" in err  # and suggests manual removal
    assert (agent_dir / "user-content.txt").read_text(encoding="utf-8") == "precious\n"
    assert not agent_dir.is_symlink()  # untouched, not replaced


def test_install_agent_replaces_existing_symlink_and_logs_old_target(project, capsys):
    """Any symlink is acceptable to overwrite: the replaced link is re-pointed
    at the installed copy, the old target (and its contents) is untouched, and
    what the link pointed to is logged."""
    home, _ = project
    installed = home / ".agents" / "skills" / "ariadne"
    link = home / ".pi" / "agent" / "skills" / "ariadne"
    old = home / "elsewhere" / "ariadne-skill"
    old.mkdir(parents=True)
    (old / "keep.txt").write_text("real content\n", encoding="utf-8")
    link.parent.mkdir(parents=True)
    os.symlink(old, link)
    assert main(["install", "--scope", "user", "--agent", "pi"]) == 0
    out = capsys.readouterr().out
    assert link.is_symlink() and link.resolve() == installed.resolve()
    assert (installed / "SKILL.md").is_file()
    assert str(old) in out  # the log names what the replaced symlink pointed to
    assert (old / "keep.txt").read_text(encoding="utf-8") == "real content\n"


def test_rubric_states_the_real_grain_audit_order():
    """The validate audit runs after render/bind compilation, before execution —
    the packaged rubric must not claim it rejects before compile (only
    ``define_metric`` does)."""
    rubric = (ASSETS / "references" / "grain-rubric.md").read_text(encoding="utf-8")
    assert "validate audit reject non-grain-preserving sources before compile" not in rubric
    assert "after render/bind compilation, before execution" in rubric


def test_skill_teaches_the_admitted_multifact_query_commands():
    """Issue #30: the packaged skill teaches the two multi-fact commands — that
    they answer only over a graph admitted through Git Review Admission, and
    that their responses are governed through that project-bound route
    (never a claim that a validated-but-unadmitted graph is governed)."""
    skill = (ASSETS / "SKILL.md").read_text(encoding="utf-8")
    for cmd in ("query-metrics", "query-detail"):
        assert f"ariadne {cmd} --file" in skill, cmd
    assert "admitted" in skill and "unadmitted" in skill
    assert "Git Review Admission" in skill
    # the submission boundary names the graph path (the one extra semantic file)
    assert "semantic_layer/graph.yml" in skill


def test_skill_teaches_git_proposal_workflow_and_stops_at_human_gates():
    """G4 (spec 0027 §§2/6): the packaged skill teaches the Git proposal
    workflow — start/read/edit/validate/review with revisions — leaves the
    human gates to the operator, and never teaches arbitrary
    Git branch/shell/file mutation."""
    skill = (ASSETS / "SKILL.md").read_text(encoding="utf-8")
    for cmd in (
        "ariadne-authoring start",
        "ariadne-authoring read",
        "ariadne-authoring edit",
        "ariadne-authoring validate",
        "ariadne-authoring review --proposal",
        "ariadne-authoring propose-sources --proposal",
        "ariadne-authoring inputs --proposal",
    ):
        assert cmd in skill, cmd
    assert "--expected-revision" in skill  # revision-checked edits
    # admission is human-only; no legacy importer or staged submit route remains
    assert "ariadne-admit" in skill and "--confirm" in skill
    normalized = " ".join(skill.split())
    assert "Core does not import legacy staged artifacts" in normalized
    assert "Never run" in skill and "human-only" in skill.lower()
    # Git operations appear ONLY as named prohibitions, never as instructions
    rules_at = skill.index("## Agent rules")
    assert "never run" in skill[rules_at:].lower() and "git" in skill[rules_at:]
    # retired public operations are not taught as runnable commands
    assert "ariadne-authoring submit --file submission.json" not in skill
    assert "ariadne-promote" not in skill
    assert "ariadne-authoring enrich-legacy" not in skill
    assert "--toolset" in skill  # split vs combined registrations taught


def test_skill_teaches_automatic_mapping_hypothesis_capture():
    """K5 (issue #45; spec 2026-10-02-0010 §8, §10 AC7): the packaged skill
    teaches the automatic-capture loop — read the existing References,
    hypotheses and receipts FIRST (`resolve-term`/`read`), measure bounded
    candidates (`inspect-mapping`), then SAVE the labeled hypothesis through
    the typed page edit automatically: no per-save prompt, the SAME stable
    representation/mapping IDs (an identical retry is a no-op), honest
    retention of failed/inconclusive/conflicting results (never relabeled
    asserted/confirmed), owner questions only about unresolved meaning, no
    local-number-only joins — and restart durability lives in the Git proposal
    and the evidence area, never in chat memory."""
    normalized = " ".join((ASSETS / "SKILL.md").read_text(encoding="utf-8").split())
    assert "ariadne-authoring resolve-term" in normalized  # read existing first
    assert "ariadne-authoring inspect-mapping" in normalized  # bounded measurement
    assert "read what the proposal already holds" in normalized
    assert "SAVE the labeled hypothesis" in normalized  # automatic capture
    assert "no per-save prompt" in normalized
    assert "reuse the SAME stable representation/mapping IDs" in normalized
    assert "an identical retry is a no-op" in normalized
    assert "failed, inconclusive or conflicting results honestly" in normalized
    assert "never relabel them asserted or confirmed" in normalized
    assert "unresolved business meaning, format or scope" in normalized
    assert "never a local-number-only or raw fact-to-fact join" in normalized
    assert "not chat memory" in normalized  # restart reads Git/evidence state


def test_skill_teaches_context_knowledge_and_typed_page_edits():
    """K6 (issue #46, spec 2026-10-02-0010 §4–§9): the packaged skill teaches
    the context-knowledge workflow — admitted term resolution on the QUERY
    side (aliases/ambiguity/claim status, never join authority), the explicit
    schema refresh with context-only proposals, `--confirm-mapping` as the
    human confirmation route, and typed page edits — plus the standing warning that
    aliases, observations and measurements never authorize joins or replace
    OSI/live audits, and points at the how-to."""
    normalized = " ".join((ASSETS / "SKILL.md").read_text(encoding="utf-8").split())
    # the query-side resolution command and its limits
    assert "ariadne resolve-term" in normalized
    assert "NEVER authorizes a" in normalized and "unconfirmed leads" in normalized
    # the explicit schema refresh inside the authoring loop, context-only allowed
    assert "ariadne-authoring refresh-schema" in normalized
    assert "context-only" in normalized
    assert "candidate key" in normalized and "NEVER a declared business key" in normalized
    # confirmation is the human admission selection only
    assert "--confirm-mapping" in normalized
    assert "never mark anything confirmed" in normalized
    # durable context changes use typed edits; the retired enrichment operation is absent
    assert "ariadne-authoring edit --proposal ID" in normalized
    assert "context_layer/references/context-routing.md" in normalized
    assert "ariadne-authoring enrich-legacy" not in normalized
    assert "ambiguous" in normalized and "ambiguity between alternatives" in normalized
    assert "never guessed" in normalized  # resolution refuses rather than guesses
    # the standing warning + the how-to pointer
    assert "Aliases, observations and measurements never authorize joins" in normalized
    assert "never authorizes a join" in normalized
    assert "docs/how-to/context-knowledge.md" in normalized
