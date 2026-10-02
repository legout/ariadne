"""The AriadneRuntime compatibility alias (spec 2026-10-02-0009 §2 "Module
ownership", ADR-0016, issue #33).

The transport-neutral query/discovery/context/ad-hoc/example orchestration
moved to :class:`ariadne.query.QueryRuntime` in the modular-core extraction.
``AriadneRuntime`` stays importable from here as ONE alias to that same
implementation class for its documented Python consumers — a plain assignment,
never a subclass, wrapper, or second implementation
(``ariadne.runtime.AriadneRuntime is ariadne.query.QueryRuntime``).
``ariadne.serve.Facade`` aliases the same class. New callers import
:class:`ariadne.query.QueryRuntime`.
"""

from ariadne.query import (  # pyright: ignore[reportMissingImports] — new-module resolver drift
    QueryRuntime,
)

# Single compatibility alias (spec 2026-10-02-0009 §2: runtime.py may retain
# AriadneRuntime as a single alias; compatibility names are not second
# implementations).
AriadneRuntime = QueryRuntime
