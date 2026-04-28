"""Contract tests for finding_id auto-derivation in make_finding factory."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"))

from finding_schema import _derive_finding_id


def test_derive_finding_id_uses_detection_id_when_present():
    fid = _derive_finding_id(
        source="sch", rule_id="AM-001",
        detection_id="absolute_max:abc123def456",
        components=["U3"], nets=None, pins=None,
        summary="Pin 5 of U3 exceeds absolute max voltage",
    )
    assert fid == "sch:absolute_max:abc123def456"


def test_derive_finding_id_falls_back_to_components():
    fid = _derive_finding_id(
        source="sch", rule_id="AM-001",
        detection_id=None,
        components=["U3"], nets=None, pins=None,
        summary="Pin 5 of U3 exceeds absolute max voltage",
    )
    assert fid == "sch:AM-001:u3"


def test_derive_finding_id_falls_back_to_summary_hash_when_no_locators():
    fid = _derive_finding_id(
        source="sch", rule_id="GENERIC",
        detection_id=None, components=None, nets=None, pins=None,
        summary="A finding with no locators at all",
    )
    parts = fid.split(":")
    assert parts[0] == "sch"
    assert parts[1] == "GENERIC"
    assert len(parts[2]) == 12  # short hash


def test_derive_finding_id_is_deterministic():
    fid1 = _derive_finding_id(
        source="sch", rule_id="VM-001",
        detection_id=None,
        components=["U1"], nets=["VCC"], pins=None,
        summary="Voltage mismatch on VCC",
    )
    fid2 = _derive_finding_id(
        source="sch", rule_id="VM-001",
        detection_id=None,
        components=["U1"], nets=["VCC"], pins=None,
        summary="Voltage mismatch on VCC",
    )
    assert fid1 == fid2


def test_derive_finding_id_normalizes_whitespace_and_case():
    fid = _derive_finding_id(
        source="pcb", rule_id="TR-001",
        detection_id=None,
        components=["  U3  "], nets=None, pins=None,
        summary="Trace too narrow",
    )
    assert fid == "pcb:TR-001:u3"
