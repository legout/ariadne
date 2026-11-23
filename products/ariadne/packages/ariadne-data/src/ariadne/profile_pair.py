"""The private profile pair of one project (spec 0040 §3.2.2, owner decision).

The Lumio-schema profile (``~/.config/ariadne/<uuid>.json``) stays exactly as the SDK
defines it. Ariadne's own settings live in the sibling ``<uuid>.ariadne.json``:
publication destination, default Visibility Scope and run-log defaults. Both files are
created atomically with mode 0600 (no chmod-after-write window); their paths are
recorded in ``.ariadne/profile.json`` so ``status`` and ``approve`` find them without
guessing. A missing or invalid sibling refuses, naming the file — never silent
defaults at approval time.
"""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from pathlib import Path

from ariadne import proposals

SIBLING_VERSION = 1
_KEYS = frozenset({"schema_version", "publication_destination", "visibility_scope", "run_log"})
_RUN_LOG_KEYS = frozenset({"enabled", "retention_days"})
RECORD_REL = proposals.ARIADNE_STATE_DIR / "profile.json"


class ProfileError(ValueError):
    """A missing or invalid private profile pair."""


def config_dir() -> Path:
    return Path.home() / ".config" / "ariadne"


def write_private(path: Path, text: str) -> None:
    """Publish ``text`` at ``path`` so a crash can never leave a partial file: write a temp
    file in the same directory created ``O_CREAT|O_EXCL`` with mode 0600 from the first byte,
    fsync it, then ``link`` it into place — which refuses if the target already exists (an
    existing file is never replaced)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.link(tmp, path)  # FileExistsError when the target exists: never replaces
    finally:
        tmp.unlink(missing_ok=True)
    proposals._fsync_path(path.parent)


def sibling_path(lumio_profile: Path) -> Path:
    return lumio_profile.with_name(f"{lumio_profile.stem}.ariadne.json")


def default_sibling(identifier: str) -> dict:
    return {
        "schema_version": SIBLING_VERSION,
        "publication_destination": str(
            Path.home() / ".local" / "share" / "ariadne" / "published" / identifier
        ),
        "visibility_scope": ["public"],
        "run_log": {"enabled": True, "retention_days": 90},
    }


def new_identifier() -> str:
    return str(uuid.uuid4())


def load_sibling(path: Path) -> dict:
    """The strictly validated Ariadne-owned settings (unknown keys refuse)."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ProfileError(
            f"{path}: the Ariadne private settings file is missing — re-run 'ariadne init' "
            "or restore it; approval never falls back to defaults"
        ) from None
    except (OSError, ValueError) as exc:
        raise ProfileError(f"{path}: unreadable Ariadne private settings ({exc})") from None
    if not isinstance(raw, dict) or set(raw) != _KEYS:
        raise ProfileError(
            f"{path}: the Ariadne private settings must have exactly the keys {sorted(_KEYS)}"
        )
    run_log = raw["run_log"]
    scope = raw["visibility_scope"]
    destination = raw["publication_destination"]
    if raw["schema_version"] != SIBLING_VERSION:
        raise ProfileError(f"{path}: schema_version must be {SIBLING_VERSION}")
    if not isinstance(destination, str) or not Path(destination).is_absolute():
        raise ProfileError(f"{path}: publication_destination must be an absolute path")
    if not (isinstance(scope, list) and scope and all(isinstance(s, str) and s for s in scope)):
        raise ProfileError(f"{path}: visibility_scope must be a non-empty list of strings")
    if (
        not isinstance(run_log, dict)
        or set(run_log) != _RUN_LOG_KEYS
        or not isinstance(run_log["enabled"], bool)
        or type(run_log["retention_days"]) is not int
        or run_log["retention_days"] < 1
    ):
        raise ProfileError(
            f"{path}: run_log must be {{enabled: bool, retention_days: positive int}}"
        )
    return raw


def record(project: Path, lumio_profile: Path, sibling: Path) -> None:
    """Record both paths in ``.ariadne/profile.json`` (atomic)."""
    path = project / RECORD_REL
    if path.exists():
        raise ValueError(f"{path}: a private profile record already exists — never replaced")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump({"lumio_profile": str(lumio_profile), "ariadne_settings": str(sibling)}, fh)
        fh.write("\n")
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def load(project: Path) -> dict:
    """The validated settings of ``project`` plus both recorded paths."""
    path = project / RECORD_REL
    try:
        rec = json.loads(path.read_text(encoding="utf-8"))
        lumio, sibling = Path(rec["lumio_profile"]), Path(rec["ariadne_settings"])
    except FileNotFoundError:
        raise ProfileError(
            f"{path}: no private profile is recorded for this project — run 'ariadne init'"
        ) from None
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ProfileError(f"{path}: unreadable profile record ({exc})") from None
    settings = load_sibling(sibling)
    if not lumio.is_file():
        raise ProfileError(f"{lumio}: the Lumio private profile is missing")
    return {**settings, "lumio_profile": str(lumio), "ariadne_settings": str(sibling)}
