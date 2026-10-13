"""Spec 0019 AC1–7: operator CLI composition of unchanged human gates.

Real temporary proposals/bundles and native review payloads are the oracle;
recording delegates check exactly-once invocation and inert selection.
"""

import io
import json
import os
import shlex
import shutil
import sys
from pathlib import Path

import pytest  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ariadne import (  # noqa: E402
    admission,
    authoring,
    execution,
    promote,
    query,
    skill,
    sources,
    status,
)
from ariadne.cli import main as cli  # noqa: E402
from tests.test_authoring import (  # noqa: E402
    approved_project,
    bundle_submission,
    write_submission,
)
from tests.test_context_admission import (  # noqa: E402
    REFERENCE_EDIT,
    TABLE_EDIT,
    admitted_candidate,
    context_only_candidate,
    order_reference_page,
    orders_resource,
    table_page,
)
from tests.test_git_authoring import branch_of  # noqa: E402
from tests.test_promote import make_staging  # noqa: E402


class Terminal(io.StringIO):
    def isatty(self):
        return True


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", os.devnull)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.chdir(tmp_path)


def run_review(*args, answers="", tty=True, output_tty=True, monkeypatch):
    monkeypatch.setattr(sys.stdout, "isatty", lambda: output_tty)
    stdin = Terminal(answers) if tty else io.StringIO(answers)
    return cli(["review", *map(str, args)], stdin=stdin)


def governed(project):
    """Ignore operational caches/locks; pin governed bytes and descriptors."""
    return {
        str(p.relative_to(project)): p.read_bytes()
        for p in project.rglob("*")
        if p.is_file()
        and ".git" not in p.relative_to(project).parts
        and ".ariadne/locks/" not in p.as_posix()
    }


@pytest.mark.parametrize("tty,output_tty", [(False, True), (True, False)])
def test_unadmitted_native_payload_noninteractive_is_read_only(
    tmp_path, monkeypatch, capsys, tty, output_tty
):
    project, api, expected = admitted_candidate(tmp_path / "managed")
    before = governed(project)

    def forbidden(*args, **kwargs):
        pytest.fail("review constructed a runtime/opened a source/invoked a human gate")

    for module, name in (
        (query.QueryRuntime, "__init__"),
        (query.QueryRuntime, "open_project"),
        (sources, "build_connection"),
        (execution, "build_connection"),
        (execution.DuckDBExecution, "__init__"),
        (admission, "main"),
        (promote, "main"),
    ):
        monkeypatch.setattr(module, name, forbidden)
    assert (
        run_review(
            "--project",
            project,
            "--proposal",
            expected["proposal"],
            answers="yes\nyes\n",
            tty=tty,
            output_tty=output_tty,
            monkeypatch=monkeypatch,
        )
        == 0
    )
    output = capsys.readouterr().out
    native = json.JSONDecoder().raw_decode(output[output.index("{") :])[0]
    assert native == expected == api.review_proposal(expected["proposal"])
    assert "not_applicable" in output and expected["review_digest"] in output
    assert "ariadne-admit" in output and "--confirm-mapping" in output
    assert not (project / ".ariadne/current.json").exists()
    assert governed(project) == before


def native_admission_args(project, payload, selections=()):
    return [
        "--project",
        str(project),
        "--proposal",
        payload["proposal"],
        "--revision",
        payload["revision"],
        "--reviewed-digest",
        payload["review_digest"],
        "--confirm",
        *[v for s in selections for v in ("--confirm-mapping", s)],
    ]


def record_admissions(monkeypatch):
    results = []
    native = admission.admit_revision

    def record(*args, **kwargs):
        result = native(*args, **kwargs)
        results.append(result)
        return result

    monkeypatch.setattr(admission, "admit_revision", record)
    return results


