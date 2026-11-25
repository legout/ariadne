"""Session cache for lumio_context.execution_identity (test-only; #153)."""

import functools

import pytest


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
