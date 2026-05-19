"""Datasheet verification bridge for kicad-happy.

Compares extracted datasheet specifications against actual schematic
connections. Produces findings for voltage violations, missing required
external components, and decoupling inadequacy.

Requires datasheets/extracted/ cache populated by the LLM extraction
pipeline (via sync_datasheets_digikey + Claude extraction).
"""

import json
import os
import re
import sys
from pathlib import Path

# Allow imports from same directory
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _load_extraction(extract_dir: str, mpn: str) -> dict:
    """Load extraction JSON for an MPN. Always returns dict; never None.

    Trust gate: low-quality extractions return {} (treated as "no extraction
    available" by callers). Two cache shapes supported:
    - v1.4: extraction.quality_score on 0-100 scale, threshold 60.
    - v1.3 legacy: meta.extraction_score on 0-10 scale, threshold 6.0.

    Returns {} for: missing dir, missing MPN, file not found, JSON parse
    error, OSError, or quality below threshold. Returns the parsed dict
    when the cache exists and passes the trust gate (or has no quality
    metadata at all — in that case we don't gate, let downstream decide).
    """
    if not extract_dir or not mpn:
        return {}

    # Preserve dots and hyphens — planner/merger write literal MPN-named
    # files (`ABM8G-106-12.000MHZ-T.json`), so the legacy positional path
    # MUST match what they wrote. Aligned with datasheet_lookup.sanitize_mpn
    # and the flag-mode regex in _cli_v14 below.
    sanitized = re.sub(r'[^A-Za-z0-9_.-]', '_', mpn.strip())

    # Direct file lookup
    path = os.path.join(extract_dir, f"{sanitized}.json")
    if os.path.isfile(path):
        try:
            with open(path) as f:
                extraction = json.load(f)
            return extraction if _passes_trust_gate(extraction) else {}
        except (json.JSONDecodeError, OSError):
            return {}

    # Manifest-based lookup (case-insensitive); try manifest.json, fall back
    # to legacy index.json.
    idx_path = os.path.join(extract_dir, "manifest.json")
    if not os.path.isfile(idx_path):
        idx_path = os.path.join(extract_dir, "index.json")
    if os.path.isfile(idx_path):
        try:
            with open(idx_path) as f:
                idx = json.load(f)
            for k, v in idx.get("extractions", {}).items():
                if k.upper() == sanitized.upper():
                    fname = v.get("file", "")
                    fpath = os.path.join(extract_dir, fname)
                    if os.path.isfile(fpath):
                        with open(fpath) as f:
                            extraction = json.load(f)
                        return extraction if _passes_trust_gate(extraction) else {}
        except (json.JSONDecodeError, OSError):
            pass

    return {}


def _passes_trust_gate(extraction: dict) -> bool:
    """Return True if extraction quality is acceptable (or unknown).

    v1.4: extraction.quality_score 0-100, threshold 60.
    v1.3: meta.extraction_score 0-10, threshold 6.0.
    No quality metadata at all: pass (don't gate; let downstream decide).
    """
    quality_v14 = (extraction.get("extraction") or {}).get("quality_score")
    if isinstance(quality_v14, (int, float)):
        return quality_v14 >= 60
    quality_v13 = (extraction.get("meta") or {}).get("extraction_score")
    if isinstance(quality_v13, (int, float)):
        return quality_v13 >= 6.0
    return True


def _resolve_extract_dir(project_dir: str) -> str:
    """Find the datasheets/extracted/ directory for a project."""
    candidates = [
        os.path.join(project_dir, "datasheets", "extracted"),
        os.path.join(os.path.dirname(project_dir), "datasheets", "extracted"),
    ]
    for c in candidates:
        if os.path.isdir(c):
            return c
    return ""


def _estimate_net_voltage(net_name: str, rail_voltages: dict) -> float:
    """Estimate the voltage on a net from rail_voltages or name parsing."""
    if not net_name:
        return None

    # Direct lookup in rail_voltages
    v = rail_voltages.get(net_name)
    if v is not None:
        return v

    # Parse from name: +3V3 → 3.3, +5V → 5.0, 12V0 → 12.0
    nu = net_name.upper().lstrip("+").rstrip("V")
    # VnnVn format: 3V3 → 3.3
    m = re.match(r'^(\d+)V(\d+)$', nu)
    if m:
        return float(f"{m.group(1)}.{m.group(2)}")
    # Plain voltage: 5V → 5.0, 12V → 12.0
    m = re.match(r'^(\d+\.?\d*)V?$', nu)
    if m:
        return float(m.group(1))

    return None


