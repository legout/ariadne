"""Import wiring for the paired Core/SDK scenarios (spec 0031 §4).

These modules reuse Core-native authoring/contract helpers
(``tests.test_contracts``, ``tests.test_git_authoring``) from the Core
member's own test tree. The member directory is inserted deliberately here
instead of relying on incidental sys.path state; the member's ``tests``
directory is a namespace portion, so its helper modules resolve without
copying any fixture tree. The paired modules themselves import each other
explicitly as ``integration.tests.lumio_metric_mvp``.
"""

from __future__ import annotations

import functools
import sys
from pathlib import Path

import pytest

CORE_MEMBER = (
    Path(__file__).resolve().parents[2] / "products" / "ariadne" / "packages" / "ariadne-data"
)
if str(CORE_MEMBER) not in sys.path:
    sys.path.insert(0, str(CORE_MEMBER))


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "real_execution_identity: skip the session cache of execution_identity"
    )


@pytest.fixture(scope="session")
def _cached_execution_identity():
    from ariadne import lumio_context

    return functools.lru_cache(maxsize=1)(lumio_context.execution_identity)


@pytest.fixture(autouse=True)
def _execution_identity_cache(request, monkeypatch, _cached_execution_identity):
    """Hashing eight packages per admission step dominates; tests that change
    the hashed code mark real_execution_identity to keep the uncached call."""
    if request.node.get_closest_marker("real_execution_identity") is None:
        from ariadne import lumio_context

        monkeypatch.setattr(lumio_context, "execution_identity", _cached_execution_identity)
