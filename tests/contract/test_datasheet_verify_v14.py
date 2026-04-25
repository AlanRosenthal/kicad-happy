"""Unit tests for datasheet_verify.py v1.4 extensions (Phase 3a)."""

import json
from pathlib import Path

import pytest

import importlib.util
import sys

REPO = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "datasheet_verify_under_test",
    REPO / "skills/datasheets/scripts/datasheet_verify.py",
)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

verify_v14_extraction = mod.verify_v14_extraction


def _ok_extraction() -> dict:
    return {
        "schema_version": {"base": "1.0", "categories": {"regulator": "0.3"}},
        "base": {
            "recommended_operating": {
                "VIN": [{"min": 4.5, "max": 40, "unit": "V",
                         "evidence": {"page": 5, "section": "ROC", "confidence": "high", "method": "table"}}]
            },
            "absolute_max": {
                "VIN_max": [{"max": 45, "unit": "V",
                             "evidence": {"page": 5, "section": "Abs Max", "confidence": "high", "method": "table"}}]
            },
            "pinout": [
                {"numbers": ["1"], "name": "VIN", "type": "power_in", "subtype": None,
                 "description": None, "power_domain": "VIN", "alt_functions": [],
                 "is_5v_tolerant": None, "absolute_max": None, "recommended": None,
                 "drive_strength": None, "notes": None,
                 "evidence": {"page": 3, "section": "Pinout", "confidence": "high", "method": "table"}},
                {"numbers": ["4"], "name": "FB", "type": "input", "subtype": None,
                 "description": None, "power_domain": None, "alt_functions": [],
                 "is_5v_tolerant": None, "absolute_max": None, "recommended": None,
                 "drive_strength": None, "notes": None,
                 "evidence": {"page": 3, "section": "Pinout", "confidence": "high", "method": "table"}},
                {"numbers": ["5"], "name": "EN", "type": "input", "subtype": None,
                 "description": None, "power_domain": None, "alt_functions": [],
                 "is_5v_tolerant": None, "absolute_max": None, "recommended": None,
                 "drive_strength": None, "notes": None,
                 "evidence": {"page": 3, "section": "Pinout", "confidence": "high", "method": "table"}}
            ]
        },
        "categories": ["regulator"],
        "regulator": {
            "topology": "buck",
            "feedback_pin": "4",
            "enable_pin": "5",
            "power_good_pin": None
        }
    }


def test_clean_extraction_zero_findings():
    assert verify_v14_extraction(_ok_extraction()) == []


def test_unresolved_power_domain_flags_warning():
    e = _ok_extraction()
    e["base"]["pinout"][0]["power_domain"] = "VBUS"  # not in recommended_operating
    issues = verify_v14_extraction(e)
    assert any(i["path"] == "base.pinout[0].power_domain" and i["severity"] == "warning" for i in issues)


def test_recommended_max_above_absolute_max_flags_error():
    e = _ok_extraction()
    e["base"]["recommended_operating"]["VIN"][0]["max"] = 50  # > absolute 45
    issues = verify_v14_extraction(e)
    assert any(i["severity"] == "error" and "VIN" in i["path"] for i in issues)


def test_min_above_max_within_specvalue_flags_error():
    e = _ok_extraction()
    e["base"]["recommended_operating"]["VIN"][0]["min"] = 50
    e["base"]["recommended_operating"]["VIN"][0]["max"] = 40
    issues = verify_v14_extraction(e)
    assert any(i["severity"] == "error" and "min > max" in i["description"] for i in issues)


def test_unresolved_regulator_pin_reference_flags_error():
    e = _ok_extraction()
    e["regulator"]["feedback_pin"] = "99"  # not in pinout
    issues = verify_v14_extraction(e)
    assert any(i["severity"] == "error" and i["path"] == "regulator.feedback_pin" for i in issues)


def test_categories_array_lists_role_but_payload_missing_flags_error():
    e = _ok_extraction()
    del e["regulator"]
    issues = verify_v14_extraction(e)
    assert any(i["severity"] == "error" and "regulator" in i["description"] for i in issues)
