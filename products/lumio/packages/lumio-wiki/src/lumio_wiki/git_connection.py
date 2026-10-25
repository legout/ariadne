"""Read-only Git connection diagnosis for the external-agent authoring journey.

Specification 0010 §2 (plan 0010 J5): guided setup reports the local Git
tool, identity, repository state and remote readability through bounded
read-only probes. A successful ``ls-remote`` proves READ access only — push
and pull-request capability stay explicitly ``unverified``; this module never
attempts a test push, branch or PR. Credential values are never read, and
credential-bearing URL material (userinfo, query, fragment) is redacted from
every diagnostic before it leaves this module. Probes are unattended: the
child never owns stdin, Git/SSH askpass prompts are suppressed, and the
effective SSH command (GIT_SSH_COMMAND > core.sshCommand > GIT_SSH) is
preserved while being forced noninteractive with BatchMode.
"""

from __future__ import annotations

import os
import re
import shlex
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

#: One whole URL token, so its query/fragment can be stripped (review F3).
_URL_TOKEN: Final[re.Pattern[str]] = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://[^\s'\"<>]+")

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

_SSH_BATCH_OPTION: Final[str] = "-oBatchMode=yes"


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


def _sanitize_credentials(text: str) -> str:
    """Redact credential material from any diagnostic text (review F3).

    URL userinfo becomes ``[redacted]`` and URL query/fragment components are
    dropped entirely; non-URL text (and scheme-less local paths) is kept.
    """

    def _strip_url(match: re.Match[str]) -> str:
        return match.group(0).split("?", 1)[0].split("#", 1)[0]

    redacted = _CREDENTIAL_URL.sub(r"\1[redacted]@", text)
    return _URL_TOKEN.sub(_strip_url, redacted)


def _bounded(text: str) -> str:
    return text.strip()[:_MESSAGE_LIMIT]


def _stderr_summary(result: subprocess.CompletedProcess[str] | None) -> str:
    """One bounded, sanitized stderr line from a failed Git command."""
    if result is None:
        return "the Git executable did not answer"
    lines = [line.strip() for line in (result.stderr or "").splitlines() if line.strip()]
    detail = lines[-1] if lines else f"git exited with code {result.returncode}"
    return _sanitize_credentials(detail)[:_MESSAGE_LIMIT]


def _ssh_batch_command(command: str) -> str | None:
    """Force BatchMode on one SSH command without discarding its selection.

    OpenSSH keeps the FIRST value for an option, so ``BatchMode=yes`` is
    inserted immediately after the program token, ahead of the operator's own
    options (identities, agents and custom flags are preserved). Returns
    ``None`` when the command cannot be split safely.
    """
    try:
        tokens = shlex.split(command)
    except ValueError:
        return None
    if not tokens:
        return None
    return shlex.join([tokens[0], _SSH_BATCH_OPTION, *tokens[1:]])


def _base_probe_env() -> dict[str, str]:
    """Unattended probe environment: no terminal, askpass or X prompts.

    Controls apply to the probe subprocess only — the process environment,
    Git configuration and ordinary credential helpers are never modified.
    """
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_ASKPASS"] = "echo"
    env["SSH_ASKPASS_REQUIRE"] = "never"
    env.pop("DISPLAY", None)
    return env


