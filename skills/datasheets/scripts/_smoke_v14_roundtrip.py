#!/usr/bin/env python3
"""v1.4 cache round-trip smoke test.

Builds a minimal synthetic analysis dict referencing an IC with MPN
LM2596-ADJ, plants the canonical v1.4 example extraction at
<tmpdir>/datasheets/extracted/LM2596-ADJ.json, and calls
run_datasheet_verification(). The pre-rc.3 behavior is that
_load_extraction() rejects the v1.4 cache as "low quality" (reads
meta.extraction_score, gets default 0, fails 6.0 threshold), returns
None, then verify_decoupling crashes on None.get("application_circuit").

Expected behavior post-rc.3 fix: no crash, returns a dict with
findings[] (possibly empty — legacy verifier short-circuits on v1.4
caches because v1.3-shape keys are absent) and summary.

Exit code 0 = pass, 1 = fail (any exception or wrong return shape).
"""

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
DS_SCRIPTS = REPO_ROOT / "skills" / "datasheets" / "scripts"
EXAMPLE_FIXTURE = REPO_ROOT / "skills" / "datasheets" / "examples" / "lm2596-adj.json"

sys.path.insert(0, str(DS_SCRIPTS))


def build_synthetic_analysis() -> dict:
    """Minimal analysis dict referencing an IC with MPN LM2596-ADJ."""
    return {
        "file": "/tmp/fake.kicad_sch",
        "components": [
            {
                "reference": "U1",
                "type": "ic",
                "value": "LM2596-ADJ",
                "mpn": "LM2596-ADJ",
                "pin_nets": {"1": "VIN", "2": "OUT", "3": "GND", "4": "FB", "5": "ON_OFF"},
            },
            {"reference": "C1", "type": "capacitor", "value": "100nF", "parsed_value": 100e-9},
            {"reference": "C2", "type": "capacitor", "value": "10uF", "parsed_value": 10e-6},
        ],
        "nets": {
            "VIN": {"pins": [{"component": "U1"}, {"component": "C1"}, {"component": "C2"}]},
            "OUT": {"pins": [{"component": "U1"}]},
            "GND": {"pins": [{"component": "U1"}, {"component": "C1"}, {"component": "C2"}]},
            "FB": {"pins": [{"component": "U1"}]},
            "ON_OFF": {"pins": [{"component": "U1"}]},
        },
        "rail_voltages": {"VIN": 12.0, "OUT": 5.0},
    }


def main() -> int:
    if not EXAMPLE_FIXTURE.exists():
        print(f"FAIL: fixture missing: {EXAMPLE_FIXTURE}", file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        cache_dir = tmp_path / "datasheets" / "extracted"
        cache_dir.mkdir(parents=True)
        shutil.copy(EXAMPLE_FIXTURE, cache_dir / "LM2596-ADJ.json")

        from datasheet_verify import run_datasheet_verification

        analysis = build_synthetic_analysis()
        try:
            result = run_datasheet_verification(analysis, project_dir=str(tmp_path))
        except AttributeError as exc:
            print(f"FAIL: AttributeError on v1.4 cache (rc.2 regression): {exc}", file=sys.stderr)
            return 1
        except Exception as exc:
            print(f"FAIL: unexpected exception: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1

        if not isinstance(result, dict):
            print(f"FAIL: result is not a dict: {type(result).__name__}", file=sys.stderr)
            return 1
        if "findings" not in result or "summary" not in result:
            print(f"FAIL: result missing required keys: {sorted(result.keys())}", file=sys.stderr)
            return 1
        if not isinstance(result["findings"], list):
            print(f"FAIL: findings is not a list: {type(result['findings']).__name__}", file=sys.stderr)
            return 1

        ics_with_ext = result["summary"].get("ics_with_extractions", 0)
        if ics_with_ext != 1:
            print(
                f"FAIL: expected ics_with_extractions=1 (LM2596-ADJ should pass v1.4 trust gate), "
                f"got {ics_with_ext}",
                file=sys.stderr,
            )
            return 1

        print(
            f"PASS: v1.4 round-trip OK. "
            f"findings={len(result['findings'])} "
            f"ics_checked={result['summary'].get('ics_checked')} "
            f"ics_with_extractions={ics_with_ext}"
        )
        return 0


def test_placement_sniff() -> int:
    """Test that verify_v14_extraction flags absolute_max entries citing
    non-stress-rating sections (the USBLC6 failure mode).
    """
    from datasheet_verify import verify_v14_extraction

    # Synthetic v1.4 extraction with the USBLC6-style misplacement:
    # entries citing "Table 2. Electrical characteristics" placed in absolute_max.
    extraction = {
        "schema_version": "1.0",
        "source": {"local_path": "fake.pdf", "sha256": "deadbeef"},
        "extraction": {"quality_score": 77},
        "base": {
            "pinout": [],
            "recommended_operating": {},
            "absolute_max": {
                # CORRECT: cites stress-rating section
                "TJ_max": [{
                    "min": None, "max": 150, "typ": None, "unit": "°C",
                    "condition": "Junction temperature",
                    "evidence": {"section": "7.1 Absolute Maximum Ratings", "page": 5},
                }],
                # WRONG: cites Table 2 (electrical chars), should be flagged
                "VBR": [{
                    "min": 6.0, "max": None, "typ": None, "unit": "V",
                    "condition": "Breakdown voltage",
                    "evidence": {"section": "Table 2. Electrical characteristics", "page": 4},
                }],
                "VF_max": [{
                    "min": None, "max": 1.1, "typ": None, "unit": "V",
                    "condition": "Forward voltage at IF=10mA",
                    "evidence": {"section": "Table 2. Electrical characteristics", "page": 4},
                }],
            },
        },
        "categories": [],
    }

    issues = verify_v14_extraction(extraction)
    placement_issues = [
        i for i in issues if "absolute_max" in i.get("path", "") and "section" in i.get("path", "")
    ]

    if len(placement_issues) != 2:
        print(
            f"FAIL: expected 2 placement-sniff issues (VBR + VF_max), "
            f"got {len(placement_issues)}: {placement_issues}",
            file=sys.stderr,
        )
        return 1

    paths = {i["path"] for i in placement_issues}
    expected = {
        "base.absolute_max.VBR[0].evidence.section",
        "base.absolute_max.VF_max[0].evidence.section",
    }
    if paths != expected:
        print(f"FAIL: unexpected paths. got {paths}, expected {expected}", file=sys.stderr)
        return 1

    # TJ_max cites an Absolute Maximum Ratings section — must NOT be flagged
    tj_flagged = any("TJ_max" in i["path"] for i in placement_issues)
    if tj_flagged:
        print(f"FAIL: TJ_max (correctly placed) was wrongly flagged", file=sys.stderr)
        return 1

    print("PASS: placement-sniff flags Table 2 entries, leaves Absolute Max section alone")
    return 0


if __name__ == "__main__":
    rc1 = main()
    rc2 = test_placement_sniff()
    sys.exit(rc1 | rc2)
