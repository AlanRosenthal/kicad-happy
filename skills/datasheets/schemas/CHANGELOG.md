# Datasheet v2 Schemas — CHANGELOG

Per-schema semver-lite versioning. Rules:

- **Additive within minor.** Adding an optional field → minor bump (0.3 → 0.4, 1.0 → 1.1). Consumers tolerate missing optional fields. Cached extractions remain valid.
- **Breaking = major bump.** Renaming, removing, or type-changing an existing field → major bump (0.3 → 1.0, 1.0 → 2.0). Cached extractions for that section flagged stale; re-extraction required for consumers gated on `min_schema >= new_major`.
- **Stale one section ≠ stale whole MPN.** A base→2.0 bump doesn't invalidate the regulator extension's cached values.
- **Pinout is flagged `still-calibrating`** through v1.4. The shape may shift with real-corpus feedback before v1.5 commits to strict additive-only discipline.

---

## scout — 1.0 (2026-04-25, Phase 3a)

Fat-scout output: `{mpn, metadata, categories, extraction_pages, quality_verdict}`. Identifies datasheet characteristics, target category extensions, per-task page lists, and a quality verdict gating extraction dispatch.

## plan — 1.0 (2026-04-25, Phase 3a)

Orchestration plan written by `plan_extraction.py`, consumed by the dispatcher and `merge_results.py`. Shape: `{plan_version, mpn, pdf_path, pdf_sha256, cache_dir, scout_ref, tasks[], execution: {started_at, completed_at, outcomes[]}}`. Each task carries `task_id`, `subagent_role`, `tier`, `schema`, `prompt_template`, `pages`, `depends_on`, `status`, `result_ref`.

## base — 1.0 (2026-04-19, v1.4)

Initial version.

Shape: `{family, description, package, thermal, absolute_max, recommended_operating, esd, moisture_sensitivity, compliance, pinout, pin_relationships}`. `absolute_max`, `recommended_operating`, `esd`, and `thermal` are objects keyed by parameter name → `SpecValue[]` (see spec §4). `pinout` is a `$ref` to `pinout.schema.json`.

## pinout — 1.0 (2026-04-19, v1.4) — still-calibrating

Initial version. Pin shape: `{numbers[], name, type, subtype, description, power_domain, alt_functions[], is_5v_tolerant, absolute_max, recommended, drive_strength, notes, evidence}`. Type vocabulary mirrors KiCad ERC pin types.

Flagged `x-still-calibrating: true` — shape may shift before v1.5.

## spec_value — 1.0 (2026-04-19, v1.4)

Initial version. `{min, typ, max, unit, condition, notes, evidence: {page, section, confidence, method}}`. Canonical SI units only. Always serialized inside a list (one-element list for single-value specs).

## regulator — 0.3 (2026-04-19, v1.4)

Initial version. Category extension for voltage regulators. Flat topology enum per spec §7 (`ldo|buck|boost|buck_boost|sepic|flyback|charge_pump|isolated`). Optional SpecValue[] fields for vin_range, vout_range, iout_max, reference_voltage, cin_min, cout_min, inductor_range, switching_freq, dropout, psrr, line_regulation, load_regulation. `stability_conditions` + `sequencing` nested objects feed SV-001 and ST-001.

Version 0.3 (not 1.0) because the field set may still shift — the first real extractions against diverse parts (LDO vs buck vs boost) may prompt adjustments. Promoted to 1.0 once v1.4 corpus re-extraction validates the shape.

## extraction — 1.0 (2026-04-19, v1.4)

Initial version. Top-level per-MPN file envelope: `{schema_version, source, extraction, base, categories, <per-category>}`. `source.family_ref` and `source.sha256` enable Tier 1 dedup; `categories[]` lists the active extensions.

## manifest — 1.0 (2026-04-19, v1.4)

Initial version. `datasheets/manifest.json` shape covering both legacy `extractions` index (v1.3 compat) and new `pdfs` SHA-dedup section (Tier 1).
