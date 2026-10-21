from __future__ import annotations

import hashlib
import importlib
import importlib.metadata
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

FORBIDDEN = {
    "lancedb",
    "pyarrow",
    "stario",
    "piccolo",
    "openai",
    "liteparse",
    "markitdown",
    "anydoc",
    "ariadne",
    "duckdb",
    "sqlglot",
    "lumio",
}


def _python_roots(wheel: Path) -> set[str]:
    roots: set[str] = set()
    with zipfile.ZipFile(wheel) as archive:
        for name in archive.namelist():
            parts = name.split("/")
            if parts[0].endswith(".data"):
                if len(parts) < 3 or parts[1] not in {"purelib", "platlib"}:
                    continue
                name = "/".join(parts[2:])

            root, separator, _ = name.partition("/")
            if root.endswith(".dist-info"):
                continue
            if not name.endswith((".py", ".so", ".pyd")):
                continue
            roots.add(root if separator else root.split(".", 1)[0])
    return roots


def assert_installed_wheel(wheel: Path) -> None:
    """Bind a candidate archive to source members and the actual installation."""
    wheel = wheel.resolve()
    name = wheel.name.split("-", 1)[0].replace("_", "-")
    root = name.replace("-", "_")
    distribution = importlib.metadata.distribution(name)
    installed_root = Path(distribution.locate_file(root)).resolve()
    assert installed_root.is_relative_to(Path(sys.prefix).resolve()), installed_root
    module = importlib.import_module(root)
    assert Path(module.__file__).resolve() == installed_root / "__init__.py"
    digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
    # Index installs omit origin metadata; member bytes still bind the artifact.
    direct_text = distribution.read_text("direct_url.json")
    direct = json.loads(direct_text) if direct_text is not None else {}
    if direct_text is not None:
        assert direct.get("url") == wheel.as_uri() and "dir_info" not in direct, direct
    archive_info = direct.get("archive_info", {})
    hashes = archive_info.get("hashes", {})
    if "sha256" in hashes:
        assert hashes["sha256"] == digest, direct
    legacy_hash = archive_info.get("hash", "")
    if legacy_hash.startswith("sha256="):
        assert legacy_hash == f"sha256={digest}", direct
    source = Path(__file__).resolve().parents[2] / "packages" / name / "src"
    members = {}
    with zipfile.ZipFile(wheel) as archive:
        for member in archive.namelist():
            if member.startswith(f"{root}/") and not member.endswith("/"):
                raw = archive.read(member)
                assert (source / member).read_bytes() == raw, f"stale source member: {member}"
                assert Path(distribution.locate_file(member)).read_bytes() == raw, member
                members[member] = hashlib.sha256(raw).hexdigest()
        metadata = next(p for p in archive.namelist() if p.endswith(".dist-info/METADATA"))
        assert distribution.read_text("METADATA").encode() == archive.read(metadata)
    assert members
    print(
        "wheel_identity:",
        json.dumps(
            {
                "wheel": str(wheel),
                "sha256": digest,
                "distribution": name,
                "installed_root": str(installed_root),
                "members": members,
            },
            sort_keys=True,
        ),
    )