def verify_pin_voltages(components: list, nets: dict, extraction_dir: str,
                        rail_voltages: dict) -> list:
    """P1: Verify pin voltage boundaries against datasheet abs max / operating ranges.

    For each IC with an extraction, checks every pin's connected net voltage
    against the pin's voltage_abs_max and voltage_operating_max from the
    extraction.

    Returns list of finding dicts.
    """
    findings = []

    for comp in components:
        if comp.get("type") != "ic":
            continue
        ref = comp["reference"]
        mpn = comp.get("mpn") or comp.get("value", "")
        if not mpn or mpn == ref:
            continue

        extraction = _load_extraction(extraction_dir, mpn)
        if not extraction or not extraction.get("pins"):
            continue

        pin_nets = comp.get("pin_nets", {})
        if not pin_nets:
            continue

        # Build pin lookup from extraction: pin_number → pin_data
        ext_pins = {}
        for p in extraction["pins"]:
            pnum = str(p.get("number", ""))
            if pnum:
                ext_pins[pnum] = p

        for pin_num, net_name in pin_nets.items():
            ext_pin = ext_pins.get(pin_num)
            if not ext_pin:
                continue

            # Skip GND pins
            pin_type = (ext_pin.get("type") or "").lower()
            if pin_type in ("ground", "gnd"):
                continue

            v_abs_max = ext_pin.get("voltage_abs_max")
            v_op_max = ext_pin.get("voltage_operating_max")
            net_voltage = _estimate_net_voltage(net_name, rail_voltages)

            if net_voltage is None:
                continue

            pin_name = ext_pin.get("name", f"pin {pin_num}")

            # Check abs max violation
            if v_abs_max is not None and net_voltage > v_abs_max:
                findings.append({
                    "type": "pin_voltage_abs_max_exceeded",
                    "severity": "CRITICAL",
                    "ref": ref,
                    "mpn": mpn,
                    "pin_number": pin_num,
                    "pin_name": pin_name,
                    "net": net_name,
                    "net_voltage_V": net_voltage,
                    "abs_max_V": v_abs_max,
                    "margin_V": round(v_abs_max - net_voltage, 3),
                    "detail": (f"{ref} pin {pin_num} ({pin_name}) on {net_name} "
                               f"({net_voltage}V) exceeds absolute maximum "
                               f"({v_abs_max}V) by {net_voltage - v_abs_max:.2f}V"),
                })
            # Check operating range exceeded (warning, not critical)
            elif v_op_max is not None and net_voltage > v_op_max:
                margin_pct = (v_abs_max - net_voltage) / v_abs_max * 100 if v_abs_max else 0
                findings.append({
                    "type": "pin_voltage_operating_exceeded",
                    "severity": "HIGH" if margin_pct < 10 else "MEDIUM",
                    "ref": ref,
                    "mpn": mpn,
                    "pin_number": pin_num,
                    "pin_name": pin_name,
                    "net": net_name,
                    "net_voltage_V": net_voltage,
                    "operating_max_V": v_op_max,
                    "abs_max_V": v_abs_max,
                    "detail": (f"{ref} pin {pin_num} ({pin_name}) on {net_name} "
                               f"({net_voltage}V) exceeds recommended operating "
                               f"maximum ({v_op_max}V)"),
                })

    return findings


