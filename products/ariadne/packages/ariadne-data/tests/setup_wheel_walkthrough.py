"""Installed-wheel self-check (spec 0040 AC1/AC5); run with the FRESH venv's Python.

Build/install separately: uv build; uv venv --python 3.14 /tmp/ariadne-wheel-venv;
uv pip install --python /tmp/ariadne-wheel-venv/bin/python dist/ariadne_data-*.whl;
/tmp/ariadne-wheel-venv/bin/python tests/setup_wheel_walkthrough.py

The wheel must expose only the `ariadne` executable. The owner path runs end to end in
a throwaway directory through that executable: init, add, a sources-only approval and a
calculation approval answered on a REAL pseudo-terminal, edit, validate and a governed
query. No provider or live LLM is needed.
"""

import json
import os
import pty
import select
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
            "  required_policies: []\n"
        )
    elif kind == "policy":
        policy_extra = "  required_policies: []\n"
    core_ref_extra = ""
    if kind == "table":
        core_ref_extra = f"  core_ref:\n    kind: resource\n    id: {resource}\n"
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
        f"  kind: {kind}\n" + policy_extra + core_ref_extra + "  native:\n"
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


def run_on_pty(binary, args, cwd, env, answers):
    """Run a human-only command on a real pty: wait for each prompt, then answer."""
    master, slave = pty.openpty()
    proc = subprocess.Popen(
        [binary, *args], cwd=cwd, env=env, stdin=slave, stdout=slave, stderr=slave, close_fds=True
    )
    os.close(slave)
    output = b""
    pending = list(answers)
    while True:
        ready, _, _ = select.select([master], [], [], 60)
        if not ready:
            proc.kill()
            raise AssertionError(f"pty timeout: {output.decode(errors='replace')}")
        try:
            chunk = os.read(master, 4096)
        except OSError:
            break
        if not chunk:
            break
        output += chunk
        if pending and b"[yes/no]" in output.split(b"\n")[-1]:
            os.write(master, pending.pop(0).encode() + b"\n")
    code = proc.wait(timeout=60)
    os.close(master)
    return code, output.decode(errors="replace")


