"""ariadne-agent: installable conversation backend over native Ariadne tools.

A separately installable distribution (ADR-0014, spec 2026-09-29-0006): it
depends on ``ariadneai`` (never the unrelated PyPI ``ariadne`` GraphQL
project) and ``tau-ai``, uses ``tau_agent.AgentHarness`` for the loop and
``tau_ai`` providers for the model, and never imports or invokes ``tau_coding``
at runtime, never launches a server, and never grants CLI, shell, or raw SQL
tools. Analyst (issue #23) and Authoring (issue #24) roles in this revision;
source approval and Promotion stay human-only, outside the agent.
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
