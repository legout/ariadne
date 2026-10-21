#!/usr/bin/env python3
"""Local tutorial helper. Prints human decisions; never approves or admits."""

import argparse
import csv
import json
import shlex
import shutil
import subprocess
import sys
from pathlib import Path


def command(*args, cwd=None):
    result = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    if result.returncode:
        print(result.stdout, end="", file=sys.stderr)
        print(result.stderr, end="", file=sys.stderr)
        raise SystemExit(result.returncode)
    return result.stdout


def cli(*args):
    return json.loads(command(*args))


def save(project, state):
    (project / ".demo-state.json").write_text(json.dumps(state, indent=2) + "\n")


def create(project):
    # Refuse existing directories; originals and real operator projects are never replaced.
    if project.exists():
        raise SystemExit(f"Choose a new directory: {project} already exists")
    shutil.copytree(Path(__file__).parent / "project", project)
    import duckdb

    with duckdb.connect(str(project / "data/orders.duckdb")) as con:
        con.execute("CREATE TABLE orders(id INTEGER, amount DOUBLE, status VARCHAR)")
        with (project / "data/orders.csv").open() as source:
            rows = [(int(r["id"]), float(r["amount"]), r["status"]) for r in csv.DictReader(source)]
        con.executemany("INSERT INTO orders VALUES (?, ?, ?)", rows)
    command("git", "init", "-q", "-b", "main", cwd=project)
    command("git", "config", "user.name", "Local tutorial operator", cwd=project)
    command("git", "config", "user.email", "tutorial@example.invalid", cwd=project)
    command("git", "add", "--", ".", cwd=project)
    command("git", "commit", "-q", "-m", "Authored synthetic local retail example", cwd=project)
    print(f"Created {project}. The database contains only the three supplied synthetic rows.")
    print("No source approval, validation, publication or admission was performed.")


def propose(project):
    head = command("git", "rev-parse", "HEAD", cwd=project).strip()
    state = cli("ariadne-authoring", "start", "--project", str(project), "--base-revision", head)
    state["revision"] = state["candidate_revision"]
    if not (project / ".ariadne/current.json").exists():
        result = cli(
            "ariadne-authoring", "propose-sources", "--project", str(project),
            "--proposal", state["proposal"], "--expected-revision", state["revision"],
            "--file", str(project / "sources.yaml"),
        )
        state.update(revision=result["revision"], source_digest=result["source_digest"])
        state["operator_source_approval"] = [
            "ariadne-authoring", "approve-sources", "--project", str(project),
            "--proposal", state["proposal"], "--revision", state["revision"],
            "--source-digest", state["source_digest"],
        ]
        print(json.dumps(result, indent=2))
        print("HUMAN: inspect the resolved synthetic source above. If you approve, run:")
        print(shlex.join(state["operator_source_approval"]))
    else:
        print("New proposal uses the explicit local HEAD; existing source permission is checked")
        print("by native validation. Changed sources require their own source approval.")
    save(project, state)
    print(f"Proposal: {state['proposal']}\nInput revision: {state['revision']}")


def review(project):
    state = json.loads((project / ".demo-state.json").read_text())
    validated = cli(
        "ariadne-authoring", "validate", "--project", str(project),
        "--proposal", state["proposal"], "--expected-revision", state["revision"],
    )
    print(json.dumps(validated, indent=2))
    if not validated["ok"]:
        raise SystemExit("Validation refused. Inspect the reported errors; nothing was admitted.")
    # Native finalization can create a commit: always use its returned revision.
    state["revision"] = validated["revision"]
    report = cli("ariadne-authoring", "review", "--project", str(project),
                 "--proposal", state["proposal"])
    print(json.dumps(report, indent=2))
    previous = "none"
    current = project / ".ariadne/current.json"
    if current.exists():
        previous = json.loads(current.read_text())["bound_release"]["knowledge"][
            "published_version"
        ]
    preview_args = [
        "ariadne-admit", "--project", str(project), "--proposal", state["proposal"],
        "--revision", state["revision"], "--reviewed-digest", report["review_digest"],
        "--context-destination", str(project.parent / (project.name + "-published")),
        "--context-expected-current", previous,
    ]
    composite = cli(*preview_args)
    print(json.dumps(composite, indent=2))
    state["operator_admission"] = preview_args + [
        "--overall-digest", composite["digest"], "--confirm"
    ]
    save(project, state)
    print("HUMAN: inspect validation, review and overall preview above. If you agree, run:")
    print(shlex.join(state["operator_admission"]))
    print("The helper has not executed that confirmation.")


def check(project):
    result = cli("ariadne", "query-metrics", "--project", str(project),
                 "--file", str(project / "metrics.json"))
    # Hand-worked from supplied CSV/rule: completed100+50, cancelled25 excluded.
    assert result["rows"] == [{"revenue": 150.0, "completed_orders": 2}], result["rows"]
    assert result["governed"] is True
    for name in ("revenue", "completed_orders"):
        encoded = json.dumps(result["context"][name])
        assert "entity:cancelled-orders" in encoded
        assert "Keep this full rule with both results." in encoded
    print(json.dumps(result, indent=2))
    print("PASS: 150 EUR, 2 completed orders; both results carry their Cancelled Orders policy.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("create", "propose", "review", "check"))
    parser.add_argument("project", type=Path)
    args = parser.parse_args()
    globals()[args.action](args.project.resolve())


if __name__ == "__main__":
    main()
