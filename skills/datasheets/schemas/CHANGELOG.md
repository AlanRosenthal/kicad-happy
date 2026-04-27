# Datasheet v2 Schemas — CHANGELOG

Per-schema semver-lite versioning. Rules:

- **Additive within minor.** Adding an optional field → minor bump (0.3 → 0.4, 1.0 → 1.1). Consumers tolerate missing optional fields. Cached extractions remain valid.
- **Breaking = major bump.** Renaming, removing, or type-changing an existing field → major bump (0.3 → 1.0, 1.0 → 2.0). Cached extractions for that section flagged stale; re-extraction required for consumers gated on `min_schema >= new_major`.
- **Stale one section ≠ stale whole MPN.** A base→2.0 bump doesn't invalidate the regulator extension's cached values.
- **Pinout is flagged `still-calibrating`** through v1.4. The shape may shift with real-corpus feedback before v1.5 commits to strict additive-only discipline.

---

## transistor.schema.json v1.0 — 2026-04-27

Initial release. Phase 3b (extraction breadth). Fields cover BJT (NPN/PNP), MOSFET (N/P-channel), JFET, IGBT discrete transistors. Field union from 2N3904 (MCC NPN BJT, TO-92) + IRLML6344 (IR/Infineon N-MOSFET, SOT-23) datasheet review.

Required: `transistor_type` (enum). All other fields nullable. BJT-vs-FET encoded as null fields per inactive type (no `oneOf` discriminator) — schema accepts a part with all FET fields populated and all BJT fields null, or vice versa. The prompt's hard rules document this exclusion explicitly.

`pin_assignment` is a closed object with 6 nullable string fields (`base_pin`, `collector_pin`, `emitter_pin`, `gate_pin`, `drain_pin`, `source_pin`). For BJT/IGBT, populate base/collector/emitter; for FET/JFET, populate gate/drain/source. Pin-resolution against `base.pinout` is registered as the empty tuple in `_PIN_FIELDS_BY_CATEGORY["transistor"]` — the nested object's pin-string fields are not yet validated against pinout. v1.5 may add nested-object pin-resolution.

`hfe`, `id_max`, `power_dissipation`, `vce_sat`, `rds_on` accept multiple SpecValues per part disambiguated via condition string (different test currents, gate voltages, or temperatures).

`thermal_resistance` follows the diode-established convention: nested object with `rtheta_ja` / `rtheta_jc` / `rtheta_jl` nullable SpecValue lists (K/W or °C/W).

`package.body_mm` follows the diode-established convention: nested `{length, width, height}` (no `_mm` suffix on inner fields; aligns with base.schema.json's pre-existing shape).

**spec_value.schema.json amendments (required by transistor field set):**
- Added `null` to `unit` type (dimensionless quantities — `hfe` current gain has no SI unit).
- Added `"C"` (coulombs) to `unit` enum (gate charge fields `qg`, `qgd`).
Both are additive non-breaking changes; existing cached extractions remain valid.

---

## diode.schema.json v1.0 — 2026-04-27

Initial release. Phase 3b (extraction breadth). Fields cover signal, switching, Schottky, zener, TVS, rectifier, bridge, and varicap diodes. Field union from 1N4148 (Vishay signal switching, DO-35) + MBRS540T3G (ON Semi Schottky power, SMC) datasheet review.

Required: `diode_type` (enum). All other fields nullable to accommodate type-specific characteristics:
- `vz` only for zeners
- `trr` typically null for slow rectifiers/zeners
- `cd` most relevant for varicaps and signal/switching diodes
- `breakdown_voltage` separate from `vr_max` (1N4148 specs both at 100V; MBRS540T3G doesn't spec breakdown explicitly)

**Field-union additions vs. design-spec field list** (per Decision 10, schema covers union of both MVP MPNs' fields): `breakdown_voltage`, `tj_max`, and the third `thermal_resistance.rtheta_jl` sub-field (junction-to-lead) were added during datasheet read of 1N4148 + MBRS540T3G — they were not in the original spec field list but are real datasheet-published parameters worth capturing. Spec deviation is licensed by the field-union methodology.

`if_max` and `vr_max` accept multiple SpecValues per part disambiguated via condition string (continuous / average / repetitive peak; VRRM / VR / VRWM).

`thermal_resistance` is a nested object with three nullable sub-fields (`rtheta_ja`, `rtheta_jc`, `rtheta_jl` — all SpecValue lists, K/W). Through-hole parts typically have only `rtheta_ja`; SMD parts often have both `rtheta_jl` and `rtheta_ja`.

`package.body_mm` is a NESTED object `{length, width, height}` (Phase 3b option A convention — first new schema using this shape; inner field names align with `base.schema.json`'s pre-existing body_mm shape, no `_mm` suffix). Symmetric across categories (transistor/opamp/mcu/crystal will adopt same shape in subsequent tasks).

Pin-resolution: diodes have no pin-reference fields; `_PIN_FIELDS_BY_CATEGORY["diode"]` is the empty tuple (already set in Task 2).

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
