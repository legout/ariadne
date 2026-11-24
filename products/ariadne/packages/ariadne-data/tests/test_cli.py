"""Local JSON CLI (ticket #8): the five operations as flat subcommands.

Public-seam tests: every invocation goes through ``ariadne.cli.main(argv, stdin)``
(the exact target of the ``ariadne`` console script) and asserts the §4 JSON
contract — exactly one JSON value + newline on stdout for success, exactly one
``{"error": {"type", "message"}}`` object on stderr plus a nonzero exit for
failure, and no success value on stdout for a failed invocation. The synthetic
retail project is one REAL native Knowledge Base (public initializer plus Git
Authoring admission); the database is deterministic — no network, no LLM.
Behavior parity is asserted against the public project runtime factory.
"""

import asyncio
import io
import json
import os
import re
import subprocess
import sys
from contextlib import redirect_stdout
from pathlib import Path

import pytest  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:  # keep tests runnable from the source tree
    sys.path.insert(0, str(REPO_ROOT))

from ariadne.authoring import AuthoringProject  # noqa: E402
from ariadne.cli import main as cli  # noqa: E402
from ariadne.query import QueryRuntime  # noqa: E402
from tests.test_git_authoring import approved, complete_bundle_project, run_git  # noqa: E402
from tests.test_serve import (  # noqa: E402
    GOLDEN_OKF,
    GOLDEN_OSI,
    GOLDEN_POLICY_EMEA,
    GOLDEN_POLICY_STATUS,
    GOTCHA_1,
    GOTCHA_2,
    seed_demo_db,
)

# The retail demo's authored native identity (spec0035 §2: one explicit
# namespace, machine-local private profile and publication destination OUTSIDE
# the content repository, beside the project root) and the one catalog asset
# whose generated native Table profile binds ``demo.main.orders``.
NAMESPACE = "urn:uuid:retail-demo-cli"
_PRIVATE_PROFILE = "ariadne-private-profile.json"
_PUBLISHED = "published"
_DEMO_ASSET = {"source": "demo", "catalog": "demo", "schema": "main", "table": "orders"}

# Each governed OSI metric's typed Policy closure: the seed-note rules its
# sanctioned expression implements — the fixture's preserved financial meaning
# (billable-status exclusion for every number, the EMEA cutover for amounts).
# gross_margin is a model-scoped composition of AGG(orders.<metric>) terms; the other
# metrics are dataset-scoped on ``orders`` (identity key ``orders.<metric>``).
_DERIVED = {"gross_margin"}


def _key(metric: str) -> str:
    return metric if metric in _DERIVED else f"orders.{metric}"


_METRIC_CLOSURE = {
    "gross_margin": ("order-status-billing", "emea-currency-cutover"),
    "gross_revenue": ("order-status-billing", "emea-currency-cutover"),
    "cogs": ("order-status-billing", "emea-currency-cutover"),
    "order_count": ("order-status-billing",),
}
# The OSI model's governed meanings, authored beside their definitions.
_METRIC_DESCRIPTIONS = {
    "gross_margin": "Ratio of sums, not an average of per-row margins",
    "gross_revenue": "Billed revenue in USD excluding non-billable statuses",
    "cogs": "Direct cost of goods in USD excluding non-billable statuses",
    "order_count": "Count of billable orders",
}
# The gross-margin page keeps the golden governed-definition body (both
# gotcha rules, verbatim); the base metrics restate their own rule citations.
_METRIC_BODIES = {
    "gross_margin": GOLDEN_OKF.split("---", 2)[2],
    "gross_revenue": (
        f"# gross_revenue\n\nGoverned definition: {GOTCHA_1}; pre-2024 EMEA "
        f"amounts follow the cutover rule ({GOTCHA_2}).\n"
    ),
    "cogs": (
        f"# cogs\n\nGoverned definition: {GOTCHA_1}; pre-2024 EMEA product "
        f"costs follow the cutover rule ({GOTCHA_2}).\n"
    ),
    "order_count": f"# order_count\n\nGoverned definition: {GOTCHA_1}.\n",
}


