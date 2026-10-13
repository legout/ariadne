"""Context knowledge K1: qualified schema pages and deterministic explicit
refresh (issue #41 / spec 2026-10-02-0010 §§2–4, §10 AC1/2/AC9; plan §2
"Physical identity and generated content", ADR-0017).

A catalog asset is the exact tuple ``{source, catalog, schema, table}`` — never
a bare table name. ``refresh_schema`` is the core's explicit regeneration of
physical facts inside one selected Git proposal: reads go through the
operator-APPROVED resolved source identity only, writes are revision-checked
complete page edits, authored meaning survives only for identical column
identity/type (removed/changed columns keep their old meaning as reviewable
history, never a rename guess), and an identical refresh is a no-op (the
candidate revision does not move). Generated pages/resources/filenames stay
distinct for same-named assets; a collision refuses rather than overwriting;
forged generated facts are refused at the edit seam; the same operation is
wired through the local CLI, the Authoring/Combined MCP registrations and the
native Authoring role.

Real temporary Git repositories, real local parquet sources, a local DuckDB
catalog fixture for same-named tables in distinct schemas (no live Postgres),
no network, no provider.
"""

import base64
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
from pathlib import Path, PurePosixPath

import duckdb  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages
import pytest  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages
import yaml  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:  # keep tests runnable from the source tree
    sys.path.insert(0, str(REPO_ROOT))

from ariadne import profiler, sources  # noqa: E402
from ariadne.authoring import AuthoringProject  # noqa: E402
from ariadne.authoring_cli import main as authoring_cli  # noqa: E402
from ariadne.authoring_sources import candidate_sources  # noqa: E402

SEED_NOTES = "# Seed notes\n\nAll orders count; support tickets are separate.\n"

# Two same-named tables in DIFFERENT sources: the AC1 same-names-distinct-assets
# fixture. sale orders carries a candidate key; support orders does not.
SALES_ORDERS_V1 = [(1, 10.0), (2, 20.0), (3, 30.0)]
SALES_ORDERS_V2 = [(1, 7), (2, 8), (3, 9)]  # amount DOUBLE -> qty BIGINT between refreshes
SUPPORT_ORDERS = [(1, 1), (2, 1)]


@pytest.fixture(autouse=True)
def isolated_git_config(monkeypatch):
    """Never touch the operator's global/system Git config: point them at
    /dev/null so only the repo-local identity seeded below exists."""
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", os.devnull)


def run_git(cwd: Path, *argv: str) -> str:
    proc = subprocess.run(["git", *argv], cwd=cwd, capture_output=True, text=True, check=False)
    assert proc.returncode == 0, f"git {argv} failed: {proc.stderr}"
    return proc.stdout


