---
name: datasheets
description: Extract structured specifications from electronic component datasheet PDFs — pinouts, electrical characteristics, peripherals, topology, and features. Cache extractions per project for consumption by schematic and PCB analyzers. Primary consumer infrastructure for `kicad`, `emc`, `spice`, and `thermal` analyzers. Use this skill whenever the user asks to extract, verify, or read specs from a component datasheet; when analyzers need verified IC knowledge (EN pin thresholds, PG presence, USB peripheral speed); or when a review mentions datasheet coverage, extraction quality, or per-MPN specifications. Also triggers on "extract this datasheet", "what are the specs for MPN X", "verify datasheet extraction", or "check pin functions for part Y".
---

# Datasheets Skill

## Purpose

Extract structured, machine-readable specifications from component datasheet PDFs and make them available to analyzer skills. Works on whatever PDFs are downloaded under `<project>/datasheets/` (downloads are owned by distributor skills like `digikey`, `mouser`, `lcsc`, `element14`).

## Scope

This skill owns:
- **Extraction schemas** — canonical JSON structures for per-MPN specs. v1.4 ships 6 JSON Schema Draft 2020-12 schemas under `schemas/` (`base`, `pinout`, `spec_value`, `regulator`, `extraction`, `manifest`) plus 5 v1.4 category extensions (diode, transistor, opamp, mcu, crystal). v1.3 cache format (`EXTRACTION_VERSION` in `scripts/datasheet_extract_cache.py`) is still read for compat.
- **Typed access layer (v1.4)** — `datasheet_types/` package exposes `DatasheetFacts`, `SpecValue`, `Pin`, `Pinout`, `lookup()`, `best()`, `trusted()`, `has_data()`. Recommended for all new consumers.
- **PDF page selection** — heuristics to pick pages most likely to contain pinouts, e-chars, applications, SPICE models.
- **Quality scoring** — v1.4 uses a three-dimension rubric (pinout completeness, base completeness, category-extension completeness, 0–100 scale). v1.3 5-dimension weighted rubric still applies to legacy caches.
- **Consumer APIs** — `scripts/datasheet_lookup.py` for v1.4 typed access; `scripts/datasheet_features.py` for the v1.3 dict-shaped helpers (`get_regulator_features`, `get_mcu_features`, `get_pin_function`) — the v1.3 helpers dual-read v1.4 caches and translate to v1.3 dict shape for legacy detector code. Sunset planned for v1.6.
- **Verification** — `datasheet_verify.py` (v1.3, schema-vs-usage cross-check) plus `datasheet_verify_v14_extraction` (v1.4, power_domain references resolve, recommended ≤ absolute, regulator pin references exist).

## Non-goals

- **No PDF downloading.** That is owned by distributor skills (`digikey`, `mouser`, `lcsc`, `element14`).
- **No global library.** Each project's extractions live in `<project>/datasheets/extracted/`. There is no shared cross-project cache.

## Cache location

```
<project>/
  design.kicad_sch
  datasheets/
    TPS61023DRLR.pdf        # downloaded by distributor skills
    extracted/
      manifest.json         # extraction manifest (legacy name: index.json)
      TPS61023DRLR.json     # structured extraction (this skill's output)
```

## Reference guides

- `references/extraction-schema.md` — canonical schema, every field defined
- `references/field-extraction-guide.md` — how to find each field in datasheets from common vendors (TI, ST, NXP, Espressif, Microchip)
- `references/quality-scoring.md` — rubric details, score thresholds
- `references/consumer-api.md` — how kicad/emc/spice/thermal consume extractions
- `references/cache-layout.md` — v1.4 cache directory convention (per-MPN files, `_families/` reservation, staleness rules)

## Entry-point scripts

- `scripts/datasheet_extract_cache.py` — v1.3 cache manager, resolver, indexer
- `scripts/datasheet_page_selector.py` — page selection heuristics (used by both v1.3 and v1.4 pipelines)
- `scripts/datasheet_score.py` — v1.3 extraction quality scoring
- `scripts/datasheet_verify.py` — cross-check extraction vs schematic usage (v1.3 + v1.4 `verify_v14_extraction` mode)
- `scripts/datasheet_lookup.py` — **v1.4** typed `lookup(mpn) → DatasheetFacts` facade with staleness detection
- `scripts/datasheet_features.py` — v1.3 consumer helper API (dual-reads v1.4 caches via `_derive_*_v14` translators)
- `scripts/plan_extraction.py` — **v1.4** orchestration plan generator (Phase 3 extraction pipeline)
- `scripts/merge_results.py` — **v1.4** per-task result validator + merger
- `datasheet_types/` — **v1.4** typed access layer package (`DatasheetFacts`, `SpecValue`, `Pin`, `Pinout`, `lookup`, `best`, `trusted`, `has_data`)

## Extraction workflow

**v1.4 pipeline (current, used for all new extractions):**
1. `plan_extraction.py` builds an orchestration plan JSON.
2. Scout subagent inspects the PDF (TOC, headings) and emits per-MPN scout audit file.
3. Category extractor prompts (base, pinout, regulator, …) run per Phase 2 dispatcher recipe.
4. `merge_results.py` validates per-task result files against schemas and merges into `<project>/datasheets/extracted/<MPN>.json`.
5. Three-dimension quality score lives at `facts.extraction.quality_score`.
6. Consumers query via `lookup(mpn, cache_dir)` or via the v1.3 compat helpers in `datasheet_features.py`.

**v1.3 legacy pipeline (read-only in v1.4):**
1. User runs an analyzer or requests extraction.
2. Skill checks the cache (`<project>/datasheets/extracted/<MPN>.json`).
3. On cache miss / stale / low score: Claude reads selected PDF pages and extracts structured data.
4. Extraction is scored; if score ≥ 6.0, cached.
5. Consumers query via `datasheet_features.py`.

## When to trigger this skill

- **Immediately after downloading datasheets** via `sync_datasheets_digikey.py`, `sync_datasheets_lcsc.py`, or equivalent. Without extraction, IC-aware checks (VM-001 rail voltage, PS-001 power-good, PR-004 USB, DP-002 USB speed classification) fall back to heuristics on unknown ICs.
- **Before running analyzers on a new project** where datasheets are present but `datasheets/extracted/` is empty — the analyzers won't produce the extractions themselves.
- **When a review flags low trust level** due to missing manufacturer evidence: extracting the ICs referenced by power regulators, MCUs, and high-speed peripherals typically flips `trust_level: low` → `mixed` or `high`.
- **When a user asks for pin verification** ("verify U1 pin names match datasheet") — this skill's cached extraction is the authoritative source.
