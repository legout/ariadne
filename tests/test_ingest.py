"""Git-candidate document ingestion (specs 0021 and 0027 §5).

LLM responses are fixture-mocked (no network), the per-type gate runs for real,
and converter calls use the existing optional [documents] dependencies.
"""

import base64
import hashlib
import json
import sys
import zipfile
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:  # keep tests runnable from the source tree
    sys.path.insert(0, str(REPO_ROOT))

from ariadne import admission as admission_module  # noqa: E402
from ariadne import authoring_sources  # noqa: E402
from ariadne.authoring import AuthoringProject  # noqa: E402
from ariadne.ingest import (  # noqa: E402
    _CONVERTERS,
    _NATIVE_SUFFIXES,
    MAX_RETRIES,
    Reconciliation,
    ingest,
    main,
    reconcile_ingest,
)
from ariadne.init import main as init_main  # noqa: E402
from tests.test_git_authoring import complete_bundle_project, run_git, worktree_of  # noqa: E402

MODEL = "test-model"


def page_entry(**overrides) -> dict:
    """One gate-clean policy page entry (the shape the system prompt asks for)."""
    entry = {
        "folder": "policies",
        "name": "churned-arr-not-expansion",
        "type": "policy",
        "title": "Churned ARR is not expansion",
        "description": "CHURNED renewal rows are excluded from expansion totals.",
        "tags": ["policy", "arr", "ingest"],
        "body": "# Churned ARR is not expansion\n\nCHURNED rows record lost ARR.",
    }
    entry.update(overrides)
    return entry


def response(*entries: dict) -> str:
    return json.dumps({"pages": list(entries)})


def make_doc(tmp_path: Path, suffix: str = ".md", text: str | None = None) -> Path:
    doc = tmp_path / f"notes{suffix}"
    doc.write_text(
        text or "# Renewal notes\n\nCHURNED rows must never be summed into expansion totals.\n",
        encoding="utf-8",
    )
    return doc


class GitIngestCase:
    """A real Authoring proposal for tests focused on document conversion."""

    def __init__(
        self,
        tmp_path: Path,
        docs: Sequence[str | Path],
        initial_files: dict[str, str] | None = None,
    ):
        self.project = complete_bundle_project(tmp_path / "project")
        registry = self.project / "ariadne.yaml"
        config = yaml.safe_load(registry.read_text(encoding="utf-8"))
        config["documents"] = {"roots": sorted({str(Path(doc).parent.resolve()) for doc in docs})}
        registry.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
        commit_paths = ["ariadne.yaml"]
        for rel, content in (initial_files or {}).items():
            path = self.project / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            commit_paths.append(rel)
        run_git(self.project, "add", "--", *commit_paths)
        run_git(
            self.project,
            "commit",
            "-q",
            "-m",
            "human: configure ingest fixture",
            "--",
            *commit_paths,
        )
        self.authoring = AuthoringProject(self.project)
        self.started = self.authoring.start_proposal()
        self.proposal = self.started["proposal"]
        self.revision = self.started["candidate_revision"]
        self.worktree = worktree_of(self.project, self.proposal)
        # The operator's G3 approval of the exact resolved registry identity
        # (spec 0027 §5: source approval is a separate human decision recorded
        # through the approve-sources seam; validate/admit requires the grant).
        resolved, digest = authoring_sources.candidate_sources(self.project, self.revision)
        assert resolved is not None and digest is not None
        self.authoring.approve_sources(self.proposal, self.revision, digest)

    def ingest(self, docs: Sequence[str | Path], *, complete=None, verbatim: bool = False) -> dict:
        result = ingest(
            list(docs),
            project=self.project,
            proposal=self.proposal,
            expected_revision=self.revision,
            complete=complete,
            verbatim=verbatim,
        )
        self.revision = result["candidate_revision"]
        return result

    def reconcile(
        self, docs: Sequence[str | Path], *, complete=None
    ) -> tuple[dict, list[Reconciliation]]:
        result, comparisons = reconcile_ingest(
            list(docs),
            project=self.project,
            proposal=self.proposal,
            expected_revision=self.revision,
            complete=complete,
        )
        self.revision = result["candidate_revision"]
        return result, comparisons

    def pages(self, result: dict) -> list[Path]:
        return [self.worktree / rel for rel in (*result["written"], *result["unchanged"])]

    def written_pages(self, result: dict) -> list[Path]:
        return [self.worktree / rel for rel in result["written"]]

    def start_next(self) -> None:
        self.started = self.authoring.start_proposal()
        self.proposal = self.started["proposal"]
        self.revision = self.started["candidate_revision"]
        self.worktree = worktree_of(self.project, self.proposal)

    def edit_page(self, section: str, name: str, content: str) -> None:
        edited = self.authoring.edit_proposal(
            self.proposal,
            self.revision,
            {"kind": "page", "section": section, "name": name, "content": content},
        )
        self.revision = edited["revision"]

    def admit(self) -> Path:
        validated = self.authoring.validate_proposal(self.proposal, self.revision)
        assert validated["ok"] is True, validated["errors"]
        review = self.authoring.review_proposal(self.proposal)
        assert review["revision"] == validated["revision"]
        admission_module.admit_revision(
            self.project,
            self.proposal,
            review["revision"],
            review["review_digest"],
            confirmed_by="human:alice",
        )
        _, snapshot = admission_module.resolve_admission(self.project)
        return snapshot


_CASE_BY_WORKTREE: dict[Path, GitIngestCase] = {}


def _case_for_worktree(worktree: Path) -> GitIngestCase:
    return _CASE_BY_WORKTREE[worktree.resolve()]


def run_ingest(tmp_path: Path, doc: Path, responses: list[str], monkeypatch):
    """One conversion call through a real revision-checked Git proposal."""
    monkeypatch.setenv("OPENAI_MODEL", MODEL)
    calls: list[list[dict]] = []

    def complete(messages):
        calls.append(messages)
        return responses[min(len(calls), len(responses)) - 1]

    case = GitIngestCase(tmp_path, [doc])
    result = case.ingest([doc], complete=complete)
    _CASE_BY_WORKTREE[case.worktree.resolve()] = case
    return case.worktree, case.pages(result), result["errors"], calls


def front_of(page: Path) -> dict:
    return yaml.safe_load(page.read_text(encoding="utf-8").split("---")[1])


# --- (a) md ingestion: typed page, mechanical provenance ----------------------


def test_md_ingestion_commits_typed_candidate_page_with_provenance(tmp_path, monkeypatch):
    doc = make_doc(tmp_path)
    staging, staged, errors, calls = run_ingest(
        tmp_path, doc, [response(page_entry())], monkeypatch
    )

    assert errors == [] and len(calls) == 1  # passed on the first attempt
    page = staging / "context_layer" / "policies" / "churned-arr-not-expansion.md"
    assert staged == [page] and page.is_file()

    front = front_of(page)
    assert front["type"] == "policy"
    assert front["status"] == "draft"
    assert front["generated"]["by"] == f"ariadne-ingest:{MODEL}"
    assert front["generated"]["at"]  # ISO stamp present
    (source,) = front["sources"]
    assert source["id"] == hashlib.sha256(doc.read_bytes()).hexdigest()[:12]
    assert source["resource"] == str(doc.resolve())
    assert source["title"] == doc.name
    assert "CHURNED" in page.read_text(encoding="utf-8")  # body survived assembly


def test_multi_page_response_commits_every_candidate_page(tmp_path, monkeypatch):
    doc = make_doc(tmp_path)
    entries = [
        page_entry(),
        page_entry(
            folder="tables",
            name="renewals",
            type="table",
            tags=["table", "renewals"],
            grain={
                "primary_key": ["account_id", "renewal_date"],
                "cardinality_enforcement": "STRICT_1_TO_1",
            },
            body="# renewals\n\nOne row per renewal event.",
        ),
    ]
    staging, staged, errors, _ = run_ingest(tmp_path, doc, [response(*entries)], monkeypatch)

    assert errors == []
    assert {p.parent.name for p in staged} == {"policies", "tables"}
    front = front_of(staging / "context_layer" / "tables" / "renewals.md")
    assert front["type"] == "table"
    assert front["grain"]["primary_key"] == ["account_id", "renewal_date"]


# --- (b) contract violations: retry loop, no partial candidate commit --------


def test_contract_violation_retries_then_stages_nothing(tmp_path, monkeypatch):
    doc = make_doc(tmp_path)
    # every round proposes a metrics page — author-owned, never ingestable
    staging, staged, errors, calls = run_ingest(
        tmp_path, doc, [response(page_entry(folder="metrics", type="metric"))], monkeypatch
    )

    assert len(calls) == 1 + MAX_RETRIES  # first attempt + ≤2 retries, then stop
    assert errors and any("author-owned" in error for error in errors)
    assert run_git(staging, "status", "--short") == ""  # rejected entries never entered Git
    feedback = calls[1][-1]["content"]
    assert "Contract violations" in feedback  # error feedback loop like the author


def test_frontmatter_gate_violation_is_fed_back_and_repaired(tmp_path, monkeypatch):
    doc = make_doc(tmp_path)
    bad = page_entry(tags=[])  # gate: policy page requires 'tags'
    staging, staged, errors, calls = run_ingest(
        tmp_path, doc, [response(bad), response(page_entry())], monkeypatch
    )

    assert len(calls) == 2  # round 1 rejected, round 2 recovered
    assert any("'tags'" in error for error in errors[0:1]) or errors == []
    assert staged and front_of(staged[0])["status"] == "draft"
    assert not any("review_needed" in p.read_text() for p in staged)


def test_gate_rejects_table_page_without_grain(tmp_path, monkeypatch):
    """Spec 0010 §3 (issue #41): a physical table page may carry UNKNOWN
    Grain — an absent grain block stages fine — while a DECLARED but
    malformed grain block (missing cardinality_enforcement) is still a named
    violation."""
    doc = make_doc(tmp_path)
    unknown = page_entry(folder="tables", name="renewals", type="table", tags=["table"])
    _, staged, errors, _ = run_ingest(tmp_path, doc, [response(unknown)], monkeypatch)
    assert staged != [] and errors == []  # unknown Grain stages honestly

    malformed = page_entry(
        folder="tables",
        name="renewals2",
        type="table",
        tags=["table"],
        grain={"primary_key": ["id"]},
    )
    _, staged, errors, _ = run_ingest(tmp_path, doc, [response(malformed)], monkeypatch)
    assert staged == []  # nothing staged...
    assert errors and any("grain" in error for error in errors)  # ...violation named


def test_index_and_log_names_never_enter_candidate(tmp_path, monkeypatch):
    doc = make_doc(tmp_path)
    _, staged, errors, _ = run_ingest(
        tmp_path, doc, [response(page_entry(name="index"))], monkeypatch
    )
    assert staged == [] and any("bookkeeping" in error for error in errors)


# --- (c) unclassifiable -> references/ + ingest tag ---------------------------


