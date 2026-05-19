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


if __name__ == "__main__":
    sys.exit(main())
