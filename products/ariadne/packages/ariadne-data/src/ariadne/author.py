"""Shared LLM completion and artifact-normalization helpers.

Git authoring uses ``normalize_layer_yaml`` for readable, revision-bound edits.
The retired document-ingest model-completion path (``_default_complete``) and
the classic bundle page gates (``_bundle_errors`` — C6, spec0035 §6) are
removed with their callers. Durable writes belong to Git proposals, not this
module.
"""

from __future__ import annotations

import yaml

from ariadne.context import (
    _load_frontmatter_meta as _load_frontmatter_meta,  # live re-export (authoring)
)

MAX_ROUNDS = 3


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
