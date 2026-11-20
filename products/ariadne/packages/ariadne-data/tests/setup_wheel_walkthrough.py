"""AC8 installed-wheel self-check; run with the FRESH venv's Python, not uv run.

Build/install separately: uv build; uv venv --python 3.14 /tmp/ariadne-wheel-venv;
uv pip install --python /tmp/ariadne-wheel-venv/bin/python dist/ariadne_data-*.whl;
/tmp/ariadne-wheel-venv/bin/python tests/setup_wheel_walkthrough.py

The harness acts as the operator for human commands in a throwaway fixture;
setup itself performs no approval/admission. No provider or live LLM is needed.
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import duckdb  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages

import ariadne

MODEL = """\
version: 0.3.0.dev0
name: events
description: Three fixture events
datasets:
- name: events
  source: events.events
  primary_key:
  - id
  fields:
  - name: id
    expression:
      sql: id
  - name: label
    expression:
      sql: label
    dimension: {}
  metrics:
  - name: event_count
    expression:
      sql: COUNT(*)
    description: Count all events
"""


def native_page(kind, title, resource, body):
    """One producer-native knowledge page in the accepted conventions (typed
    Entity identity, producer envelope, KB-relative citations). The TABLE page
    anchors its canonical ``core_ref`` resource identity WITHOUT the
    system-owned ``native.resource`` binding (an ordinary batch may introduce
    core_ref, never the stamped resource facts); non-table kinds cite their
    document/Policy path as a DECLARED SOURCE resource — ``native.resource``
    stays reserved to generated physical-table profiles with Core
    provenance; the METRIC declares its dimensions/grain from the actual
    MODEL (dimension field ``label``, dataset primary key ``id``)."""
    entity_id = "entity:" + title.lower().replace(" ", "-").replace("_", "-")
    policy_extra = ""
    if kind == "metric":
        policy_extra = (
            "  metric_ref:\n"
            "    model: events\n"
            f"    metric: events.{title}\n"
            "  required_policies:\n"
            '    - namespace: "urn:uuid:wheel-walkthrough"\n'
            '      entity_id: "entity:all-events-count"\n'
        )
    elif kind == "policy":
        policy_extra = "  required_policies: []\n"
    core_ref_extra = ""
    if kind == "table":
        core_ref_extra = (
            "  core_ref:\n"
            "    kind: resource\n"
            f"    id: {resource}\n"
        )
    # the document/Policy path rides the DECLARED native source record —
    # never the protected native.resource claim
    source_resource = f"        resource: {resource}\n" if kind != "table" else ""
    metric_native_extra = ""
    if kind == "metric":
        metric_native_extra = (
            f"    governed_by: {resource}\n"
            "    dimensions:\n      - label\n"
            "    grain:\n"
            "      primary_key:\n        - id\n"
            '      cardinality_enforcement: "strict_1_to_1"\n'
        )
    return (
        "---\n"
        f'id: "{entity_id}"\n'
        f'title: "{title}"\n'
        f"entity_types:\n  - {kind}\n"
        f"tags:\n  - {kind}\n"
        f'summary: "{body}"\n'
        'lifecycle: "approved"\n'
        'visibility: "public"\n'
        "sources:\n"
        "  - id: rule\n"
        "    title: Owner rule\n"
        "ariadne_profile:\n"
        "  version: 1\n"
        f"  kind: {kind}\n"
        + policy_extra
        + core_ref_extra
        + "  native:\n"
        f"    type: {kind}\n"
        f"    title: {title}\n"
        f"    description: {body}\n"
        f"    tags:\n      - {kind}\n"
        "    status: draft\n"
        "    sources:\n"
        "      - id: rule\n"
        "        title: Owner rule\n"
        + source_resource
        + metric_native_extra
        + "---\n\n"
        + f"# {title}\n\n"
        + body
        + "\n"
    )


def main():
    prefix = Path(sys.prefix)
    assert prefix in Path(ariadne.__file__).resolve().parents, "not a wheel-installed package"
    assert "site-packages" in str(ariadne.__file__)
    bin_dir = prefix / "bin"
    with tempfile.TemporaryDirectory(prefix="ariadne-wheel-walkthrough-") as tmp:
        root = Path(tmp)
        home = root / "home"
        home.mkdir()
        project = root / "project"
        env = dict(
            os.environ,
            HOME=str(home),
            GIT_CONFIG_GLOBAL=os.devnull,
            GIT_CONFIG_SYSTEM=os.devnull,
            PYTHONPATH="",
        )
        for key in ("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "OPENAI_API_KEY", "OPENAI_MODEL"):
            env.pop(key, None)

        def command(name, *args, cwd=root, structured=False) -> Any:
            binary = str(bin_dir / name) if name.startswith("ariadne") else name
            result = subprocess.run(
                [binary, *args], cwd=cwd, env=env, capture_output=True, text=True, check=False
            )
            assert result.returncode == 0, f"{name} {args}: {result.stdout}\n{result.stderr}"
            print(f"PASS {name} {' '.join(args)}")
            return json.loads(result.stdout) if structured else result.stdout

        for name in (
            "ariadne",
            "ariadne-authoring",
            "ariadne-admit",
            "ariadne-init",
            "ariadne-skill",
        ):
            command(name, "--help")
        assert "--no-input" in command("ariadne", "setup", "--help")
        assert "--json" in command("ariadne", "status", "--help")
        scaffold = command(
            "ariadne", "setup", "--project", str(project), "--no-input", "--agents", "--agent", "pi"
        )
        assert "Ready: no" in scaffold and "git init" in scaffold
        assert not (project / ".git").exists() and not (project / ".ariadne").exists()
        assert (project / ".pi/skills/ariadne").resolve() == project / ".agents/skills/ariadne"
        command("git", "init", "-q", str(project))
        command("git", "config", "user.name", "Wheel Operator", cwd=project)
        command("git", "config", "user.email", "wheel@example.test", cwd=project)
        # setup without Git materializes only the selected agent install (S2)
        (project / "data").mkdir()
        (project / "data/seed_notes.md").write_text(
            "# Events\n\nOne row per unique event id; count every event once.\n", encoding="utf-8"
        )
        # the native authoring surface: the knowledge/ KB plus the revision-2
        # integrated selector with the authored §10.1 binding inventory (the
        # narrative Policy binds the metric and its generated computation;
        # enforcement null — no graph policy audit)
        kb = project / "knowledge"
        kb.mkdir(parents=True, exist_ok=True)
        (kb / "lumio.yaml").write_text(
            "version: 2\n"
            'mode: "categorized"\n'
            "categories:\n"
            "  - name: tables\n"
            "  - name: references\n"
            "  - name: policies\n"
            "  - name: metrics\n"
            "  - name: computations\n"
            "ontology:\n"
            "  entity_types:\n"
            "    table: {}\n"
            "    reference: {}\n"
            "    policy: {}\n"
            "    metric: {}\n"
            "    computation: {}\n"
            "  predicates: {}\n"
            "  redirects: {}\n",
            encoding="utf-8",
        )
        (kb / ".lumio-authoring.yaml").write_text(
            'version: 1\nnamespace: "urn:uuid:wheel-walkthrough"\nsources: {}\nbindings: {}\n',
            encoding="utf-8",
        )
        (project / "context_integration.yaml").write_text(
            "version: 1\n"
            "mode: integrated\n"
            "subtree: knowledge\n"
            "namespace: urn:uuid:wheel-walkthrough\n"
            "profile: ariadne-context/1\n"
            "support_revision: 2\n"
            "policy_bindings:\n"
            "  version: 1\n"
            "  bindings:\n"
            "    - subject: {kind: metric, identity: events::events.event_count}\n"
            "      policy: {namespace: urn:uuid:wheel-walkthrough,"
            " entity_id: entity:all-events-count}\n"
            "      operations: [get_metric, query_metrics]\n"
            "      enforcement: null\n",
            encoding="utf-8",
        )
        conn = duckdb.connect()
        conn.execute(
            "CREATE TABLE events AS SELECT * FROM "
            "(VALUES (1, 'a'), (2, 'b'), (3, 'c')) t(id, label)"
        )
        conn.execute("COPY events TO ? (FORMAT PARQUET)", [str(project / "data/events.parquet")])
        conn.close()
        intake = root / "sources.yaml"
        intake.write_text(
            "sources:\n- name: events\n  type: parquet\n  path: data/events.parquet\n"
        )
        started = command("ariadne-authoring", "start", "--project", str(project), structured=True)
        pid = started["proposal"]
        declared = command(
            "ariadne-authoring",
            "propose-sources",
            "--project",
            str(project),
            "--proposal",
            pid,
            "--expected-revision",
            started["candidate_revision"],
            "--file",
            str(intake),
            structured=True,
        )
        # Exact operator handoff is visible when resuming setup, but setup never executes it.
        resumed = command("ariadne", "setup", "--project", str(project), "--no-input")
        assert (
            f"--proposal {pid}" in resumed
            and f"--source-digest {declared['source_digest']}" in resumed
        )
        assert not (project / ".ariadne/source-approvals.json").exists()
        command(
            "ariadne-authoring",
            "approve-sources",
            "--project",
            str(project),
            "--proposal",
            pid,
            "--revision",
            declared["revision"],
            "--source-digest",
            declared["source_digest"],
        )
        command("ariadne-authoring", "inputs", "--project", str(project), "--proposal", pid)
        revision = declared["revision"]
        # the OSI/model draft rides the live single-edit seam; the knowledge
        # pages ride ONE native page batch (AC4) through the edit-pages command
        # (a native skill profile refuses — the skill page is not authored)
        edits = [{"kind": "model", "name": "events", "content": MODEL}]
        from ariadne.sources import table_resource

        events_table_uri = table_resource("events", None, "events", "events")
        pages = [
            {
                "path": "knowledge/tables/events.md",
                "content": native_page(
                    "table", "events", events_table_uri, "One row per event."
                ),
            },
            {
                "path": "knowledge/references/event-rule.md",
                "content": native_page(
                    "reference", "Event rule", "data/seed_notes.md", "All events count."
                ),
            },
            {
                "path": "knowledge/policies/all-events-count.md",
                "content": native_page(
                    "policy", "All events count", "data/seed_notes.md", "Count every event once."
                ),
            },
            {
                "path": "knowledge/metrics/event-count.md",
                "content": native_page(
                    "metric", "event_count", "policies/all-events-count.md", "Count all events."
                ),
            },
        ]
        for edit in edits:
            edit_file = root / "edit.json"
            edit_file.write_text(json.dumps(edit), encoding="utf-8")
            changed = command(
                "ariadne-authoring",
                "edit",
                "--project",
                str(project),
                "--proposal",
                pid,
                "--expected-revision",
                revision,
                "--file",
                str(edit_file),
                structured=True,
            )
            revision = changed["revision"]
        pages_file = root / "pages.json"
        pages_file.write_text(json.dumps(pages), encoding="utf-8")
        changed = command(
            "ariadne-authoring",
            "edit-pages",
            "--project",
            str(project),
            "--proposal",
            pid,
            "--expected-revision",
            revision,
            "--file",
            str(pages_file),
            structured=True,
        )
        revision = changed["revision"]
        validated = command(
            "ariadne-authoring",
            "validate",
            "--project",
            str(project),
            "--proposal",
            pid,
            "--expected-revision",
            revision,
            structured=True,
        )
        assert validated["ok"] is True, validated
        review = command(
            "ariadne-authoring",
            "review",
            "--project",
            str(project),
            "--proposal",
            pid,
            structured=True,
        )
        assert not (project / ".ariadne/current.json").exists()
        # integrated admission goes through the composite preview the
        # operator confirms (spec0032 §10): the preview is computed in-process
        # (the walkthrough runs on the installed wheel's own API) and its
        # exact digest rides the admit command alongside the operator-owned
        # local publication destination
        from ariadne import admission

        published = root / "published"
        composite = admission.overall_review(
            project,
            pid,
            review["revision"],
            review["review_digest"],
            destination=str(published),
            expected_current="none",
            scope=["public"],
        )
        command(
            "ariadne-admit",
            "--project",
            str(project),
            "--proposal",
            pid,
            "--revision",
            review["revision"],
            "--reviewed-digest",
            review["review_digest"],
            "--context-destination",
            str(published),
            "--context-expected-current",
            "none",
            f"--overall-digest={composite['digest']}",
            "--confirm",
        )
        metrics = command("ariadne", "list-metrics", "--project", str(project), structured=True)
        assert metrics[0]["name"] == "events::events.event_count"  # spec 0039 §6 identity
        result = command(
            "ariadne", "get-metric", "event_count", "--project", str(project), structured=True
        )
        assert result["rows"] == [{"event_count": 3}]  # independently seeded three rows
        assert result["governed"] is True
        assert result["admission"]["route"] == "git-review-admission"
        report = command("ariadne", "status", "--project", str(project), "--json", structured=True)
        assert report["ready"] is True and report["project"]["admission"]["state"] == "valid"
    print(
        f"AC8 PASS: installed core wheel at {ariadne.__file__}; fresh governed event_count=3; "
        "no optional agent/MCP/provider required; no publication."
    )


if __name__ == "__main__":
    main()
