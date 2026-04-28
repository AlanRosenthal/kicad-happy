# Design Context Subagent Prompt — SCAFFOLD (4d-active fills in)

> **Status:** Phase 4d-skeleton scaffold. Final prompt content lands in 4d-active (Task 31). This stub exists so the dispatcher and merge pipeline can validate end-to-end without LLM dispatch.

## Inputs

You will receive:
- `analysis/schematic.json` (component types, BOM list, net counts)
- `.kicad-happy.json` (if present — user-declared design intent)

## Task

Produce `analysis/design_context.json` conforming to `skills/kicad/review/schemas/design_context.schema.json`.

Closed-set fields only:
- `design_category`: one of {mcu_dev_board, motor_controller, power_supply, sensor_node, audio, rf_frontend, industrial_io, general}
- `environment`: one of {hobby, consumer, industrial, automotive, medical, aerospace, unspecified}
- `compliance_targets`: list of strings (well-known compliance marks like "AEC-Q100", "IEC 62368")
- `user_declared_intent`: verbatim from `.kicad-happy.json` `design_intent.description` (or null)
- `confidence`: high | medium | low (your confidence in the inference)
- `evidence`: free-text explaining the inference
- `resolution`: inferred_only | user_override | agree

## Resolution rules

If the user declared `design_category` or `environment` in `.kicad-happy.json`:
- Emit triple `{inferred, declared, effective}` for that field.
- `effective = declared` (user always wins).
- `resolution = "user_override"` if inferred ≠ declared; `"agree"` if they match.

Otherwise:
- Emit plain string.
- `resolution = "inferred_only"`.

(Final scaffold content — TBD in 4d-active. v1.4 ships skeleton only per spec §7.1.)