def test_unclassifiable_lands_in_references_with_ingest_tag(tmp_path, monkeypatch):
    doc = make_doc(tmp_path, text="Meeting musings with no schema and no rule.\n")
    entry = page_entry(
        folder="references",
        name="cs-weekly-musings",
        type="reference",
        tags=["ingest", "notes"],
        body="# CS weekly musings\n\nBackground context worth keeping.",
    )
    staging, staged, errors, _ = run_ingest(tmp_path, doc, [response(entry)], monkeypatch)

    assert errors == []
    page = staging / "context_layer" / "references" / "cs-weekly-musings.md"
    assert staged == [page]
    front = front_of(page)
    assert front["type"] == "reference" and "ingest" in front["tags"]


# --- (c2) K2: structured References survive ingestion (issue #42) ------------


def _reference_entry(**overrides) -> dict:
    """One gate-clean structured Reference entry: the order-number term with
    its allowlisted aliases/bindings/declaration (the allowlist shape the K2
    system prompt describes)."""
    payload = (
        base64.urlsafe_b64encode(
            json.dumps(["orders", None, "orders", "orders"], separators=(",", ":")).encode()
        )
        .decode()
        .rstrip("=")
    )
    entry = page_entry(
        folder="references",
        name="order-number",
        type="reference",
        title="Order number",
        description="The shared order-number concept of the orders store.",
        tags=["reference", "term"],
        body=(
            "# Order number\n\nThe store-scoped local number and the concatenated global identity."
        ),
    )
    entry["aliases"] = ["order number concept"]
    entry["ariadne"] = {
        "version": 1,
        "reference_role": "term",
        "representations": [
            {
                "id": "global-order-number",
                "aliases": ["global order number"],
                "fields": [
                    {
                        "resource": f"ariadne://table/{payload}",
                        "column": "global_order_number",
                    }
                ],
                "scope": [],
            }
        ],
        "mappings": [],
    }
    entry.update(overrides)
    return entry


def test_ingest_preserves_reference_bindings_without_fabricating_measurements(
    tmp_path, monkeypatch
):
    """K2 (issue #42, spec 0010 §3/AC10): ordinary ingestion PRESERVES the
    allowlisted aliases/bindings/structured declaration with the ACTUAL input
    document's provenance — the previous _assemble silently dropped them — and
    the shared per-type gate refuses a fabricated confirmation/measurement
    claim, feeding it back instead of staging anything."""
    doc = make_doc(
        tmp_path,
        text="# Order numbers\n\nA global order number concatenates the store prefix "
        "and the local number; both representations are documented here.\n",
    )
    staging, staged, errors, calls = run_ingest(
        tmp_path, doc, [response(_reference_entry())], monkeypatch
    )

    assert errors == []
    page = staging / "context_layer" / "references" / "order-number.md"
    assert staged == [page]
    front = front_of(page)
    # the structured declaration survived the candidate write verbatim (the
    # metadata-loss path: _assemble used to drop everything but fixed keys)
    assert front["aliases"] == ["order number concept"]
    extension = front["ariadne"]
    assert extension["version"] == 1 and extension["reference_role"] == "term"
    (representation,) = extension["representations"]
    assert representation["id"] == "global-order-number"
    assert representation["fields"][0]["column"] == "global_order_number"
    assert representation["fields"][0]["resource"].startswith("ariadne://table/")
    # provenance is the ACTUAL input document — mechanically attached, never
    # authored — and no measurement/approval state was fabricated
    assert front["sources"] == [
        {
            "id": hashlib.sha256(doc.read_bytes()).hexdigest()[:12],
            "resource": str(doc.resolve()),
            "title": doc.name,
        }
    ]
    assert "status" in front and front["status"] == "draft"
    assert set(front) == {
        "type",
        "status",
        "title",
        "description",
        "tags",
        "sources",
        "generated",
        "aliases",
        "ariadne",
    }
    # the resolver reads the staged page: the preserved declaration resolves
    from ariadne.context import resolve_term

    resolved = resolve_term([(staging / "context_layer", True)], "global order number")
    assert [match["representation"] for match in resolved["matches"]] == ["global-order-number"]
    assert resolved["matches"][0]["draft"] is True

    # a fabricated confirmation claim is REFUSED: the gate feeds it back and
    # nothing is staged (the strict mapping allowlist, shared with Git
    # validation — a document never confirms itself)
    forged = _reference_entry()
    forged["ariadne"] = {
        **forged["ariadne"],
        "mappings": [
            {
                "id": "local-to-global",
                "family": "prefix",
                "from": "global-order-number",
                "to": "global-order-number",
                "claim": "asserted",
                "source_ids": [],
                "confirmed": True,
                "tested": 999,
            }
        ],
    }
    second = tmp_path / "second"
    second.mkdir()
    staging2, staged2, errors2, _calls = run_ingest(
        second, make_doc(second, text="second document\n"), [response(forged)], monkeypatch
    )
    assert staged2 == [] and errors2, "a fabricated claim must never stage"
    assert any("unsupported field(s)" in error for error in errors2)
    assert any("'confirmed'" in error for error in errors2)


def test_non_reference_ariadne_blocks_are_refused_not_preserved(tmp_path, monkeypatch):
    """Spec 0010 §3: the ``ariadne`` extension belongs to References. A table
    or policy entry carrying one — fabricated authority/measurements included
    — is REFUSED at staging (nothing stages while it stands), never laundered
    by silently preserving or dropping the block; the repaired entry without
    it stages clean."""
    doc = make_doc(tmp_path)
    smuggled = page_entry(
        folder="tables",
        name="renewals",
        type="table",
        tags=["table", "renewals"],
        body="# renewals\n\nOne row per renewal event.",
    )
    smuggled["ariadne"] = {"confirmed": True, "observations": {"tested": 999}}
    clean = {key: value for key, value in smuggled.items() if key != "ariadne"}

    # the block standing on a non-Reference: refused every round, nothing staged
    staging, staged, errors, calls = run_ingest(tmp_path, doc, [response(smuggled)], monkeypatch)
    assert staged == []
    assert len(calls) == 1 + MAX_RETRIES  # fed back each round, never written
    assert any("belongs to References" in error for error in errors)
    case = _case_for_worktree(staging)
    assert case.revision == case.started["candidate_revision"]

    # the fed-back violation is repairable: the entry without the block stages
    repair = tmp_path / "repair"
    repair.mkdir()
    _, staged2, errors2, _ = run_ingest(
        repair, make_doc(repair), [response(smuggled), response(clean)], monkeypatch
    )
    assert errors2 == [] and len(staged2) == 1
    assert "ariadne" not in front_of(staged2[0])  # never preserved on a table


def test_mapping_citing_the_input_document_stages_and_validates(tmp_path, monkeypatch):
    """The document's staged footnote id is core-owned: the prompt material
    carries the ACTUAL staged citation id, the model cites the input document
    with the explicit ``@document`` token, and _assemble binds the token
    mechanically to the real digest id — a documented asserted mapping
    survives ingestion and validates (not only empty-mappings documents)."""
    doc = make_doc(
        tmp_path,
        text="# Order numbers\n\nA global order number concatenates the store "
        "prefix and the local number; the document states the correspondence.\n",
    )
    entry = _reference_entry()
    table_resource_uri = entry["ariadne"]["representations"][0]["fields"][0]["resource"]
    entry["ariadne"]["representations"].append(
        {
            "id": "local-order-number",
            "aliases": ["local order number"],
            "fields": [{"resource": table_resource_uri, "column": "local_order_number"}],
            "scope": [],
        }
    )
    entry["ariadne"]["mappings"] = [
        {
            "id": "documented-correspondence",
            "family": "prefix",
            "from": "local-order-number",
            "to": "global-order-number",
            "claim": "asserted",
            "source_ids": ["@document"],
        }
    ]
    digest = hashlib.sha256(doc.read_bytes()).hexdigest()[:12]
    staging, staged, errors, calls = run_ingest(tmp_path, doc, [response(entry)], monkeypatch)

    assert errors == []
    assert staged == [staging / "context_layer" / "references" / "order-number.md"]
    # the prompt material named the ACTUAL staged citation id (core-owned)
    assert digest in calls[0][1]["content"]
    # the token was bound mechanically — the staged mapping cites the digest
    front = front_of(staged[0])
    assert front["ariadne"]["mappings"][0]["source_ids"] == [digest]
    assert "@document" not in staged[0].read_text(encoding="utf-8")
    # and the staged page validates end to end: the resolver serves the mapping
    from ariadne.context import resolve_term

    resolved = resolve_term([(staging / "context_layer", True)], "global order number")
    [mapping] = resolved["matches"][0]["mappings"]
    assert mapping["claim"] == "asserted" and mapping["source_ids"] == [digest]


def test_ingestion_does_not_register_mentioned_sources_or_retain_originals(tmp_path, monkeypatch):
    """Mentioned locations stay inert, and originals remain outside authored Git."""
    doc = make_doc(
        tmp_path,
        text="# Warehouse notes\n\nThe nightly warehouse snapshot lives at "
        "s3://corp/warehouse/sales as an iceberg table; returns land in the "
        "finance Postgres.\n",
    )
    entry = page_entry(
        folder="tables",
        name="warehouse-sales",
        type="table",
        tags=["table", "warehouse"],
        body=(
            "# Warehouse sales\n\nThe nightly snapshot mentioned by the document "
            "(s3://corp/warehouse/sales); no schema was measured.\n"
        ),
    )
    case = GitIngestCase(tmp_path, [doc])
    project = case.project
    registry = project / "ariadne.yaml"
    registry_before = registry.read_bytes()
    result = case.ingest([doc], complete=lambda _m: response(entry))
    staged, errors = case.pages(result), result["errors"]

    assert errors == [] and staged
    # the staged page cites the ACTUAL input document — mechanically attached
    front = front_of(staged[0])
    (source,) = front["sources"]
    assert source["id"] == hashlib.sha256(doc.read_bytes()).hexdigest()[:12]
    assert source["resource"] == str(doc.resolve())
    # no measured facts were fabricated for the mentioned location
    assert "ariadne" not in front and "grain" not in front
    assert front["status"] == "draft"

    # the mentioned source was never registered: the project registry and the
    # local source set are byte-identical, and nothing was connected
    assert registry.read_bytes() == registry_before
    config = yaml.safe_load(registry.read_text(encoding="utf-8"))
    assert {source["name"] for source in config["sources"]} == {"events", "labels"}
    candidate_files = run_git(
        project, "ls-tree", "-r", "--name-only", result["candidate_revision"]
    ).splitlines()
    assert "context_layer/tables/warehouse-sales.md" in candidate_files
    assert not any(path.startswith("answer_examples/") for path in candidate_files)
    assert "data/docs/notes.md" not in candidate_files  # original is external, not retained
    assert not (project / "staging").exists()


# --- (d) name collisions suffix atomically -----------------------------------


def test_name_collision_suffixes_never_overwrites(tmp_path, monkeypatch):
    doc = make_doc(tmp_path)
    original = "---\ntype: policy\n---\n\nkeep me\n"
    case = GitIngestCase(
        tmp_path,
        [doc],
        {"context_layer/policies/churned-arr-not-expansion.md": original},
    )
    result = case.ingest([doc], complete=lambda _m: response(page_entry()))

    assert result["errors"] == []
    assert result["written"] == ["context_layer/policies/churned-arr-not-expansion-2.md"]
    existing = case.worktree / "context_layer/policies/churned-arr-not-expansion.md"
    assert existing.read_text(encoding="utf-8") == original