def verify_required_externals(components: list, nets: dict, extraction_dir: str,
                              comp_lookup: dict) -> list:
    """P1: Verify required external components per datasheet pin specs.

    Checks pins with 'required_external' field in extraction — these are
    pins where the datasheet says "connect X here" (bypass cap, pull-up,
    inductor, etc.). Verifies something appropriate is actually connected.

    Returns list of finding dicts.
    """
    findings = []

    for comp in components:
        if comp.get("type") != "ic":
            continue
        ref = comp["reference"]
        mpn = comp.get("mpn") or comp.get("value", "")
        if not mpn or mpn == ref:
            continue

        extraction = _load_extraction(extraction_dir, mpn)
        if not extraction or not extraction.get("pins"):
            continue

        pin_nets = comp.get("pin_nets", {})

        ext_pins = {}
        for p in extraction["pins"]:
            pnum = str(p.get("number", ""))
            if pnum:
                ext_pins[pnum] = p

        for pin_num, net_name in pin_nets.items():
            ext_pin = ext_pins.get(pin_num)
            if not ext_pin:
                continue

            required = ext_pin.get("required_external")
            if not required:
                continue

            pin_name = ext_pin.get("name", f"pin {pin_num}")
            pin_type = (ext_pin.get("type") or "").lower()

            # Skip ground pins (always connected)
            if pin_type in ("ground", "gnd"):
                continue

            # Check what's connected to this pin's net
            net_info = nets.get(net_name, {})
            net_pins = net_info.get("pins", []) if isinstance(net_info, dict) else []

            # Find other components on this net (excluding the IC itself)
            connected_refs = set()
            connected_types = set()
            for p in net_pins:
                c_ref = p.get("component", "")
                if c_ref and c_ref != ref:
                    connected_refs.add(c_ref)
                    c = comp_lookup.get(c_ref, {})
                    connected_types.add(c.get("type", ""))

            # Parse required_external for expected component types
            req_lower = required.lower()
            expected_types = set()
            if any(k in req_lower for k in ("cap", "capacitor", "decoupling", "bypass")):
                expected_types.add("capacitor")
            if any(k in req_lower for k in ("resistor", "pull-up", "pullup", "pull-down", "divider")):
                expected_types.add("resistor")
            if any(k in req_lower for k in ("inductor", "ferrite", "bead")):
                expected_types.update(("inductor", "ferrite_bead"))
            if any(k in req_lower for k in ("diode", "schottky")):
                expected_types.add("diode")

            if not expected_types:
                continue  # Can't parse requirement — skip

            # Check if any expected type is connected
            if not expected_types & connected_types:
                # Nothing matching the requirement is connected
                findings.append({
                    "type": "missing_required_external",
                    "severity": "HIGH",
                    "ref": ref,
                    "mpn": mpn,
                    "pin_number": pin_num,
                    "pin_name": pin_name,
                    "net": net_name,
                    "required": required,
                    "expected_types": sorted(expected_types),
                    "connected_types": sorted(connected_types),
                    "detail": (f"{ref} pin {pin_num} ({pin_name}): datasheet requires "
                               f"\"{required}\" but none found on net {net_name}"),
                })

    return findings


def _parse_cap_recommendation(text: str) -> dict:
    """Parse a capacitor recommendation string into structured requirements.

    Examples:
        "10uF ceramic, X5R or X7R" -> {min_farads: 10e-6, count: 1, dielectric: ["X5R","X7R"]}
        "22uF ceramic x2" -> {min_farads: 22e-6, count: 2}
        "100nF" -> {min_farads: 100e-9, count: 1}
    """
    from kicad_utils import parse_value

    result = {"min_farads": None, "count": 1, "dielectric": [], "max_distance_mm": None}

    if not text:
        return result

    text_lower = text.lower()

    # Extract count: "x2", "x3", "x 2"
    count_match = re.search(r'[x\u00d7]\s*(\d+)', text_lower)
    if count_match:
        result["count"] = int(count_match.group(1))

    # Extract distance: "within 10mm", "< 5mm"
    dist_match = re.search(r'within\s+(\d+\.?\d*)\s*mm', text_lower)
    if not dist_match:
        dist_match = re.search(r'<\s*(\d+\.?\d*)\s*mm', text_lower)
    if dist_match:
        result["max_distance_mm"] = float(dist_match.group(1))

    # Extract dielectric: X5R, X7R, C0G, NP0
    for d in ("X5R", "X7R", "X7S", "C0G", "NP0", "X6S"):
        if d.lower() in text_lower:
            result["dielectric"].append(d)

    # Extract capacitance value
    cap_match = re.search(r'(\d+\.?\d*)\s*(uF|\u00b5F|nF|pF|u|n|p)', text, re.IGNORECASE)
    if cap_match:
        val_str = cap_match.group(1) + cap_match.group(2)
        parsed = parse_value(val_str, component_type="capacitor")
        if parsed:
            result["min_farads"] = parsed

    return result


