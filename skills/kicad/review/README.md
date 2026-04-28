# `skills/kicad/review/` — Layer 2 LLM Review Sub-component

This is an internal sub-component of the kicad skill. It is NOT a standalone skill (no nested SKILL.md — confirmed unsupported across Claude Code, Codex, Gemini CLI). Referenced from `skills/kicad/SKILL.md` as a progressive-disclosure link.

## Purpose

Layer 2 review runs after deterministic Layer 1 analyzers (`analyze_*.py`) complete. It produces *tagged annotations* on findings — never mutating Layer 1 output. Stripping `llm_*` fields recovers byte-identical Layer 1 baseline (HI-3).

See: `docs/superpowers/specs/2026-04-27-phase-4-layer2-review-and-detector-upgrades-design.md` §4 + §7.

## Structure

| Path | Purpose |
|------|---------|
| `prompts/design_context.md` | Subagent prompt: read schematic + BOM + design intent, emit design_context.json |
| `prompts/reviewer.md` | Subagent prompt: read findings + design context + extractions, emit review_annotations.json |
| `schemas/design_context.schema.json` | JSON Schema for design context output |
| `schemas/review_annotations.schema.json` | JSON Schema for review annotations |
| `schemas/severity_tuning.schema.json` | JSON Schema validating `severity_tuning.json` |
| `scripts/build_review_plan.py` | Emits plan JSON with `task_type: "review"` (extends Phase 3 plan dispatcher) |
| `scripts/merge_annotations.py` | Validates + applies overlays to raw analyzer JSONs → `analysis/merged/<analyzer>.json` |
| `scripts/validate_review.py` | Standalone CLI for review_annotations.json validation |
| `scripts/run_phase4_exercise.py` | Orchestrates the end-to-end Phase 4 fixture exercise (4d-active) |
| `severity_tuning.json` | Central tuning matrix consumed by `make_finding()` factory |
| `fixtures/*.example.json` | Round-trip fixtures for schema contract tests |

## Hard invariants enforced

See spec §8 — HI-1 through HI-9. Most relevant:
- **HI-2:** `merge_annotations.py` only writes the `llm_review` sibling field; never touches detector-owned fields.
- **HI-3:** Strip-LLM round-trip is byte-identical to raw input.
- **HI-6:** `reviewer_observations[]` lives in `review_annotations.json`, never merged into `findings[]`.
- **HI-8:** Suppression authority limits enforced at merge time.

## v1.4 deliverable status

- Active: insertion points A, B, C, D (per spec §15).
- Skeleton-only: insertion point E (novel findings) — schema + tagging ship; prompt minimal; config default disabled. Activates in v1.5 after corpus calibration.