def main():
    prefix = Path(sys.prefix)
    assert prefix in Path(ariadne.__file__).resolve().parents, "not a wheel-installed package"
    assert "site-packages" in str(ariadne.__file__)
    bin_dir = prefix / "bin"
    # AC5: the installed wheel exposes only `ariadne` (no removed executables, no aliases)
    removed = (
        "ariadne-validate",
        "ariadne-serve",
        "ariadne-analyst-mcp",
        "ariadne-authoring-mcp",
        "ariadne-init",
        "ariadne-skill",
        "ariadne-profiler",
        "ariadne-authoring",
        "ariadne-admit",
    )
    present = sorted(p.name for p in bin_dir.glob("ariadne*"))
    assert present == ["ariadne"], f"unexpected executables: {present}"
    assert not [name for name in removed if (bin_dir / name).exists()]
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
        ariadne_bin = str(bin_dir / "ariadne")

        def cli(*args, cwd=project, structured=True) -> Any:
            result = subprocess.run(
                [ariadne_bin, *args, "--json"],
                cwd=cwd,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            assert result.returncode == 0, f"ariadne {args}: {result.stdout}\n{result.stderr}"
            print(f"PASS ariadne {' '.join(args)}")
            return json.loads(result.stdout) if structured else result.stdout

        for sub in (
            "init",
            "add",
            "draft",
            "validate",
            "diff",
            "approve",
            "status",
            "query",
            "detail",
            "metrics",
            "datasets",
            "search",
            "page",
            "serve",
            "skill",
            "profile",
            "migrate",
        ):
            helped = subprocess.run(
                [ariadne_bin, sub, "--help"], env=env, capture_output=True, text=True, check=False
            )
            assert helped.returncode == 0 and sub in helped.stdout, sub

        # --- the owner path (spec 0040 §1): no ID, revision, digest or selector anywhere
        project.mkdir()
        subprocess.run(["git", "init", "-q", str(project)], check=True, env=env)
        subprocess.run(
            ["git", "config", "user.name", "Wheel Operator"], cwd=project, env=env, check=True
        )
        subprocess.run(
            ["git", "config", "user.email", "wheel@example.test"], cwd=project, env=env, check=True
        )
        out = cli("init", str(project), "--yes", cwd=root)
        assert out["initialized"] is True
        (project / "data").mkdir(exist_ok=True)
        conn = duckdb.connect()
        conn.execute(
            "CREATE TABLE events AS SELECT * FROM "
            "(VALUES (1, 'a'), (2, 'b'), (3, 'c')) t(id, label)"
        )
        conn.execute("COPY events TO ? (FORMAT PARQUET)", [str(project / "data/events.parquet")])
        conn.close()

        added = cli("add", "data/events.parquet", "--name", "events")
        assert added["draft"]["generation"] == 1 and "source_digest" in added
        assert not (project / ".ariadne/source_grants.json").exists()  # nothing granted yet

        # a sources-only approval on a real terminal: offline display, then "yes"
        code, shown = run_on_pty(
            ariadne_bin, ["approve", "--project", str(project)], project, env, ["yes"]
        )
        assert code == 0, shown
        assert "no source has been read" in shown
        grants = json.loads((project / ".ariadne/source_grants.json").read_text(encoding="utf-8"))
        assert [g["source"]["name"] for g in grants["grants"]] == ["events"]
        assert not (project / ".ariadne/current.json").exists()  # no release activated

        # the model draft, native pages and validation
        from ariadne.sources import table_resource

        events_table_uri = table_resource("events", None, "events", "events")
        pages = [
            {
                "path": "knowledge/tables/events.md",
                "content": native_page("table", "events", events_table_uri, "One row per event."),
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
                    "policy",
                    "All events count",
                    "data/seed_notes.md",
                    "Count every event once.",
                ),
            },
            {
                "path": "knowledge/metrics/event-count.md",
                "content": native_page(
                    "metric",
                    "event_count",
                    "references/event-rule.md",
                    "Count all events.",
                ),
            },
        ]
        (project / "data/seed_notes.md").write_text(
            "# Events\n\nOne row per unique event id; count every event once.\n", encoding="utf-8"
        )
        for edit in (
            {"kind": "model", "name": "events", "content": MODEL},
            {"kind": "seed_notes", "content": (project / "data/seed_notes.md").read_text("utf-8")},
            {"kind": "pages", "pages": pages},
        ):
            edit_file = root / "edit.json"
            edit_file.write_text(json.dumps(edit), encoding="utf-8")
            cli("draft", "edit", str(edit_file))
        validated = cli("validate")
        assert validated["ok"] is True, validated
        diff = cli("diff")
        assert diff["approval_kind"] == "calculation" and diff["validation"] == "validated"

        # pre-approval draft preview (spec 0040 §3.6): same numbers, not yet governed
        preview = cli("preview", "event_count")
        assert preview["rows"] == [{"event_count": 3}]
        assert preview["governed"] is False

        # no terminal, no approval: stdin/stdout are pipes here
        refused = subprocess.run(
            [ariadne_bin, "approve", "--project", str(project)],
            cwd=project,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert refused.returncode == 1 and "interactive terminal" in refused.stderr
        assert not (project / ".ariadne/current.json").exists()

        # calculation approval on a real terminal, then the governed answer
        code, shown = run_on_pty(
            ariadne_bin, ["approve", "--project", str(project)], project, env, ["yes"]
        )
        assert code == 0, shown
        metrics = cli("metrics")
        assert metrics[0]["name"] == "events::events.event_count"  # spec 0039 §6 identity
        result = cli("query", "event_count")
        assert result["rows"] == [{"event_count": 3}]  # independently seeded three rows
        assert result["governed"] is True
        assert result["admission"]["route"] == "git-review-admission"
        report = cli("status")
        assert report["ready"] is True and report["project"]["admission"]["state"] == "valid"
    print(
        f"PASS: installed wheel at {ariadne.__file__}; only `ariadne` is installed; owner path "
        "with pty approvals gives governed event_count=3; no optional agent/MCP/provider."
    )


if __name__ == "__main__":
    main()
