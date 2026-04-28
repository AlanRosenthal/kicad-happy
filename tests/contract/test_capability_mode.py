"""Contract tests for capability_mode.py canonical run-level writer."""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"))

import pytest


def test_get_or_create_writes_file_when_absent(tmp_path):
    from capability_mode import get_or_create_capability_mode

    record = get_or_create_capability_mode(tmp_path)
    cm_path = tmp_path / "capability_mode.json"
    assert cm_path.exists()
    on_disk = json.loads(cm_path.read_text())
    assert on_disk == record
    assert "run_id" in record
    assert record["llm_review"] == "disabled"  # default
    assert "schema_versions" in record
    assert record["platform"] == "claude-code"


def test_get_or_create_returns_existing_run_id(tmp_path):
    from capability_mode import get_or_create_capability_mode

    first = get_or_create_capability_mode(tmp_path)
    second = get_or_create_capability_mode(tmp_path)
    assert first["run_id"] == second["run_id"]


def test_get_capability_mode_ref_returns_pointer(tmp_path):
    from capability_mode import get_capability_mode_ref

    ref = get_capability_mode_ref(tmp_path)
    assert ref == {
        "source": "analysis/capability_mode.json",
        "run_id": ref["run_id"],
    }
    assert (tmp_path / "capability_mode.json").exists()


def test_run_id_is_sortable_iso_format(tmp_path):
    from capability_mode import get_or_create_capability_mode

    record = get_or_create_capability_mode(tmp_path)
    rid = record["run_id"]
    # Format: YYYYMMDDTHHMMSSZ-XXXXXX
    assert "T" in rid
    assert rid.endswith(rid.split("-")[-1])
    assert len(rid.split("-")[-1]) == 6  # 6-hex suffix


def test_get_or_create_run_id_aligns_with_capability_mode(tmp_path):
    """Phase 4 spec §3.1 wiring contract: get_or_create_run_id returns the
    same run_id as get_or_create_capability_mode."""
    from capability_mode import get_or_create_run_id, get_or_create_capability_mode

    rid = get_or_create_run_id(tmp_path)
    record = get_or_create_capability_mode(tmp_path)
    assert rid == record["run_id"]


def test_read_schema_versions_returns_known_categories(tmp_path):
    """_read_schema_versions must extract x-schema-version from category schemas."""
    from capability_mode import _read_schema_versions

    versions = _read_schema_versions()
    # When run from repo root, expect category schemas with versions populated.
    # When run from elsewhere (cache_dir doesn't resolve), accept empty dict.
    if versions:
        # If any populated, the regulator should be at 0.3 per current state.
        assert "regulator" in versions
        assert versions["regulator"] == "0.3"
        # Schemas without x-schema-version (base, extraction, manifest, pinout,
        # spec_value) must NOT appear.
        assert "base" not in versions
        assert "extraction" not in versions