def _native_policy_page(slug: str, title: str, rule: str, tag: str, body: str) -> str:
    """One producer-native Policy page: the original Golden policy body
    verbatim inside its typed native wrapper (identity/metadata unchanged)."""
    return (
        "---\n"
        f'id: "entity:{slug}"\n'
        f'title: "{title}"\n'
        "entity_types:\n  - policy\n"
        f"tags: [policy, {tag}]\n"
        f'summary: "{rule}."\n'
        "lifecycle: approved\n"
        "visibility: public\n"
        "sources:\n"
        "  - id: seed-notes\n"
        "    title: Seed notes\n"
        "ariadne_profile:\n"
        "  version: 1\n"
        "  kind: policy\n"
        "  required_policies: []\n"
        "  native:\n"
        "    type: policy\n"
        f"    title: {title}\n"
        f"    description: {rule}.\n"
        f"    tags: [policy, {tag}]\n"
        "    status: stable\n"
        "    stale_after: 2027-12-31\n"
        "    sources:\n"
        "      - id: seed-notes\n"
        "        title: Seed notes\n"
        "        resource: data/seed_notes.md\n"
        f"---{body}"
    )


def _native_metric_page(metric: str, policies: tuple[str, ...]) -> str:
    """One producer-native Metric page: ``metric_ref`` binds the OSI metric,
    ``required_policies`` carries its typed Policy closure (spec0035 §5)."""
    required = "".join(
        f"    - namespace: {NAMESPACE}\n      entity_id: entity:{policy}\n" for policy in policies
    )
    sources = "".join(f"  - id: {policy}\n    title: {policy}\n" for policy in policies)
    native_sources = "".join(
        f"      - id: {policy}\n        title: {policy}\n        resource: policies/{policy}.md\n"
        for policy in policies
    )
    description = _METRIC_DESCRIPTIONS[metric]
    return (
        "---\n"
        f'id: "entity:{metric.replace("_", "-")}"\n'
        f'title: "{metric}"\n'
        "entity_types:\n  - metric\n"
        "tags: [metric]\n"
        f'summary: "{description}."\n'
        "lifecycle: approved\n"
        "visibility: public\n"
        f"sources:\n{sources}"
        "ariadne_profile:\n"
        "  version: 1\n"
        "  kind: metric\n"
        "  metric_ref:\n"
        f"    model: orders\n    metric: {_key(metric)}\n"
        "  required_policies:\n"
        f"{required}"
        "  native:\n"
        "    type: metric\n"
        "    status: stable\n"
        f"    title: {metric}\n"
        f"    description: {description}.\n"
        "    tags: [metric]\n"
        "    stale_after: 2027-12-31\n"
        "    sources:\n"
        f"{native_sources}"
        f"    governed_by: policies/{policies[0]}.md\n"
        "    dimensions:\n      - region\n      - status\n      - order_date\n"
        "    grain:\n      primary_key: [order_id]\n"
        "      cardinality_enforcement: strict_1_to_1\n"
        f"---\n{_METRIC_BODIES[metric]}"
    )


def _selector_text() -> str:
    """The revision-4 integrated selector: the §10.1 opt-in plus the authored
    binding inventory classifying every metric's complete typed closure."""
    bindings = "".join(
        f"    - subject: {{kind: metric, identity: orders::{_key(metric)}}}\n"
        f"      policy: {{namespace: {NAMESPACE}, entity_id: entity:{policy}}}\n"
        "      operations: [get_metric, query_metrics]\n"
        "      enforcement: null\n"
        for metric, policies in _METRIC_CLOSURE.items()
        for policy in policies
    )
    return (
        "version: 1\nmode: integrated\nsubtree: knowledge\n"
        f"namespace: {NAMESPACE}\nprofile: ariadne-context/1\nsupport_revision: 4\n"
        f"policy_bindings:\n  version: 1\n  bindings:\n{bindings}"
    )


