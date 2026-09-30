"""ariadne-agent: installable conversation backend over native Ariadne tools.

A separately installable distribution (ADR-0014, spec 2026-09-29-0006): it
depends on ``ariadne-core`` (never the unrelated PyPI ``ariadne`` GraphQL
project) and ``tau-ai``, uses ``tau_agent.AgentHarness`` for the loop and
``tau_ai`` providers for the model, and never imports or invokes ``tau_coding``
at runtime, never launches a server, and never grants CLI, shell, or raw SQL
tools. Analyst role only in this revision (issue #23).
"""

from ariadne_agent.session import (
    ROLES,
    AgentSession,
    AgentSessionEvent,
    AssistantText,
    RunCompleted,
    SessionError,
    ToolActivity,
    open_session,
)

__all__ = [
    "ROLES",
    "AgentSession",
    "AgentSessionEvent",
    "AssistantText",
    "RunCompleted",
    "SessionError",
    "ToolActivity",
    "open_session",
]
