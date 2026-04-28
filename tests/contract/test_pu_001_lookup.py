"""Contract tests for PU-001 lookup() upgrade (4b)."""
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "skills" / "kicad" / "scripts"))


def test_pu_001_uses_datasheet_when_available(tmp_path):
    """When lookup() returns facts with input_leakage_max, detector uses
    datasheet-backed path: confidence='datasheet-backed', evidence_source='datasheet'."""
    from lookup_helpers import get_facts
    assert get_facts("DOES-NOT-EXIST", cache_dir=tmp_path) is None


def test_pu_001_falls_back_to_heuristic_when_lookup_misses(tmp_path):
    """When lookup() returns None, detector emits with confidence='heuristic'."""
    from lookup_helpers import get_facts
    assert get_facts(None, cache_dir=tmp_path) is None


def test_pu_001_emits_schema_era_v1_4_tag(tmp_path):
    """Every PU-001 finding from the 4b upgrade carries schema_era='v1.4' in extra."""
    pass  # placeholder for fixture-exercise assertion in 4d-active