def write_parquet(path: Path, rows: list[tuple], columns: list[str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    values = ", ".join(str(row) for row in rows)
    duckdb.connect().execute(
        f"COPY (SELECT * FROM (VALUES {values}) "
        f"t({', '.join(columns)})) TO '{path}' (FORMAT PARQUET)"
    ).close()
    return path


def git_project(tmp_path: Path) -> Path:
    """A real temporary Git data project with two same-named parquet sources
    (sales/support, each one ``orders`` table) committed as the human-created
    initial artifact revision."""
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    write_parquet(
        project / "data" / "sales" / "orders.parquet",
        SALES_ORDERS_V1,
        ["order_id", "amount"],
    )
    write_parquet(
        project / "data" / "support" / "orders.parquet",
        SUPPORT_ORDERS,
        ["ticket_id", "order_ref"],
    )
    (project / "ariadne.yaml").write_text(
        "sources:\n"
        "  - name: sales\n"
        "    type: parquet\n"
        "    path: data/sales/orders.parquet\n"
        "  - name: support\n"
        "    type: parquet\n"
        "    path: data/support/orders.parquet\n",
        encoding="utf-8",
    )
    (project / "data").mkdir(exist_ok=True)
    (project / "data" / "seed_notes.md").write_text(SEED_NOTES, encoding="utf-8")
    run_git(project, "init", "-q")
    run_git(project, "config", "user.name", "Ariadne Tests")
    run_git(project, "config", "user.email", "tests@ariadne.local")
    run_git(project, "add", "--", "ariadne.yaml", "data/seed_notes.md")
    run_git(project, "commit", "-q", "-m", "human: initial artifacts")
    return project


def approved(api: AuthoringProject, project: Path, started: dict) -> str:
    """The operator's approval of the candidate's exact resolved source identity
    (the G3 human step): refresh opens only this identity afterwards."""
    resolved, digest = candidate_sources(project, started["candidate_revision"])
    assert resolved is not None and digest is not None
    api.approve_sources(started["proposal"], started["candidate_revision"], digest)
    return digest


SALES_ASSET = {"source": "sales", "catalog": None, "schema": "sales", "table": "orders"}
SUPPORT_ASSET = {"source": "support", "catalog": None, "schema": "support", "table": "orders"}


def sqlite_lake_project(tmp_path: Path) -> Path:
    """A Git data project over one ATTACHED sqlite catalog (the attach exposes
    declared NOT NULL metadata through information_schema): one collection
    ``lake.main`` with customers (one NOT NULL + one nullable column), orders
    and a never-refreshed audit table — the fix-pass fixtures for declared
    nullability and overview membership (issue #41). Like the parquet
    fixtures, the db file itself stays UNTRACKED next to the registry."""
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    db = project / "lake.db"
    con = sqlite3.connect(db)
    try:
        con.execute("CREATE TABLE customers (id INTEGER NOT NULL, name TEXT, note TEXT)")
        con.execute(
            "CREATE TABLE orders (order_id INTEGER NOT NULL, customer_id INTEGER, memo TEXT)"
        )
        con.execute("CREATE TABLE audit (event TEXT)")
        con.executemany(
            "INSERT INTO customers VALUES (?, ?, ?)",
            [(1, "A", "n1"), (2, "B", "n2"), (3, "C", "n3")],
        )
        con.executemany(
            "INSERT INTO orders VALUES (?, ?, ?)",
            [(1, 1, "m"), (2, 2, "m"), (3, 3, "m"), (4, 1, "m")],
        )
        con.execute("INSERT INTO audit VALUES ('sweep')")
        con.commit()
    finally:
        con.close()
    (project / "ariadne.yaml").write_text(
        "sources:\n  - name: lake\n    type: sqlite\n    path: lake.db\n",
        encoding="utf-8",
    )
    (project / "data").mkdir(exist_ok=True)
    (project / "data" / "seed_notes.md").write_text(SEED_NOTES, encoding="utf-8")
    run_git(project, "init", "-q")
    run_git(project, "config", "user.name", "Ariadne Tests")
    run_git(project, "config", "user.email", "tests@ariadne.local")
    run_git(project, "add", "--", "ariadne.yaml", "data/seed_notes.md")
    run_git(project, "commit", "-q", "-m", "human: initial artifacts")
    return project


LAKE_CUSTOMERS = {
    "source": "lake",
    "catalog": "lake",
    "schema": "main",
    "table": "customers",
}
LAKE_ORDERS = {"source": "lake", "catalog": "lake", "schema": "main", "table": "orders"}


def collection_resource_of(asset: dict) -> str:
    payload = json.dumps(
        [asset["source"], asset["catalog"], asset["schema"]],
        separators=(",", ":"),
        ensure_ascii=False,
    )
    encoded = base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii").rstrip("=")
    return f"ariadne://collection/{encoded}"


def table_resource(asset: dict) -> str:
    payload = json.dumps(
        [asset["source"], asset["catalog"], asset["schema"], asset["table"]],
        separators=(",", ":"),
        ensure_ascii=False,
    )
    encoded = base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii").rstrip("=")
    return f"ariadne://table/{encoded}"


def generated_filename(resource: str, source: str) -> str:
    slug = source.replace("_", "-")[:48]
    return f"{slug}-{hashlib.sha256(resource.encode('utf-8')).hexdigest()}.md"


def commit_paths(project: Path, revision: str) -> list[str]:
    return sorted(
        line.split("\t", 1)[-1]
        for line in run_git(project, "show", "--name-status", "--format=", revision).splitlines()
        if line.strip()
    )


def page_paths(result: dict) -> dict[str, str]:
    return {page["resource"]: page["path"] for page in result["pages"]}


# ---------------------------------------------------------- [1] the red seam


def test_refresh_keeps_same_named_assets_distinct_and_preserves_only_unchanged_meaning(
    tmp_path,
):
    """Issue #41 [1], the red seam: two approved sources expose ``orders``; one
    refresh generates distinct resources/pages/filenames with Dataset Overviews
    linking the represented tables; authored column meaning survives refresh
    only for identical column identity/type (a removed/type-changed column's
    meaning moves to reviewable history, never onto another column); and the
    second identical refresh leaves the candidate revision unchanged (no-op).
    """
    project = git_project(tmp_path)
    api = AuthoringProject(project)
    started = api.start_proposal()
    proposal, revision = started["proposal"], started["candidate_revision"]
    approved(api, project, started)

    first = api.refresh_schema(proposal, revision, [SALES_ASSET, SUPPORT_ASSET])
    assert first["changed"] is True
    assert first["revision"] != revision
    pages = page_paths(first)
    sales_resource = table_resource(SALES_ASSET)
    support_resource = table_resource(SUPPORT_ASSET)
    assert sales_resource != support_resource  # same name, distinct assets
    assert pages[sales_resource] != pages[support_resource]
    assert pages[sales_resource].endswith(generated_filename(sales_resource, "sales"))
    assert pages[support_resource].endswith(generated_filename(support_resource, "support"))
    by_kind = {}
    for page in first["pages"]:
        by_kind.setdefault(page["kind"], []).append(page)
    assert len(by_kind["table"]) == 2  # one schema page per documented table
    assert len(by_kind["dataset"]) == 2  # one Dataset Overview per collection
    # the overview links exactly the represented tables, not every source
    sales_overview = next(p for p in by_kind["dataset"] if "sales" in p["path"])
    overview_text = run_git(project, "show", f"{first['revision']}:{sales_overview['path']}")
    assert "orders" in overview_text and "support" not in overview_text

    # author meaning for two sales columns, then change the source underneath
    page = api.read_artifact(
        proposal,
        {"kind": "page", "section": "tables", "name": Path(pages[sales_resource]).stem},
    )
    authored = (
        page["content"]
        .replace(
            "`order_id` — unknown (not yet authored)",
            "`order_id` — business key of a sale",
        )
        .replace(
            "`amount` — unknown (not yet authored)",
            "`amount` — net amount of the sale in source currency",
        )
    )
    assert authored != page["content"]  # the placeholders were found and replaced
    edited = api.edit_proposal(
        proposal,
        first["revision"],
        {
            "kind": "page",
            "section": "tables",
            "name": Path(pages[sales_resource]).stem,
            "content": authored,
        },
    )
    assert edited["changed"] is True

    # the physical source changes: `amount` (DOUBLE) disappears, `qty` (BIGINT)
    # arrives — the authored meanings must not be guessed onto `qty`
    write_parquet(
        project / "data" / "sales" / "orders.parquet",
        SALES_ORDERS_V2,
        ["order_id", "qty"],
    )
    second = api.refresh_schema(proposal, edited["revision"], [SALES_ASSET, SUPPORT_ASSET])
    sales_page = next(p for p in second["pages"] if p["resource"] == sales_resource)
    assert sales_page["changes"]["removed"] == ["amount"]
    assert sales_page["changes"]["added"] == ["qty"]
    assert sales_page["changes"]["type_changed"] == []
    refreshed = api.read_artifact(
        proposal,
        {"kind": "page", "section": "tables", "name": Path(pages[sales_resource]).stem},
    )
    assert "`order_id` — business key of a sale" in refreshed["content"]  # identical column
    assert "net amount of the sale in source currency" in refreshed["content"]  # history keeps it
    assert "qty` — unknown (not yet authored)" in refreshed["content"]  # no rename guess
    assert "Schema history" in refreshed["content"]  # the change is flagged for review
    support_page = next(p for p in second["pages"] if p["resource"] == support_resource)
    assert support_page["changes"] == {"added": [], "removed": [], "type_changed": []}

    # the second IDENTICAL request is a no-op: same inputs, same content, no new commit
    third = api.refresh_schema(proposal, second["revision"], [SALES_ASSET, SUPPORT_ASSET])
    assert third["changed"] is False
    assert third["revision"] == second["revision"]


# --------------------------------------------- [2] the catalog tuple grouping


def test_catalog_groups_same_named_tables_by_full_tuple(tmp_path):
    """Issue #41 [2], focused catalog variant: same-named tables in DISTINCT
    SCHEMAS of one attached catalog stay distinct assets — grouped by the
    complete (catalog, schema, table) tuple with ordinal column order
    preserved, explicit identity fields and distinct resources (a local
    DuckDB catalog fixture; no live Postgres). The Source's type only selects
    the attach-style ``ref`` prefix here (``<catalog>.<schema>``)."""
    db = tmp_path / "lake.duckdb"
    con = duckdb.connect(str(db))
    con.execute("CREATE SCHEMA a")
    con.execute("CREATE SCHEMA b")
    con.execute("CREATE SCHEMA c")
    con.execute("CREATE TABLE a.orders (id INTEGER NOT NULL, label VARCHAR)")
    con.execute("CREATE TABLE b.orders (id INTEGER, x INTEGER, y INTEGER DEFAULT 3)")
    con.execute("CREATE TABLE c.items (sku VARCHAR)")
    con.close()
    attached = duckdb.connect()
    attached.execute(f"ATTACH '{db}' AS lake")
    entry = sources._catalog_entry(
        attached, sources.Source(name="lake", type="sqlite", path=str(db))
    )
    by_schema = {table["schema"]: table for table in entry["tables"]}
    assert set(by_schema) == {"a", "b", "c"}  # three tables, not two merged "orders"
    assert by_schema["a"]["columns"] == [
        {"name": "id", "type": "INTEGER"},
        {"name": "label", "type": "VARCHAR"},
    ]
    assert [col["name"] for col in by_schema["b"]["columns"]] == ["id", "x", "y"]
    assert all(table["source"] == "lake" for table in entry["tables"])
    assert all(table["catalog"] == "lake" for table in entry["tables"])
    assert by_schema["a"]["ref"] == "lake.a" and by_schema["b"]["ref"] == "lake.b"
    assert by_schema["a"]["resource"] != by_schema["b"]["resource"]
    assert by_schema["a"]["resource"].startswith("ariadne://table/")

    # the profile keeps unambiguous legacy keys; the same-source name
    # collision keys those tables by their canonical resources
    profiled = profiler._profile_source(attached, entry)
    keys = set(profiled["tables"])
    assert "items" in keys  # unambiguous name keeps the legacy key
    collision_keys = {k for k in keys if k.startswith("ariadne://table/")}
    assert len(collision_keys) == 2
    for key in collision_keys:
        table = profiled["tables"][key]
        assert table["table"] == "orders" and table["resource"] == key
        assert table["source"] == "lake" and table["catalog"] == "lake"
    attached.close()


def test_canonical_resource_scheme_is_deterministic_and_credential_free():
    """Issue #41 [3], worked example: the canonical resource payload is the
    compact-separator JSON array (no ASCII escaping) as unpadded URL-safe
    base64; decode round-trips the exact identifiers; malformed URIs and
    non-credential-free shapes refuse; the filename scheme keeps same-named
    assets distinct after the 48-char slug cap through the full digest."""
    from ariadne.context import generated_page_filename
    from ariadne.sources import collection_resource, parse_resource, table_resource

    payload = '["sales",null,"sales","orders"]'
    encoded = base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii").rstrip("=")
    uri = table_resource("sales", None, "sales", "orders")
    assert uri == f"ariadne://table/{encoded}"
    kind, parts = parse_resource(uri)
    assert kind == "table" and parts == ["sales", None, "sales", "orders"]
    kind, parts = parse_resource(collection_resource("sales", None, "sales"))
    assert kind == "collection" and parts == ["sales", None, "sales"]
    # non-ASCII identifiers survive without ASCII escaping
    unicode_uri = table_resource("däta", "läke", "schéma", "örtder")
    assert parse_resource(unicode_uri)[1] == ["däta", "läke", "schéma", "örtder"]
    for bad in ("file:///etc/passwd", "ariadne://table/!!!", "ariadne://view/x", uri + "x"):
        with pytest.raises(ValueError):
            parse_resource(bad)
    # <source-slug>-<sha256(resource)>.md: capping the slug keeps the digest
    long_source = "s" * 46 + "_x"  # slug caps at 48 after the underscore swap
    one = generated_page_filename("ariadne://table/a", long_source)
    two = generated_page_filename("ariadne://table/b", long_source)
    assert one != two  # the full digest preserves distinction after capping
    assert one.startswith("s" * 46 + "-x-") and one.endswith(".md")
    assert len(one.rsplit("-", 1)[1]) == 67  # 64 hex + ".md"


# ------------------------------------------- [3] approval, bounds and refusals


def test_refresh_reads_only_the_approved_identity_and_refuses_unknown_assets(tmp_path, monkeypatch):
    """Issue #41 [5]/[6]: without the operator's approval nothing is opened;
    approved, an unknown asset and malformed/empty requests are explicit
    errors listing what the approved identity actually holds."""
    import ariadne.sources as sources_module

    project = git_project(tmp_path)
    api = AuthoringProject(project)
    started = api.start_proposal()
    proposal, revision = started["proposal"], started["candidate_revision"]

    opened: list[list[str | None]] = []
    real = sources_module.build_connection

    def spy(registry, read_only=True):
        opened.append([src.path for src in registry.sources])
        return real(registry, read_only)

    monkeypatch.setattr(sources_module, "build_connection", spy)
    with pytest.raises(ValueError, match="approval"):
        api.refresh_schema(proposal, revision, [SALES_ASSET])
    assert opened == []  # the connection builder never ran unapproved

    approved(api, project, started)
    with pytest.raises(ValueError, match="catalog asset"):
        api.refresh_schema(proposal, revision, [{"source": "sales"}])
    with pytest.raises(ValueError, match="explicit non-empty list"):
        api.refresh_schema(proposal, revision, [])
    with pytest.raises(ValueError, match="stale revision"):
        api.refresh_schema(proposal, "0" * 40, [SALES_ASSET])
    assert opened == []  # every shape/stale refusal preceded any source access
    # an unknown asset is refused against the approved catalog enumeration
    # (the only way to name what the identity actually holds — still the
    # approved, read-only identity, never an unapproved location)
    with pytest.raises(ValueError, match="not present in the approved resolved"):
        api.refresh_schema(
            proposal,
            revision,
            [{**SALES_ASSET, "table": "nope"}],
        )
    assert opened and all(
        set(paths)
        == {
            str(project / "data" / "sales" / "orders.parquet"),
            str(project / "data" / "support" / "orders.parquet"),
        }
        for paths in opened
    )


def test_authored_edits_cannot_forge_generated_facts_or_overwrite_collisions(tmp_path):
    """Issue #41 [5]: a complete page edit may carry the generated blocks
    unchanged, but introducing or changing the core-owned facts (``ariadne``
    schema/observations, the ``resource`` binding) is refused; a different
    page already sitting at a generated filename is a collision that refresh
    refuses rather than overwriting."""
    project = git_project(tmp_path)
    api = AuthoringProject(project)
    started = api.start_proposal()
    proposal, revision = started["proposal"], started["candidate_revision"]
    approved(api, project, started)

    first = api.refresh_schema(proposal, revision, [SALES_ASSET])
    sales_path = page_paths(first)[table_resource(SALES_ASSET)]
    name = PurePosixPath(sales_path).stem
    page = api.read_artifact(proposal, {"kind": "page", "section": "tables", "name": name})
    meta, _body = _split_page(page["content"])

    forged_resource = dict(meta)
    forged_resource["resource"] = table_resource(SUPPORT_ASSET)
    with pytest.raises(ValueError, match="system-owned"):
        api.edit_proposal(
            proposal,
            first["revision"],
            {
                "kind": "page",
                "section": "tables",
                "name": name,
                "content": _render_page(forged_resource, _body),
            },
        )
    forged_schema = dict(meta)
    ariadne = dict(meta["ariadne"])
    ariadne["schema"] = [{**meta["ariadne"]["schema"][0], "type": "MAGIC"}]
    forged_schema["ariadne"] = ariadne
    with pytest.raises(ValueError, match="system-owned"):
        api.edit_proposal(
            proposal,
            first["revision"],
            {
                "kind": "page",
                "section": "tables",
                "name": name,
                "content": _render_page(forged_schema, _body),
            },
        )
    stripped = dict(meta)
    del stripped["ariadne"]  # silently dropping the generated facts is the same forgery
    with pytest.raises(ValueError, match="system-owned"):
        api.edit_proposal(
            proposal,
            first["revision"],
            {
                "kind": "page",
                "section": "tables",
                "name": name,
                "content": _render_page(stripped, _body),
            },
        )

    # a plain authored page claims the canonical filename of ANOTHER asset:
    # refresh refuses the collision instead of overwriting it
    support_name = PurePosixPath(generated_filename(table_resource(SUPPORT_ASSET), "support")).stem
    squatter = api.edit_proposal(
        proposal,
        first["revision"],
        {
            "kind": "page",
            "section": "tables",
            "name": support_name,
            "content": "# somebody else's page\n",
        },
    )
    assert squatter["changed"] is True
    with pytest.raises(ValueError, match="collision"):
        api.refresh_schema(proposal, squatter["revision"], [SALES_ASSET, SUPPORT_ASSET])


def _split_page(text: str) -> tuple[dict, str]:
    match = re.match(r"\A---\s*\n(.*?)\n---\s*\n(.*)\Z", text, re.DOTALL)
    assert match
    return yaml.safe_load(match.group(1)), match.group(2)


def _render_page(meta: dict, body: str) -> str:
    front = yaml.safe_dump(meta, sort_keys=False, default_flow_style=False)
    return f"---\n{front}---\n\n{body}"


# ------------------------------------------------------ [4] adapters and diffs


def test_cli_refresh_schema_roundtrip(tmp_path, capsys):
    """Issue #41 [6]: the local CLI surface returns the same JSON envelope as
    the core operation, and the second identical call reports the no-op."""
    project = git_project(tmp_path)
    api = AuthoringProject(project)
    started = api.start_proposal()
    approved(api, project, started)
    request = tmp_path / "assets.json"
    request.write_text(json.dumps([SALES_ASSET, SUPPORT_ASSET]), encoding="utf-8")

    code = authoring_cli(
        [
            "refresh-schema",
            "--proposal",
            started["proposal"],
            "--expected-revision",
            started["candidate_revision"],
            "--file",
            str(request),
            "--project",
            str(project),
        ]
    )
    assert code == 0
    first = json.loads(capsys.readouterr().out)
    assert first["changed"] is True and len(first["pages"]) == 4

    code = authoring_cli(
        [
            "refresh-schema",
            "--proposal",
            started["proposal"],
            "--expected-revision",
            first["revision"],
            "--file",
            str(request),
            "--project",
            str(project),
        ]
    )
    assert code == 0
    second = json.loads(capsys.readouterr().out)
    assert second["changed"] is False and second["revision"] == first["revision"]


def test_schema_only_candidate_invents_no_categories_and_validates_pages(tmp_path):
    """Issue #41 [4]: a schema-only candidate (tables + Dataset Overviews, no
    models/metrics/policies/skills) passes the APPLICABLE page contracts with
    NOTHING invented for absent categories — and the K4 (issue #44)
    applicability decision carries: the semantic checks are explicitly
    not_applicable WITH reasons, so the exact schema-only revision is
    admissible before the first metric. Review stays read-only with bounded
    bodies/diff."""
    from ariadne import admission

    project = git_project(tmp_path)
    api = AuthoringProject(project)
    started = api.start_proposal()
    proposal, revision = started["proposal"], started["candidate_revision"]
    approved(api, project, started)

    refreshed = api.refresh_schema(proposal, revision, [SALES_ASSET, SUPPORT_ASSET])
    result = api.validate_proposal(proposal, refreshed["revision"])
    assert result["ok"] is True and result["errors"] == []  # K4: context-only validates
    checks = {check["name"]: check for check in result["report"]["checks"]}
    for name in ("structural", "compile", "bind", "grain"):
        assert checks[name]["outcome"] == "not_applicable", name
        assert checks[name]["detail"], f"{name} carries no not_applicable reason"
    assert checks["page_contract"]["outcome"] == "passed"  # applicable pages all valid
    assert checks["citations"]["outcome"] == "passed"  # the catalog resources verify
    invented = [
        rel
        for rel in result["artifact_files"]
        if any(section in rel for section in ("policies/", "metrics/", "skills/", "computations/"))
    ]
    assert invented == []  # no invented missing categories
    assert admission.load_current(project) is None  # nothing was admitted

    review = api.review_proposal(proposal)
    changed = {entry["path"] for entry in review["changes"] if entry["change"] == "A"}
    # the generated pages plus the finalize pass's regenerated index trees
    # (system bookkeeping) — and nothing else was added
    assert {page["path"] for page in refreshed["pages"]} <= changed
    assert changed - {page["path"] for page in refreshed["pages"]} == {
        "context_layer/index.md",
        "context_layer/datasets/index.md",
        "context_layer/tables/index.md",
    }
    bodies = {entry["resource"]: entry for entry in review["files"]}
    sales_page = bodies[page_paths(refreshed)[table_resource(SALES_ASSET)]]
    assert sales_page["part"] == 1 and sales_page["complete"] is True
    assert "# Schema" in sales_page["text"]
    # fix4 (issue #53, owner-approved design; spec 0010 §4): the regenerated
    # index is the reader's resource->page resolution source — every
    # refreshed table's index line carries its canonical resource marker
    tables_index = bodies["context_layer/tables/index.md"]["text"]
    for asset in (SALES_ASSET, SUPPORT_ASSET):
        assert f"resource: `{table_resource(asset)}`" in tables_index
    assert tables_index.count("resource: `") == 2  # one marker per table page, nothing else


# ------------------------------------- fix pass (review findings 1-5, no new scope)


def test_generated_body_sections_cannot_be_forged_or_dropped(tmp_path):
    """Finding 1: the core-owned BODY sections of an inherited generated page
    (the ``# Schema`` block, Observations, Schema history) are system facts
    too — a page edit that changes or removes them is refused, dropping the
    frontmatter entirely is no bypass, while authored edits OUTSIDE the
    core-owned sections stay accepted."""
    project = git_project(tmp_path)
    api = AuthoringProject(project)
    started = api.start_proposal()
    proposal = started["proposal"]
    approved(api, project, started)

    first = api.refresh_schema(proposal, started["candidate_revision"], [SALES_ASSET])
    sales_path = page_paths(first)[table_resource(SALES_ASSET)]
    name = PurePosixPath(sales_path).stem
    page = api.read_artifact(proposal, {"kind": "page", "section": "tables", "name": name})
    meta, body = _split_page(page["content"])
    assert "| `order_id` | INTEGER | unknown | unknown | unknown |" in body

    # a forged schema ROW (false declared facts) must refuse
    forged_row = body.replace(
        "| `order_id` | INTEGER | unknown | unknown | unknown |",
        "| `order_id` | INTEGER | false | none | NOT NULL PRIMARY KEY |",
    )
    assert forged_row != body
    with pytest.raises(ValueError, match="core-generated"):
        api.edit_proposal(
            proposal,
            first["revision"],
            {
                "kind": "page",
                "section": "tables",
                "name": name,
                "content": _render_page(meta, forged_row),
            },
        )
    # REMOVING a core-owned body section must refuse too
    start = body.index("# Schema")
    end = body.index("## Observations")
    with pytest.raises(ValueError, match="core-generated"):
        api.edit_proposal(
            proposal,
            first["revision"],
            {
                "kind": "page",
                "section": "tables",
                "name": name,
                "content": _render_page(meta, body[:start] + body[end:]),
            },
        )
    # dropping the frontmatter entirely is no bypass: the base still carries
    # the system-owned claims (and its generated body) the edit must inherit
    with pytest.raises(ValueError, match="system-owned"):
        api.edit_proposal(
            proposal,
            first["revision"],
            {"kind": "page", "section": "tables", "name": name, "content": body},
        )

    # authored edits OUTSIDE the core-owned sections stay accepted — and the
    # revision the refusals saw is still current, so nothing was written
    authored = body.replace(
        "Summary: unknown — not yet authored.",
        "Summary: every order of the sales lane.",
    ).replace(
        "`order_id` — unknown (not yet authored)",
        "`order_id` — business key of a sale",
    )
    assert authored != body
    edited = api.edit_proposal(
        proposal,
        first["revision"],
        {
            "kind": "page",
            "section": "tables",
            "name": name,
            "content": _render_page(meta, authored),
        },
    )
    assert edited["changed"] is True


def test_refresh_exposes_declared_nullability_true_and_false_correctly(tmp_path):
    """Finding 2: declared nullability flows through unmangled — a NOT NULL
    column generates ``nullable: false`` (and a ``false`` Schema-table row),
    a nullable one ``nullable: true``; nothing else is manufactured."""
    project = sqlite_lake_project(tmp_path)
    api = AuthoringProject(project)
    started = api.start_proposal()
    approved(api, project, started)

    refreshed = api.refresh_schema(
        started["proposal"], started["candidate_revision"], [LAKE_CUSTOMERS]
    )
    path = page_paths(refreshed)[table_resource(LAKE_CUSTOMERS)]
    page = api.read_artifact(
        started["proposal"],
        {"kind": "page", "section": "tables", "name": PurePosixPath(path).stem},
    )
    meta, body = _split_page(page["content"])
    by_column = {entry["column"]: entry for entry in meta["ariadne"]["schema"]}
    assert by_column["id"]["nullable"] is False  # declared NOT NULL
    assert by_column["name"]["nullable"] is True  # declared nullable
    assert by_column["note"]["nullable"] is True
    assert "| `id` | BIGINT | false | unknown | unknown |" in body
    assert "| `name` | VARCHAR | true | unknown | unknown |" in body


def test_narrower_refresh_keeps_still_represented_table_links(tmp_path):
    """Finding 4: a Dataset Overview's membership is the collection's EXISTING
    represented pages PLUS the requested updates — a narrower second refresh
    never drops a still-present table's link, and a never-refreshed approved
    asset is never added."""
    project = sqlite_lake_project(tmp_path)
    api = AuthoringProject(project)
    started = api.start_proposal()
    proposal = started["proposal"]
    approved(api, project, started)

    first = api.refresh_schema(
        proposal, started["candidate_revision"], [LAKE_CUSTOMERS, LAKE_ORDERS]
    )
    overview_path = page_paths(first)[collection_resource_of(LAKE_CUSTOMERS)]
    first_text = run_git(project, "show", f"{first['revision']}:{overview_path}")
    assert "[customers](" in first_text and "[orders](" in first_text

    second = api.refresh_schema(proposal, first["revision"], [LAKE_ORDERS])
    second_text = run_git(project, "show", f"{second['revision']}:{overview_path}")
    assert "[customers](" in second_text  # still represented: link kept
    assert "[orders](" in second_text
    assert "audit" not in second_text  # never refreshed: never asserted documented
    overview = next(
        page
        for page in second["pages"]
        if page["resource"] == collection_resource_of(LAKE_CUSTOMERS)
    )
    assert overview["changes"] == {"added": [], "removed": []}  # no false removal flag


def test_multiline_column_meaning_moves_to_history_completely():
    """Finding 5: a multiline authored column meaning moves into the history
    entry as ONE complete block — continuation lines never stay orphaned in
    the active meanings section of a removed/type-changed column."""
    from ariadne.context import build_table_page

    resource = table_resource(SALES_ASSET)
    asset = {**SALES_ASSET, "resource": resource}
    unknown = {"nullable": "unknown", "default": "unknown", "comment": "unknown"}
    profile = {
        "row_count": 3,
        "primary_key_candidates": ["order_id"],
        "columns": {
            "order_id": {"null_count": 0, "distinct_count": 3},
            "amount": {"null_count": 0, "distinct_count": 2},
        },
    }
    v1, _flags = build_table_page(
        asset=asset,
        columns=[
            {"column": "order_id", "type": "BIGINT", **unknown},
            {"column": "amount", "type": "DOUBLE", **unknown},
        ],
        profile=profile,
        existing_text=None,
        now="2026-02-01T00:00:00+00:00",
    )
    authored = v1.replace(
        "- `amount` — unknown (not yet authored)",
        "- `amount` — net amount of the sale.\n  Includes returns; the gross figure is derived.",
    )
    assert authored != v1  # the placeholder was found and replaced

    v2, flags = build_table_page(
        asset=asset,
        columns=[
            {"column": "order_id", "type": "BIGINT", **unknown},
            {"column": "amount", "type": "VARCHAR", **unknown},
        ],
        profile=profile,
        existing_text=authored,
        now="2026-02-02T00:00:00+00:00",
    )
    assert flags["type_changed"] == [{"column": "amount", "from": "DOUBLE", "to": "VARCHAR"}]
    assert "`amount` type changed DOUBLE -> VARCHAR" in v2
    # the COMPLETE block (first line + continuation) rides into history …
    assert (
        "retained meaning: net amount of the sale. Includes returns; "
        "the gross figure is derived." in v2
    )
    # … and nothing of it stays orphaned in the active meanings section
    assert v2.count("Includes returns") == 1
    assert "- `amount` — unknown (not yet authored)" in v2  # reseeded, no rename guess


def test_refresh_preserves_supplied_quality_profile_without_touching_core_facts():
    """Issue #53 (spec 0013 §2): ordinary refresh preserves an authored
    ``ariadne_quality`` profile verbatim while the core-owned
    resource/schema/observations keep their ownership — an identical refresh
    is a byte-level no-op even with the authored profile present, and a schema
    change regenerates only the core-owned facts. No new quality-producing
    refresh exists: this pins build_table_page's existing preservation."""
    from ariadne.context import _load_frontmatter_meta, _page_contract_errors, build_table_page
    from ariadne.sources import parse_resource

    resource = table_resource(SALES_ASSET)
    asset = {**SALES_ASSET, "resource": resource}
    unknown = {"nullable": "unknown", "default": "unknown", "comment": "unknown"}
    profile = {
        "row_count": 3,
        "primary_key_candidates": ["order_id"],
        "columns": {
            "order_id": {"null_count": 0, "distinct_count": 3},
            "amount": {"null_count": 0, "distinct_count": 2},
        },
    }
    columns = [
        {"column": "order_id", "type": "BIGINT", **unknown},
        {"column": "amount", "type": "DOUBLE", **unknown},
    ]
    v1, _flags = build_table_page(
        asset=asset,
        columns=columns,
        profile=profile,
        existing_text=None,
        now="2026-02-01T00:00:00+00:00",
    )
    # ordinary page editing adds the supplied metadata (issue #53: authored
    # extras ride the existing preservation seam, not a new refresh product)
    quality = {
        "version": 1,
        "reports": [
            {
                "id": "owner-completeness",
                "asset": resource,
                "source_ids": [f"catalog-{asset['source']}-{asset['schema']}-{asset['table']}"],
                "scope": {
                    "kind": "asset",
                    "description": "All rows of the sales orders table.",
                    "population": "every row of the physical table",
                    "period": None,
                },
                "reported_at": "2026-01-15T00:00:00+00:00",
                "checks": [
                    {
                        "id": "completeness",
                        "kind": "completeness",
                        "outcome": "unknown",
                        "criterion": "every order placed is present",
                        "tested_population": "all orders",
                        "tested_period": None,
                    }
                ],
            }
        ],
    }
    meta = _load_frontmatter_meta(v1)
    meta["ariadne_quality"] = quality
    front = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True, default_flow_style=False)
    _fm, body = v1.split("---\n\n", 1)
    authored = f"---\n{front}---\n\n{body}"

    # an identical refresh preserves the supplied profile and every authored
    # fact (parsed equality; the refresh also canonicalizes frontmatter key
    # order on its first pass over a hand-edited page) and reports no change
    v2, flags = build_table_page(
        asset=asset,
        columns=columns,
        profile=profile,
        existing_text=authored,
        now="2026-02-02T00:00:00+00:00",
    )
    assert flags == {"added": [], "removed": [], "type_changed": []}
    assert _load_frontmatter_meta(v2) == meta
    # the canonical form is now a byte-level no-op: identical refresh, identical
    # bytes, profile present (the existing no-op contract, profile included)
    v2b, flags2b = build_table_page(
        asset=asset,
        columns=columns,
        profile=profile,
        existing_text=v2,
        now="2026-02-02T00:00:00+00:00",
    )
    assert v2b == v2 and flags2b == flags

    # a schema change regenerates ONLY the core-owned facts; the supplied
    # profile survives verbatim and the page still passes the shared gate
    v3, flags3 = build_table_page(
        asset=asset,
        columns=[
            {"column": "order_id", "type": "BIGINT", **unknown},
            {
                "column": "qty",
                "type": "BIGINT",
                **unknown,
            },
        ],
        profile=profile,
        existing_text=v2,
        now="2026-02-03T00:00:00+00:00",
    )
    assert flags3["removed"] == ["amount"] and "`amount` removed" in v3
    meta3 = _load_frontmatter_meta(v3)
    assert meta3["ariadne_quality"] == quality  # preserved verbatim
    assert meta3["resource"] == resource  # the core binding is untouched
    assert [entry["column"] for entry in meta3["ariadne"]["schema"]] == ["order_id", "qty"]
    assert parse_resource(meta3["resource"])[0] == "table"
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        page = root / "context_layer" / "tables" / "orders.md"
        page.parent.mkdir(parents=True)
        page.write_text(v3, encoding="utf-8")
        assert _page_contract_errors(root, page, "table") == []


# ------------- C1 (issue #69): selected observed filter values (spec 0024 §3)

# One independently authored fixture family: a typed parquet table whose
# literals ARE the expectations — region = EMEA, AMER, EMEA (histogram EMEA 2
# / AMER 1 straight from those literals), status is the profiled-but-
# unselected field, code keeps integer-looking STRINGS exact, note carries a
# measured null beside two values, tier is constant (no histogram), and
# observed_on is temporal (not an exact filter-value representation).
REGIONS_SCHEMA = [
    ("id", "BIGINT"),
    ("region", "VARCHAR"),
    ("status", "VARCHAR"),
    ("code", "VARCHAR"),
    ("note", "VARCHAR"),
    ("tier", "VARCHAR"),
    ("observed_on", "DATE"),
]


def regions_rows_v1() -> list[tuple]:
    from datetime import date

    return [
        (1, "EMEA", "open", "007", None, "std", date(2026, 1, 1)),
        (2, "AMER", "open", "008", "x", "std", date(2026, 1, 2)),
        (3, "EMEA", "closed", "007", "y", "std", date(2026, 1, 1)),
    ]


def regions_rows_v2() -> list[tuple]:
    """V2 changes ``code`` from VARCHAR to a true BIGINT between refreshes."""
    from datetime import date

    return [
        (1, "EMEA", "open", 7, None, "std", date(2026, 1, 1)),
        (2, "AMER", "open", 8, "x", "std", date(2026, 1, 2)),
        (3, "EMEA", "closed", 7, "y", "std", date(2026, 1, 1)),
    ]


REGIONS_SCHEMA_V2 = [(name, "BIGINT" if name == "code" else kind) for name, kind in REGIONS_SCHEMA]


_FIXTURE_IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
_FIXTURE_TYPE_RE = re.compile(r"[A-Z][A-Z0-9]*\Z")


def write_typed_parquet(path: Path, schema: list[tuple[str, str]], rows: list[tuple]) -> Path:
    """One parquet file with EXPLICIT column types (the shared write_parquet
    helper stringifies row tuples, which would erase typed columns). The DDL
    interpolates only allowlist-checked fixture identifiers/types — values
    ride as bound parameters."""
    path.parent.mkdir(parents=True, exist_ok=True)
    for name, kind in schema:
        assert _FIXTURE_IDENTIFIER_RE.fullmatch(name), name
        assert _FIXTURE_TYPE_RE.fullmatch(kind), kind
    create = f"CREATE TABLE t ({', '.join(f'{name} {kind}' for name, kind in schema)})"
    insert = f"INSERT INTO t VALUES ({', '.join('?' for _ in schema)})"
    copy = f"COPY t TO '{path}' (FORMAT PARQUET)"
    con = duckdb.connect()
    # nosemgrep — allowlist-asserted fixture identifiers/types only (the
    # repository discipline for DDL that parameters cannot carry); row values
    # ride as bound parameters
    con.execute(create)
    con.executemany(insert, rows)
    con.execute(copy)
    con.close()
    return path


def regions_project(
    tmp_path: Path, rows: list[tuple], schema: list[tuple[str, str]] | None = None
) -> Path:
    """A one-source Git data project over the typed regions fixture."""
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    write_typed_parquet(
        project / "data" / "regions" / "regions.parquet", schema or REGIONS_SCHEMA, rows
    )
    (project / "ariadne.yaml").write_text(
        "sources:\n  - name: regions\n    type: parquet\n    path: data/regions/regions.parquet\n",
        encoding="utf-8",
    )
    (project / "data").mkdir(exist_ok=True)
    (project / "data" / "seed_notes.md").write_text(SEED_NOTES, encoding="utf-8")
    run_git(project, "init", "-q")
    run_git(project, "config", "user.name", "Ariadne Tests")
    run_git(project, "config", "user.email", "tests@ariadne.local")
    run_git(project, "add", "--", "ariadne.yaml", "data/seed_notes.md")
    run_git(project, "commit", "-q", "-m", "human: initial artifacts")
    return project


REGIONS_ASSET = {"source": "regions", "catalog": None, "schema": "regions", "table": "regions"}


def regions_page_name(result: dict) -> str:
    return PurePosixPath(page_paths(result)[table_resource(REGIONS_ASSET)]).stem


def read_full_page(api: AuthoringProject, proposal: str, name: str) -> str:
    """The COMPLETE page text through the public read route (bounded parts
    reassembled — a 200-column page spans several 20k-char parts)."""
    chunk = api.read_artifact(proposal, {"kind": "page", "section": "tables", "name": name})
    content, part = chunk["content"], chunk["part"]
    while part < chunk["parts"]:
        part += 1
        chunk = api.read_artifact(
            proposal, {"kind": "page", "section": "tables", "name": name}, part=part
        )
        content += chunk["content"]
    return content


def select_observed_values(
    api: AuthoringProject, proposal: str, revision: str, name: str, selection
) -> dict:
    """Edit one table page's authored ``observed_value_columns`` through the
    PUBLIC complete-page edit (spec 0024 §3: human-owned frontmatter, edited
    with the expected candidate revision)."""
    meta, body = _split_page(read_full_page(api, proposal, name))
    if selection is None:
        meta.pop("observed_value_columns", None)
    else:
        meta["observed_value_columns"] = selection
    return api.edit_proposal(
        proposal,
        revision,
        {
            "kind": "page",
            "section": "tables",
            "name": name,
            "content": _render_page(meta, body),
        },
    )


def table_page(api: AuthoringProject, proposal: str, name: str) -> tuple[dict, dict, str]:
    """(frontmatter meta, ariadne observations, page text) of one candidate
    table page, read through the public read route."""
    meta, _body = _split_page(read_full_page(api, proposal, name))
    return meta, meta["ariadne"]["observations"], _body


def started_regions_project(
    tmp_path: Path,
    rows: list[tuple] | None = None,
    schema: list[tuple[str, str]] | None = None,
):
    """(project, api, proposal) with an approved first refresh already done."""
    project = regions_project(tmp_path, rows or regions_rows_v1(), schema)
    api = AuthoringProject(project)
    started = api.start_proposal()
    approved(api, project, started)
    first = api.refresh_schema(started["proposal"], started["candidate_revision"], [REGIONS_ASSET])
    return project, api, first


def test_selected_observed_values_public_route_emea_amer(tmp_path):
    """C1's public route (spec 0024 §3 + §6 AC2): absent selection keeps the
    legacy page shape; the normal selection edit -> refresh -> read route
    publishes ONLY the selected measured values — the histogram EMEA 2 /
    AMER 1 comes from the authored literals, never implementation output —
    rendered as data in the core observation section; the unselected
    ``status`` field never appears; the identical refresh is a byte/revision
    no-op."""
    _project, api, first = started_regions_project(tmp_path)
    proposal = first["proposal"]
    name = regions_page_name(first)

    _meta, observations, page_text = table_page(api, proposal, name)
    assert "value_evidence" not in observations  # absent selection: legacy shape
    assert "value evidence" not in page_text

    edited = select_observed_values(api, proposal, first["revision"], name, {"region": "VARCHAR"})
    second = api.refresh_schema(proposal, edited["revision"], [REGIONS_ASSET])
    assert second["changed"] is True
    _meta, observations, page_text = table_page(api, proposal, name)
    assert observations["value_evidence"] == {
        "region": {
            "state": "observed",
            "top_values": [
                {"value": "EMEA", "count": 2},
                {"value": "AMER", "count": 1},
            ],
        }
    }
    assert '`region`: observed — "EMEA" (2), "AMER" (1)' in page_text
    assert '"open"' not in page_text and '"closed"' not in page_text  # unselected field

    third = api.refresh_schema(proposal, second["revision"], [REGIONS_ASSET])
    assert third["changed"] is False
    assert third["revision"] == second["revision"]  # identical inputs: no new revision
    assert table_page(api, proposal, name)[2] == page_text  # and identical bytes


@pytest.mark.parametrize(
    "column,selected_type,expected",
    [
        (
            "region",
            "VARCHAR",
            {
                "state": "observed",
                "top_values": [
                    {"value": "EMEA", "count": 2},
                    {"value": "AMER", "count": 1},
                ],
            },
        ),
        (  # integer-looking STRINGS stay exact strings
            "code",
            "VARCHAR",
            {
                "state": "observed",
                "top_values": [
                    {"value": "007", "count": 2},
                    {"value": "008", "count": 1},
                ],
            },
        ),
        (  # a measured null stays null (never the string "NULL")
            "note",
            "VARCHAR",
            {
                "state": "observed",
                "top_values": [
                    {"value": None, "count": 1},
                    {"value": "x", "count": 1},
                    {"value": "y", "count": 1},
                ],
            },
        ),
        (
            "id",
            "BIGINT",
            {
                "state": "observed",
                "top_values": [
                    {"value": 1, "count": 1},
                    {"value": 2, "count": 1},
                    {"value": 3, "count": 1},
                ],
            },
        ),
        ("tier", "VARCHAR", {"state": "unavailable", "reason": "not_in_profile"}),
        (
            "observed_on",
            "DATE",
            {"state": "unavailable", "reason": "unsupported_representation"},
        ),
        ("region", "INTEGER", {"state": "unavailable", "reason": "type_changed"}),
        ("ghost", "VARCHAR", {"state": "unavailable", "reason": "column_missing"}),
    ],
)
def test_selected_column_evidence_states(column, selected_type, expected, tmp_path):
    """The parametrized evidence family (spec 0024 §3, §6 AC3): each selected
    column produces exactly its representation-driven outcome, and ONLY
    selected columns appear in ``value_evidence``. Expectations derive from
    the authored literals and the spec's supported/unavailable contract, not
    from implementation output."""
    _project, api, first = started_regions_project(tmp_path)
    proposal = first["proposal"]
    name = regions_page_name(first)
    edited = select_observed_values(api, proposal, first["revision"], name, {column: selected_type})
    api.refresh_schema(proposal, edited["revision"], [REGIONS_ASSET])
    _meta, observations, page_text = table_page(api, proposal, name)
    assert list(observations["value_evidence"]) == [column]  # only the selected column
    assert observations["value_evidence"][column] == expected
    if expected["state"] == "unavailable":
        assert "top_values" not in observations["value_evidence"][column]
    if column == "observed_on":
        # the profiler's stringified dates never leak as filter literals
        assert "2026-01-01" not in page_text and "2026-01-02" not in page_text
    if column == "note":
        assert '`note`: observed — null (1), "x" (1), "y" (1)' in page_text


def test_type_change_rebinding_and_deselection_keep_history(tmp_path):
    """Spec 0024 §3/§6 AC4: a type change loses usable values with a visible
    reason while the human-owned selection is preserved for review; repeating
    the refresh stays unavailable (the old type binding is never erased);
    explicit rebinding restores evidence; deselection removes ACTIVE evidence
    while historical candidate revisions keep their bytes and the schema
    history survives."""
    project, api, first = started_regions_project(tmp_path)
    proposal = first["proposal"]
    name = regions_page_name(first)
    page_path = page_paths(first)[table_resource(REGIONS_ASSET)]

    edited = select_observed_values(
        api, proposal, first["revision"], name, {"region": "VARCHAR", "code": "VARCHAR"}
    )
    second = api.refresh_schema(proposal, edited["revision"], [REGIONS_ASSET])
    _meta, observations, _text = table_page(api, proposal, name)
    assert observations["value_evidence"]["code"]["top_values"] == [
        {"value": "007", "count": 2},
        {"value": "008", "count": 1},
    ]

    # the source changes code VARCHAR -> BIGINT underneath
    write_typed_parquet(
        project / "data" / "regions" / "regions.parquet",
        REGIONS_SCHEMA_V2,
        regions_rows_v2(),
    )
    third = api.refresh_schema(proposal, second["revision"], [REGIONS_ASSET])
    meta, observations, page_text = table_page(api, proposal, name)
    assert observations["value_evidence"]["code"] == {
        "state": "unavailable",
        "reason": "type_changed",
    }
    assert observations["value_evidence"]["region"]["state"] == "observed"  # untouched column
    assert meta["observed_value_columns"] == {  # selection preserved for review
        "region": "VARCHAR",
        "code": "VARCHAR",
    }
    assert "type changed VARCHAR -> BIGINT" in page_text  # schema history intact

    # a repeated refresh cannot erase the binding and reactivate old values
    fourth = api.refresh_schema(proposal, third["revision"], [REGIONS_ASSET])
    assert fourth["changed"] is False
    assert table_page(api, proposal, name)[1]["value_evidence"]["code"]["reason"] == "type_changed"

    # explicit rebinding to the new recorded type restores exact integer values
    rebound = select_observed_values(
        api, proposal, third["revision"], name, {"region": "VARCHAR", "code": "BIGINT"}
    )
    fifth = api.refresh_schema(proposal, rebound["revision"], [REGIONS_ASSET])
    assert fifth["changed"] is True
    assert table_page(api, proposal, name)[1]["value_evidence"]["code"] == {
        "state": "observed",
        "top_values": [
            {"value": 7, "count": 2},
            {"value": 8, "count": 1},
        ],
    }

    # deselection (empty mapping) removes active evidence after refresh —
    # never a scrub of historical candidate revisions or Git history
    cleared = select_observed_values(api, proposal, fifth["revision"], name, {})
    sixth = api.refresh_schema(proposal, cleared["revision"], [REGIONS_ASSET])
    assert sixth["changed"] is True
    _meta, observations, page_text = table_page(api, proposal, name)
    assert "value_evidence" not in observations
    assert "value evidence" not in page_text
    assert "EMEA" in run_git(project, "show", f"{second['revision']}:{page_path}")


def test_value_evidence_unit_seams_sampled_label_and_malformed_inputs():
    """The producer unit seam (spec 0024 §3): a SAMPLED profile stays labeled
    sampled beside its selected evidence; a malformed authored selection and a
    malformed supplied measurement are errors, never implicit publications."""
    from ariadne.context import build_table_page

    asset = {
        "source": "s",
        "catalog": None,
        "schema": "s",
        "table": "t",
        "resource": "ariadne://table/e30=",
    }
    columns = [
        {
            "column": "region",
            "type": "VARCHAR",
            "nullable": "unknown",
            "default": "unknown",
            "comment": "unknown",
        }
    ]
    profile = {
        "sampled": True,
        "row_count": 3,
        "primary_key_candidates": [],
        "columns": {
            "region": {
                "null_count": 0,
                "distinct_count": 2,
                "top_values": [
                    {"value": "EMEA", "count": 2},
                    {"value": "AMER", "count": 1},
                ],
            }
        },
    }
    existing = (
        "---\n"
        "type: table\n"
        "title: s.s.t\n"
        "description: table\n"
        "tags: [table, schema]\n"
        "observed_value_columns:\n"
        "  region: VARCHAR\n"
        "---\n\n"
        "# s.s.t\n"
    )
    page, _flags = build_table_page(
        asset=asset,
        columns=columns,
        profile=profile,
        existing_text=existing,
        now="2026-10-13T12:00:00+00:00",
    )
    assert "- scope: sampled" in page  # the sampled label survives evidence generation
    assert '`region`: observed — "EMEA" (2), "AMER" (1)' in page

    malformed_selection = existing.replace("  region: VARCHAR\n", "  [region]\n")
    with pytest.raises(ValueError, match="not a valid selection"):
        build_table_page(
            asset=asset,
            columns=columns,
            profile=profile,
            existing_text=malformed_selection,
            now="2026-10-13T12:00:00+00:00",
        )

    malformed_profile = {
        "sampled": False,
        "row_count": 3,
        "primary_key_candidates": [],
        "columns": {
            "region": {
                "null_count": 0,
                "distinct_count": 2,
                "top_values": [{"value": "EMEA"}],
            }
        },
    }
    with pytest.raises(ValueError, match="malformed measurement"):
        build_table_page(
            asset=asset,
            columns=columns,
            profile=malformed_profile,
            existing_text=existing,
            now="2026-10-13T12:00:00+00:00",
        )


@pytest.mark.parametrize(
    "raw_selection,expected_fragment",
    [
        ("  region: VARCHAR\n", None),  # the valid form passes the gate
        ("  region: VARCHAR\n  region: BIGINT\n", "duplicate declaration"),
        (
            "  region: VARCHAR\nobserved_value_columns:\n  status: VARCHAR\n",
            "declared more than once",
        ),
        ("  1: VARCHAR\n", "non-empty string"),
        ("  region:\n", "non-empty string"),
        ("  '': VARCHAR\n", "non-empty string"),
        ("  [region]\n", "must be a mapping"),
    ],
)
def test_selection_contract_gate(raw_selection, expected_fragment, tmp_path):
    """The authoring validation boundary (spec 0024 §3): a malformed mapping
    or duplicate declaration fails the shared page-contract gate before human
    admission; the valid selection and the plain legacy page both pass."""
    from ariadne.context import _page_contract_errors, build_table_page

    asset = {
        "source": "s",
        "catalog": None,
        "schema": "s",
        "table": "t",
        "resource": "ariadne://table/e30=",
    }
    columns = [
        {
            "column": "region",
            "type": "VARCHAR",
            "nullable": "unknown",
            "default": "unknown",
            "comment": "unknown",
        }
    ]
    profile = {
        "row_count": 3,
        "primary_key_candidates": [],
        "columns": {"region": {"null_count": 0, "distinct_count": 2}},
    }
    page, _flags = build_table_page(
        asset=asset,
        columns=columns,
        profile=profile,
        existing_text=None,
        now="2026-10-13T12:00:00+00:00",
    )
    head, body = page.split("---\n\n", 1)
    text = head + "observed_value_columns:\n" + raw_selection + "---\n\n" + body
    root = tmp_path / "staging"
    page_path = root / "context_layer" / "tables" / "t.md"
    page_path.parent.mkdir(parents=True)
    page_path.write_text(text, encoding="utf-8")
    errors = _page_contract_errors(root, page_path, "table")
    if expected_fragment is None:
        assert errors == []
    else:
        assert any(expected_fragment in error for error in errors)


def test_value_evidence_bound_fallback_never_clips(tmp_path):
    """Spec 0024 §3/§6 AC5, fallback half: independently known long exact
    strings (2x 4500 chars + JSON structure = well over the 8192 compact-JSON
    UTF-8 byte bound) make the successful mapping exceed the bound — every
    selected column falls back to unavailable/too_large and NO clipped or
    partial literal is published."""
    long_a, long_b = "A" * 4500, "B" * 4500
    rows = [(1, long_a, "x"), (2, long_b, "y"), (3, long_a, "x")]
    schema = [("id", "BIGINT"), ("region", "VARCHAR"), ("status", "VARCHAR")]
    _project, api, first = started_regions_project(tmp_path, rows=rows, schema=schema)
    proposal = first["proposal"]
    name = regions_page_name(first)

    edited = select_observed_values(api, proposal, first["revision"], name, {"region": "VARCHAR"})
    second = api.refresh_schema(proposal, edited["revision"], [REGIONS_ASSET])
    assert second["changed"] is True  # the fallback mapping fits: refresh succeeds
    _meta, observations, page_text = table_page(api, proposal, name)
    assert observations["value_evidence"] == {
        "region": {"state": "unavailable", "reason": "too_large"}
    }
    assert long_a not in page_text and long_b not in page_text  # never published
    assert long_a[:200] not in page_text  # never a clipped or partial literal
    assert "top_values" not in str(observations["value_evidence"])


def test_status_only_value_evidence_overflow_refuses_without_writes(tmp_path):
    """Spec 0024 §3/§6 AC5, refusal half: when even the status-only mapping
    exceeds the 8192-byte compact-JSON bound (200 selected columns; each
    status-only entry is ~53 bytes, so ~10.6 KiB > 8 KiB by literal
    arithmetic), the refresh refuses atomically — the candidate revision, the
    page bytes and the tracked tree are unchanged."""
    schema = [("id", "BIGINT")] + [(f"c{i:03d}", "VARCHAR") for i in range(200)]
    rows = [(1, *("a" if i % 2 == 0 else "b" for i in range(200)))]
    rows += [(2, *("b" if i % 2 == 0 else "a" for i in range(200)))]
    rows += [(3, *("a" if i % 2 == 0 else "b" for i in range(200)))]
    project, api, first = started_regions_project(tmp_path, rows=rows, schema=schema)
    proposal = first["proposal"]
    name = regions_page_name(first)
    page_path = page_paths(first)[table_resource(REGIONS_ASSET)]
    before_tree = run_git(project, "ls-tree", "-r", "--name-only", first["revision"])

    selection = {f"c{i:03d}": "VARCHAR" for i in range(200)}
    edited = select_observed_values(api, proposal, first["revision"], name, selection)
    before_page = run_git(project, "show", f"{edited['revision']}:{page_path}")
    with pytest.raises(ValueError, match="status-only value evidence"):
        api.refresh_schema(proposal, edited["revision"], [REGIONS_ASSET])

    # nothing was written: the revision, the page bytes and the tracked tree
    # (table page, Dataset Overview, index trees) are all unchanged
    record = json.loads((project / ".ariadne" / "proposals" / f"{proposal}.json").read_text())
    assert record["candidate_revision"] == edited["revision"]
    assert run_git(project, "show", f"{edited['revision']}:{page_path}") == before_page
    assert run_git(project, "ls-tree", "-r", "--name-only", edited["revision"]) == before_tree


def test_malformed_selection_and_stale_revision_refuse_without_writes(tmp_path):
    """Spec 0024 §3: a malformed authored selection (a list, not a mapping)
    refuses the refresh BEFORE any write, and the existing stale-revision
    gate refuses identically — candidate revision, page bytes and tracked
    tree unchanged in both cases."""
    project, api, first = started_regions_project(tmp_path)
    proposal = first["proposal"]
    name = regions_page_name(first)
    page_path = page_paths(first)[table_resource(REGIONS_ASSET)]

    edited = select_observed_values(api, proposal, first["revision"], name, ["region"])
    before_page = run_git(project, "show", f"{edited['revision']}:{page_path}")
    before_tree = run_git(project, "ls-tree", "-r", "--name-only", edited["revision"])
    with pytest.raises(ValueError, match="not a valid selection"):
        api.refresh_schema(proposal, edited["revision"], [REGIONS_ASSET])
    with pytest.raises(ValueError, match="stale revision"):
        api.refresh_schema(proposal, "0" * 40, [REGIONS_ASSET])
    record = json.loads(
        (project / ".ariadne" / "proposals" / f"{proposal}.json").read_text(encoding="utf-8")
    )
    assert record["candidate_revision"] == edited["revision"]
    assert run_git(project, "show", f"{edited['revision']}:{page_path}") == before_page
    assert run_git(project, "ls-tree", "-r", "--name-only", edited["revision"]) == before_tree


def test_generated_value_evidence_is_protected_at_the_edit_seam(tmp_path):
    """Spec 0024 §3/§5: the measured values/counts are system-owned — an
    authored replacement inside ``ariadne.observations.value_evidence`` is
    refused at the edit seam like every other generated fact."""
    _project, api, first = started_regions_project(tmp_path)
    proposal = first["proposal"]
    name = regions_page_name(first)
    edited = select_observed_values(api, proposal, first["revision"], name, {"region": "VARCHAR"})
    second = api.refresh_schema(proposal, edited["revision"], [REGIONS_ASSET])
    meta, body = _split_page(read_full_page(api, proposal, name))

    forged = dict(meta)
    ariadne = dict(meta["ariadne"])
    observations = dict(ariadne["observations"])
    observations["value_evidence"] = {
        "region": {
            "state": "observed",
            "top_values": [{"value": "FORGED", "count": 99}],
        }
    }
    ariadne["observations"] = observations
    forged["ariadne"] = ariadne
    with pytest.raises(ValueError, match="system-owned"):
        api.edit_proposal(
            proposal,
            second["revision"],
            {
                "kind": "page",
                "section": "tables",
                "name": name,
                "content": _render_page(forged, body),
            },
        )


def test_artifact_bound_refusal_refreshes_nothing_atomically(tmp_path):
    """Fix F1 (parent-authorized, spec 0024 §3/§6 AC5): when one refresh covers
    two selected tables and the SECOND regenerated page would exceed the
    existing 2,097,152-byte artifact bound (a ~2,096,865-byte existing page —
    calibrated authored bulk — plus selected evidence), the refusal must be
    ATOMIC: no page, candidate revision or tracked-tree byte moves. The
    sequential edit seam checks one page at a time, so without the pre-flight
    the first table's page is already written when the second refuses."""
    OPS_ASSET = {"source": "ops", "catalog": None, "schema": "ops", "table": "orders"}
    WIDE_ASSET = {"source": "wide", "catalog": None, "schema": "wide", "table": "wide"}
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    write_typed_parquet(
        project / "data" / "ops" / "orders.parquet",
        [("id", "BIGINT"), ("region", "VARCHAR")],
        [(1, "EMEA"), (2, "AMER"), (3, "EMEA")],
    )
    write_typed_parquet(
        project / "data" / "wide" / "wide.parquet",
        [("id", "BIGINT"), ("region2", "VARCHAR"), ("status2", "VARCHAR"), ("code2", "VARCHAR")],
        [(1, "EMEA", "open", "007"), (2, "AMER", "open", "008"), (3, "EMEA", "closed", "007")],
    )
    (project / "ariadne.yaml").write_text(
        "sources:\n  - name: ops\n    type: parquet\n    path: data/ops/orders.parquet\n"
        "  - name: wide\n    type: parquet\n    path: data/wide/wide.parquet\n",
        encoding="utf-8",
    )
    (project / "data").mkdir(exist_ok=True)
    (project / "data" / "seed_notes.md").write_text(SEED_NOTES, encoding="utf-8")
    run_git(project, "init", "-q")
    run_git(project, "config", "user.name", "Ariadne Tests")
    run_git(project, "config", "user.email", "tests@ariadne.local")
    run_git(project, "add", "--", "ariadne.yaml", "data/seed_notes.md")
    run_git(project, "commit", "-q", "-m", "human: initial artifacts")
    api = AuthoringProject(project)
    started = api.start_proposal()
    approved(api, project, started)
    first = api.refresh_schema(
        started["proposal"], started["candidate_revision"], [OPS_ASSET, WIDE_ASSET]
    )
    proposal = first["proposal"]
    ops_path = next(
        p["path"] for p in first["pages"] if p["kind"] == "table" and "ops" in p["path"]
    )
    wide_path = next(
        p["path"] for p in first["pages"] if p["kind"] == "table" and "wide" in p["path"]
    )
    ops_name, wide_name = PurePosixPath(ops_path).stem, PurePosixPath(wide_path).stem

    # the reviewer's probe shape: authored bulk brings the existing wide page
    # within a few hundred bytes of the artifact bound, still under it
    meta, body = _split_page(read_full_page(api, proposal, wide_name))
    filled = body.rstrip("\n") + f"\n\n## Author notes\n\n{'n' * 2_094_000}\n"
    rev = api.edit_proposal(
        proposal,
        first["revision"],
        {
            "kind": "page",
            "section": "tables",
            "name": wide_name,
            "content": _render_page(meta, filled),
        },
    )["revision"]
    wide_selection = {"region2": "VARCHAR", "status2": "VARCHAR", "code2": "VARCHAR"}
    edited = select_observed_values(api, proposal, rev, wide_name, wide_selection)
    edited = select_observed_values(
        api, proposal, edited["revision"], ops_name, {"region": "VARCHAR"}
    )
    rev = edited["revision"]
    wide_size = len(run_git(project, "show", f"{rev}:{wide_path}"))
    assert 2_096_600 <= wide_size < 2_097_152  # under the bound, close enough to cross it

    before_tree = run_git(project, "ls-tree", "-r", "--name-only", rev)
    before_ops = run_git(project, "show", f"{rev}:{ops_path}")
    before_wide = run_git(project, "show", f"{rev}:{wide_path}")
    with pytest.raises(ValueError, match="2097152-byte bound"):
        api.refresh_schema(proposal, rev, [OPS_ASSET, WIDE_ASSET])

    # atomic refusal: the first table's page never moved either
    record = json.loads(
        (project / ".ariadne" / "proposals" / f"{proposal}.json").read_text(encoding="utf-8")
    )
    assert record["candidate_revision"] == rev
    assert run_git(project, "show", f"{rev}:{ops_path}") == before_ops
    assert run_git(project, "show", f"{rev}:{wide_path}") == before_wide
    assert run_git(project, "ls-tree", "-r", "--name-only", rev) == before_tree


def test_uhugeint_native_integer_values_stay_exact(tmp_path):
    """Fix F2 (parent-authorized, spec 0024 §3/AC3): UHUGEINT belongs to the
    native integer family — a selected native catalog column with the
    hand-specified values 7, 8, 7 publishes exact INTEGER evidence 7:2, 8:1
    (never floats; parquet cannot carry unsigned 128-bit, so the fixture is a
    native DuckDB source, the only representation whose catalog type IS
    UHUGEINT)."""
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    (project / "data").mkdir(exist_ok=True)
    db = project / "data" / "flags.duckdb"
    con = duckdb.connect(str(db))
    con.execute("CREATE TABLE flags_t (id BIGINT NOT NULL, flags UHUGEINT)")
    con.executemany("INSERT INTO flags_t VALUES (?, ?)", [(1, 7), (2, 8), (3, 7)])
    con.close()
    (project / "ariadne.yaml").write_text(
        "sources:\n  - name: flagdb\n    type: duckdb\n    path: data/flags.duckdb\n",
        encoding="utf-8",
    )
    (project / "data" / "seed_notes.md").write_text(SEED_NOTES, encoding="utf-8")
    run_git(project, "init", "-q")
    run_git(project, "config", "user.name", "Ariadne Tests")
    run_git(project, "config", "user.email", "tests@ariadne.local")
    run_git(project, "add", "--", "ariadne.yaml", "data/seed_notes.md")
    run_git(project, "commit", "-q", "-m", "human: initial artifacts")
    api = AuthoringProject(project)
    started = api.start_proposal()
    approved(api, project, started)
    FLAG_ASSET = {"source": "flagdb", "catalog": "flagdb", "schema": "main", "table": "flags_t"}
    first = api.refresh_schema(
        proposal := started["proposal"], started["candidate_revision"], [FLAG_ASSET]
    )
    name = PurePosixPath(page_paths(first)[table_resource(FLAG_ASSET)]).stem

    edited = select_observed_values(api, proposal, first["revision"], name, {"flags": "UHUGEINT"})
    second = api.refresh_schema(proposal, edited["revision"], [FLAG_ASSET])
    assert second["changed"] is True
    _meta, observations, page_text = table_page(api, proposal, name)
    assert observations["value_evidence"] == {
        "flags": {
            "state": "observed",
            "top_values": [
                {"value": 7, "count": 2},
                {"value": 8, "count": 1},
            ],
        }
    }
    # exact native integers, never coerced floats
    for entry in observations["value_evidence"]["flags"]["top_values"]:
        assert isinstance(entry["value"], int) and not isinstance(entry["value"], bool)
    assert "`flags`: observed — 7 (2), 8 (1)" in page_text
