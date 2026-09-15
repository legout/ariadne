"""Deterministic validation: real Datus compile of staged OSI models (ticket #4).

``validate(staging_dir)`` compiles every model under
``<staging>/semantic_layer/models/`` with the datus-semantic-osi adapter
(mechanism per docs/research/datus-spike.md §5: Python import, compile-only,
no db_config) and returns a :class:`ValidationResult`. Severity ``warning``
issues are pass-through (spike §3.2 — the intended gotcha pattern
``CASE WHEN <dimension> ...`` triggers an advisory lint); only ``error``
severity, load/schema exceptions, or a failed SQL dry-run of a listed metric
count as compile failures. The returned error messages are the feedback the
author loop replays into the next LLM round.

CLI::

    python -m ariadne.validate staging/    # exit 0 = compiles, 1 = errors printed
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ValidationResult:
    ok: bool
    errors: list[str] = field(default_factory=list)


def _models_dir(staging_dir: str | Path) -> Path:
    return Path(staging_dir) / "semantic_layer" / "models"


def validate(staging_dir: str | Path) -> ValidationResult:
    """Compile the staged OSI models; warnings pass through, errors are captured."""
    try:
        from datus_semantic_osi.adapter import DatusOSIAdapter
        from datus_semantic_osi.config import DatusOSIConfig
    except ImportError as exc:  # keep the failure actionable for the author loop
        return ValidationResult(
            False,
            [
                "datus-semantic-osi is not importable "
                "(install 'datus-semantic-osi[metricflow]' on Python 3.12): "
                f"{exc}"
            ],
        )

    async def _compile():
        adapter = DatusOSIAdapter(
            DatusOSIConfig(semantic_models_path=str(_models_dir(staging_dir)))
        )
        result = await adapter.validate_semantic()
        errors = [
            issue.message
            for issue in result.issues
            if getattr(issue, "severity", "error") == "error"
        ]
        if not result.valid and not errors:  # failed without a graded issue: keep everything
            errors = [issue.message for issue in result.issues]
        if not errors:
            # Lowering check: validate_semantic can pass a model whose metrics
            # still fail to lower to SQL; compile each one for real.
            for metric in await adapter.list_metrics():
                await adapter.query_metrics(
                    metrics=[metric.name], dimensions=[], dry_run=True
                )
        return errors

    try:
        errors = asyncio.run(_compile())
    except Exception as exc:
        return ValidationResult(False, [f"compile failed: {type(exc).__name__}: {exc}"])
    return ValidationResult(not errors, errors)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m ariadne.validate",
        description="Compile staged OSI semantic models with Datus (exit 0/1).",
    )
    parser.add_argument("staging_dir", nargs="?", default="staging")
    args = parser.parse_args(argv)
    result = validate(args.staging_dir)
    if result.ok:
        print(f"ok: staged OSI models under {args.staging_dir} compile")
        return 0
    for error in result.errors:
        print(f"error: {error}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