# --- (e) unsupported extension + missing extra name the extra ----------------


def test_unsupported_extension_error_names_support_and_extra(tmp_path, monkeypatch):
    doc = make_doc(tmp_path, suffix=".pages")
    staging, staged, errors, calls = run_ingest(
        tmp_path, doc, [response(page_entry())], monkeypatch
    )

    assert staged == [] and calls == []  # rejected before any LLM call
    (error,) = errors
    assert "[documents]" in error and "uv pip install" in error
    assert ".md" in error and ".pdf" in error  # the supported set is named


def test_missing_pdf_converter_error_names_requirement(tmp_path, monkeypatch):
    doc = make_doc(tmp_path, suffix=".pdf", text="unused")
    monkeypatch.setenv("OPENAI_MODEL", MODEL)
    monkeypatch.setitem(sys.modules, "liteparse", None)  # import raises ImportError
    monkeypatch.setitem(sys.modules, "liteparse.parser", None)
    case = GitIngestCase(tmp_path, [doc])
    result = case.ingest([doc], complete=lambda _m: "")

    assert case.pages(result) == []
    assert any("liteparse" in error and "[documents]" in error for error in result["errors"])


def test_missing_docx_converter_error_names_markitdown_extra(tmp_path, monkeypatch):
    doc = make_doc(tmp_path, suffix=".docx", text="unused")
    monkeypatch.setenv("OPENAI_MODEL", MODEL)
    monkeypatch.setitem(sys.modules, "markitdown", None)
    case = GitIngestCase(tmp_path, [doc])
    result = case.ingest([doc], complete=lambda _m: "")

    assert case.pages(result) == []
    assert any("markitdown[docx]" in error for error in result["errors"])


def test_ingest_writes_only_to_the_selected_git_candidate(tmp_path, monkeypatch):
    doc = make_doc(tmp_path)
    case = GitIngestCase(tmp_path, [doc])
    result = case.ingest([doc], complete=lambda _m: response(page_entry()))

    assert result["errors"] == []
    assert result["written"] == ["context_layer/policies/churned-arr-not-expansion.md"]
    assert case.pages(result) == [
        case.worktree / "context_layer/policies/churned-arr-not-expansion.md"
    ]
    assert not (case.project / "staging").exists()
    candidate_files = run_git(
        case.project, "ls-tree", "-r", "--name-only", result["candidate_revision"]
    ).splitlines()
    assert not any(path.startswith("data/docs/") for path in candidate_files)


def test_model_stamp_uses_env_loaded_by_the_first_call(tmp_path, monkeypatch):
    """Regression (live run): the default endpoint loads ARIADNE_ENV inside the
    first LLM call — the stamp must be read after that, not before."""
    doc = make_doc(tmp_path)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)

    def complete(messages):
        monkeypatch.setenv("OPENAI_MODEL", "late-model")  # what _load_env does
        return response(page_entry())

    case = GitIngestCase(tmp_path, [doc])
    result = case.ingest([doc], complete=complete)
    assert result["errors"] == []
    assert front_of(case.pages(result)[0])["generated"]["by"] == "ariadne-ingest:late-model"


# --- (f) init scaffolds operator inputs, not a document upload store -----------


def test_init_keeps_private_document_inputs_operator_managed(tmp_path):
    target = tmp_path / "proj"
    assert init_main([str(target)]) == 0
    seed_notes = target / "data" / "seed_notes.md"
    docs = target / "data" / "docs"
    assert seed_notes.is_file() and not docs.exists()
    inert_files = ("ariadne.yaml", "AGENTS.md", ".env.example", ".gitignore")
    assert all((target / path).is_file() for path in inert_files)

    seed_notes.write_text("# Operator-maintained seed notes\n", encoding="utf-8")
    private = docs / "contract.md"
    private.parent.mkdir(parents=True)
    private.write_text("# Operator-owned original\n", encoding="utf-8")
    seed_bytes = seed_notes.read_bytes()
    private_bytes = private.read_bytes()

    assert init_main([str(target)]) == 0  # idempotent re-run never overwrites inputs
    assert seed_notes.read_bytes() == seed_bytes
    assert private.read_bytes() == private_bytes


# --- (g) converter dispatch table + real conversions behind importorskip ------


@pytest.mark.parametrize(
    ("suffix", "requirement"),
    [
        (".pdf", "liteparse"),
        (".docx", "markitdown[docx]"),
        (".pptx", "markitdown[docx]"),
        (".xlsx", "markitdown[docx]"),
        (".html", "markitdown[docx]"),
        (".doc", "firecrawl-anydoc"),
        (".rtf", "firecrawl-anydoc"),
        (".epub", "firecrawl-anydoc"),
        (".csv", "firecrawl-anydoc"),
        (".odt", "firecrawl-anydoc"),
        (".ods", "firecrawl-anydoc"),
        (".odp", "firecrawl-anydoc"),
        (".xls", "firecrawl-anydoc"),
    ],
)
def test_dispatch_table_maps_suffix_to_requirement(suffix, requirement):
    assert suffix in _CONVERTERS
    assert _CONVERTERS[suffix][1] == requirement


def test_dispatch_table_exactly_matches_native_suffixes():
    assert set(_CONVERTERS) | set(_NATIVE_SUFFIXES) == {
        ".md",
        ".txt",
        ".pdf",
        ".docx",
        ".pptx",
        ".xlsx",
        ".html",
        ".doc",
        ".rtf",
        ".epub",
        ".csv",
        ".odt",
        ".ods",
        ".odp",
        ".xls",
    }


def test_native_conversion_is_plain_read(tmp_path):
    from ariadne.ingest import _convert

    doc = make_doc(tmp_path)
    assert _convert(doc) == doc.read_text(encoding="utf-8")


def _minimal_pdf(path: Path) -> Path:
    lines = [
        b"%PDF-1.4",
        b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj",
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj",
        b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]"
        b"/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>endobj",
        b"4 0 obj<</Length 60>>stream",
        b"BT /F1 24 Tf 72 700 Td (Renewals policy notes) Tj ET",
        b"endstream",
        b"endobj",
        b"5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj",
        b"trailer<</Root 1 0 R>>",
    ]
    path.write_bytes(b"\n".join(lines))
    return path


def test_pdf_conversion_via_liteparse(tmp_path):
    pytest.importorskip("liteparse")
    from ariadne.ingest import _convert

    text = _convert(_minimal_pdf(tmp_path / "doc.pdf"))
    assert "Renewals policy notes" in text


def _minimal_docx(path: Path) -> Path:
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body><w:p><w:r><w:t>Renewal policy from the handbook</w:t></w:r></w:p></w:body>"
        "</w:document>"
    )
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/word/document.xml" ContentType="application/vnd.'
            'openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>',
        )
        zf.writestr(
            "_rels/.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/'
            'officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
            "</Relationships>",
        )
        zf.writestr("word/document.xml", document)
    return path


def test_docx_conversion_via_markitdown(tmp_path):
    pytest.importorskip("markitdown")
    from ariadne.ingest import _convert

    text = _convert(_minimal_docx(tmp_path / "handbook.docx"))
    assert "Renewal policy from the handbook" in text


def test_html_conversion_via_markitdown(tmp_path):
    pytest.importorskip("markitdown")
    from ariadne.ingest import _convert

    doc = tmp_path / "page.html"
    doc.write_text(
        "<html><body><h1>Fiscal calendar</h1><p>FY ends in <b>June</b>.</p></body></html>"
    )
    text = _convert(doc)
    assert "Fiscal calendar" in text and "June" in text


def test_rtf_conversion_via_firecrawl_anydoc(tmp_path):
    pytest.importorskip("anydoc")
    from ariadne.ingest import _convert

    doc = tmp_path / "memo.rtf"
    doc.write_text(r"{\rtf1\ansi Churned ARR is not booked ARR.}")
    assert "Churned ARR" in _convert(doc)


# --- (h) untrusted model output ------------------------------------------------


# --- (i) secret scan: LLM output is untrusted ------------------------------


def test_secret_token_in_body_rejects_page_naming_class_not_secret(tmp_path, monkeypatch):
    """A source document's credentials echoed by the LLM must never reach
    staging: the page is rejected naming the pattern CLASS, the secret value
    itself appears nowhere in the feedback or errors, and nothing is staged."""
    doc = make_doc(tmp_path)
    secret = "sk-" + "a1B2c3D4e5F6g7H8i9J0k1"  # fake token, 24 chars
    poisoned = page_entry(body=f"# Rotation\n\nuse {secret} in prod\n")
    staging, staged, errors, calls = run_ingest(
        tmp_path,
        doc,
        [response(poisoned)],
        monkeypatch,  # replayed every round
    )

    assert len(calls) == 1 + MAX_RETRIES  # every round violates
    case = _case_for_worktree(staging)
    assert staged == [] and case.revision == case.started["candidate_revision"]
    feedback = calls[1][-1]["content"]
    assert "api_token" in feedback  # pattern CLASS named
    assert secret not in feedback and secret not in str(errors)  # value never echoed


def test_secret_page_rejected_then_clean_retry_stages(tmp_path, monkeypatch):
    """The retry loop continues without the secret: a clean round stages."""
    doc = make_doc(tmp_path)
    secret = "sk-" + "a1B2c3D4e5F6g7H8i9J0k1"
    staging, staged, errors, calls = run_ingest(
        tmp_path,
        doc,
        [response(page_entry(body=f"key {secret}")), response(page_entry())],
        monkeypatch,
    )

    assert len(calls) == 2  # round 1 rejected, round 2 recovered
    assert staged and front_of(staged[0])["status"] == "draft"
    assert not any(secret in page.read_text(encoding="utf-8") for page in staged)


@pytest.mark.parametrize(
    ("entry", "expected_class"),
    [
        (
            page_entry(body="# key\n\n-----BEGIN RSA PRIVATE KEY-----\nMIIEpA...\n"),
            "private_key",
        ),
        (page_entry(body="# aws\n\nid AKIAIOSFODNN7EXAMPLE\n"), "aws_access_key"),
        # frontmatter values are scanned too: title renders into the YAML block
        (page_entry(title="the settings password: hunter2"), "credential_assignment"),
        (
            page_entry(body="curl -H 'Authorization: Bearer eyJhbGciOiJIUzI1NiJ9'"),
            "bearer_token",
        ),
    ],
)
def test_secret_scan_covers_frontmatter_and_every_pattern_class(
    tmp_path, monkeypatch, entry, expected_class
):
    doc = make_doc(tmp_path)
    _, staged, errors, _ = run_ingest(tmp_path, doc, [response(entry)], monkeypatch)

    assert staged == []
    assert any(expected_class in error for error in errors)


# --- CLI ----------------------------------------------------------------------


def _ingest_cli_args(case: GitIngestCase, doc: Path) -> list[str]:
    return [
        str(doc),
        "--project",
        str(case.project),
        "--proposal",
        case.proposal,
        "--expected-revision",
        case.revision,
    ]