def create_git_demo_project(root: Path) -> tuple[Path, Path]:
    """Build and human-admit the synthetic retail project as one real native
    Knowledge Base: the public initializer scaffolds ``knowledge/`` (explicit
    namespace and machine-local private profile, actual Control File + Source
    Reference Manifest), the human base revision adds the demo SQLite source,
    the OSI model and the typed native metric/Policy pages, and one Git
    proposal carries the generated Table profile (``refresh_schema``), full
    native validation and the composite human admission."""
    from ariadne import admission
    from ariadne.init import _scaffold

    root.mkdir(parents=True, exist_ok=True)
    run_git(root, "init", "-q")
    run_git(root, "config", "user.name", "Ariadne Tests")
    run_git(root, "config", "user.email", "tests@ariadne.local")
    _scaffold(root, NAMESPACE, root.parent / _PRIVATE_PROFILE)
    db = seed_demo_db(root / "data" / "demo.db")
    (root / "ariadne.yaml").write_text(
        "sources:\n  - name: demo\n    type: sqlite\n    path: data/demo.db\n",
        encoding="utf-8",
    )
    (root / "data" / "seed_notes.md").write_text(
        "# Seed notes\n\nExclude CANCELLED and RETURNED rows. "
        "Convert pre-2024 EMEA EUR/GBP values before aggregation.\n",
        encoding="utf-8",
    )
    model = root / "semantic_layer" / "models" / "orders.yml"
    model.parent.mkdir(parents=True, exist_ok=True)
    model.write_text(GOLDEN_OSI, encoding="utf-8")
    pages = {
        "policies/order-status-billing.md": _native_policy_page(
            "order-status-billing",
            "Order status billing",
            GOTCHA_1,
            "billing",
            GOLDEN_POLICY_STATUS.split("---", 2)[2],
        ),
        "policies/emea-currency-cutover.md": _native_policy_page(
            "emea-currency-cutover",
            "EMEA currency cutover",
            GOTCHA_2,
            "currency",
            GOLDEN_POLICY_EMEA.split("---", 2)[2],
        ),
        **{
            f"metrics/{metric}.md": _native_metric_page(metric, policies)
            for metric, policies in _METRIC_CLOSURE.items()
        },
    }
    kb = root / "knowledge"
    for rel, content in pages.items():
        page = kb / rel
        page.parent.mkdir(parents=True, exist_ok=True)
        page.write_text(content, encoding="utf-8")
    (root / "context_integration.yaml").write_text(_selector_text(), encoding="utf-8")
    tracked = [
        "AGENTS.md",
        ".env.example",
        ".gitignore",
        "ariadne.yaml",
        "data/seed_notes.md",
        "semantic_layer/models/orders.yml",
        "context_integration.yaml",
        "knowledge",
    ]
    run_git(root, "add", "--", *tracked)
    run_git(root, "commit", "-q", "-m", "human: synthetic retail project", "--", *tracked)
    api = AuthoringProject(root)
    started = api.start_proposal()
    approved(api, root, started)
    refreshed = api.refresh_schema(
        started["proposal"], started["candidate_revision"], [_DEMO_ASSET]
    )
    validated = api.validate_proposal(started["proposal"], refreshed["revision"])
    assert validated["ok"] is True, validated["errors"]
    review = api.review_proposal(started["proposal"])
    assert review["revision"] == validated["revision"]
    with redirect_stdout(io.StringIO()):
        composite = admission.overall_review(
            root,
            review["proposal"],
            review["revision"],
            review["review_digest"],
            destination=root.parent / _PUBLISHED,
            expected_current="none",
        )
        admission.admit_revision(
            root,
            review["proposal"],
            review["revision"],
            review["review_digest"],
            confirmed_by="human:synthetic-operator",
            overall_preview=composite,
            confirmed_overall_digest=composite["digest"],
        )
    return root, db


