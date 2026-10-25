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


def _ssh_batch_shell_command(shell_command: str) -> str | None:
    """Force BatchMode on one shell-form SSH command without changing it.

    ``GIT_SSH_COMMAND``/``core.sshCommand`` are interpreted by the shell
    (git(1)), so the command string is preserved verbatim apart from
    inserting ``-oBatchMode=yes`` immediately after the program token —
    OpenSSH keeps the first obtained value, so the option also wins over a
    later conflicting one, while quoting and shell expansion stay intact.
    Only a plain ``ssh``/``…/ssh`` program token is recognized; anything
    else (quoted programs, env prefixes, wrappers) returns ``None`` so the
    caller refuses instead of executing a changed command (review F4).
    """
    parts = shell_command.strip().split(None, 1)
    if not parts:
        return None
    program = parts[0]
    if Path(program).name != "ssh":
        return None
    if len(parts) == 1:
        return f"{program} {_SSH_BATCH_OPTION}"
    return f"{program} {_SSH_BATCH_OPTION} {parts[1]}"


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
    """Return the effective noninteractive SSH command, or ``None`` when the
    operator's selection cannot be made safely unattended (review F4).

    Git's documented precedence and forms are preserved (git(1)):
    ``GIT_SSH_COMMAND`` (shell-interpreted) overrides ``core.sshCommand``
    (same shell form) overrides ``GIT_SSH`` — a program pathname, not a
    shell command. A recognized ordinary OpenSSH pathname (``…/ssh``) keeps
    the SAME selected executable — never split or substituted — and gains
    BatchMode through Git's shell-form override with the pathname safely
    quoted; any other pathname (wrappers, paths with spaces) stays bounded-
    unavailable because no option can be added without changing it.
    """
    shell_command = env.get("GIT_SSH_COMMAND")
    if not shell_command and project is not None:
        result, _error = _probe(
            _git_argv(project, "config", "--get", "core.sshcommand"),
            timeout=_LOCAL_TIMEOUT_SECONDS,
            env=env,
        )
        if result is not None and result.returncode == 0:
            configured = (result.stdout or "").strip()
            if configured:
                shell_command = configured
    if shell_command:
        return _ssh_batch_shell_command(shell_command)
    program_path = env.get("GIT_SSH")
    if program_path:
        if Path(program_path).name == "ssh" and not any(
            character.isspace() for character in program_path
        ):
            return f"{shlex.quote(program_path)} {_SSH_BATCH_OPTION}"
        return None
    return f"ssh {_SSH_BATCH_OPTION}"


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


def _is_ssh_transport(raw_url: str) -> bool:
    """Whether the selected effective remote URL actually uses SSH.

    Recognizes ordinary ``ssh://`` URLs and scp-like ``[user@]host:path``
    forms. Any other scheme (https, git, file, …) and plain local paths are
    NOT SSH: incidental punctuation in a local path never scopes the SSH
    refusal to it (review F4).
    """
    stripped = raw_url.strip()
    if stripped.startswith("ssh://"):
        return True
    if "://" in stripped:
        return False
    head = stripped.split("/", 1)[0]
    if ":" not in head:
        return False
    host = head.split(":", 1)[0]
    return "@" in host or "." in host


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
    raw_url = (url_result.stdout or "").strip()
    url = _bounded(_sanitize_credentials(raw_url))
    if ssh_unavailable and _is_ssh_transport(raw_url):
        # SSH-specific inability refuses only a remote that actually uses
        # SSH; HTTPS/local/file transports proceed with their own credential
        # mechanisms (review F4).
        code = "probe_unavailable"
        message = (
            "the configured SSH selection cannot be made noninteractive for "
            "an unattended probe without changing it; check "
            "GIT_SSH_COMMAND/core.sshCommand/GIT_SSH"
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
        # Classification reads Git's stderr internally; the emitted message
        # is FIXED per category (review F3) — arbitrary stderr never leaves
        # this module. The safe URL projection is the only variable part.
        stderr = "" if ls_result is None else (ls_result.stderr or "")
        lowered = stderr.lower()
        if any(marker in lowered for marker in _AUTH_FAILURE_MARKERS):
            code = "authentication_failed"
            message = (
                f"authentication failed for remote {name!r} at {url}"
                " (Git diagnostic details: [redacted])"
            )
        else:
            code = "probe_failed"
            exit_status = ls_result.returncode if ls_result is not None else -1
            message = (
                "the read-only remote probe failed "
                f"(git exit code {exit_status}) for remote {name!r} at {url}"
            )
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