def verify_decoupling(components: list, nets: dict, extraction_dir: str,
                      comp_lookup: dict, parsed_values: dict) -> list:
    """P2: Verify per-IC decoupling against datasheet application circuit.

    For each IC with an extraction containing application_circuit.decoupling_cap
    or input_cap_recommended / output_cap_recommended, checks that the actual
    caps on power pins meet the requirements (count, value, type).

    Returns list of finding dicts.
    """
    findings = []

    for comp in components:
        if comp.get("type") != "ic":
            continue
        ref = comp["reference"]
        mpn = comp.get("mpn") or comp.get("value", "")
        if not mpn or mpn == ref:
            continue

        extraction = _load_extraction(extraction_dir, mpn)
        if not extraction or not extraction.get("application_circuit"):
            continue
        app_circuit = extraction["application_circuit"]

        pin_nets = comp.get("pin_nets", {})
        ext_pins = {str(p.get("number", "")): p for p in extraction.get("pins", [])}

        # Collect recommendations
        recommendations = []
        for key in ("input_cap_recommended", "output_cap_recommended", "decoupling_cap"):
            text = app_circuit.get(key)
            if text:
                recommendations.append((key, text, _parse_cap_recommendation(text)))

        if not recommendations:
            continue

        # Find power pins and their connected caps
        power_pin_nets = set()
        for pin_num, net_name in pin_nets.items():
            ep = ext_pins.get(pin_num)
            if ep:
                pt = (ep.get("type") or "").lower()
                direction = (ep.get("direction") or "").lower()
                if pt in ("power",) and direction in ("input", "output", "bidirectional"):
                    power_pin_nets.add(net_name)

        # Count caps on power nets
        caps_on_power = []
        for net_name in power_pin_nets:
            net_info = nets.get(net_name, {})
            for p in net_info.get("pins", []) if isinstance(net_info, dict) else []:
                c_ref = p.get("component", "")
                c = comp_lookup.get(c_ref, {})
                if c.get("type") == "capacitor" and c_ref != ref:
                    cap_val = parsed_values.get(c_ref, 0)
                    caps_on_power.append({
                        "ref": c_ref,
                        "value": c.get("value", ""),
                        "farads": cap_val,
                        "net": net_name,
                    })

        # Check each recommendation
        for key, text, req in recommendations:
            if req["min_farads"] is None:
                continue

            # Find matching caps (value >= recommended)
            matching = [c for c in caps_on_power if c["farads"] >= req["min_farads"] * 0.8]
            total_matching = len(matching)

            if total_matching < req["count"]:
                severity = "HIGH" if total_matching == 0 else "MEDIUM"
                findings.append({
                    "type": "decoupling_insufficient",
                    "severity": severity,
                    "ref": ref,
                    "mpn": mpn,
                    "requirement_key": key,
                    "requirement_text": text,
                    "required_count": req["count"],
                    "required_min_farads": req["min_farads"],
                    "actual_count": total_matching,
                    "actual_caps": [{"ref": c["ref"], "value": c["value"]} for c in caps_on_power],
                    "detail": (f"{ref} ({mpn}): datasheet recommends \"{text}\" "
                               f"but found {total_matching}/{req['count']} matching caps "
                               f"on power pins"),
                })

    return findings