@pytest.fixture(scope="module")
def served(tmp_path_factory):
    """A synthetic retail project with its exact validated Git revision admitted."""
    return create_git_demo_project(tmp_path_factory.mktemp("cli") / "project")


def run_cli(served, _unused_path, *args, stdin=None):
    project, _db = served
    return cli([*args, "--project", str(project), "--json"], stdin=stdin)


def error_payload(err: str):
    """Parse and shape-check one §4 JSON error object (stderr must be exactly it)."""
    payload = json.loads(err)
    assert payload["error"]["message"]
    assert set(payload) == {"error"} and set(payload["error"]) == {"type", "message"}
    return payload["error"]


def make_runtime(served, _unused_path):
    project, _db = served
    return QueryRuntime.open_project(project)


def project_refs(served):
    project, _db = served
    return run_git(project, "for-each-ref", "--format=%(refname)=%(objectname)", "refs/heads")


# --- All five commands: parity with the runtime + the one-value JSON contract --


def test_list_metrics_matches_runtime_one_json_value(served, tmp_path, capsys):
    code = run_cli(served, tmp_path / "staging", "metrics")
    assert code == 0
    out = capsys.readouterr().out
    assert out.endswith("\n") and out.count("\n") == 1  # exactly one JSON value + newline
    assert json.loads(out) == asyncio.run(make_runtime(served, tmp_path / "staging").list_metrics())


def test_list_datasets_matches_runtime(served, tmp_path, capsys):
    code = run_cli(served, tmp_path / "staging", "datasets")
    assert code == 0
    assert json.loads(capsys.readouterr().out) == asyncio.run(
        make_runtime(served, tmp_path / "staging").list_datasets()
    )


def test_get_metric_matches_runtime_including_context(served, tmp_path, capsys):
    code = run_cli(served, tmp_path / "staging", "query", "gross_margin", "--by", "region")
    assert code == 0
    result = json.loads(capsys.readouterr().out)
    expected = asyncio.run(
        make_runtime(served, tmp_path / "staging").get_metric("gross_margin", ["region"])
    )
    # Row order is not guaranteed across independent executions (no ORDER BY in
    # the compiled SQL) — compare order-independently, shape and values exactly.
    assert sorted(result["rows"], key=lambda r: r["region"]) == sorted(
        expected["rows"], key=lambda r: r["region"]
    )
    result["rows"] = expected["rows"]
    # The advisory data_signals view carries the assessment instant of ITS OWN
    # execution (issue #53: every read is a fresh pure assessment) — like row
    # order above, it is not stable across independent executions; compare the
    # view with the instant normalized out, everything else exactly.
    result["data_signals"]["assessed_at"] = expected["data_signals"]["assessed_at"]
    assert result == expected  # metric/dimensions/columns/sql/governed/context
    assert result["governed"] is True
    assert result["rows"] and "CANCELLED" in result["sql"]


def test_get_metric_repeats_dimensions(served, tmp_path, capsys):
    code = run_cli(
        served,
        tmp_path / "staging",
        "query",
        "order_count",
        "--by",
        "region",
        "--by",
        "status",
    )
    assert code == 0
    result = json.loads(capsys.readouterr().out)
    assert result["dimensions"] == ["region", "status"]
    assert result["rows"] and {"region", "status"} <= set(result["rows"][0])


def test_get_metric_serializes_temporal_values_as_iso(served, tmp_path, capsys):
    code = run_cli(served, tmp_path / "staging", "query", "order_count", "--by", "order_date")
    assert code == 0
    result = json.loads(capsys.readouterr().out)
    dates = [row["order_date"] for row in result["rows"]]
    assert dates and all(re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) for value in dates)


def test_get_metric_unknown_metric_error_shape(served, tmp_path, capsys):
    code = run_cli(served, tmp_path / "staging", "query", "nonexistent")
    assert code == 1
    captured = capsys.readouterr()
    assert captured.out == ""  # no success value on stdout
    error = error_payload(captured.err)
    assert error["type"] == "ValueError"
    # §7/§8.12: unknown-metric message verbatim — available metrics + ad-hoc route
    assert "unknown metric" in error["message"]
    assert "gross_margin" in error["message"]