def test_cli_commits_and_reports_candidate(tmp_path, monkeypatch, capsys):
    import ariadne.ingest as ingest_module
    from ariadne import proposals

    doc = make_doc(tmp_path)
    case = GitIngestCase(tmp_path, [doc])
    monkeypatch.setenv("OPENAI_MODEL", MODEL)
    monkeypatch.setattr(ingest_module, "_default_complete", lambda _m: response(page_entry()))
    code = main(_ingest_cli_args(case, doc))

    assert code == 0
    out = capsys.readouterr().out
    assert "written: context_layer/policies/churned-arr-not-expansion.md" in out
    assert "candidate:" in out
    candidate = proposals._load_record(case.project, case.proposal)["candidate_revision"]
    page = case.worktree / "context_layer/policies/churned-arr-not-expansion.md"
    assert page.is_file()
    assert f"candidate: {candidate}" in out


def test_cli_fails_on_unsupported_extension(tmp_path, capsys):
    doc = make_doc(tmp_path, suffix=".pages")
    case = GitIngestCase(tmp_path, [doc])
    assert main(_ingest_cli_args(case, doc)) == 1
    assert "[documents]" in capsys.readouterr().err


def test_cli_refuses_retired_db_and_staging_selectors(tmp_path, monkeypatch):
    doc = make_doc(tmp_path)
    case = GitIngestCase(tmp_path, [doc])
    before = case.revision
    with pytest.raises(SystemExit):
        main([*_ingest_cli_args(case, doc), "--db", "demo.db", "--staging", "staging"])
    assert case.revision == before
    assert run_git(case.worktree, "status", "--short") == ""


# --- (j) opt-in evidence reconciliation (spec 2026-09-23-0004, issue #12 unit A) ---


APPROVED = "policies/churned-arr-not-expansion.md"  # context-layer-relative path
PROMOTED_AT = "2026-09-24T10:00:00+00:00"


_CASE_BY_SNAPSHOT: dict[Path, GitIngestCase] = {}


def _case_for_snapshot(snapshot: Path) -> GitIngestCase:
    return _CASE_BY_SNAPSHOT[snapshot.resolve()]


def _admit_case(case: GitIngestCase) -> Path:
    snapshot = case.admit()
    _CASE_BY_SNAPSHOT[snapshot.resolve()] = case
    case.start_next()
    return snapshot


def _reconcile_candidate(case: GitIngestCase, docs, *, complete=None):
    result, comparisons = case.reconcile(docs, complete=complete)
    return case.written_pages(result), result["errors"], comparisons


def _reconcile_snapshot(snapshot: Path, docs, *, complete=None):
    return _reconcile_candidate(_case_for_snapshot(snapshot), docs, complete=complete)


def _served_snapshot(served: Path) -> dict[str, bytes]:
    """Every immutable admitted file's bytes — reconciliation cannot rewrite it."""
    return {
        p.relative_to(served).as_posix(): p.read_bytes()
        for p in sorted(served.rglob("*"))
        if p.is_file()
    }


def test_reconcile_journey(tmp_path, monkeypatch):
    """Reconcile revisions against an admitted Git base without mutating it."""
    monkeypatch.setenv("OPENAI_MODEL", MODEL)
    doc = make_doc(tmp_path)
    case = GitIngestCase(tmp_path, [doc])
    first = case.ingest([doc], complete=lambda _m: response(page_entry()))
    assert first["errors"] == [] and len(first["written"]) == 1
    snapshot = _admit_case(case)

    page = case.worktree / "context_layer" / APPROVED
    human_text = page.read_text(encoding="utf-8").replace(
        "CHURNED rows record lost ARR.",
        "CHURNED rows record lost ARR. (annotated by the owner.)",
    )
    case.edit_page("policies", "churned-arr-not-expansion", human_text)
    snapshot = _admit_case(case)
    immutable = _served_snapshot(snapshot)

    doc.write_text(
        "# Renewal notes v2\n\nCHURNED never counts toward expansion or net new ARR.\n",
        encoding="utf-8",
    )
    changed_entry = page_entry(
        body="# Churned ARR is not expansion\n\nCHURNED rows record lost ARR and never "
        "count toward net new either."
    )
    no_conflict = _advisor_aware_complete(changed_entry, json.dumps({"possible_conflict": False}))
    written, errors, comparisons = _reconcile_candidate(case, [doc], complete=no_conflict)
    assert errors == [] and len(written) == 1
    assert written[0] == case.worktree / "context_layer" / APPROVED
    assert _served_snapshot(snapshot) == immutable
    (record,) = comparisons
    assert record.proposal == APPROVED
    assert record.match == "same-path" and record.change == "changed"
    assert record.old_source is not None
    assert record.old_source["digest"] != record.new_source["digest"]
    assert record.old_source["resource"] == record.new_source["resource"] == str(doc.resolve())
    diff_lines = record.diff.splitlines()
    assert "-CHURNED rows record lost ARR. (annotated by the owner.)" in diff_lines
    assert "+CHURNED rows record lost ARR and never count toward net new either." in diff_lines
    assert record.advisory.status == "none"
    front = front_of(written[0])
    assert front["status"] == "draft"
    assert front["sources"][0]["id"] == hashlib.sha256(doc.read_bytes()).hexdigest()[:12]

    snapshot = _admit_case(case)
    written, errors, comparisons = _reconcile_candidate(
        case, [doc], complete=lambda _m: response(changed_entry)
    )
    assert written == [] and errors == []
    (record,) = comparisons
    assert record.change == "unchanged" and record.candidate_path is not None

    doc.write_text(
        doc.read_text(encoding="utf-8") + "\n(v2 re-export with new bytes)\n", encoding="utf-8"
    )
    written, errors, comparisons = _reconcile_candidate(
        case, [doc], complete=lambda _m: response(changed_entry)
    )
    assert errors == [] and len(written) == 1
    (record,) = comparisons
    assert record.change == "provenance_only"
    digest = hashlib.sha256(doc.read_bytes()).hexdigest()[:12]
    assert front_of(written[0])["sources"][0]["id"] == digest

    snapshot = _admit_case(case)
    renamed = page_entry(name="churned-arr-not-expansion-v2")
    written, errors, comparisons = _reconcile_candidate(
        case, [doc], complete=lambda _m: response(renamed)
    )
    assert errors == [] and len(written) == 1
    assert written[0].name == "churned-arr-not-expansion-v2.md"
    (record,) = comparisons
    assert record.match == "new" and record.change == "new"
    assert record.warning is not None and "possible duplicate" in record.warning
    assert APPROVED in record.warning
    assert record.candidate_path == written[0].relative_to(case.worktree).as_posix()

    other = tmp_path / "other-playbook.md"
    other.write_text("# Another team's playbook\n\nTheir own rule.\n", encoding="utf-8")
    before_revision = case.revision
    written, errors, comparisons = _reconcile_candidate(
        case,
        [other],
        complete=lambda _m: response(
            page_entry(
                name="seat-based-renewal-window",
                title="Seat-based renewal window",
                description="Seats renew in the booked month.",
                body="# Seat-based renewal window\n\nSeats renew in the booked month.",
            ),
            page_entry(),
        ),
    )
    assert written == [] and comparisons == []
    assert any("identity conflict" in error and APPROVED in error for error in errors)
    assert case.revision == before_revision


def test_cli_reconcile_reports_match_diff_and_sources(tmp_path, monkeypatch, capsys):
    """The CLI reports a Git candidate comparison without editing admission."""
    import ariadne.ingest as ingest_module

    monkeypatch.setenv("OPENAI_MODEL", MODEL)
    doc = make_doc(tmp_path)
    case = GitIngestCase(tmp_path, [doc])
    first = case.ingest([doc], complete=lambda _m: response(page_entry()))
    assert first["errors"] == []
    _admit_case(case)

    page = case.worktree / "context_layer" / APPROVED
    case.edit_page(
        "policies",
        "churned-arr-not-expansion",
        page.read_text(encoding="utf-8").replace(
            "CHURNED rows record lost ARR.", "CHURNED rows record lost ARR. (owner note)"
        ),
    )
    snapshot = _admit_case(case)
    immutable = _served_snapshot(snapshot)
    doc.write_text("# Renewal notes v2\n\nCHURNED never counts toward net new ARR.\n")
    monkeypatch.setattr(
        ingest_module,
        "_default_complete",
        lambda _m: response(page_entry(body="# Churned ARR is not expansion\n\nRewritten for v2.")),
    )
    assert main([*_ingest_cli_args(case, doc), "--reconcile"]) == 0
    out = capsys.readouterr().out
    assert f"reconcile: {APPROVED}" in out and "same-path" in out and "changed" in out
    assert "old source:" in out and "new source:" in out
    assert "-CHURNED rows record lost ARR. (owner note)" in out
    assert (case.worktree / "context_layer" / APPROVED).is_file()
    assert _served_snapshot(snapshot) == immutable


def test_cli_reconcile_requires_candidate_identity_before_model_call(tmp_path, monkeypatch, capsys):
    import ariadne.ingest as ingest_module

    def boom(_messages):
        raise AssertionError("model must not be called")

    monkeypatch.setattr(ingest_module, "_default_complete", boom)
    with pytest.raises(SystemExit):
        main([str(make_doc(tmp_path)), "--reconcile"])
    assert "--project" in capsys.readouterr().err


def _approved_state(tmp_path, entry, text=None):
    """Ingest and explicitly Git-admit one synthetic page; return snapshot and case."""
    doc = make_doc(tmp_path, text=text)
    case = GitIngestCase(tmp_path, [doc])
    result = case.ingest([doc], complete=lambda _m: response(entry))
    assert result["errors"] == [] and len(result["written"]) == 1
    return _admit_case(case), doc


def test_reconcile_detects_changed_table_grain_as_changed(tmp_path):
    """Finding 2: a human edit to substantive per-type metadata (table grain)
    must stay a visible change, not classify as unchanged."""
    entry = page_entry(
        folder="tables",
        name="renewals",
        type="table",
        title="Renewals",
        description="One row per renewal event.",
        tags=["table", "renewals"],
        grain={
            "primary_key": ["account_id", "renewal_date"],
            "cardinality_enforcement": "STRICT_1_TO_1",
        },
        body="# Renewals\n\nOne row per renewal event.",
    )
    served, doc = _approved_state(tmp_path, entry)
    case = _case_for_snapshot(served)
    page = case.worktree / "context_layer" / "tables" / "renewals.md"
    edited = page.read_text(encoding="utf-8").replace(
        "cardinality_enforcement: STRICT_1_TO_1", "cardinality_enforcement: ONE_TO_MANY"
    )
    case.edit_page("tables", "renewals", edited)
    _admit_case(case)

    staging = case.worktree
    staged, errors, comparisons = _reconcile_candidate(
        case, [doc], complete=lambda _m: response(entry)
    )
    assert errors == []
    (record,) = comparisons
    assert record.change == "changed"  # grain is owner metadata, not bookkeeping
    assert "STRICT_1_TO_1" in record.diff
    (proposal,) = staged
    assert proposal == staging / "context_layer" / "tables" / "renewals.md"