def run_datasheet_verification(analysis: dict, project_dir: str = "") -> dict:
    """Run all datasheet verification checks.

    Args:
        analysis: Full schematic analysis JSON (from analyze_schematic.py)
        project_dir: Project directory for finding datasheets/extracted/

    Returns dict with:
        findings: list of verification findings
        summary: {ics_checked, ics_with_extractions, total_findings, by_severity}
    """
    components = analysis.get("components", [])
    nets = analysis.get("nets", {})
    rail_voltages = analysis.get("rail_voltages", {})
    parsed_values = {}
    comp_lookup = {}
    for c in components:
        ref = c.get("reference", "")
        comp_lookup[ref] = c
        pv = c.get("parsed_value")
        if isinstance(pv, (int, float)):
            parsed_values[ref] = pv
        elif isinstance(pv, dict):
            parsed_values[ref] = pv.get("value", 0)

    # Resolve extraction directory
    if not project_dir:
        src_file = analysis.get("file", "")
        if src_file:
            project_dir = os.path.dirname(os.path.abspath(src_file))
    extract_dir = _resolve_extract_dir(project_dir) if project_dir else ""

    if not extract_dir:
        return {"findings": [], "summary": {
            "ics_checked": 0, "ics_with_extractions": 0,
            "total_findings": 0, "by_severity": {},
            "note": "No datasheets/extracted/ directory found",
        }}

    # Count ICs with extractions
    ic_count = 0
    ic_with_ext = 0
    for c in components:
        if c.get("type") == "ic":
            ic_count += 1
            mpn = c.get("mpn") or c.get("value", "")
            if mpn and _load_extraction(extract_dir, mpn):
                ic_with_ext += 1

    # Run checks
    all_findings = []
    all_findings.extend(verify_pin_voltages(components, nets, extract_dir, rail_voltages))
    all_findings.extend(verify_required_externals(components, nets, extract_dir, comp_lookup))
    all_findings.extend(verify_decoupling(components, nets, extract_dir, comp_lookup, parsed_values))

    # Build severity summary
    by_severity = {}
    for f in all_findings:
        sev = f.get("severity", "INFO")
        by_severity[sev] = by_severity.get(sev, 0) + 1

    return {
        "findings": all_findings,
        "summary": {
            "ics_checked": ic_count,
            "ics_with_extractions": ic_with_ext,
            "total_findings": len(all_findings),
            "by_severity": by_severity,
        },
    }


# ---------------------------------------------------------------------------
# v1.4 extension: verify_v14_extraction (Phase 3a)
# ---------------------------------------------------------------------------

def _spec_max(sv_list):
    if isinstance(sv_list, list) and sv_list and isinstance(sv_list[0], dict):
        return sv_list[0].get("max")
    return None


def _spec_min(sv_list):
    if isinstance(sv_list, list) and sv_list and isinstance(sv_list[0], dict):
        return sv_list[0].get("min")
    return None


def _all_pin_numbers(pinout):
    nums = set()
    for pin in pinout or []:
        for n in pin.get("numbers", []) or []:
            nums.add(str(n))
    return nums


_PIN_FIELDS_BY_CATEGORY = {
    "regulator": ("feedback_pin", "compensation_pin", "enable_pin", "power_good_pin", "vin_pin", "vout_pin"),
    "diode": (),
    "transistor": (),  # pin_assignment is a nested object — checked separately if needed
    "opamp": ("shutdown_pin",),
    "mcu": ("reset_pin",),  # boot_pins is a list-of-objects, deferred to v1.5 if validation needed
    "crystal": (),
}


