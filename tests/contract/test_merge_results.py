"""Unit tests for merge_results.py (Phase 3a)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "skills/datasheets/scripts/merge_results.py"
FIX = REPO / "tests/fixtures/datasheets"
PLAN_FIX = FIX / "plan-lm2596-adj.example.json"
SCOUT_FIX = FIX / "scout-lm2596-adj.example.json"
REG_RESULT_FIX = FIX / "result-regulator-complete.example.json"
SCHEMA_DIR = REPO / "skills/datasheets/schemas"
EXTRACTION_SCHEMA = SCHEMA_DIR / "extraction.schema.json"


def _build_registry() -> Registry:
    """Build a referencing Registry so $ref between schemas resolves."""
    registry = Registry()
    for schema_path in SCHEMA_DIR.glob("*.schema.json"):
        schema = json.loads(schema_path.read_text())
        uri = schema.get("$id")
        if uri:
            registry = registry.with_resource(uri, Resource.from_contents(schema))
    return registry


def _build_base_result(task_id: str = "base") -> dict:
    """Minimal base result that satisfies base.schema.json."""
    return {
        "task_id": task_id,
        "schema_version": "1.0",
        "status": "complete",
        "extracted_at": "2026-04-25T11:00:00Z",
        "model_tier": "B",
        "model_id": "claude-sonnet-4-6",
        "data": {
            "family": "step-down switching regulator",
            "package": {
                "code": "TO-263-5",
                "pin_count": 5,
                "pitch_mm": None,
                "body_mm": None,
                "thermal_pad": True,
                "evidence": {
                    "page": 1,
                    "section": "Features",
                    "confidence": "high",
                    "method": "prose",
                },
            },
            "thermal": {},
            "absolute_max": {},
            "recommended_operating": {},
            "esd": {},
            "moisture_sensitivity": None,
            "compliance": [],
            "pinout": [],
            "pin_relationships": [],
        },
    }


def _build_pinout_result() -> dict:
    return {
        "task_id": "pinout",
        "schema_version": "1.0",
        "status": "complete",
        "extracted_at": "2026-04-25T11:00:00Z",
        "model_tier": "A",
        "model_id": "claude-opus-4-7",
        "data": [
            {
                "numbers": ["1"],
                "name": "VIN",
                "type": "power_in",
                "subtype": None,
                "description": "Input voltage",
                "power_domain": "VIN",
                "alt_functions": [],
                "is_5v_tolerant": None,
                "absolute_max": None,
                "recommended": None,
                "drive_strength": None,
                "notes": None,
                "evidence": {
                    "page": 3,
                    "section": "Pin Configuration",
                    "confidence": "high",
                    "method": "table",
                },
            }
        ],
    }


@pytest.fixture
def workdir(tmp_path):
    cache = tmp_path / "datasheets" / "extracted"
    cache.mkdir(parents=True)
    plan = json.loads(PLAN_FIX.read_text())
    plan["cache_dir"] = str(cache)
    (cache / "LM2596-ADJ.plan.json").write_text(json.dumps(plan, indent=2))
    (cache / "LM2596-ADJ.scout.json").write_text(SCOUT_FIX.read_text())
    (cache / "LM2596-ADJ.base.result.json").write_text(
        json.dumps(_build_base_result(), indent=2)
    )
    (cache / "LM2596-ADJ.pinout.result.json").write_text(
        json.dumps(_build_pinout_result(), indent=2)
    )
    (cache / "LM2596-ADJ.regulator.result.json").write_text(REG_RESULT_FIX.read_text())
    return tmp_path, cache


def _run(*args):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
    )


def test_merge_writes_extraction_json(workdir):
    tmp, cache = workdir
    res = _run("LM2596-ADJ", "--cache-dir", str(cache))
    assert res.returncode == 0, res.stderr
    out = json.loads((cache / "LM2596-ADJ.json").read_text())
    assert out["source"]["mpn"] == "LM2596-ADJ"
    assert out["base"]["package"]["code"] == "TO-263-5"
    assert out["regulator"]["topology"] == "buck"
    assert "regulator" in out["categories"]


def test_merged_extraction_validates_against_schema(workdir):
    tmp, cache = workdir
    _run("LM2596-ADJ", "--cache-dir", str(cache))
    out = json.loads((cache / "LM2596-ADJ.json").read_text())
    schema = json.loads(EXTRACTION_SCHEMA.read_text())
    registry = _build_registry()
    validator = Draft202012Validator(schema, registry=registry)
    errors = sorted(validator.iter_errors(out), key=lambda e: list(e.absolute_path))
    assert errors == [], "\n".join(
        f"{list(e.absolute_path)}: {e.message}" for e in errors
    )


def test_merge_records_outcomes_in_plan(workdir):
    tmp, cache = workdir
    _run("LM2596-ADJ", "--cache-dir", str(cache))
    plan = json.loads((cache / "LM2596-ADJ.plan.json").read_text())
    by = {o["task_id"]: o for o in plan["execution"]["outcomes"]}
    assert by["base"]["final_status"] == "complete"
    assert by["regulator"]["final_status"] == "complete"
    assert plan["execution"]["completed_at"] is not None


def test_merge_writes_quality_score_field(workdir):
    tmp, cache = workdir
    _run("LM2596-ADJ", "--cache-dir", str(cache))
    out = json.loads((cache / "LM2596-ADJ.json").read_text())
    assert "quality_score" in out["extraction"]
    assert (
        out["extraction"]["quality_score"] is None
        or 0 <= out["extraction"]["quality_score"] <= 100
    )
