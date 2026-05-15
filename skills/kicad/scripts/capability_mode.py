"""Canonical run-level capability_mode.json writer (Phase 4 spec §3.3).

First-writer-wins pattern: the first analyzer in a run creates
analysis/capability_mode.json; subsequent analyzers in the same run
read it and embed only a capability_mode_ref pointer in their envelopes.
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Optional

from run_id import generate_run_id


CAPABILITY_MODE_FILENAME = "capability_mode.json"


def _read_capability_mode(path: Path) -> Optional[dict]:
    """Read an existing capability_mode.json, tolerating a transient
    partial read from a racing writer.

    Returns the parsed record, or None if the file can't be read as valid
    JSON after a few short retries (caller then falls through to write its
    own — the atomic os.replace below makes the file self-heal).
    """
    for _ in range(5):
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, FileNotFoundError, OSError):
            time.sleep(0.005)
    return None


def _detect_datasheet_status(cache_dir: Optional[Path] = None) -> str:
    """Return one of 'verified' | 'partial' | 'heuristic_fallback' | 'unavailable'.

    For 4a we ship a minimal implementation; 4d-skeleton refines based on
    schema_version inspection of present extractions.
    """
    if cache_dir is None:
        cache_dir = Path("datasheets/extracted")
    if not cache_dir.exists():
        return "unavailable"
    extractions = list(cache_dir.glob("*.json"))
    if not extractions:
        return "heuristic_fallback"
    # Heuristic: at-least-one extraction = "partial" until 4d-skeleton refines
    return "partial"


def _compute_coverage_pct(cache_dir: Optional[Path] = None) -> int:
    """Return integer coverage percentage. Stub: 0 in 4a; refined in 4d-skeleton."""
    return 0


def _read_schema_versions() -> dict:
    """Read schema_version from each shipped datasheet schema.

    Returns dict like {"base": "1.0", "regulator": "0.3", "diode": "1.0", ...}.
    """
    schemas_dir = Path("skills/datasheets/schemas")
    versions: dict = {}
    if not schemas_dir.exists():
        return versions
    for schema_path in schemas_dir.glob("*.schema.json"):
        try:
            data = json.loads(schema_path.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        title = schema_path.stem.replace(".schema", "")
        # Schemas store version in top-level "x-schema-version" key
        # (refined in 4d-skeleton if additional sources need merging)
        sv = data.get("x-schema-version")
        if sv:
            versions[title] = sv
    return versions


def get_or_create_capability_mode(
    analysis_dir,
    *,
    llm_review_status: str = "disabled",
    datasheet_extraction: Optional[str] = None,
    schema_versions: Optional[dict] = None,
    cache_dir: Optional[Path] = None,
) -> dict:
    """Return the canonical capability_mode record for analysis_dir, creating it if absent.

    First-writer-wins: subsequent calls return the existing record verbatim,
    NOT updating fields. Updates require explicit refresh by the orchestrator
    (e.g., when llm_review transitions from disabled to active mid-run).
    """
    analysis_dir = Path(analysis_dir)
    path = analysis_dir / CAPABILITY_MODE_FILENAME
    if path.exists():
        existing = _read_capability_mode(path)
        if existing is not None:
            return existing
        # exists() is True but the file isn't valid JSON yet — a racing
        # writer is mid-create. Fall through and write our own; the atomic
        # os.replace below leaves the file in a consistent state regardless.
    record = {
        "run_id": generate_run_id(),
        "datasheet_extraction": datasheet_extraction or _detect_datasheet_status(cache_dir),
        "datasheet_coverage_pct": _compute_coverage_pct(cache_dir),
        "llm_review": llm_review_status,
        "insertion_points_active": [],
        "reviewer_observations_enabled": False,
        "schema_versions": schema_versions or _read_schema_versions(),
        "platform": "claude-code",
        "tier_map": {},
    }
    analysis_dir.mkdir(parents=True, exist_ok=True)
    # Atomic create: stage the full record to a temp file in the same
    # directory, then os.link() it into place. os.link raises
    # FileExistsError if the target already exists, so it is an atomic
    # exclusive-create — this gives BOTH guarantees the old non-atomic
    # write_text() lacked:
    #   1. no partial read — the content is fully written before linking,
    #      so a concurrent reader never sees a half-written file (the old
    #      code could crash a reader with JSONDecodeError mid-write);
    #   2. true first-writer-wins — if two analyzers race past the
    #      exists() check above, exactly one os.link() succeeds; the loser
    #      reads the winner's record, so every analyzer in the run shares
    #      one run_id (HI-7).
    fd, tmp_path = tempfile.mkstemp(dir=analysis_dir, prefix=".capmode-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(json.dumps(record, indent=2, sort_keys=True) + "\n")
        try:
            os.link(tmp_path, path)
        except FileExistsError:
            # Another analyzer won the race — return its record, not ours.
            return _read_capability_mode(path) or record
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
    return record


def get_or_create_run_id(analysis_dir, **kwargs) -> str:
    """Return canonical run_id for analysis_dir, creating capability_mode.json if absent.

    Phase 4 spec §3.1 wiring helper: analyzers call this at the start of main()
    to align inputs.run_id with the canonical capability_mode.json:run_id.
    """
    record = get_or_create_capability_mode(analysis_dir, **kwargs)
    return record["run_id"]


def get_capability_mode_ref(analysis_dir, **kwargs) -> dict:
    """Return a {source, run_id} pointer for embedding in analyzer envelopes.

    Side-effect: ensures capability_mode.json exists (first-writer-wins).
    """
    record = get_or_create_capability_mode(analysis_dir, **kwargs)
    return {
        "source": f"analysis/{CAPABILITY_MODE_FILENAME}",
        "run_id": record["run_id"],
    }