def test_local_cli_runs_with_mcp_import_blocked(served, tmp_path):
    """§7/AC-1 in-suite: with ``mcp`` blocked, the base import chain
    (ariadne.query + ariadne.cli) still serves the full local interface."""
    root, db = served
    code = (
        "import sys; sys.modules['mcp'] = None; "
        "import ariadne.cli, ariadne.query; "
        "sys.exit(ariadne.cli.main(sys.argv[1:]))"
    )
    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            code,
            "metrics",
            "--json",
            "--project",
            str(root),
        ],
        capture_output=True,
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT)},
        timeout=120,
        check=False,
    )
    assert proc.returncode == 0
    names = json.loads(proc.stdout)
    assert any("gross_margin" in str(entry) for entry in names)


# --- ariadne-serve: the optional-extra hint, without masking -------------------


def _serve_args(served, tmp_path):
    root, _db = served
    return ["--project", str(root)]


def test_serve_main_hints_mcp_extra_when_mcp_absent(served, tmp_path):
    # A fresh interpreter keeps earlier MCP tests from caching the imported SDK.
    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; sys.modules['mcp'] = None; "
            "from ariadne.serve import main; sys.exit(main(sys.argv[1:]))",
            *_serve_args(served, tmp_path),
        ],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT)},
        timeout=120,
        check=False,
    )
    assert proc.returncode == 1
    assert "pip install 'ariadne-data[mcp]'" in proc.stderr


def test_serve_main_does_not_mask_unrelated_missing_modules(served, tmp_path, monkeypatch):
    from ariadne import serve

    def boom(facade, **kwargs):  # G6: build_app now carries the toolset kwarg
        raise ModuleNotFoundError("No module named 'flask'", name="flask")

    monkeypatch.setattr(serve, "build_app", boom)
    with pytest.raises(ModuleNotFoundError):
        serve.main(_serve_args(served, tmp_path))


def test_serve_main_startup_failure_not_masked_as_missing_mcp(tmp_path, monkeypatch, capsys):
    monkeypatch.setitem(sys.modules, "mcp", None)
    from ariadne import serve

    code = serve.main(["--project", str(tmp_path / "missing-project")])
    assert code == 1
    err = capsys.readouterr().err
    assert "pip install 'ariadne-data[mcp]'" not in err  # the hint never masks startup failures
    assert "error:" in err  # the runtime startup failure itself


def test_query_metrics_without_admission_errors_per_the_json_contract(tmp_path, capsys):
    """A project without a human admission fails closed with one JSON error."""
    project = tmp_path / "no-admission"
    code = cli(
        ["query", "gross_margin", "--project", str(project), "--json"],
    )
    assert code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    error = json.loads(captured.err)
    assert error["error"]["type"] == "ValueError"
    assert "admission" in error["error"]["message"].lower()


# --- the one CLI: the exhaustive command table and the removals (spec 0040 §3.1) --

_TABLE = (
    "init add draft validate diff preview approve status query detail metrics datasets "
    "search page serve skill profile migrate"
).split()


@pytest.mark.parametrize(
    "removed",
    [
        "list-metrics",
        "list-datasets",
        "get-metric",
        "define-metric",
        "query-metrics",
        "query-detail",
        "query-records",
        "search-context",
        "search-examples",
        "save-example",
        "resolve-term",
        "review",
        "setup",
    ],
)
def test_removed_commands_have_no_alias(removed, capsys):
    assert cli([removed]) == 1
    error = error_payload(capsys.readouterr().err)
    assert error["type"] == "UsageError"


def test_every_documented_subcommand_has_working_help(capsys):
    from ariadne.cli import build_parser

    commands = list(_TABLE)
    for command in commands:
        with pytest.raises(SystemExit) as exc:  # argparse prints the help, then exits 0
            build_parser().parse_args([command, "--help"])
        assert exc.value.code == 0
        assert command in capsys.readouterr().out