def test_reconcile_uses_the_matching_approved_source_for_identity(tmp_path):
    """Finding 3: with several approved citations, old source/digest must follow
    the entry that actually matched, not the first entry."""
    served, doc = _approved_state(tmp_path, page_entry())
    case = _case_for_snapshot(served)
    other = tmp_path / "original-handbook.docx"
    other.write_bytes(b"another approved source")
    page = case.worktree / "context_layer" / APPROVED
    content = page.read_text(encoding="utf-8")
    metadata = front_of(page)
    metadata["sources"].insert(
        0,
        {
            "id": hashlib.sha256(other.read_bytes()).hexdigest()[:12],
            "resource": str(other.resolve()),
            "title": other.name,
        },
    )
    body = content.split("---", 2)[2]
    edited = f"---\n{yaml.safe_dump(metadata, sort_keys=False)}---{body}"
    case.edit_page("policies", "churned-arr-not-expansion", edited)
    _admit_case(case)

    staged, errors, comparisons = _reconcile_candidate(
        case, [doc], complete=lambda _m: response(page_entry())
    )
    assert errors == []
    assert staged == []  # identical page and identical MATCHED digest: unchanged
    (record,) = comparisons
    assert record.change == "unchanged"
    assert record.old_source is not None
    assert record.old_source["resource"] == str(doc.resolve())
    assert record.old_source["digest"] == hashlib.sha256(doc.read_bytes()).hexdigest()[:12]


def test_reconcile_duplicate_proposed_path_detected_even_when_first_is_unchanged(tmp_path):
    """Finding 5: the same proposed path emitted twice must fail preflight even
    when the first occurrence classifies unchanged (it never enters the plan)."""
    served, doc = _approved_state(tmp_path, page_entry())
    changed = page_entry(body="# Churned ARR is not expansion\n\nRewritten body.")

    case = _case_for_snapshot(served)
    candidate_page = case.worktree / "context_layer" / APPROVED
    original = candidate_page.read_bytes()
    before_revision = case.revision
    staged, errors, comparisons = _reconcile_candidate(
        case, [doc], complete=lambda _m: response(page_entry(), changed)
    )
    assert staged == [] and comparisons == []
    assert any("duplicate proposal path" in e and APPROVED in e for e in errors)
    assert case.revision == before_revision
    assert candidate_page.read_bytes() == original


# --- (l) opt-in conflict advisory (spec 2026-09-23-0004 AC4, issue #12 unit B) ---


def _approved_policy_with_human_edit(tmp_path, *, annotation="(owner annotation)"):
    """Admit a Policy, a human Git edit and a changed external source snapshot."""
    served, doc = _approved_state(tmp_path, page_entry())
    case = _case_for_snapshot(served)
    candidate = case.worktree / "context_layer" / APPROVED
    edited = candidate.read_text(encoding="utf-8").replace(
        "CHURNED rows record lost ARR.", f"CHURNED rows record lost ARR. {annotation}"
    )
    case.edit_page("policies", "churned-arr-not-expansion", edited)
    served = _admit_case(case)
    doc.write_text(
        "# Renewal notes v2\n\nCHURNED rows never count toward expansion nor net new ARR.\n"
    )
    changed_entry = page_entry(
        body="# Churned ARR is not expansion\n\nCHURNED rows record lost ARR and never "
        "count toward net new either."
    )
    return served, doc, changed_entry


def _approved_policy_with_operator_note(
    tmp_path, *, annotation="(owner annotation)", description=None, advance_doc=True
):
    """The credential-carrying variant: the approved Policy's note/description
    enters through the operator's own INITIAL bundle bytes. The typed edit seam
    refuses credential-shaped artifact content (spec 0027 §4), so an approved
    page with a stray secret only exists as the owner's committed page — the
    real-world shape these egress/redaction cases test. ``advance_doc=False``
    keeps the source snapshot unchanged for the metadata-only variants."""
    doc = make_doc(tmp_path)
    note = f" {annotation}" if annotation else ""
    default_description = "CHURNED renewal rows are excluded from expansion totals."
    page = (
        "---\n"
        "type: policy\n"
        "status: draft\n"
        "title: Churned ARR is not expansion\n"
        f"description: {description or default_description}\n"
        "tags: [policy, arr, ingest]\n"
        "sources:\n"
        f"  - id: {hashlib.sha256(doc.read_bytes()).hexdigest()[:12]}\n"
        f"    resource: {doc.resolve()}\n"
        f"    title: {doc.name}\n"
        "---\n\n"
        "# Churned ARR is not expansion\n\n"
        f"CHURNED rows record lost ARR.{note}\n"
    )
    case = GitIngestCase(
        tmp_path,
        [doc],
        initial_files={"context_layer/policies/churned-arr-not-expansion.md": page},
    )
    served = _admit_case(case)
    changed_entry = page_entry(
        body="# Churned ARR is not expansion\n\nCHURNED rows record lost ARR and never "
        "count toward net new either."
    )
    if advance_doc:
        doc.write_text(
            "# Renewal notes v2\n\nCHURNED rows never count toward expansion nor net new ARR.\n",
            encoding="utf-8",
        )
    return served, doc, changed_entry


def test_reconcile_advisory_supported_quotes_for_changed_policy(tmp_path, monkeypatch):
    """Unit B eligibility + quote verification: ONLY a same-path matched approved
    POLICY with changed body gets the extra call; the provider receives the
    converted document and the approved Policy title/body/source identity —
    never verified identities — and each quote is checked verbatim."""
    monkeypatch.setenv("OPENAI_MODEL", MODEL)
    served, doc, changed_entry = _approved_policy_with_human_edit(tmp_path)
    calls: list[list[dict]] = []

    def complete(messages):
        calls.append(messages)
        if len(calls) == 1:
            return response(changed_entry)  # distillation
        return json.dumps(
            {
                "possible_conflict": True,
                "note": "the revision drops the net-new exclusion",
                "quotes": [
                    "CHURNED rows record lost ARR. (owner annotation)",  # verbatim: approved
                    "CHURNED rows never count toward expansion nor net new ARR.",  # verbatim: doc
                    "INVENTED passage present in neither text",  # must come back unverified
                ],
            }
        )

    candidate = _case_for_snapshot(served).worktree
    staged, errors, comparisons = _reconcile_snapshot(served, [doc], complete=complete)
    assert errors == []
    (proposal,) = staged  # deterministic candidate edits are independent of the advisory
    assert proposal == candidate / "context_layer" / APPROVED
    (record,) = comparisons
    assert record.change == "changed"

    advisory = record.advisory
    assert advisory.status == "supported"
    assert advisory.note == "the revision drops the net-new exclusion"
    assert advisory.quotes is not None
    verified = {q["text"] for q in advisory.quotes if q["verified"]}
    unverified = [q["text"] for q in advisory.quotes if not q["verified"]]
    assert verified == {
        "CHURNED rows record lost ARR. (owner annotation)",
        "CHURNED rows never count toward expansion nor net new ARR.",
    }
    assert unverified == ["INVENTED passage present in neither text"]

    # egress contract: exactly one extra call, advisory-shaped, minimal content
    assert len(calls) == 2
    payload = calls[1][-1]["content"]
    assert "CHURNED rows never count toward expansion nor net new ARR." in payload  # converted doc
    assert "CHURNED rows record lost ARR. (owner annotation)" in payload  # approved body
    assert "Churned ARR is not expansion" in payload  # approved title
    assert str(doc.resolve()) in payload  # source identity
    assert "human:alice" not in payload  # verified identities never leave the layer
    assert "verified" not in calls[1][0]["content"]  # system prompt carries none either


def test_reconcile_advisory_refuses_credential_pattern_before_any_egress(tmp_path):
    """An approved Policy that appears to contain a credential is NEVER sent:
    no extra model call at all, the class (not the secret) is reported, and the
    deterministic diff + staging stand."""
    served, doc, changed_entry = _approved_policy_with_operator_note(
        tmp_path, annotation="(api token: sk-a1B2c3D4e5F6g7H8i9J0k1 in a note)"
    )
    secret = "sk-a1B2c3D4e5F6g7H8i9J0k1"
    calls: list[list[dict]] = []

    def complete(messages):
        calls.append(messages)
        return response(changed_entry)

    candidate = _case_for_snapshot(served).worktree
    staged, errors, comparisons = _reconcile_snapshot(served, [doc], complete=complete)
    assert errors == []
    (proposal,) = staged  # the candidate write is unaffected by the advisory refusal
    assert proposal == candidate / "context_layer" / APPROVED
    (record,) = comparisons
    assert record.change == "changed" and record.diff  # deterministic diff stands
    advisory = record.advisory
    assert advisory.status == "unavailable"
    assert "api_token" in advisory.reason  # pattern CLASS named
    assert secret not in advisory.reason and secret not in str(advisory)  # secret never echoed
    assert len(calls) == 1  # distillation only: the approved text never left
    assert not any(secret in str(c) for c in calls)


def test_reconcile_advisory_invented_quotes_are_unverified(tmp_path):
    """A suggestion whose quotes appear in neither text is unverified, never
    evidence — while the deterministic diff and staging persist."""
    served, doc, changed_entry = _approved_policy_with_human_edit(tmp_path)

    def complete(messages):
        if any(
            m["role"] == "system" and "reconciliation advisor" in m["content"] for m in messages
        ):
            return json.dumps(
                {
                    "possible_conflict": True,
                    "note": "fabricated concern",
                    "quotes": ["made up passage one", "made up passage two"],
                }
            )
        return response(changed_entry)

    staged, errors, comparisons = _reconcile_snapshot(served, [doc], complete=complete)
    assert errors == []
    assert len(staged) == 1  # safe candidate edit persists
    (record,) = comparisons
    advisory = record.advisory
    assert advisory.status == "unverified"
    assert advisory.quotes is not None and advisory.quotes
    assert all(not quote["verified"] for quote in advisory.quotes)


def test_reconcile_advisory_provider_failure_is_unavailable_but_stages(tmp_path):
    """A failing advisory call leaves the deterministic comparison visible,
    marks the advisory unavailable, and does not prevent safe staging."""
    served, doc, changed_entry = _approved_policy_with_human_edit(tmp_path)

    def complete(messages):
        if any(
            m["role"] == "system" and "reconciliation advisor" in m["content"] for m in messages
        ):
            raise RuntimeError("provider exploded")
        return response(changed_entry)

    candidate = _case_for_snapshot(served).worktree
    staged, errors, comparisons = _reconcile_snapshot(served, [doc], complete=complete)
    assert errors == []
    (proposal,) = staged  # candidate edit happened despite the advisory failure
    assert proposal == candidate / "context_layer" / APPROVED
    (record,) = comparisons
    assert record.change == "changed" and "-CHURNED" in record.diff  # diff still visible
    assert record.advisory.status == "unavailable"
    assert "RuntimeError" in record.advisory.reason


def test_reconcile_advisory_no_suggestion_is_not_proof_of_consistency(tmp_path):
    """An absent suggestion is never reported as consistency."""
    served, doc, changed_entry = _approved_policy_with_human_edit(tmp_path)

    def complete(messages):
        if any(
            m["role"] == "system" and "reconciliation advisor" in m["content"] for m in messages
        ):
            return json.dumps({"possible_conflict": False})
        return response(changed_entry)

    _, errors, comparisons = _reconcile_snapshot(served, [doc], complete=complete)
    assert errors == []
    (record,) = comparisons
    assert record.advisory.status == "none"
    assert "not proof of consistency" in record.advisory.reason