def verify_v14_extraction(extraction: dict) -> list[dict]:
    """Return inconsistencies in a v1.4 extraction JSON.

    Each finding: {path, severity ('warning'|'error'), description}.
    Empty list = clean.
    """
    issues: list[dict] = []
    base = extraction.get("base") or {}
    pinout = base.get("pinout") or []
    rec_op = base.get("recommended_operating") or {}
    abs_max = base.get("absolute_max") or {}

    # 1. power_domain references resolve to recommended_operating keys
    rec_keys = set(rec_op.keys())
    for i, pin in enumerate(pinout):
        pd = pin.get("power_domain")
        if pd is not None and pd not in rec_keys:
            issues.append({
                "path": f"base.pinout[{i}].power_domain",
                "severity": "warning",
                "description": f"power_domain {pd!r} does not resolve to a key in base.recommended_operating ({sorted(rec_keys)})",
            })

    # 2. min/max sanity within each SpecValue
    for block_name, block in (("recommended_operating", rec_op), ("absolute_max", abs_max)):
        for key, sv_list in (block or {}).items():
            if not isinstance(sv_list, list):
                continue
            for j, sv in enumerate(sv_list):
                if not isinstance(sv, dict):
                    continue
                lo, hi = sv.get("min"), sv.get("max")
                if lo is not None and hi is not None:
                    try:
                        if float(lo) > float(hi):
                            issues.append({
                                "path": f"base.{block_name}.{key}[{j}]",
                                "severity": "error",
                                "description": f"min > max ({lo} > {hi})",
                            })
                    except (TypeError, ValueError):
                        pass

    # 3. recommended.max <= absolute.max for matching parameter pairs (heuristic on key suffix)
    for rec_key, rec_list in rec_op.items():
        rec_hi = _spec_max(rec_list)
        if rec_hi is None:
            continue
        # Try exact match (rec key VIN ↔ abs_max key VIN_max), or same key in absolute_max
        candidates = [f"{rec_key}_max", rec_key]
        for cand in candidates:
            if cand not in abs_max:
                continue
            abs_hi = _spec_max(abs_max[cand])
            if abs_hi is None:
                continue
            try:
                if float(rec_hi) > float(abs_hi):
                    issues.append({
                        "path": f"base.recommended_operating.{rec_key}",
                        "severity": "error",
                        "description": f"recommended.max ({rec_hi}) exceeds absolute_max.{cand}.max ({abs_hi})",
                    })
            except (TypeError, ValueError):
                pass
            break

    # 4. category pin references resolve to pinout (registry-driven)
    pin_nums = _all_pin_numbers(pinout)
    for category, fields in _PIN_FIELDS_BY_CATEGORY.items():
        block = extraction.get(category)
        if not isinstance(block, dict) or block.get("_extraction_failed"):
            continue
        for f in fields:
            v = block.get(f)
            if v is None:
                continue
            if str(v) not in pin_nums:
                issues.append({
                    "path": f"{category}.{f}",
                    "severity": "error",
                    "description": f"references pin {v!r} which is not present in base.pinout ({sorted(pin_nums)})",
                })

    # 4b. absolute_max placement sniff — flag entries whose evidence.section
    # looks like an operating-point / characterization table. Catches the
    # "Table 2 electrical characteristics stuffed into absolute_max" failure
    # mode observed on USBLC6-2SC6 (SacMap rev2 first-project review,
    # 2026-05-19). Uses a denylist for known operating-point markers; a
    # section that contains stress markers ("absolute"/"stress"/"maximum
    # ratings") is allowed through even if it also contains operating
    # words (combined tables). Default is silent-pass on ambiguous names.
    _op_marker_re = re.compile(
        r'\b(electrical\s+characteristic|operating\s+condition|recommended\s+operating|dc\s+characteristic|ac\s+characteristic)',
        re.IGNORECASE,
    )
    _stress_marker_re = re.compile(
        r'\b(absolute|stress|maximum\s+rating)',
        re.IGNORECASE,
    )
    for key, sv_list in (abs_max or {}).items():
        if not isinstance(sv_list, list):
            continue
        for j, sv in enumerate(sv_list):
            if not isinstance(sv, dict):
                continue
            evidence = sv.get("evidence") or {}
            section = (evidence.get("section") or "").strip()
            if not section:
                continue  # no evidence to sniff — silent skip
            looks_operating = bool(_op_marker_re.search(section))
            looks_stress = bool(_stress_marker_re.search(section))
            if looks_operating and not looks_stress:
                issues.append({
                    "path": f"base.absolute_max.{key}[{j}].evidence.section",
                    "severity": "warning",
                    "description": (
                        f"absolute_max entry cites section {section!r}, which "
                        "looks like operating-point / characterization data "
                        "(no 'absolute'/'stress'/'maximum rating' keywords). "
                        "May be placed in the wrong slot."
                    ),
                })

    # 5. categories array consistency
    cats = extraction.get("categories") or []
    for cat in cats:
        payload = extraction.get(cat)
        if payload is None:
            issues.append({
                "path": f"categories[{cat!r}]",
                "severity": "error",
                "description": f"categories lists {cat!r} but top-level {cat} field is missing",
            })
        elif isinstance(payload, dict) and payload.get("_extraction_failed") is True:
            issues.append({
                "path": f"{cat}",
                "severity": "error",
                "description": f"category {cat!r} payload is the partial-merge sentinel: {payload.get('reason') or 'no reason given'}",
            })
        elif isinstance(payload, dict) and not payload:
            issues.append({
                "path": f"categories[{cat!r}]",
                "severity": "error",
                "description": f"categories lists {cat!r} but top-level {cat} field is an empty object",
            })
        elif isinstance(payload, list) and not payload:
            issues.append({
                "path": f"categories[{cat!r}]",
                "severity": "error",
                "description": f"categories lists {cat!r} but top-level {cat} field is an empty list",
            })

    return issues


