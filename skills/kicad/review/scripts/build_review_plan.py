"""Build a Phase 4 review plan JSON for dispatcher consumption.

Emits a plan with task_type:"review" for design_context + reviewer subagents.
Per spec §4.5 + Q7-C: shared plan schema (extends Phase 3 extraction plan
shape additively); domain-specific result schemas + merge tools.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

def _now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_plan(analysis_dir):
    """Build a 2-task review plan: design_context + reviewer."""
    analysis_dir = Path(analysis_dir)
    now = _now_iso()
    plan = {
        "schema_version": "1.0",
        "plan_id": f"review-{now}",
        "created_at": now,
        "purpose": "phase4_review",
        "tasks": [
            {
                "task_id": "design_context",
                "task_type": "review",
                "tier": "B",
                "prompt_path": "skills/kicad/review/prompts/design_context.md",
                "result_path": str(analysis_dir / "design_context.json"),
                "result_schema": "skills/kicad/review/schemas/design_context.schema.json",
                "input_artifacts": [
                    str(analysis_dir / "schematic.json"),
                    ".kicad-happy.json",
                ],
            },
            {
                "task_id": "reviewer",
                "task_type": "review",
                "tier": "A",
                "prompt_path": "skills/kicad/review/prompts/reviewer.md",
                "result_path": str(analysis_dir / "review_annotations.json"),
                "result_schema": "skills/kicad/review/schemas/review_annotations.schema.json",
                "input_artifacts": [
                    str(analysis_dir / "schematic.json"),
                    str(analysis_dir / "pcb.json"),
                    str(analysis_dir / "emc.json"),
                    str(analysis_dir / "thermal.json"),
                    str(analysis_dir / "cross_analysis.json"),
                    str(analysis_dir / "design_context.json"),
                ],
                "depends_on": ["design_context"],
            },
        ],
    }
    return plan


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--analysis-dir", required=True, type=Path)
    p.add_argument("--output", type=Path)
    args = p.parse_args()
    plan = build_plan(args.analysis_dir)
    out = json.dumps(plan, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(out)
    else:
        print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
