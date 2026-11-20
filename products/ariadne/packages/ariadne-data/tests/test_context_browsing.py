"""Context browsing over the admitted native Context snapshot.

The fixture pages are the authored native bundle constants admitted through
the real composite journey; project admission and pinned-snapshot tamper
refusals are covered by the Git lifecycle tests (spec0035 §6: the classic
``context_layer`` browsing seam is retired).
"""

import asyncio

import pytest  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages

from ariadne.authoring import AuthoringProject
from ariadne.discovery import DiscoveryRuntime
from tests.test_git_admission import _policy_edit, admit, admitted_ready
from tests.test_git_authoring import (
    NATIVE_POLICY_PAGE,
    complete_bundle_project,
)

REVISED_BODY = "The browsing revision body."


@pytest.fixture(scope="module")
def runtime(tmp_path_factory):
    project = complete_bundle_project(tmp_path_factory.mktemp("browsing_project"))
    api = AuthoringProject(project)
    review, _journey = admitted_ready(api, project, _policy_edit(REVISED_BODY))
    assert admit(project, review) == 0
    return DiscoveryRuntime.open_project(project)


def test_listing_is_a_metadata_directory(runtime):
    listing = asyncio.run(runtime.list_context_pages())
    assert [entry["path"] for entry in listing] == [
        "computations/events-event_count.md",
        "metrics/event-count.md",
        "policies/all-events-count.md",
    ]
    titles = {entry["path"]: entry["title"] for entry in listing}
    assert titles["metrics/event-count.md"] == "event_count"
    assert titles["policies/all-events-count.md"] == "All events count"
    # the finalize pass's generated page: the documented title format
    expected_title = "sanctioned SQL — events::events.event_count"
    assert titles["computations/events-event_count.md"] == expected_title
    for entry in listing:
        assert entry["draft"] is False
        assert "content" not in entry
        assert entry["context_signals"]["pages"][0]["path"] == entry["path"]


def test_read_returns_the_exact_page(runtime):
    served = asyncio.run(runtime.read_context_page("policies/all-events-count.md"))
    assert served["path"] == "policies/all-events-count.md"
    assert served["draft"] is False
    # the exact authored canonical bytes of the served revision
    assert served["content"] == NATIVE_POLICY_PAGE.replace("The rule body.", REVISED_BODY)
    assert served["context_signals"]["pages"][0]["path"] == "policies/all-events-count.md"


def test_invalid_paths_refuse_naming_the_rejected_path(runtime, tmp_path):
    """Absolute, escaping, backslashed, non-markdown, unknown and empty paths
    each refuse through the pinned native facade, naming the rejected path —
    the served root is the verified snapshot itself, so no path resolves
    outside it and nothing is read."""
    from lumio_wiki.ariadne_context import UnadmittedInputError

    for bad in (
        "/etc/passwd.md",
        "../policies/all-events-count.md",
        "policies\\all-events-count.md",
        "policies/order-status.txt",
        "policies/missing.md",
        "",
    ):
        with pytest.raises(
            UnadmittedInputError, match="no visible context page at path"
        ) as refusal:
            asyncio.run(runtime.read_context_page(bad))
        assert repr(bad) in str(refusal.value), "the refusal names the rejected path"