def _cli_v14(argv: list[str] | None = None) -> int:
    """v1.4 verifier CLI.

    Two invocation shapes supported:

    1. Positional (original): ``datasheet_verify.py <extraction_path>``
    2. Flag-based (harness 4-check gate, Check 2):
       ``datasheet_verify.py --mpn <mpn> --extract-dir <dir> --self-consistency --json``

    Output shape:
        positional → {"issues": [...], "count": N}
        flag-based with --json → {"violations": [...], "count": N, "mpn": ..., "extract_dir": ...}

    Exit codes:
        0  no issues
        1  ≥1 issue
        2  CLI / I/O error (missing file, bad JSON, missing required flags)
    """
    import argparse, json as _json, re as _re, sys as _sys
    from pathlib import Path as _Path

    ap = argparse.ArgumentParser(
        description="Verify v1.4 extraction JSON for cross-field consistency."
    )
    ap.add_argument(
        "extraction_path",
        nargs="?",
        help="path to <mpn>.json extraction (positional mode)",
    )
    ap.add_argument(
        "--mpn",
        help="MPN to look up under --extract-dir (flag mode)",
    )
    ap.add_argument(
        "--extract-dir",
        type=_Path,
        help="directory containing <mpn>.json (flag mode)",
    )
    ap.add_argument(
        "--self-consistency",
        action="store_true",
        help=(
            "explicit opt-in to v1.4 self-consistency mode "
            "(flag mode; required when using --mpn/--extract-dir)"
        ),
    )
    ap.add_argument(
        "--json",
        dest="emit_json",
        action="store_true",
        help="emit harness-shape JSON ({violations: [...]}) instead of legacy {issues: [...]}",
    )
    args = ap.parse_args(argv)

    flag_mode = bool(args.mpn or args.extract_dir or args.self_consistency)
    positional_mode = args.extraction_path is not None

    if flag_mode and positional_mode:
        print(
            "error: cannot mix positional extraction_path with --mpn/--extract-dir flags",
            file=_sys.stderr,
        )
        return 2
    if flag_mode:
        if not (args.mpn and args.extract_dir and args.self_consistency):
            print(
                "error: flag mode requires --mpn, --extract-dir, and --self-consistency",
                file=_sys.stderr,
            )
            return 2
        sanitized = _re.sub(r"[^A-Za-z0-9_.-]", "_", args.mpn.strip())
        path = args.extract_dir / f"{sanitized}.json"
    elif positional_mode:
        path = _Path(args.extraction_path)
    else:
        ap.print_usage(_sys.stderr)
        print(
            "error: must supply either positional extraction_path "
            "or --mpn/--extract-dir/--self-consistency",
            file=_sys.stderr,
        )
        return 2

    if not path.exists():
        print(f"error: extraction file not found: {path}", file=_sys.stderr)
        return 2
    try:
        extraction = _json.loads(path.read_text())
    except _json.JSONDecodeError as exc:
        print(f"error: extraction file is not valid JSON: {exc}", file=_sys.stderr)
        return 2

    issues = verify_v14_extraction(extraction)

    if flag_mode and args.emit_json:
        _json.dump(
            {
                "violations": issues,
                "count": len(issues),
                "mpn": args.mpn,
                "extract_dir": str(args.extract_dir),
            },
            _sys.stdout,
            indent=2,
        )
    elif args.emit_json or positional_mode:
        _json.dump({"issues": issues, "count": len(issues)}, _sys.stdout, indent=2)
    else:
        # Flag mode without --json: minimal human summary.
        print(f"{args.mpn}: {len(issues)} issue(s)")
        for i in issues:
            print(f"  [{i['severity']}] {i['path']}: {i['description']}")
    if args.emit_json or positional_mode:
        _sys.stdout.write("\n")
    return 0 if not issues else 1


if __name__ == "__main__":
    sys.exit(_cli_v14())