def _run_git(
    argv: list[str], *, timeout: float, env: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    """Execute one bounded read-only Git command (subprocess dependency boundary).

    ``stdin=DEVNULL`` keeps the child from ever owning the interactive
    terminal; the timeout bounds every probe. Git's own credential
    resolution (SSH agent, credential helper) stays authoritative.
    """
    return subprocess.run(
        argv,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
        env=env,
        stdin=subprocess.DEVNULL,
    )


def _probe(
    argv: list[str], *, timeout: float, env: dict[str, str]
) -> tuple[subprocess.CompletedProcess[str] | None, str | None]:
    """Run one probe; ``(None, reason)`` when the executable or time is missing."""
    try:
        return _run_git(argv, timeout=timeout, env=env), None
    except FileNotFoundError:
        return None, "missing"
    except subprocess.TimeoutExpired:
        return None, "timeout"


def _resolve_ssh_command(project: Path | None, env: dict[str, str]) -> str | None:
    """Return the effective SSH command, forced noninteractive (review F4).

    Resolution follows Git's documented precedence — ``GIT_SSH_COMMAND``
    overrides ``core.sshCommand`` overrides ``GIT_SSH`` — so an operator's
    selected command is extended with BatchMode, never discarded. Without a
    configured command, the ordinary ``ssh`` transport is used. ``None``
    means the configured command cannot be made safely unattended.
    """
    command = env.get("GIT_SSH_COMMAND")
    if not command and project is not None:
        result, _error = _probe(
            _git_argv(project, "config", "--get", "core.sshcommand"),
            timeout=_LOCAL_TIMEOUT_SECONDS,
            env=env,
        )
        if result is not None and result.returncode == 0:
            command = (result.stdout or "").strip()
    if not command:
        command = env.get("GIT_SSH")
    if not command:
        return f"ssh {_SSH_BATCH_OPTION}"
    return _ssh_batch_command(command)


def _git_argv(project: Path | None, *args: str) -> list[str]:
    """Build one probe argv: askpass-safe, lock-free, optionally repo-scoped.

    ``-c core.askPass=echo`` suppresses a configured interactive askpass for
    this invocation only (no Git configuration is modified); ``--`` before a
    remote name keeps untrusted names from becoming Git options.
    """
    argv = ["git", "-c", "core.askPass=echo", "--no-optional-locks"]
    if project is not None:
        argv += ["-C", str(project)]
    argv += list(args)
    return argv


def _config_value(project: Path, key: str, env: dict[str, str]) -> str | None:
    result, _error = _probe(
        _git_argv(project, "config", "--get", key),
        timeout=_LOCAL_TIMEOUT_SECONDS,
        env=env,
    )
    if result is None or result.returncode != 0:
        return None
    return _bounded(result.stdout) or None


def _probe_repository(
    project: Path, blockers: list[str], env: dict[str, str]
) -> GitRepositoryStatus:
    result, _error = _probe(
        _git_argv(project, "rev-parse", "--is-inside-work-tree"),
        timeout=_LOCAL_TIMEOUT_SECONDS,
        env=env,
    )
    inside = result is not None and result.returncode == 0 and result.stdout.strip() == "true"
    if not inside:
        blockers.append(
            "the project is not inside a Git work tree; clone or initialize the "
            "content repository first"
        )
        return GitRepositoryStatus(is_repository=False, branch=None, clean=None)
    branch_result, _error = _probe(
        _git_argv(project, "symbolic-ref", "--quiet", "--short", "HEAD"),
        timeout=_LOCAL_TIMEOUT_SECONDS,
        env=env,
    )
    branch = None
    if branch_result is not None and branch_result.returncode == 0:
        branch = _bounded(branch_result.stdout) or None
    status_result, _error = _probe(
        _git_argv(project, "status", "--porcelain"),
        timeout=_LOCAL_TIMEOUT_SECONDS,
        env=env,
    )
    clean = None
    if status_result is not None and status_result.returncode == 0:
        clean = status_result.stdout.strip() == ""
    return GitRepositoryStatus(is_repository=True, branch=branch, clean=clean)


def _probe_remote(
    project: Path,
    remote: str | None,
    blockers: list[str],
    guidance: list[str],
    env: dict[str, str],
    ssh_unavailable: bool,
) -> GitRemoteStatus:
    name = remote or "origin"
    url_result, _error = _probe(
        _git_argv(project, "remote", "get-url", name),
        timeout=_LOCAL_TIMEOUT_SECONDS,
        env=env,
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
    url = _bounded(_sanitize_credentials(url_result.stdout))
    if ssh_unavailable:
        code = "probe_unavailable"
        message = (
            "the configured SSH command cannot be made noninteractive for an "
            "unattended probe; check GIT_SSH_COMMAND/core.sshCommand"
        )
        blockers.append(f"remote read probe unavailable ({code}): {message}")
        guidance.append(_CREDENTIAL_GUIDANCE)
        return GitRemoteStatus(
            name=name,
            configured=True,
            url=url,
            read=READ_FAILED,
            failure_code=code,
            failure_message=message,
        )
    ls_result, ls_error = _probe(
        _git_argv(project, "ls-remote", "--", name),
        timeout=_REMOTE_TIMEOUT_SECONDS,
        env=env,
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
    the selected remote's readability through bounded, unattended, read-only
    commands. A successful read probe never proves push or PR capability;
    ``push_pr`` stays ``unverified``. No repository, config, branch or remote
    is modified, and no credential value is read or echoed.
    """
    project_path = Path(project).expanduser()
    blockers: list[str] = []
    guidance: list[str] = []

    env = _base_probe_env()
    ssh_command = _resolve_ssh_command(project_path if project_path.is_dir() else None, env)
    ssh_unavailable = ssh_command is None
    if ssh_command is not None:
        env["GIT_SSH_COMMAND"] = ssh_command

    version_result, version_error = _probe(
        _git_argv(None, "--version"),
        timeout=_LOCAL_TIMEOUT_SECONDS,
        env=env,
    )
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
        user_name = _config_value(project_path, "user.name", env)
        user_email = _config_value(project_path, "user.email", env)
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
        repository = _probe_repository(project_path, blockers, env)
        if repository.is_repository:
            remote_status = _probe_remote(
                project_path, remote, blockers, guidance, env, ssh_unavailable
            )
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
