"""Read-only Git connection diagnosis for the external-agent authoring journey.

Specification 0010 §2 (plan 0010 J5): guided setup reports the local Git
tool, identity, repository state and remote readability through bounded
read-only probes. A successful ``ls-remote`` proves READ access only — push
and pull-request capability stay explicitly ``unverified``; this module never
attempts a test push, branch or PR. Credential values are never read, and
credential-bearing URLs are redacted from every diagnostic before it leaves
this module.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Final

import msgspec

#: Versioned report contract (plan 0010: new JSON results carry a schema version).
REPORT_SCHEMA_VERSION: Final[int] = 1

#: Remote-read outcomes. ``ls-remote`` success means read success ONLY (§2).
READ_SUCCESS: Final[str] = "success"
READ_FAILED: Final[str] = "failed"
READ_NOT_ATTEMPTED: Final[str] = "not-attempted"

#: Push/PR capability is a constant truthful status: this probe never proves it.
PUSH_PR_UNVERIFIED: Final[str] = "unverified"

_LOCAL_TIMEOUT_SECONDS: Final[float] = 15.0
_REMOTE_TIMEOUT_SECONDS: Final[float] = 30.0
_MESSAGE_LIMIT: Final[int] = 200

#: ``scheme://user:password@host`` userinfo is redacted, never echoed (§2.1).
_CREDENTIAL_URL: Final[re.Pattern[str]] = re.compile(
    r"([A-Za-z][A-Za-z0-9+.-]*://)([^/@:\s'\"]+)(:[^/@\s'\"]*)?@"
)

_AUTH_FAILURE_MARKERS: Final[tuple[str, ...]] = (
    "authentication failed",
    "could not read username",
    "permission denied",
    "access denied",
    "unauthorized",
)

_CREDENTIAL_GUIDANCE: Final[str] = (
    "use an ordinary SSH agent/key or Git credential helper on the host; Lumio "
    "never reads or echoes key/token values and never embeds credentials in "
    "remote URLs"
)


class GitToolStatus(msgspec.Struct, frozen=True):
    """Local Git executable availability and reported version."""

    available: bool
    version: str | None


class GitIdentityStatus(msgspec.Struct, frozen=True):
    """Commit-identity configuration (nonsecret ``user.name``/``user.email``)."""

    configured: bool
    user_name: str | None
    user_email: str | None


class GitRepositoryStatus(msgspec.Struct, frozen=True):
    """Read-only repository state of the selected project directory."""

    is_repository: bool
    branch: str | None
    clean: bool | None


class GitRemoteStatus(msgspec.Struct, frozen=True):
    """Selected remote configuration and one bounded read-only read probe."""

    name: str | None
    configured: bool
    url: str | None
    read: str
    failure_code: str | None
    failure_message: str | None


class GitConnectionReport(msgspec.Struct, frozen=True):
    """Versioned, secret-free Git connection diagnosis (spec 0010 §2, plan J5).

    ``push_pr`` is always ``unverified``: read access is reported separately
    from write capability, and no probe here can upgrade it.
    """

    schema_version: int
    project: str
    tool: GitToolStatus
    identity: GitIdentityStatus
    repository: GitRepositoryStatus
    remote: GitRemoteStatus
    push_pr: str
    blockers: tuple[str, ...]
    guidance: tuple[str, ...]


def _run_git(argv: list[str], *, timeout: float) -> subprocess.CompletedProcess[str]:
    """Execute one bounded read-only Git command (subprocess dependency boundary).

    ``GIT_TERMINAL_PROMPT=0`` keeps a missing credential helper from blocking
    on an interactive prompt; the timeout bounds every probe. Git's own
    credential resolution (SSH agent, credential helper) stays authoritative.
    """
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    return subprocess.run(
        argv,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
        env=env,
    )


def _probe(
    argv: list[str], *, timeout: float
) -> tuple[subprocess.CompletedProcess[str] | None, str | None]:
    """Run one probe; ``(None, reason)`` when the executable or time is missing."""
    try:
        return _run_git(argv, timeout=timeout), None
    except FileNotFoundError:
        return None, "missing"
    except subprocess.TimeoutExpired:
        return None, "timeout"


def _bounded(text: str) -> str:
    return text.strip()[:_MESSAGE_LIMIT]


def _redact_credentials(text: str) -> str:
    return _CREDENTIAL_URL.sub(r"\1[redacted]@", text)


def _stderr_summary(result: subprocess.CompletedProcess[str] | None) -> str:
    """One bounded, redacted stderr line from a failed Git command."""
    if result is None:
        return "the Git executable did not answer"
    lines = [line.strip() for line in (result.stderr or "").splitlines() if line.strip()]
    detail = lines[-1] if lines else f"git exited with code {result.returncode}"
    return _redact_credentials(detail)[:_MESSAGE_LIMIT]


def _config_value(project: Path, key: str) -> str | None:
    result, _error = _probe(
        ["git", "--no-optional-locks", "-C", str(project), "config", "--get", key],
        timeout=_LOCAL_TIMEOUT_SECONDS,
    )
    if result is None or result.returncode != 0:
        return None
    return _bounded(result.stdout) or None


def _probe_repository(project: Path, blockers: list[str]) -> GitRepositoryStatus:
    result, _error = _probe(
        ["git", "--no-optional-locks", "-C", str(project), "rev-parse", "--is-inside-work-tree"],
        timeout=_LOCAL_TIMEOUT_SECONDS,
    )
    inside = result is not None and result.returncode == 0 and result.stdout.strip() == "true"
    if not inside:
        blockers.append(
            "the project is not inside a Git work tree; clone or initialize the "
            "content repository first"
        )
        return GitRepositoryStatus(is_repository=False, branch=None, clean=None)
    branch_result, _error = _probe(
        [
            "git",
            "--no-optional-locks",
            "-C",
            str(project),
            "symbolic-ref",
            "--quiet",
            "--short",
            "HEAD",
        ],
        timeout=_LOCAL_TIMEOUT_SECONDS,
    )
    branch = None
    if branch_result is not None and branch_result.returncode == 0:
        branch = _bounded(branch_result.stdout) or None
    status_result, _error = _probe(
        ["git", "--no-optional-locks", "-C", str(project), "status", "--porcelain"],
        timeout=_LOCAL_TIMEOUT_SECONDS,
    )
    clean = None
    if status_result is not None and status_result.returncode == 0:
        clean = status_result.stdout.strip() == ""
    return GitRepositoryStatus(is_repository=True, branch=branch, clean=clean)


def _probe_remote(
    project: Path, remote: str | None, blockers: list[str], guidance: list[str]
) -> GitRemoteStatus:
    name = remote or "origin"
    url_result, _error = _probe(
        ["git", "--no-optional-locks", "-C", str(project), "remote", "get-url", name],
        timeout=_LOCAL_TIMEOUT_SECONDS,
    )
    if url_result is None or url_result.returncode != 0:
        blockers.append(
            f"remote {name!r} is not configured; add it with 'git remote add {name} <url>'"
        )
        return GitRemoteStatus(
            name=name,
            configured=False,
            url=None,
            read=READ_NOT_ATTEMPTED,
            failure_code=None,
            failure_message=None,
        )
    url = _bounded(_redact_credentials(url_result.stdout))
    # "--" ends option parsing: a remote name is untrusted input and must
    # never become an option such as --upload-pack (arbitrary execution).
    ls_result, ls_error = _probe(
        ["git", "--no-optional-locks", "-C", str(project), "ls-remote", "--", name],
        timeout=_REMOTE_TIMEOUT_SECONDS,
    )
    if ls_result is not None and ls_result.returncode == 0:
        guidance.append(
            "read access verified with ls-remote; push/PR access is unverified — "
            "no test push, branch or PR was attempted"
        )
        return GitRemoteStatus(
            name=name,
            configured=True,
            url=url,
            read=READ_SUCCESS,
            failure_code=None,
            failure_message=None,
        )
    if ls_result is None and ls_error == "timeout":
        code = "timeout"
        message = f"git ls-remote did not answer within {int(_REMOTE_TIMEOUT_SECONDS)}s"
    else:
        stderr = "" if ls_result is None else (ls_result.stderr or "")
        lowered = stderr.lower()
        code = (
            "authentication_failed"
            if any(marker in lowered for marker in _AUTH_FAILURE_MARKERS)
            else "probe_failed"
        )
        message = _stderr_summary(ls_result)
    blockers.append(f"remote read probe failed ({code}): {message}")
    guidance.append(_CREDENTIAL_GUIDANCE)
    return GitRemoteStatus(
        name=name,
        configured=True,
        url=url,
        read=READ_FAILED,
        failure_code=code,
        failure_message=message,
    )


def check_git_connection(project: str | Path, *, remote: str | None = None) -> GitConnectionReport:
    """Diagnose Git connectivity for one local project directory, read-only.

    Probes the Git executable/version, commit identity, repository state and
    the selected remote's readability through bounded read-only commands with
    ``--no-optional-locks``. A successful read probe never proves push or PR
    capability; ``push_pr`` stays ``unverified``. No repository, config,
    branch or remote is modified, and no credential value is read or echoed.
    """
    project_path = Path(project).expanduser()
    blockers: list[str] = []
    guidance: list[str] = []

    version_result, version_error = _probe(["git", "--version"], timeout=_LOCAL_TIMEOUT_SECONDS)
    if version_result is None or version_result.returncode != 0:
        reason = "was not found" if version_error == "missing" else "did not answer"
        blockers.append(f"the Git executable {reason}; install Git, then re-run this check")
        return GitConnectionReport(
            schema_version=REPORT_SCHEMA_VERSION,
            project=str(project_path),
            tool=GitToolStatus(available=False, version=None),
            identity=GitIdentityStatus(configured=False, user_name=None, user_email=None),
            repository=GitRepositoryStatus(is_repository=False, branch=None, clean=None),
            remote=GitRemoteStatus(
                name=remote,
                configured=False,
                url=None,
                read=READ_NOT_ATTEMPTED,
                failure_code=None,
                failure_message=None,
            ),
            push_pr=PUSH_PR_UNVERIFIED,
            blockers=tuple(blockers),
            guidance=(),
        )
    tool = GitToolStatus(available=True, version=_bounded(version_result.stdout))

    if not project_path.is_dir():
        blockers.append(f"project directory not found: {project_path}")
        identity = GitIdentityStatus(configured=False, user_name=None, user_email=None)
        repository = GitRepositoryStatus(is_repository=False, branch=None, clean=None)
        remote_status = GitRemoteStatus(
            name=remote,
            configured=False,
            url=None,
            read=READ_NOT_ATTEMPTED,
            failure_code=None,
            failure_message=None,
        )
    else:
        user_name = _config_value(project_path, "user.name")
        user_email = _config_value(project_path, "user.email")
        configured = user_name is not None and user_email is not None
        if not configured:
            blockers.append(
                "Git identity incomplete: set user.name and user.email "
                "(git config --global user.name 'Your Name'; "
                "git config --global user.email 'you@example.com')"
            )
        identity = GitIdentityStatus(
            configured=configured, user_name=user_name, user_email=user_email
        )
        repository = _probe_repository(project_path, blockers)
        if repository.is_repository:
            remote_status = _probe_remote(project_path, remote, blockers, guidance)
        else:
            remote_status = GitRemoteStatus(
                name=remote,
                configured=False,
                url=None,
                read=READ_NOT_ATTEMPTED,
                failure_code=None,
                failure_message=None,
            )

    return GitConnectionReport(
        schema_version=REPORT_SCHEMA_VERSION,
        project=str(project_path),
        tool=tool,
        identity=identity,
        repository=repository,
        remote=remote_status,
        push_pr=PUSH_PR_UNVERIFIED,
        blockers=tuple(blockers),
        guidance=tuple(guidance),
    )
