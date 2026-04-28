"""Contract tests for severity tuning matrix + _apply_severity_tuning impl."""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"))

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
TUNING_PATH = REPO_ROOT / "skills" / "kicad" / "review" / "severity_tuning.json"


def test_tuning_file_validates_against_schema():
    from jsonschema import Draft202012Validator
    schema = json.loads((REPO_ROOT / "skills" / "kicad" / "review" / "schemas"
                          / "severity_tuning.schema.json").read_text())
    data = json.loads(TUNING_PATH.read_text())
    Draft202012Validator(schema).validate(data)


def test_tuning_includes_all_phase4_detectors():
    """Spec §4.4: 11 rule entries (XT-001..005 share one entry under XT-001)."""
    data = json.loads(TUNING_PATH.read_text())
    expected = {"AM-001", "OV-001", "TJ-001", "FT-001", "PM-001", "EX-001",
                 "PU-001", "LR-001", "XT-001", "FS-001", "VM-001"}
    assert set(data["rules"].keys()) == expected


def test_apply_tuning_returns_base_when_no_design_context():
    from finding_schema import _apply_severity_tuning
    assert _apply_severity_tuning("AM-001", "warning", None) == "warning"


def test_apply_tuning_floor_does_not_lower_severity():
    """AM-001 hobby floor 'warning' must not lower base severity 'error'."""
    from finding_schema import _apply_severity_tuning
    dc = {"environment": "hobby"}
    result = _apply_severity_tuning("AM-001", "error", dc)
    assert result == "error"


def test_apply_tuning_floor_raises_info_to_warning():
    """AM-001 hobby floor 'warning' raises base severity 'info' up to 'warning'."""
    from finding_schema import _apply_severity_tuning
    dc = {"environment": "hobby"}
    result = _apply_severity_tuning("AM-001", "info", dc)
    assert result == "warning"


def test_apply_tuning_delta_walks_warning_to_error():
    """OV-001 has +1 delta on automotive; warning -> error."""
    from finding_schema import _apply_severity_tuning
    dc = {"environment": "automotive"}
    result = _apply_severity_tuning("OV-001", "warning", dc)
    assert result == "error"


def test_apply_tuning_caps_at_max():
    """OV-001 tuning_max_severity is 'error'; cannot escalate above."""
    from finding_schema import _apply_severity_tuning
    dc = {"environment": "automotive"}
    # Already at error; +1 delta should cap at error (not synthetic 'critical')
    result = _apply_severity_tuning("OV-001", "error", dc)
    assert result == "error"


def test_apply_tuning_ignores_unknown_rule_id():
    from finding_schema import _apply_severity_tuning
    dc = {"environment": "medical"}
    result = _apply_severity_tuning("UNKNOWN-999", "warning", dc)
    assert result == "warning"  # unknown rules pass through unchanged
