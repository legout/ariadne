"""Shared LLM completion and artifact-normalization helpers.

Git authoring uses ``normalize_layer_yaml`` for readable, revision-bound edits;
document ingestion uses ``_default_complete`` for its optional LLM path. Durable
writes belong to Git proposals, not this module.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, cast

import yaml

from ariadne.context import (
    _bundle_errors as _bundle_errors,
)
from ariadne.context import (
    _load_frontmatter_meta as _load_frontmatter_meta,
)

ENV_PATH = Path(os.environ.get("ARIADNE_ENV", "/home/volker/coding/ariadne/.env"))
MAX_ROUNDS = 3


def _load_env(path: Path = ENV_PATH) -> None:
    """Load KEY=VALUE lines into os.environ without overriding existing vars."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def _default_complete(messages: list[dict[str, str]]) -> str:
    """One OpenAI-compatible chat completion for document ingestion."""
    _load_env()
    api_key = os.environ.get("OPENAI_API_KEY")
    model = os.environ.get("OPENAI_MODEL")
    if not api_key or not model:
        raise RuntimeError(
            f"OPENAI_API_KEY/OPENAI_MODEL not set; expected in {ENV_PATH} "
            "(or the environment) — never commit secrets"
        )
    from openai import OpenAI  # pyright: ignore[reportMissingImports]

    client = OpenAI(base_url=os.environ.get("OPENAI_BASE_URL") or None, api_key=api_key)
    response = client.chat.completions.create(
        model=model,
        messages=cast("Any", messages),
        temperature=0.2,
    )
    return response.choices[0].message.content or ""


class _LayerDumper(yaml.SafeDumper):  # type: ignore[no-any-unimported]
    """Use readable literal blocks for multiline strings."""


def _block_str_representer(dumper: _LayerDumper, data: str):  # type: ignore[no-any-unimported]
    style = "|" if "\n" in data else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style=style)


_LayerDumper.add_representer(str, _block_str_representer)


def normalize_layer_yaml(content: str) -> str:
    """Re-emit mapping YAML with multiline SQL as reviewable literal blocks."""
    try:
        doc = yaml.safe_load(content)
    except yaml.YAMLError:
        return content
    if not isinstance(doc, dict):
        return content
    return yaml.dump(
        doc,
        Dumper=_LayerDumper,
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=True,
        width=4096,
    )