def test_all_selections_inert_until_one_exact_native_command(tmp_path, monkeypatch, capsys):
    project, api, candidate = context_only_candidate(tmp_path / "managed")
    edited = api.edit_proposal(
        candidate["proposal"],
        candidate["revision"],
        {**REFERENCE_EDIT, "name": "other-number", "content": order_reference_page()},
    )
    validated = api.validate_proposal(candidate["proposal"], edited["revision"])
    assert validated["ok"]
    payload = api.review_proposal(candidate["proposal"])
    selections = [
        "order-number:global-order-concatenation",
        "other-number:global-order-concatenation",
    ]
    expected_argv = native_admission_args(project, payload, selections)
    native = admission.main
    calls = []
    before = governed(project)
    results = record_admissions(monkeypatch)

    def invoke(argv):
        assert argv == expected_argv
        assert not calls
        calls.append(argv)
        return native(argv)  # the exact hand-typed CLI entry point, no alternate writer

    class CheckingTerminal(Terminal):
        def readline(self, *args):
            assert calls == [] and governed(project) == before
            output = capsys.readouterr().out
            if self.tell() == 0:
                assert payload["review_digest"] in output
                assert "store_id" in output and "Verified citation/evidence identities" in output
            if self.tell() == len("yes\nyes\n"):
                assert payload["revision"] in output and payload["review_digest"] in output
                assert "Complete mapping selection: " + json.dumps(selections) in output
                assert shlex.join(["ariadne-admit", *expected_argv]) in output
            assert "Select --confirm-mapping order-number:local-to-global-prefix" not in output
            return super().readline(*args)

    monkeypatch.setattr(admission, "main", invoke)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    assert (
        cli(
            ["review", "--project", str(project), "--proposal", payload["proposal"]],
            stdin=CheckingTerminal("yes\nyes\nyes\n"),
        )
        == 0
    )
    assert calls == [expected_argv] and len(results) == 1
    assert json.dumps(results[0]) in capsys.readouterr().out
    current = admission.load_current(project)
    assert current is not None
    assert current["commit"] == payload["revision"]
    assert current["review_digest"] == payload["review_digest"]
    assert [f"{m['reference']}:{m['mapping']}" for m in current["confirmed_mappings"]] == selections