def test_reconcile_advisory_skips_ineligible_pages(tmp_path):
    """Unchanged, provenance-only, new, non-Policy and title-only pages are not advised."""
    table_entry = page_entry(
        folder="tables",
        name="renewals",
        type="table",
        title="Renewals",
        description="One row per renewal event.",
        tags=["table", "renewals"],
        grain={"primary_key": ["account_id"], "cardinality_enforcement": "STRICT_1_TO_1"},
        body="# Renewals\n\nOne row per renewal event.",
    )

    def scenario(base: Path, entry, doc_mutate, page_transform) -> Reconciliation:
        base.mkdir(parents=True)
        snapshot, doc = _approved_state(base, entry)
        case = _case_for_snapshot(snapshot)
        path = case.worktree / "context_layer" / entry["folder"] / f"{entry['name']}.md"
        content = path.read_text(encoding="utf-8")
        edited = page_transform(content)
        if edited != content:
            case.edit_page(entry["folder"], entry["name"], edited)
            snapshot = _admit_case(case)
        doc_mutate(doc)
        calls: list[list[dict]] = []

        def complete(messages):
            calls.append(messages)
            return response(entry)

        _, errors, comparisons = _reconcile_snapshot(snapshot, [doc], complete=complete)
        assert errors == []
        assert len(calls) == 1  # distillation only
        (record,) = comparisons
        return record

    def identity(content):
        return content

    def body_edit(content):
        return content.replace("One row per renewal event.", "Human edit.")

    def title_edit(content):
        return content.replace(
            "title: Churned ARR is not expansion", "title: Retitled by the owner"
        )

    record = scenario(tmp_path / "c1", page_entry(), lambda doc: None, identity)
    assert record.change == "unchanged" and record.advisory.status == "not_applicable"
    record = scenario(
        tmp_path / "c2",
        page_entry(),
        lambda doc: doc.write_text(doc.read_text(encoding="utf-8") + "\n(re-export)\n"),
        identity,
    )
    assert record.change == "provenance_only" and record.advisory.status == "not_applicable"

    base = tmp_path / "c3"
    base.mkdir()
    snapshot, doc = _approved_state(base, page_entry())
    calls = []
    renamed = page_entry(name="churned-arr-not-expansion-v2")

    def complete(messages):
        calls.append(messages)
        return response(renamed)

    _, errors, comparisons = _reconcile_snapshot(snapshot, [doc], complete=complete)
    assert errors == [] and len(calls) == 1
    (record,) = comparisons
    assert record.change == "new" and record.advisory.status == "not_applicable"

    record = scenario(tmp_path / "c4", table_entry, lambda doc: None, body_edit)
    assert record.match == "same-path" and record.change == "changed"
    assert record.advisory.status == "not_applicable"

    record = scenario(tmp_path / "c5", page_entry(), lambda doc: None, title_edit)
    assert record.change == "changed" and record.advisory.status == "not_applicable"


def test_reconcile_source_mismatch_never_discloses_approved_policy(tmp_path):
    """A same-path source mismatch fails before approved Policy text can egress."""
    served, _doc = _approved_state(tmp_path, page_entry())
    other = tmp_path / "other-playbook.md"
    other.write_text("# Another playbook\n\nTheir rule.\n", encoding="utf-8")
    calls: list[list[dict]] = []

    def complete(messages):
        calls.append(messages)
        return response(page_entry())

    staged, errors, _ = _reconcile_snapshot(served, [other], complete=complete)
    assert staged == [] and any("identity conflict" in error for error in errors)
    assert len(calls) == 1
    assert not any("CHURNED rows record lost ARR." in str(call) for call in calls)


def _advisor_aware_complete(changed_entry, advisory_answer):
    """complete() that answers the distillation with the changed entry and the
    advisory call with ``advisory_answer`` (a JSON string)."""

    def complete(messages):
        if any(
            m["role"] == "system" and "reconciliation advisor" in m["content"] for m in messages
        ):
            return advisory_answer
        return response(changed_entry)

    return complete


def test_reconcile_advisory_uses_the_first_converted_text_when_doc_changes_mid_run(tmp_path):
    """P1: quote verification must use the SAME converted text the distillation
    saw — rewriting or deleting the document during the first model call can
    neither stale the evidence nor crash the finished comparison."""
    # case 1: the document is REWRITTEN during the distillation call; a quote
    # present only in the FIRST text must still verify.
    base = tmp_path / "c1"
    base.mkdir(parents=True)
    served, doc, changed_entry = _approved_policy_with_human_edit(base)

    def complete(messages):
        if any(
            m["role"] == "system" and "reconciliation advisor" in m["content"] for m in messages
        ):
            return json.dumps(
                {
                    "possible_conflict": True,
                    "note": "net-new exclusion dropped",
                    "quotes": ["never count toward expansion nor net new ARR."],
                }
            )
        doc.write_text("# totally different\n\nreplacement content\n", encoding="utf-8")
        return response(changed_entry)

    candidate = _case_for_snapshot(served).worktree
    staged, errors, comparisons = _reconcile_snapshot(served, [doc], complete=complete)
    assert errors == []
    (proposal,) = staged
    assert proposal == candidate / "context_layer" / APPROVED
    (record,) = comparisons
    assert record.change == "changed" and record.diff  # deterministic result stands
    assert record.advisory.status == "supported"  # verified against the FIRST text
    assert record.advisory.quotes and record.advisory.quotes[0]["verified"]

    # case 2: the document is DELETED during the distillation call; the finished
    # comparison, staging and a valid absence answer survive without a crash.
    base2 = tmp_path / "c2"
    base2.mkdir(parents=True)
    served2, doc2, changed_entry2 = _approved_policy_with_human_edit(base2)

    def complete2(messages):
        if any(
            m["role"] == "system" and "reconciliation advisor" in m["content"] for m in messages
        ):
            return json.dumps({"possible_conflict": False})
        doc2.unlink()  # the document vanishes mid-run
        return response(changed_entry2)

    staged2, errors2, comparisons2 = _reconcile_snapshot(served2, [doc2], complete=complete2)
    assert errors2 == []
    (proposal2,) = staged2  # candidate edit happened before the advisory
    assert proposal2.is_file()
    (record2,) = comparisons2
    assert record2.change == "changed" and record2.diff
    assert record2.advisory.status == "none"


def test_reconcile_advisory_malformed_conflict_flag_is_unavailable(tmp_path):
    """P2: possible_conflict must be an explicit boolean — a missing or invalid
    flag is an unusable answer (unavailable), never an absence claim."""
    served, doc, changed_entry = _approved_policy_with_human_edit(tmp_path)
    payloads = [
        json.dumps({"note": "flag forgotten"}),
        json.dumps({"possible_conflict": "maybe"}),
        json.dumps({"possible_conflict": None}),
    ]
    for payload in payloads:
        _, errors, comparisons = _reconcile_snapshot(
            served, [doc], complete=_advisor_aware_complete(changed_entry, payload)
        )
        assert errors == []
        (record,) = comparisons
        assert record.advisory.status == "unavailable", payload
        assert "possible_conflict" in record.advisory.reason


def test_reconcile_credential_refusal_redacts_secret_from_diff_and_cli_output(
    tmp_path, monkeypatch, capsys
):
    secret = "sk-a1B2c3D4e5F6g7H8i9J0k1"
    served, doc, changed_entry = _approved_policy_with_operator_note(
        tmp_path, annotation=f"(note: {secret} embedded)"
    )
    case = _case_for_snapshot(served)
    staged, errors, comparisons = _reconcile_candidate(
        case, [doc], complete=lambda _m: response(changed_entry)
    )
    assert errors == [] and len(staged) == 1
    (record,) = comparisons
    assert record.change == "changed"
    assert record.advisory.status == "unavailable" and "api_token" in record.advisory.reason
    assert secret not in record.diff and "[redacted api_token]" in record.diff
    assert secret not in str(record)

    import ariadne.ingest as ingest_module

    monkeypatch.setenv("OPENAI_MODEL", MODEL)
    base = tmp_path / "cli"
    base.mkdir()
    served2, doc2, changed_entry2 = _approved_policy_with_operator_note(
        base, annotation=f"(note: {secret} embedded)"
    )
    case2 = _case_for_snapshot(served2)
    monkeypatch.setattr(ingest_module, "_default_complete", lambda _m: response(changed_entry2))
    assert main([*_ingest_cli_args(case2, doc2), "--reconcile"]) == 0
    out = capsys.readouterr().out
    assert secret not in out and "[redacted api_token]" in out
    assert (case2.worktree / "context_layer" / APPROVED).is_file()


def test_reconcile_credential_refusal_redacts_entire_pem_block_from_diff_and_cli(
    tmp_path, monkeypatch, capsys
):
    pem_payload = "MIIEowIBAAKCAQEA7SYNTHETICnotAREALkeyPAYLOAD0123456789=="
    pem = f"-----BEGIN RSA PRIVATE KEY-----\n{pem_payload}\n-----END RSA PRIVATE KEY-----"
    served, doc, changed_entry = _approved_policy_with_operator_note(
        tmp_path, annotation=f"({pem})"
    )
    case = _case_for_snapshot(served)
    staged, errors, comparisons = _reconcile_candidate(
        case, [doc], complete=lambda _m: response(changed_entry)
    )
    assert errors == [] and len(staged) == 1
    (record,) = comparisons
    assert record.change == "changed"
    assert record.advisory.status == "unavailable" and "private_key" in record.advisory.reason
    assert pem_payload not in record.diff
    assert "BEGIN RSA PRIVATE KEY" not in record.diff
    assert "END RSA PRIVATE KEY" not in record.diff
    assert "[redacted private_key]" in record.diff
    assert "CHURNED rows record lost ARR" in record.diff
    assert pem_payload in (served / "context_layer" / APPROVED).read_text(encoding="utf-8")

    import ariadne.ingest as ingest_module

    monkeypatch.setenv("OPENAI_MODEL", MODEL)
    base = tmp_path / "cli"
    base.mkdir()
    served2, doc2, changed_entry2 = _approved_policy_with_operator_note(base, annotation=f"({pem})")
    case2 = _case_for_snapshot(served2)
    monkeypatch.setattr(ingest_module, "_default_complete", lambda _m: response(changed_entry2))
    assert main([*_ingest_cli_args(case2, doc2), "--reconcile"]) == 0
    out = capsys.readouterr().out
    assert pem_payload not in out and "PRIVATE KEY" not in out
    assert "[redacted private_key]" in out
    assert (case2.worktree / "context_layer" / APPROVED).is_file()