def _cli(*args: str, cwd: Path, env: dict[str, str] | None = None) -> str:
    result = subprocess.run(
        [sys.executable, "-I", "-m", "lumio_wiki.cli", *args],
        cwd=cwd,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def main() -> int:
    """Verify the candidate base wheel, native admission and Git-free reads."""
    if len(sys.argv) not in (3, 4):
        raise SystemExit(
            "usage: verify_lumio_wiki_wheel.py WIKI_WHEEL VALID_FIXTURE [CATEGORIZED_FIXTURE]"
        )
    wiki_wheel = Path(sys.argv[1])
    valid_fixture = Path(sys.argv[2])
    categorized_fixture = Path(sys.argv[3]) if len(sys.argv) == 4 else valid_fixture

    assert _python_roots(wiki_wheel) == {"lumio_wiki"}
    assert_installed_wheel(wiki_wheel)

    requirements = importlib.metadata.requires("lumio-wiki") or []
    # Core (unconditional) runtime deps only — exclude optional extras gated
    # by environment markers (the "; extra == ..." entries). lumio-wiki must
    # stay lightweight and model-free (ADR-0010): pinning the exact core set
    # guards against an accidental heavy dependency landing in the base wheel.
    # ``msgpack`` is the Discovery Graph serialization format (#108);
    # ``msgspec[yaml]`` is the compiled-Markdown struct codec.
    core_requirements = sorted(
        requirement.replace(" ", "").lower()
        for requirement in requirements
        if ";" not in requirement
    )
    assert core_requirements == ["msgpack>=1.0", "msgspec[yaml]>=0.21.1"], core_requirements

    assert all(importlib.util.find_spec(name) is None for name in FORBIDDEN)
    installed = {
        distribution.metadata["Name"].lower().replace("_", "-")
        for distribution in importlib.metadata.distributions()
    }
    assert {"lumio-wiki", "msgspec"} <= installed
    assert installed.isdisjoint(FORBIDDEN), sorted(installed & FORBIDDEN)

    import lumio_wiki

    kb, report = lumio_wiki.load_knowledge_base(valid_fixture)
    assert report.is_valid
    assert lumio_wiki.validate(valid_fixture).is_valid
    assert kb.fingerprint().digest == lumio_wiki.fingerprint_sources(valid_fixture).digest
    assert kb.search_pages("LanceDB")
    assert kb.lookup_by_title("Architecture")[0].body
    assert kb.related_from("Lumio Overview") == []
    assert kb.graph_path("Lumio Overview", "Technology Stack") is None
    assert kb.retrieve("Lumio uses LanceDB", limit=2)
    health = kb.health_report()
    assert not health.broken_relationships

    with tempfile.TemporaryDirectory() as temporary:
        regenerated = Path(temporary) / "kb"
        shutil.copytree(categorized_fixture, regenerated)
        lumio_wiki.regenerate_reserved_artifacts(regenerated)
        assert (regenerated / "index.md").is_file()
        assert (regenerated / "hot.md").is_file()
        categorized, categorized_report = lumio_wiki.load_knowledge_base(regenerated)
        assert categorized_report.is_valid
        assert categorized.control is not None
        assert categorized.related_from("Lumio Overview") == [
            lumio_wiki.Relationship(target="Acme Corp", type="uses")
        ]
        assert categorized.graph_path("Lumio Overview", "Acme Corp") == [
            "Lumio Overview",
            "Acme Corp",
        ]

        entry = lumio_wiki.make_activity_log_entry(
            operation="verify",
            description="isolated wheel publication",
        )
        log_path = lumio_wiki.append_activity_log_entry(regenerated, entry)
        assert log_path == regenerated / "log.md"
        assert "verify: isolated wheel publication" in log_path.read_text(encoding="utf-8")

        exported = lumio_wiki.export_okf_profile1(kb.public_pages())
        bundle = Path(temporary) / "okf"
        for relative, content in exported.files.items():
            target = bundle / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        assert lumio_wiki.import_okf_profile1(bundle).proposed_pages

        authoring = Path(temporary) / "authoring"
        shutil.copytree(categorized_fixture, authoring, ignore=shutil.ignore_patterns(".lumio"))
        (authoring / ".lumio-authoring.yaml").write_text(
            "version: 1\nnamespace: installed-wheel-proof\nsources: {}\nbindings: {}\n"
        )
        subprocess.run(["git", "init", "-q", str(authoring)], check=True)
        for key, value in (("user.name", "Wheel verifier"), ("user.email", "wheel@example.com")):
            subprocess.run(["git", "-C", str(authoring), "config", key, value], check=True)
        subprocess.run(["git", "-C", str(authoring), "add", "-A"], check=True)
        subprocess.run(["git", "-C", str(authoring), "commit", "-qm", "Adopt KB"], check=True)
        original = Path(temporary) / "original.txt"
        original.write_bytes(b"Private wheel source A.\n")
        authored = Path(temporary) / "compiled.md"
        authored.write_text(
            "---\nid: entity:wheel-proof\ntitle: Wheel Proof\nentity_types: [concept]\n"
            "tags: [wheel]\nsummary: Portable compiled knowledge.\n"
            "category: references\ntype: source-digest\n"
            "durability_rationale: Stable installation reference.\n"
            "lifecycle: approved\nvisibility: public\n"
            "sources:\n  - id: wheel-source\n    title: Wheel source\n---\n\n"
            "# Wheel Proof\n\nWheel sources remain private; compiled knowledge is portable.\n"
        )
        registry = Path(temporary) / "private-registry"
        _cli(
            "ingest",
            str(authoring),
            str(original),
            "--compiled-page",
            str(authored),
            "--source-id",
            "wheel-source",
            "--source-registry",
            str(registry),
            cwd=authoring,
        )
        _cli("validate", str(authoring), cwd=authoring)
        assert not (authoring / ".lumio/ingest/proposals").exists()
        subprocess.run(
            ["git", "-C", str(authoring), "add", "references", ".lumio-authoring.yaml"], check=True
        )
        subprocess.run(
            ["git", "-C", str(authoring), "commit", "-qm", "Authored knowledge"], check=True
        )
        revision = subprocess.check_output(
            ["git", "-C", str(authoring), "rev-parse", "HEAD"],
            text=True,
        ).strip()
        destination = Path(temporary) / "published"
        args = (
            "publish",
            str(authoring),
            "--revision",
            revision,
            "--to",
            str(destination),
            "--expected-current",
            "none",
            "--source-registry",
            str(registry),
            "--json",
        )
        review = json.loads(_cli(*args, cwd=authoring))
        assert review["revision"] == revision and not review["blocking_diagnostics"]
        assert not destination.exists(), "preview must not prepare or activate a version"
        # This verifier authorizes only its own disposable fixture publication.
        receipt = json.loads(_cli(*args, "--confirm", review["review_digest"], cwd=authoring))
        assert receipt["activated"] and receipt["revision"] == revision
        snapshot = lumio_wiki.open_knowledge_base(lumio_wiki.FilesystemLocation(destination))
        page = snapshot.knowledge_base.lookup_by_title("Wheel Proof")[0]
        assert "Wheel sources remain private; compiled knowledge is portable." in page.body
        assert not any(p.name == ".lumio-authoring.yaml" for p in destination.rglob("*"))
        assert not any(p.name == "original.txt" for p in destination.rglob("*"))

        no_git = Path(temporary) / "empty-path"
        no_git.mkdir()
        read_env = {**os.environ, "PATH": str(no_git)}
        assert shutil.which("git", path=read_env["PATH"]) is None
        _cli("validate", str(authoring), cwd=no_git, env=read_env)
        query = _cli("search", str(destination), "compiled knowledge", cwd=no_git, env=read_env)
        assert "Wheel Proof" in query and "references/wheel_proof.md" in query
        raw = _cli("page", str(destination), "Wheel Proof", "--raw", cwd=no_git, env=read_env)
        assert "Wheel sources remain private; compiled knowledge is portable." in raw
        print(
            "installed Git author/admit/query and Git-free validation/read/query passed:", revision
        )

    imported_forbidden = {
        name.split(".", 1)[0] for name in sys.modules if name.split(".", 1)[0] in FORBIDDEN
    }
    assert not imported_forbidden, sorted(imported_forbidden)
    print("lumio-wiki isolated wheel verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