def test_bounded_native_parts_display_required_scope_before_selection(
    tmp_path, monkeypatch, capsys
):
    project, api, candidate = context_only_candidate(tmp_path / "managed")
    page = order_reference_page().replace(
        "ariadne:\n", "# padding\n" * (authoring.EVIDENCE_PART_CHARS // 10 + 1) + "ariadne:\n"
    )
    edited = api.edit_proposal(
        candidate["proposal"], candidate["revision"], {**REFERENCE_EDIT, "content": page}
    )
    assert api.validate_proposal(candidate["proposal"], edited["revision"])["ok"]
    expected_part = api.review_proposal(candidate["proposal"], part=2)
    before = governed(project)
    calls = []
    monkeypatch.setattr(admission, "main", lambda argv: calls.append(argv))
    assert (
        run_review(
            "--project",
            project,
            "--proposal",
            candidate["proposal"],
            answers="\nno\n",
            monkeypatch=monkeypatch,
        )
        == 0
    )
    output = capsys.readouterr().out
    assert json.dumps(expected_part, indent=2) in output
    scope = output.split("Required scope/representations — exact reviewed Reference page:")[1]
    assert "store_id" in scope and "scope:" in scope
    assert calls == [] and governed(project) == before


def test_skipped_assertions_stay_asserted_without_confirmation(tmp_path, monkeypatch, capsys):
    project, api, payload = admitted_candidate(tmp_path / "managed")
    results = record_admissions(monkeypatch)
    assert (
        run_review(
            "--project",
            project,
            "--proposal",
            payload["proposal"],
            answers="\nyes\n",
            monkeypatch=monkeypatch,
        )
        == 0
    )
    assert results[0]["confirmed_mappings"] == []
    assert results[0]["retained_confirmations"] == []
    current = admission.load_current(project)
    assert current is not None
    page = project / current["snapshot"] / "context_layer/references/order-number.md"
    meta = yaml.safe_load(page.read_text().split("---")[1])
    assert [m["claim"] for m in meta["ariadne"]["mappings"]] == ["hypothesis", "asserted"]
    assert current["confirmed_mappings"] == []
    output = capsys.readouterr().out
    assert output.count("Select --confirm-mapping") == 1
    assert "Select --confirm-mapping order-number:local-to-global-prefix" not in output
    assert json.dumps(results[0]) in output


def test_native_retained_and_lapsed_outcomes_are_reported(tmp_path, monkeypatch, capsys):
    project, api, first = admitted_candidate(tmp_path / "managed")
    selection = "order-number:global-order-concatenation"
    assert admission.main(native_admission_args(project, first, [selection])) == 0
    capsys.readouterr()
    results = record_admissions(monkeypatch)
    edited = api.edit_proposal(
        first["proposal"],
        branch_of(project, first["proposal"]),
        {
            **TABLE_EDIT,
            "content": table_page().replace(
                "One row per store-scoped order.", "Unrelated description."
            ),
        },
    )
    assert api.validate_proposal(first["proposal"], edited["revision"])["ok"]
    assert (
        run_review(
            "--project",
            project,
            "--proposal",
            first["proposal"],
            answers="\nyes\n",
            monkeypatch=monkeypatch,
        )
        == 0
    )
    retained = results[-1]
    assert retained["confirmed_mappings"] == []
    assert retained["retained_confirmations"][0]["selection"] == selection
    assert retained["lapsed_confirmations"] == []
    assert json.dumps(retained) in capsys.readouterr().out

    meta = yaml.safe_load(order_reference_page().split("---")[1])
    meta["sources"].append(
        {"id": "orders-catalog", "resource": orders_resource(), "title": "orders catalog"}
    )
    meta["ariadne"]["mappings"][1]["source_ids"] = ["orders-catalog"]
    edited = api.edit_proposal(
        first["proposal"],
        branch_of(project, first["proposal"]),
        {
            **REFERENCE_EDIT,
            "content": "---\n" + yaml.safe_dump(meta, sort_keys=False) + "---\n\n# Order number\n",
        },
    )
    assert api.validate_proposal(first["proposal"], edited["revision"])["ok"]
    assert (
        run_review(
            "--project",
            project,
            "--proposal",
            first["proposal"],
            answers="\nyes\n",
            monkeypatch=monkeypatch,
        )
        == 0
    )
    lapsed = results[-1]
    assert lapsed["confirmed_mappings"] == [] and lapsed["retained_confirmations"] == []
    assert lapsed["lapsed_confirmations"][0]["mapping"] == "global-order-concatenation"
    assert "changed" in lapsed["lapsed_confirmations"][0]["reason"]
    assert json.dumps(lapsed) in capsys.readouterr().out


@pytest.mark.parametrize("answers,code", [("yes\nno\n", 0), ("", 1), ("yes\n", 1)])
def test_decline_or_eof_before_admission_preserves_governed_bytes(
    tmp_path,
    monkeypatch,
    capsys,
    answers,
    code,
):
    project, api, payload = admitted_candidate(tmp_path / "managed")
    before = governed(project)
    calls = []
    monkeypatch.setattr(admission, "main", lambda argv: calls.append(argv))
    assert (
        run_review(
            "--project",
            project,
            "--proposal",
            payload["proposal"],
            answers=answers,
            monkeypatch=monkeypatch,
        )
        == code
    )
    assert calls == [] and governed(project) == before
    assert not (project / ".ariadne/current.json").exists()


@pytest.mark.parametrize("at", [0, 1])
def test_keyboard_interrupt_before_admission_preserves_governed_bytes(tmp_path, monkeypatch, at):
    project, api, payload = admitted_candidate(tmp_path / "managed")
    before = governed(project)
    calls = []
    monkeypatch.setattr(admission, "main", lambda argv: calls.append(argv))
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)

    class Interrupted(Terminal):
        def readline(self, size=-1):
            if self.tell() >= at:
                raise KeyboardInterrupt
            return super().readline(size)

    assert (
        cli(
            ["review", "--project", str(project), "--proposal", payload["proposal"]],
            stdin=Interrupted("\n"),
        )
        == 1
    )
    assert calls == [] and governed(project) == before