def test_reconcile_credential_in_approved_description_refuses_and_redacts(
    tmp_path, monkeypatch, capsys
):
    token = "hunter2-rotation"
    description_line = f"ops note (password = {token}) for renewals."
    served, doc, changed_entry = _approved_policy_with_operator_note(
        tmp_path, description=description_line
    )
    snapshot = _served_snapshot(served)
    calls: list[list[dict]] = []

    def complete(messages):
        calls.append(messages)
        return response(changed_entry)

    case = _case_for_snapshot(served)
    staged, errors, comparisons = _reconcile_candidate(case, [doc], complete=complete)
    assert errors == [] and len(staged) == 1
    assert _served_snapshot(served) == snapshot
    assert token in (served / "context_layer" / APPROVED).read_text(encoding="utf-8")
    (record,) = comparisons
    assert record.change == "changed"
    assert record.advisory.status == "unavailable"
    assert "credential_assignment" in record.advisory.reason
    assert token not in record.advisory.reason
    assert len(calls) == 1
    assert record.diff and token not in record.diff
    assert "[redacted credential_assignment]" in record.diff
    assert "never count toward net new either." in record.diff

    import ariadne.ingest as ingest_module

    monkeypatch.setenv("OPENAI_MODEL", MODEL)
    base = tmp_path / "cli"
    base.mkdir()
    served2, doc2, changed_entry2 = _approved_policy_with_operator_note(
        base, description=description_line
    )
    case2 = _case_for_snapshot(served2)
    monkeypatch.setattr(ingest_module, "_default_complete", lambda _m: response(changed_entry2))
    assert main([*_ingest_cli_args(case2, doc2), "--reconcile"]) == 0
    out = capsys.readouterr().out
    assert token not in out and "[redacted credential_assignment]" in out
    assert (case2.worktree / "context_layer" / APPROVED).is_file()

    base3 = tmp_path / "c3"
    base3.mkdir()
    served3, doc3, _unchanged_entry = _approved_policy_with_operator_note(
        base3, annotation="", description=description_line, advance_doc=False
    )
    case3 = _case_for_snapshot(served3)
    calls3: list[list[dict]] = []

    def complete3(messages):
        calls3.append(messages)
        return response(page_entry())

    staged3, errors3, comparisons3 = _reconcile_candidate(case3, [doc3], complete=complete3)
    assert errors3 == [] and len(staged3) == 1
    (record3,) = comparisons3
    assert record3.change == "changed" and record3.advisory.status == "not_applicable"
    assert len(calls3) == 1
    assert token not in record3.diff
    assert "[redacted credential_assignment]" in record3.diff


# --- (p) opt-in verbatim mode (spec 2026-10-13-0021, issue #66 V1) --------------

_VERBATIM_TOKEN = "hunter2-rotation"


# AC1 fixture: textual frontmatter of its own (with a tempting `status: stable`),
# indented/trailing whitespace, a code block and NO final newline — hand-authored
# in the spec's image, so every expected value below comes from this literal.
VERBATIM_SOURCE = (
    "---\n"
    "title: Source-owned notes\n"
    "status: stable\n"
    "---\n"
    "\n"
    "  Indented lead-in with trailing spaces.   \n"
    "\n"
    "```python\n"
    "rotation_code = 'placeholder'\n"
    "```\n"
    "\n"
    "Final line without a trailing newline"
)


class _FixedClock:
    """datetime replacement handing out one controllable instant — the retry
    journey advances the generation clock between intakes to prove timestamps
    are ignored, never rewritten."""

    def __init__(self, start: datetime):
        self.now_value = start

    def now(self, _tz):
        return self.now_value


def test_verbatim_preserves_document_and_never_calls_model(tmp_path, monkeypatch):
    """Verbatim writes one exact-content Reference into the selected Git candidate."""
    import ariadne.ingest as ingest_module

    def supplied(_messages):
        raise AssertionError("verbatim mode must never call a supplied completion callback")

    def default_boom(_messages):
        raise AssertionError("the default completion boundary must not be invoked")

    monkeypatch.setattr(ingest_module, "_default_complete", default_boom)
    doc = tmp_path / "field-notes.md"
    doc.write_text(VERBATIM_SOURCE, encoding="utf-8")
    case = GitIngestCase(tmp_path, [doc])
    base_files = set(
        run_git(case.project, "ls-tree", "-r", "--name-only", case.revision).splitlines()
    )
    result = case.ingest([doc], complete=supplied, verbatim=True)

    assert result["errors"] == []
    assert result["written"] == ["context_layer/references/field-notes.md"]
    page = case.worktree / result["written"][0]
    page_text = page.read_text(encoding="utf-8")
    assert page_text.split("\n---\n\n", 1)[1] == VERBATIM_SOURCE
    front = front_of(page)
    assert front["type"] == "reference" and front["status"] == "draft"
    assert front["tags"] == ["ingest", "verbatim"]
    assert front["generated"]["by"] == "ariadne-ingest:verbatim"
    assert front["generated"]["at"]
    assert front["sources"] == [
        {
            "id": hashlib.sha256(doc.read_bytes()).hexdigest()[:12],
            "resource": str(doc.resolve()),
            "title": doc.name,
        }
    ]
    assert front["title"] == "field-notes" and "field-notes.md" in front["description"]
    assert set(front) == {"type", "status", "title", "description", "tags", "sources", "generated"}
    candidate_files = set(
        run_git(
            case.project, "ls-tree", "-r", "--name-only", result["candidate_revision"]
        ).splitlines()
    )
    assert candidate_files - base_files == {"context_layer/references/field-notes.md"}
    assert str(doc.resolve()) not in candidate_files


def test_verbatim_uses_existing_converter_output(tmp_path, monkeypatch):
    """The installed converter seam supplies exact text; no model call is made."""
    converter_text = (
        "\n  \n# Converted handbook\n\nParagraph retained from the converter.  \n(no final newline)"
    )
    calls = []

    def fake_convert(path):
        calls.append((path, path.read_bytes()))  # bytes captured before cleanup
        return converter_text

    monkeypatch.setitem(_CONVERTERS, ".html", (fake_convert, _CONVERTERS[".html"][1]))

    def boom(_messages):
        raise AssertionError("verbatim mode must never call a model")

    doc = tmp_path / "handbook.html"
    doc.write_text("<html><body>raw bytes never read natively</body></html>", encoding="utf-8")
    case = GitIngestCase(tmp_path, [doc])
    result = case.ingest([doc], complete=boom, verbatim=True)

    # spec 0027 §5: conversion reads one bounded byte SNAPSHOT through a
    # temporary scratch file (same bytes, cleaned up), never the original path
    assert result["errors"] == []
    assert len(calls) == 1
    scratch, scratch_bytes = calls[0]
    assert scratch.suffix == ".html" and scratch_bytes == doc.read_bytes()
    assert scratch != doc
    assert not scratch.exists()  # the temporary scratch file is cleaned up
    page = case.worktree / "context_layer/references/handbook.md"
    assert result["written"] == ["context_layer/references/handbook.md"]
    assert page.read_text(encoding="utf-8").split("\n---\n\n", 1)[1] == converter_text
    assert front_of(page)["sources"] == [
        {
            "id": hashlib.sha256(doc.read_bytes()).hexdigest()[:12],
            "resource": str(doc.resolve()),
            "title": doc.name,
        }
    ]


def test_verbatim_retry_is_candidate_bound_and_never_overwrites(tmp_path, monkeypatch):
    """Retries are no-op only for the same source/content; changed bindings get new files."""
    import ariadne.ingest as ingest_module

    clock = _FixedClock(datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC))
    monkeypatch.setattr(ingest_module, "datetime", clock)
    converted = {"text": "# Handbook v1\n\nUnchanged converted paragraph.\n"}
    monkeypatch.setitem(
        _CONVERTERS, ".html", (lambda _path: converted["text"], _CONVERTERS[".html"][1])
    )
    doc = tmp_path / "handbook.html"
    doc.write_text("binary-ish v1", encoding="utf-8")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    twin = elsewhere / "handbook.html"
    twin.write_text("binary-ish v1", encoding="utf-8")
    case = GitIngestCase(tmp_path, [doc, twin])

    first = case.ingest([doc], verbatim=True)
    draft1 = case.worktree / first["written"][0]
    original = draft1.read_bytes()
    original_mtime = draft1.stat().st_mtime_ns

    clock.now_value += timedelta(hours=2)
    same = case.ingest([doc], verbatim=True)
    assert same["written"] == [] and same["unchanged"] == ["context_layer/references/handbook.md"]
    assert draft1.read_bytes() == original and draft1.stat().st_mtime_ns == original_mtime
    assert front_of(draft1)["generated"]["at"] == "2026-01-01T12:00:00+00:00"

    doc.write_text("binary-ish v2", encoding="utf-8")
    changed_source = case.ingest([doc], verbatim=True)
    draft2 = case.worktree / changed_source["written"][0]
    assert draft2.name == "handbook-2.md" and draft1.read_bytes() == original
    assert front_of(draft2)["sources"][0]["id"] == hashlib.sha256(doc.read_bytes()).hexdigest()[:12]

    doc.write_text("binary-ish v1", encoding="utf-8")
    converted["text"] = "# Handbook v1 (re-converted)\n\nDifferent converter output.\n"
    changed_text = case.ingest([doc], verbatim=True)
    draft3 = case.worktree / changed_text["written"][0]
    assert draft3.name == "handbook-3.md"
    assert draft3.read_text(encoding="utf-8").split("\n---\n\n", 1)[1] == converted["text"]
    assert draft1.read_bytes() == original and draft2.is_file()

    distinct_source = case.ingest([twin], verbatim=True)
    draft4 = case.worktree / distinct_source["written"][0]
    assert draft4.name == "handbook-4.md"
    assert front_of(draft4)["sources"][0]["resource"] == str(twin.resolve())
    assert draft4.read_bytes() != draft1.read_bytes()

    doc.write_text("binary-ish v1", encoding="utf-8")
    converted["text"] = "# Handbook v1\n\nUnchanged converted paragraph.\n"
    human_edit = draft1.read_text(encoding="utf-8") + "\n(owner annotation)"
    case.edit_page("references", "handbook", human_edit)
    result = case.ingest([doc], verbatim=True)
    draft5 = case.worktree / result["written"][0]
    assert draft5.name == "handbook-5.md"
    assert draft1.read_text(encoding="utf-8").endswith("(owner annotation)")
    assert draft5.read_bytes() != draft1.read_bytes()


def _verbatim_refusal(case_name: str, tmp_path: Path, monkeypatch):
    if case_name == "unsupported":
        doc = make_doc(tmp_path, suffix=".pages")
        return GitIngestCase(tmp_path, [doc]), [doc], ["[documents]", "uv pip install"], []
    if case_name == "empty":
        doc = make_doc(tmp_path, text="   \n\t \n")
        return GitIngestCase(tmp_path, [doc]), [doc], ["empty"], []
    if case_name == "converter-unavailable":
        doc = make_doc(tmp_path, suffix=".pdf", text="unused")
        monkeypatch.setitem(sys.modules, "liteparse", None)
        monkeypatch.setitem(sys.modules, "liteparse.parser", None)
        return GitIngestCase(tmp_path, [doc]), [doc], ["liteparse", "[documents]"], []
    if case_name == "credential-body":
        doc = make_doc(tmp_path, text=f"# ops\n\nrotation password: {_VERBATIM_TOKEN}\n")
        return GitIngestCase(tmp_path, [doc]), [doc], ["credential_assignment"], [_VERBATIM_TOKEN]
    doc = tmp_path / "token=topsecret987x.md"
    doc.write_text("# innocent body\n", encoding="utf-8")
    return GitIngestCase(tmp_path, [doc]), [doc], ["credential_assignment"], ["topsecret987x"]