def test_skill_accepts_json_and_every_table_command_takes_it(capsys):
    """Finding 6: `--json` works for `skill` too (one JSON value on stdout)."""
    assert cli(["skill", "path", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True and payload["output"]


def test_json_prompts_go_to_stderr_and_stdout_is_only_the_result(tmp_path, capsys, monkeypatch):
    """Finding 6 (second pass): interactive commands under --json keep their prompt off
    stdout: `draft discard --json` and `init --json` (Git identity prompts) write one JSON
    value to stdout and the prompt to stderr."""
    import io
    import os

    from ariadne import draft
    from ariadne.authoring import AuthoringProject

    class Tty(io.StringIO):
        def isatty(self):
            return True

    monkeypatch.setenv("HOME", str(tmp_path / "home"))  # never the real ~/.config/ariadne
    (tmp_path / "home").mkdir()
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", os.devnull)
    for key in ("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL"):
        monkeypatch.delenv(key, raising=False)
    project = complete_bundle_project(tmp_path)
    AuthoringProject(project).start_proposal()
    assert draft.status(project) is not None
    answers, shown = Tty("yes\n"), Tty()
    monkeypatch.setattr(sys, "stdin", answers)
    monkeypatch.setattr(sys, "stdout", shown)
    err = Tty()
    monkeypatch.setattr(sys, "stderr", err)
    assert cli(["draft", "discard", "--json", "--project", str(project)]) == 0
    assert "[yes/no]" in err.getvalue() and "[yes/no]" not in shown.getvalue()
    assert json.loads(shown.getvalue())["discarded"] is True

    fresh = tmp_path / "fresh"
    fresh.mkdir()
    subprocess.run(["git", "init", "-q", str(fresh)], check=True)
    answers, shown, err = Tty("Name\nn@example.test\n"), Tty(), Tty()
    monkeypatch.setattr(sys, "stdin", answers)
    monkeypatch.setattr(sys, "stdout", shown)
    monkeypatch.setattr(sys, "stderr", err)
    code = cli(["init", str(fresh), "--json", "--project", str(fresh)], stdin=answers)
    assert code == 0, err.getvalue()
    assert "Git user.name" in err.getvalue() and "Git user.name" not in shown.getvalue()
    assert json.loads(shown.getvalue())["initialized"] is True
    assert (Path.home() / ".config" / "ariadne").is_dir()  # profiles landed under the test HOME

    # a normal terminal operator whose STDERR is redirected (not a TTY) is still prompted:
    # the interaction check stays on stdin/stdout, only the prompt text moves
    redirected = tmp_path / "redirected"
    redirected.mkdir()
    subprocess.run(["git", "init", "-q", str(redirected)], check=True)
    answers, shown, err = Tty("Name\nn@example.test\n"), Tty(), io.StringIO()  # err: no isatty
    monkeypatch.setattr(sys, "stdin", answers)
    monkeypatch.setattr(sys, "stdout", shown)
    monkeypatch.setattr(sys, "stderr", err)
    code = cli(["init", str(redirected), "--json", "--project", str(redirected)], stdin=answers)
    assert code == 0, err.getvalue()
    assert "Git user.name" in err.getvalue()

    # stdout NOT a terminal: no prompt may be allowed, whatever stderr is
    nonterminal = tmp_path / "nonterminal"
    nonterminal.mkdir()
    subprocess.run(["git", "init", "-q", str(nonterminal)], check=True)
    answers, shown, err = Tty("Name\nn@example.test\n"), io.StringIO(), Tty()
    monkeypatch.setattr(sys, "stdin", answers)
    monkeypatch.setattr(sys, "stdout", shown)
    monkeypatch.setattr(sys, "stderr", err)
    assert cli(["init", str(nonterminal), "--json", "--project", str(nonterminal)]) == 1
    assert "no Git identity resolves" in err.getvalue()