def test_stale_displayed_review_is_not_refreshed_or_retried(tmp_path, monkeypatch, capsys):
    project, api, payload = admitted_candidate(tmp_path / "managed")
    native = admission.main
    calls = []

    def move_then_delegate(argv):
        calls.append(argv)
        api.edit_proposal(
            payload["proposal"],
            payload["revision"],
            {
                **TABLE_EDIT,
                "content": table_page().replace(
                    "One row per store-scoped order.", "Moved candidate."
                ),
            },
        )
        return native(argv)

    monkeypatch.setattr(admission, "main", move_then_delegate)
    assert (
        run_review(
            "--project",
            project,
            "--proposal",
            payload["proposal"],
            answers="\nyes\n",
            monkeypatch=monkeypatch,
        )
        == 1
    )
    assert calls == [native_admission_args(project, payload)]
    assert not (project / ".ariadne/current.json").exists()
    output = capsys.readouterr()
    assert payload["revision"][:12] in output.err
    assert "current candidate" in output.err and "nothing was activated" in output.err
    assert "read-only" in output.out.lower() and "ariadne status" in output.out
    assert "do not assume rollback or retry" in output.out


@pytest.mark.parametrize("failure", [KeyboardInterrupt, OSError])
def test_failure_after_native_activation_reports_current_without_retry(
    tmp_path,
    monkeypatch,
    capsys,
    failure,
):
    project, api, payload = admitted_candidate(tmp_path / "managed")
    native = admission.main
    calls = []

    def activate_then_fail(argv):
        calls.append(argv)
        assert native(argv) == 0
        raise failure("after activation")

    monkeypatch.setattr(admission, "main", activate_then_fail)
    assert (
        run_review(
            "--project",
            project,
            "--proposal",
            payload["proposal"],
            answers="\nyes\n",
            monkeypatch=monkeypatch,
        )
        == 1
    )
    assert len(calls) == 1
    current = admission.load_current(project)
    assert current is not None and current["commit"] == payload["revision"]
    output = capsys.readouterr().out
    assert "Current recorded activated revision: " + payload["revision"] in output
    assert "do not assume rollback or retry" in output
    assert shlex.join(["ariadne", "status", "--project", str(project), "--json"]) in output
    assert "before delegation" not in output


def test_missing_validation_is_displayed_and_native_admission_refuses(
    tmp_path, monkeypatch, capsys
):
    project, api, candidate = context_only_candidate(tmp_path / "managed")
    before = governed(project)
    native = admission.main
    calls = []

    def record(argv):
        calls.append(argv)
        return native(argv)

    monkeypatch.setattr(admission, "main", record)
    assert (
        run_review(
            "--project",
            project,
            "--proposal",
            candidate["proposal"],
            answers="\nyes\n",
            monkeypatch=monkeypatch,
        )
        == 1
    )
    output = capsys.readouterr()
    assert '"report": null' in output.out
    assert "no validation evidence" in output.err
    assert "nothing was activated" in output.err
    assert len(calls) == 1 and governed(project) == before
    assert not (project / ".ariadne/current.json").exists()


def test_no_proposal_lists_and_stops_invalid_explicit_proposal_refuses(
    tmp_path, monkeypatch, capsys
):
    project, api, payload = admitted_candidate(tmp_path / "managed")
    calls = []
    monkeypatch.setattr(admission, "main", lambda argv: calls.append(argv))
    assert run_review("--project", project, monkeypatch=monkeypatch) == 0
    assert payload["proposal"] in capsys.readouterr().out
    assert (
        run_review("--project", project, "--proposal", "not-a-proposal", monkeypatch=monkeypatch)
        == 1
    )
    assert "error" in capsys.readouterr().err
    assert calls == []
    empty = tmp_path / "empty"
    empty.mkdir()
    assert run_review("--project", empty, monkeypatch=monkeypatch) == 0
    assert "No pending proposals" in capsys.readouterr().out


