"""AC8 installed-wheel self-check; run with the FRESH venv's Python, not uv run.

Build/install separately: uv build; uv venv --python 3.12 /tmp/ariadne-wheel-venv;
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
import yaml

import ariadne

MODEL = """\
version: 0.2.0.dev0
semantic_model:
  - name: events
    description: Three fixture events
    datasets:
      - name: events
        source: events.events
        primary_key: [id]
        fields:
          - name: id
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: id
          - name: label
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: label
            dimension: {}
    metrics:
      - name: event_count
        description: Count all events
        expression:
          dialects:
            - dialect: ANSI_SQL
              expression: COUNT(*)
"""


def page(kind, title, resource, body, **extra):
    return (
        "---\n"
        + yaml.safe_dump(
            {
                "type": kind,
                "title": title,
                "description": body,
                "tags": [kind],
                **({"status": "draft"} if kind in ("policy", "metric") else {}),
                "sources": [{"id": "rule", "resource": resource, "title": "Owner rule"}],
                **extra,
            },
            sort_keys=False,
        )
        + "---\n\n"
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
        (project / "data/seed_notes.md").write_text(
            "# Events\n\nOne row per unique event id; count every event once.\n", encoding="utf-8"
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
        edits = [
            {"kind": "model", "name": "events", "content": MODEL},
            {
                "kind": "page",
                "section": "tables",
                "name": "events",
                "content": page(
                    "table",
                    "Events",
                    "events.events",
                    "One row per event.",
                    grain={"primary_key": ["id"], "cardinality_enforcement": "STRICT_1_TO_1"},
                ),
            },
            {
                "kind": "page",
                "section": "references",
                "name": "event-rule",
                "content": page(
                    "reference", "Event rule", "data/seed_notes.md", "All events count."
                ),
            },
            {
                "kind": "page",
                "section": "policies",
                "name": "all-events-count",
                "content": page(
                    "policy", "All events count", "data/seed_notes.md", "Count every event once."
                ),
            },
            {
                "kind": "page",
                "section": "metrics",
                "name": "event_count",
                "content": page(
                    "metric", "event_count", "policies/all-events-count.md", "Count all events."
                ),
            },
            {
                "kind": "page",
                "section": "skills",
                "name": "query-events",
                "content": page(
                    "skill", "Query events", "data/seed_notes.md", "Query the admitted metric."
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
            "--confirm",
        )
        metrics = command("ariadne", "list-metrics", "--project", str(project), structured=True)
        assert any(m["name"] == "event_count" for m in metrics)
        result = command(
            "ariadne", "get-metric", "event_count", "--project", str(project), structured=True
        )
        assert result["rows"] == [{"event_count": 3}]  # independently seeded three rows
        assert result["governed"] is True
        assert result["admission"]["route"] == "git-review-admission"
        report = command("ariadne", "status", "--project", str(project), "--json", structured=True)
        assert report["ready"] is True and report["project"]["admission"]["state"] == "valid"
        legacy = root / "legacy"
        command("ariadne", "setup", "--legacy", "--project", str(legacy), "--no-input")
        assert "## Promotion gate" in (legacy / "AGENTS.md").read_text()
    print(
        f"AC8 PASS: installed core wheel at {ariadne.__file__}; fresh governed event_count=3; "
        "no optional agent/MCP/provider required; no publication."
    )


if __name__ == "__main__":
    main()
