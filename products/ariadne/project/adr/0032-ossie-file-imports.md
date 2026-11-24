---
status: proposed
---

# ADR-0032: Optional Ossie converters and file exchange

[Spec 0041](../../../../project/specs/2026-11-24-0041-automatic-authoring.md)
uses local files as the interchange boundary. Native Ossie exports enter the
pinned [ADR-0028](0028-ossie-03-semantic-format.md) format directly; optional
converter extras translate other inputs before the same all-or-nothing draft
validation. Imports neither grant source access nor serve calculations.

File exchange is chosen over embedding NVIDIA auto-ontology or pulling from its
running server. It reuses conversion without adding a server dependency,
network credentials or a second semantic format to Ariadne.