@pytest.mark.parametrize(
    "flags",
    [
        ["--proposal", "p"],
        ["--project", ".", "--served", "."],
        ["--yes"],
        ["--confirm"],
    ],
)
def test_interface_rejects_route_conflicts_and_bypass_flags(monkeypatch, capsys, flags):
    assert run_review(*flags, monkeypatch=monkeypatch) == 1
    assert json.loads(capsys.readouterr().err)["error"]["message"]


def staged_bundle(root, *, pk="id"):
    root.mkdir()
    project = approved_project(root)
    authoring.submit_bundle(write_submission(project, bundle_submission(pk=pk)), project=project)
    return project, authoring.review_bundle(project=project)


@pytest.mark.parametrize("tty,output_tty", [(False, True), (True, False)])
def test_noninteractive_legacy_inventory_never_consumes_affirmative_input(
    tmp_path,
    monkeypatch,
    capsys,
    tty,
    output_tty,
):
    staging = make_staging(tmp_path / "drafts")
    served = tmp_path / "fresh"
    before = governed(tmp_path)
    calls = []
    monkeypatch.setattr(promote, "main", lambda argv: calls.append(argv))
    assert (
        run_review(
            "--staging",
            staging,
            "--served",
            served,
            answers="yes\n",
            tty=tty,
            output_tty=output_tty,
            monkeypatch=monkeypatch,
        )
        == 0
    )
    output = capsys.readouterr().out
    assert "Ordinary merge-only" in output and "no bundle digest" in output
    assert "created" in output and "orders.yml" in output
    assert (
        shlex.join(["ariadne-promote", "--staging", str(staging), "--served", str(served)])
        in output
    )
    assert calls == [] and not served.exists() and governed(tmp_path) == before


@pytest.mark.parametrize("answer,code", [("yes\n", 0), ("no\n", 1), ("", 1)])
def test_ordinary_promotion_uses_only_native_prompt_and_fresh_target(
    tmp_path,
    monkeypatch,
    capsys,
    answer,
    code,
):
    staging = make_staging(tmp_path / "drafts")
    served = tmp_path / "fresh"
    native = promote.main
    before = governed(tmp_path)
    calls = []

    def record(argv):
        assert not served.exists() and governed(tmp_path) == before
        calls.append(argv)
        return native(argv)

    monkeypatch.setattr(promote, "main", record)
    assert (
        run_review(
            "--staging", staging, "--served", served, answers=answer, monkeypatch=monkeypatch
        )
        == code
    )
    assert calls == [["--staging", str(staging), "--served", str(served)]]
    output = capsys.readouterr().out
    assert output.count("file(s) as human:") == 1
    assert "--yes" not in output and "--digest" not in output
    if code == 0:
        meta = yaml.safe_load(
            (served / "context_layer/metrics/gross_margin.md").read_text().split("---")[1]
        )
        assert meta["status"] == "stable" and len(meta["verified"]) == 1
    else:
        assert not served.exists() and governed(tmp_path) == before


def test_legacy_root_selection_preserves_ambiguity_and_requires_fresh_target(
    tmp_path, monkeypatch, capsys
):
    make_staging(tmp_path / "staging")
    assert run_review(monkeypatch=monkeypatch) == 1
    assert "before first Promotion" in capsys.readouterr().err
    for root in (tmp_path, tmp_path / "served"):
        (root / "context_layer").mkdir(parents=True)
        (root / "semantic_layer/models").mkdir(parents=True)
        if root == tmp_path:
            assert run_review(tty=False, monkeypatch=monkeypatch) == 0
            assert f"Selected served target: {tmp_path}" in capsys.readouterr().out
    assert run_review(tty=False, monkeypatch=monkeypatch) == 1
    assert "ambiguous promoted roots" in capsys.readouterr().err