@pytest.mark.parametrize(
    "case_name",
    ["unsupported", "empty", "converter-unavailable", "credential-body", "credential-wrapper"],
)
def test_verbatim_refusals_leave_candidate_unchanged(tmp_path, monkeypatch, case_name):
    case, docs, must_contain, must_not_echo = _verbatim_refusal(case_name, tmp_path, monkeypatch)
    before = case.revision
    result = case.ingest(docs, verbatim=True)

    assert result["written"] == [] and result["unchanged"] == []
    assert result["candidate_revision"] == before
    assert result["errors"]
    joined = "\n".join(result["errors"])
    for needle in must_contain:
        assert needle in joined, (case_name, needle, result["errors"])
    for secret in must_not_echo:
        assert secret not in joined, case_name
    assert run_git(case.worktree, "status", "--short") == ""


def test_verbatim_refuses_documents_outside_configured_roots(tmp_path):
    allowed_dir = tmp_path / "allowed"
    allowed_dir.mkdir()
    allowed = allowed_dir / "notes.md"
    allowed.write_text("# Allowed\n", encoding="utf-8")
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    outside = outside_dir / "notes.md"
    outside.write_text("# Not allowed\n", encoding="utf-8")
    case = GitIngestCase(tmp_path, [allowed])
    before = case.revision

    result = case.ingest([outside], verbatim=True)

    assert result["written"] == [] and result["candidate_revision"] == before
    assert result["errors"] and any("root" in error.lower() for error in result["errors"])
    assert run_git(case.worktree, "status", "--short") == ""


def test_verbatim_cli_retries_and_reports_partial_batch(tmp_path, monkeypatch, capsys):
    """CLI retries report no-op honestly; mixed batches report actual candidate writes."""
    import ariadne.ingest as ingest_module
    from ariadne import proposals

    doc = make_doc(tmp_path)
    case = GitIngestCase(tmp_path, [doc])
    args = [*_ingest_cli_args(case, doc), "--verbatim"]
    assert main(args) == 0
    first = capsys.readouterr()
    assert "written: context_layer/references/notes.md" in first.out
    assert "candidate:" in first.out
    case.revision = proposals._load_record(case.project, case.proposal)["candidate_revision"]

    assert main([*_ingest_cli_args(case, doc), "--verbatim"]) == 0
    retry = capsys.readouterr()
    assert "unchanged: context_layer/references/notes.md" in retry.out
    assert "written:" not in retry.out and retry.err == ""

    def model_boom(_messages):
        raise AssertionError("model must not be called")

    def convert_boom(_path):
        raise AssertionError("converter must not run")

    monkeypatch.setattr(ingest_module, "_default_complete", model_boom)
    monkeypatch.setattr(ingest_module, "_convert", convert_boom)
    with pytest.raises(SystemExit):
        main([*_ingest_cli_args(case, doc), "--verbatim", "--reconcile"])
    refusal = capsys.readouterr()
    assert "--verbatim" in refusal.err and "--reconcile" in refusal.err

    monkeypatch.undo()
    good = tmp_path / "good-notes.md"
    good.write_text("# Good notes\n\nFine to preserve.\n", encoding="utf-8")
    bad = make_doc(tmp_path, suffix=".pages")
    batch_case = GitIngestCase(tmp_path / "batch", [good, bad])
    code = main([str(good), str(bad), *_ingest_cli_args(batch_case, good)[1:], "--verbatim"])
    assert code == 1
    batch = capsys.readouterr()
    assert "written: context_layer/references/good-notes.md" in batch.out
    assert "[documents]" in batch.err
    batch_case.revision = proposals._load_record(batch_case.project, batch_case.proposal)[
        "candidate_revision"
    ]
    assert f"candidate: {batch_case.revision}" in batch.out
    assert (batch_case.worktree / "context_layer/references/good-notes.md").is_file()


def test_verbatim_reference_is_discoverable_as_unadmitted_candidate_draft(tmp_path):
    from ariadne.context import list_pages, read_page, search_pages

    doc = tmp_path / "glossary.md"
    doc.write_text(
        "# Glossary\n\nRenewal means reopening the contract for another term.\n", encoding="utf-8"
    )
    case = GitIngestCase(tmp_path, [doc])
    result = case.ingest([doc], verbatim=True)
    assert result["errors"] == [] and len(result["written"]) == 1
    context = case.worktree / "context_layer"
    roots = [(context, True)]

    hits = search_pages("renewal reopening contract", limit=5, roots=roots)
    assert [(hit["path"], hit["draft"]) for hit in hits] == [("references/glossary.md", True)]
    assert "# Glossary" in hits[0]["content"]
    assert "Renewal means reopening the contract for another term." in hits[0]["content"]
    listing = list_pages(roots)
    listed = [(entry["path"], entry["draft"]) for entry in listing]
    # the whole selected candidate is unadmitted: the verbatim draft is
    # labeled like every inherited bundle page, never admitted content
    assert ("references/glossary.md", True) in listed
    assert all(draft is True for _path, draft in listed)
    page = read_page("references/glossary.md", context, draft=True)
    assert page["draft"] is True
    assert page["content"] == (case.worktree / result["written"][0]).read_text(encoding="utf-8")


def test_verbatim_retry_detects_authoring_edits_and_malformed_candidates(tmp_path, monkeypatch):
    """Typed Git edits, including malformed YAML and formatting changes, never get overwritten."""
    import ariadne.ingest as ingest_module

    clock = _FixedClock(datetime(2026, 2, 1, 9, 0, 0, tzinfo=UTC))
    monkeypatch.setattr(ingest_module, "datetime", clock)
    doc = make_doc(tmp_path)
    case = GitIngestCase(tmp_path, [doc])
    first = case.ingest([doc], verbatim=True)
    draft = case.worktree / first["written"][0]
    original = draft.read_text(encoding="utf-8")
    lines = original.splitlines(keepends=True)
    # a typed frontmatter edit OUTSIDE the system-owned ``generated`` block
    # (spec 0027 §4: claims inherited unchanged are allowed, never authored)
    gen_line = next(index for index, line in enumerate(lines) if line.startswith("generated:"))
    lines.insert(gen_line, "note: owner annotation\n")
    edited = "".join(lines)
    case.edit_page("references", "notes", edited)
    clock.now_value += timedelta(hours=1)
    changed = case.ingest([doc], verbatim=True)
    assert changed["written"] == ["context_layer/references/notes-2.md"]
    assert draft.read_text(encoding="utf-8") == edited

    memo = tmp_path / "memo.md"
    memo.write_text("# Memo\n\nBody text.\n", encoding="utf-8")
    memo_case = GitIngestCase(tmp_path / "memo-case", [memo])
    first_memo = memo_case.ingest([memo], verbatim=True)
    memo_page = memo_case.worktree / first_memo["written"][0]
    page_text = memo_page.read_text(encoding="utf-8")
    trimmed = page_text.replace("\n---\n\n", "\n---\n", 1)
    memo_case.edit_page("references", "memo", trimmed)
    second_memo = memo_case.ingest([memo], verbatim=True)
    assert second_memo["written"] == ["context_layer/references/memo-2.md"]
    assert memo_page.read_text(encoding="utf-8") == trimmed

    # a malformed candidate page can only enter through the operator's own
    # initial bundle (the typed seam refuses claim-less malformed frontmatter);
    # ingest must neither crash nor overwrite it, and the batch proceeds
    malformed = (
        "---\ntype: reference\n  sources: [unclosed\n---\n\n# notes\n\nbroken by the owner\n"
    )
    later = tmp_path / "second-notes.md"
    later.write_text("# Second\n\nAnother document in the same batch.\n", encoding="utf-8")
    broken_case = GitIngestCase(
        tmp_path / "malformed-case",
        [doc, later],
        initial_files={"context_layer/references/notes.md": malformed},
    )
    result = broken_case.ingest([doc, later], verbatim=True)
    assert result["errors"] == []
    assert result["unchanged"] == []
    assert result["written"] == [
        "context_layer/references/notes-2.md",
        "context_layer/references/second-notes.md",
    ]
    assert (broken_case.worktree / "context_layer/references/notes.md").read_text(
        encoding="utf-8"
    ) == malformed


def test_verbatim_retry_detects_changes_on_timestamp_line(tmp_path, monkeypatch):
    """Only the timestamp value is ignored; any other timestamp-line edit changes the page."""
    import ariadne.ingest as ingest_module

    clock = _FixedClock(datetime(2026, 5, 1, 7, 0, 0, tzinfo=UTC))
    monkeypatch.setattr(ingest_module, "datetime", clock)
    doc = make_doc(tmp_path)

    def canonical_page(base: Path) -> str:
        seed = GitIngestCase(base / "seed", [doc])
        first = seed.ingest([doc], verbatim=True)
        return (seed.worktree / first["written"][0]).read_text(encoding="utf-8")

    def with_at_line(page_text: str, line: str) -> str:
        lines = page_text.splitlines(keepends=True)
        at_line = next(index for index, text in enumerate(lines) if text.startswith("  at: "))
        lines[at_line] = line
        return "".join(lines)

    # a candidate page (operator-authored initial bundle) differing ONLY in
    # the timestamp VALUE is the explicit no-op: the value is masked
    older_value = with_at_line(canonical_page(tmp_path), "  at: '2026-04-30T07:00:00+00:00'\n")
    same = GitIngestCase(
        tmp_path / "value-only",
        [doc],
        initial_files={"context_layer/references/notes.md": older_value},
    )
    result = same.ingest([doc], verbatim=True)
    assert result["written"] == [] and result["unchanged"] == ["context_layer/references/notes.md"]
    assert (same.worktree / "context_layer/references/notes.md").read_text(
        encoding="utf-8"
    ) == older_value

    # any OTHER byte on that line — an appended comment — stays a change
    annotated = with_at_line(
        canonical_page(tmp_path / "annotated"),
        "  at: '2026-05-01T07:00:00+00:00' # owner annotation\n",
    )
    commented = GitIngestCase(
        tmp_path / "annotated",
        [doc],
        initial_files={"context_layer/references/notes.md": annotated},
    )
    second = commented.ingest([doc], verbatim=True)
    assert second["written"] == ["context_layer/references/notes-2.md"]
    assert (commented.worktree / "context_layer/references/notes.md").read_text(
        encoding="utf-8"
    ) == annotated

    # a corrupted timestamp line is a change too, never a false 'unchanged'
    corrupted_page = with_at_line(canonical_page(tmp_path / "corrupted"), "  at: [unclosed\n")
    corrupted = GitIngestCase(
        tmp_path / "corrupted",
        [doc],
        initial_files={"context_layer/references/notes.md": corrupted_page},
    )
    third = corrupted.ingest([doc], verbatim=True)
    assert third["written"] == ["context_layer/references/notes-2.md"]
    assert (corrupted.worktree / "context_layer/references/notes.md").read_text(
        encoding="utf-8"
    ) == corrupted_page
