# Ariadne project facts

## What this project is

TODO: one paragraph — what the database is about, who owns it, which questions
the governed metrics answer. The human-owned rules live in `data/seed_notes.md`;
served policy pages cite them.

## The ariadne skill

Load the ariadne skill (`ariadne-skill install` if absent) — it carries the
workflow and the grain rules. This file holds only project facts.

## Layout

| Directory | Role |
| :--- | :--- |
| `data/` | Inputs: the database(s), `data/seed_notes.md`, `data/docs/` source documents. |
| `staging/` | Authoring output awaiting human review — the only place agents write. |
| `context_layer/` | Served OKF bundle: policies, metrics, computations (promotion output). |
| `semantic_layer/` | Served OSI models: the governed metric definitions (promotion output). |

## Promotion gate

Served artifacts arrive ONLY by human promotion (`ariadne-promote`): agents never
write outside `staging/`, and anything staged with `status: review_needed` refuses
promotion until a human resolves it.