def test_review_needed_and_empty_staging_make_no_human_call(tmp_path, monkeypatch, capsys):
    staging = make_staging(tmp_path / "staging")
    model = staging / "semantic_layer/models/orders.yml"
    model.write_text(model.read_text() + "\nstatus: review_needed\n")
    calls = []
    monkeypatch.setattr(promote, "main", lambda argv: calls.append(argv))
    assert run_review("--served", tmp_path / "fresh", monkeypatch=monkeypatch) == 1
    assert "review_needed" in capsys.readouterr().err
    assert (
        run_review(
            "--served", tmp_path / "fresh", "--staging", tmp_path / "empty", monkeypatch=monkeypatch
        )
        == 0
    )
    assert "No pending Promotion" in capsys.readouterr().out
    assert calls == [] and not (tmp_path / "fresh").exists()


@pytest.mark.parametrize("tty", [False, True])
def test_bundle_review_matches_native_payload_and_digest_route(tmp_path, monkeypatch, capsys, tty):
    project, expected = staged_bundle(tmp_path / "legacy")
    served = tmp_path / "fresh"
    staging = project / "staging"
    native = promote.main
    calls = []
    before = governed(project)

    def record(argv):
        assert governed(project) == before and not served.exists()
        calls.append(argv)
        return native(argv)

    monkeypatch.setattr(promote, "main", record)
    assert (
        run_review(
            "--staging",
            staging,
            "--served",
            served,
            answers="yes\n",
            tty=tty,
            monkeypatch=monkeypatch,
        )
        == 0
    )
    output = capsys.readouterr().out
    shown = json.JSONDecoder().raw_decode(output[output.index("{") :])[0]
    assert shown == expected and "Digest-backed bundle" in output
    expected_argv = [
        "--staging",
        str(staging),
        "--served",
        str(served),
        "--digest",
        expected["digest"],
    ]
    assert shlex.join(["ariadne-promote", *expected_argv]) in output
    assert "--yes" not in output
    if tty:
        assert calls == [expected_argv] and output.count("file(s) as human:") == 1
        assert (served / "data/seed_notes.md").read_text() == "# Seed notes\n\nAll events count.\n"
        assert authoring.review_bundle(project=project)["status"] == "promoted"
    else:
        assert calls == [] and governed(project) == before and not served.exists()


def test_relocated_bundle_refuses_with_exact_operator_handoffs(tmp_path, monkeypatch, capsys):
    project, payload = staged_bundle(tmp_path / "legacy")
    staging = tmp_path / "relocated"
    shutil.copytree(project / "staging", staging)
    served = tmp_path / "fresh"
    calls = []
    monkeypatch.setattr(promote, "main", lambda argv: calls.append(argv))
    monkeypatch.setattr(admission, "main", lambda argv: calls.append(argv))
    monkeypatch.setattr(
        authoring, "review_bundle", lambda **kwargs: pytest.fail("reviewed wrong bundle")
    )
    assert (
        run_review(
            "--staging", staging, "--served", served, answers="yes\n", monkeypatch=monkeypatch
        )
        == 1
    )
    message = json.loads(capsys.readouterr().err)["error"]["message"]
    assert "relocated active bundle" in message
    assert str(staging) in message and str(project / "staging") in message
    assert shlex.join(["ariadne-authoring", "review", "--project", str(project)]) in message
    assert (
        shlex.join(
            [
                "ariadne-promote",
                "--staging",
                str(staging),
                "--served",
                str(served),
                "--digest",
                payload["digest"],
            ]
        )
        in message
    )
    assert "not reviewed here" in message
    assert calls == [] and not served.exists()


