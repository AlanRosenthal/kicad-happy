"""Detector-side helpers for Phase 4 lookup() integration + design_context reading.

Used by 4b upgraded detectors and 4c new detectors to consume v1.4
datasheet facts via the Phase 2 Consumer API. Soft-fallback semantics
per Phase 4 spec §5.1: lookup() returning None falls back to heuristic.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional


def get_facts(mpn, cache_dir=None):
    """Return DatasheetFacts for mpn, or None on cache miss / stale / below-gate.

    Soft-fallback gate: detector callers check `if facts is None:` and fall
    back to heuristic. Trust-gate filtering happens at field level via
    facts.best(field, trust_gate=...).
    """
    if not mpn:
        return None
    try:
        from datasheet_types import lookup
    except ImportError:
        return None
    try:
        return lookup(mpn, cache_dir=cache_dir)
    except Exception:
        return None


def read_design_context(analysis_dir):
    """Return the design_context.json dict from analysis_dir, or None if absent."""
    analysis_dir = Path(analysis_dir)
    path = analysis_dir / "design_context.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None
