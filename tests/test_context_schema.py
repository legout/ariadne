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