@pytest.mark.parametrize("invalid", [False, True])
def test_bundle_native_stale_digest_or_failed_validation_refuses_without_serving(
    tmp_path,
    monkeypatch,
    capsys,
    invalid,
):
    project, payload = staged_bundle(tmp_path / "legacy", pk="label" if invalid else "id")
    staging = project / "staging"
    served = tmp_path / "fresh"
    native = promote.main
    calls = []

    def record(argv):
        calls.append(argv)
        if not invalid:
            notes = project / authoring.BUNDLE_STAGING_REL / "data/seed_notes.md"
            notes.write_text(notes.read_text() + "\nChanged after review.\n")
        return native(argv)

    monkeypatch.setattr(promote, "main", record)
    assert (
        run_review(
            "--staging", staging, "--served", served, answers="yes\n", monkeypatch=monkeypatch
        )
        == 1
    )
    assert len(calls) == 1 and calls[0][-2:] == ["--digest", payload["digest"]]
    assert not served.exists()
    output = capsys.readouterr()
    assert ("only a proposal" if invalid else "changed after the review") in output.err
    assert "do not assume rollback or retry" in output.out


def test_interrupted_post_admission_inspection_guides_status_without_pre_call_claim(
    tmp_path, monkeypatch, capsys
):
    project, api, payload = admitted_candidate(tmp_path / "managed")
    native = admission.main
    read_current = admission.load_current
    calls = []

    def activate_then_interrupt(argv):
        calls.append(argv)
        assert native(argv) == 0
        monkeypatch.setattr(admission, "load_current", interrupt_inspection)
        raise KeyboardInterrupt

    def interrupt_inspection(project):
        raise KeyboardInterrupt

    monkeypatch.setattr(admission, "main", activate_then_interrupt)
    assert (
        run_review(
            "--project",
            project,
            "--proposal",
            payload["proposal"],
            answers="\nyes\n",
            monkeypatch=monkeypatch,
        )
        == 1
    )
    assert len(calls) == 1
    current = read_current(project)
    assert current is not None and current["commit"] == payload["revision"]
    output = capsys.readouterr()
    assert "Admission descriptor inspection refused: KeyboardInterrupt" in output.out
    assert "ariadne status" in output.out
    assert "before delegation" not in output.out + output.err


def test_operator_rule_reinstalled_for_selected_project_pi_only(tmp_path, monkeypatch, capsys):
    assert skill.main(["install", "--scope", "project", "--agent", "pi"]) == 0
    target = tmp_path / ".agents/skills/ariadne"
    (target / "SKILL.md").write_text("outdated skill")
    assert skill.main(["install", "--scope", "project", "--agent", "pi"]) == 0
    selected = status._skill_targets({("project", None), ("project", "pi")})
    assert len(selected) == 2 and all(t["state"] == "ok" for t in selected)
    installed = " ".join((tmp_path / ".pi/skills/ariadne/SKILL.md").read_text().split())
    assert "`ariadne review` is operator-only: agents never run it" in installed
    assert "even inside terminal sessions" in installed
    assert "read-only `ariadne-authoring review`" in installed
    assert "its exact payload/digest and STOP" in installed
    assert not (tmp_path / ".claude").exists() and not (tmp_path / ".hermes").exists()


def test_no_mcp_or_native_agent_registration_exposes_walkthrough():
    # Explicit registrations, not CLI subcommands, own agent authority.
    from ariadne.serve import build_app

    for toolset in ("combined", "analyst", "authoring"):
        app = build_app(lambda: pytest.fail("registration constructed a runtime"), toolset=toolset)
        names = {tool.name for tool in app._tool_manager.list_tools()}
        assert "review" not in names and "ariadne_review" not in names
        assert "authoring_review_proposal" in names or toolset == "analyst"
    for path in (REPO_ROOT / "ariadne-agent/src/ariadne_agent").glob("*.py"):
        text = path.read_text()
        assert "ariadne.review" not in text and "ariadne review" not in text
