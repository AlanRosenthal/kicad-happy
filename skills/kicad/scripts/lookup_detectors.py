"""Phase 4 4c: 6 new detectors consuming v1.4 datasheet facts via lookup().

Each detector probes facts.base.<field> or facts.regulator.<field> via the
typed Consumer API (datasheet_types) and emits findings with
confidence='datasheet-backed' + evidence_source='datasheet' when data is
present. Soft-skip when the cache is missing or below trust gate — no
analyzer ever blocks on lookup() per Phase 4 spec §5.1.

API surface (Phase 4b alignment, 2026-05-03):
    facts = get_facts(mpn, cache_dir=cache_dir)        # may be None
    if facts is None: return []                        # silent skip
    specs = facts.base.absolute_max.get(key)           # list[SpecValue]
    if has_data(specs):
        sv = best(specs, min_confidence='medium')      # SpecValue or None
        if sv is not None and sv.max is not None:
            ...

Synonym resolution (Phase 4c addendum §A2): base.absolute_max,
base.recommended_operating, and base.thermal use additionalProperties:
SpecValue[] — extractors emit mixed key spellings (VDD/VCC/VDDA, TJ/TJ_max).
_resolve_key() walks a synonym tuple and returns the first match.

All findings tagged schema_era='v1.4' for harness regression assertions.
"""
from __future__ import annotations

import logging
from typing import Optional

from finding_schema import make_finding
from lookup_helpers import get_facts, has_data, best


log = logging.getLogger(__name__)


# Synonym tables for rail-key resolution. Order matters: first match wins.
VDD_SYNONYMS = ("VDD", "VCC", "VDDA", "VDDIO", "VCC_dual_supply",
                "VCC_single_supply", "VDDD", "AVDD", "DVDD")
TJ_SYNONYMS = ("TJ", "TJ_max", "TJmax", "Tj", "Tj_max")
THETA_JA_SYNONYMS = ("theta_ja", "Rtheta_JA", "R_theta_JA", "RthJA")


def _resolve_key(block: Optional[dict], synonyms) -> Optional[list]:
    """Return the first synonym's SpecValue list from `block`, or None.

    Synonym order in the tuple defines resolution priority. None block
    or no key match → None (caller treats as no data).
    """
    if not block:
        return None
    for key in synonyms:
        specs = block.get(key)
        if specs:
            return specs
    return None


def _candidate_synonyms(domain: Optional[str], base_synonyms: tuple) -> tuple:
    """Build a synonym tuple that prefers the pin's declared domain first,
    then falls back to the base synonym set."""
    if not domain:
        return base_synonyms
    if domain in base_synonyms:
        # Move declared domain to the front
        return (domain,) + tuple(s for s in base_synonyms if s != domain)
    return (domain,) + base_synonyms


def _connected_net(ctx, ref: str, pin_numbers) -> Optional[str]:
    """Return the net connected to the first matching pin number, or None."""
    if not pin_numbers:
        return None
    for pnum in pin_numbers:
        key = (ref, str(pnum))
        if key in ctx.pin_net:
            net, _ = ctx.pin_net[key]
            if net:
                return net
    return None


def _component_mpn(component: dict) -> Optional[str]:
    """Resolve an IC's MPN with the same fallback chain as Phase 4b."""
    return component.get("mpn") or component.get("value") or None


# ---------------------------------------------------------------------------
# AM-001 — absolute-max violation
# ---------------------------------------------------------------------------

def detect_absolute_max_violations(ctx, rail_voltages: dict) -> list[dict]:
    """AM-001: For each IC pin with a power_domain, compare the connected
    rail voltage to base.absolute_max[domain] (with synonym resolution).

    Per-pin Pin.absolute_max overrides the rail-level limit when stricter.

    Severity: error (safety check — exceeding absolute_max kills the part).
    """
    findings: list[dict] = []
    cache_dir = getattr(ctx, "cache_dir", None)
    design_context = getattr(ctx, "design_context", None)

    for component in ctx.components:
        ref = component.get("reference") or component.get("ref")
        mpn = _component_mpn(component)
        if not ref or not mpn:
            continue
        facts = get_facts(mpn, cache_dir=cache_dir)
        if facts is None:
            continue
        base = getattr(facts, "base", None)
        if base is None:
            continue
        am_block = getattr(base, "absolute_max", None)
        pinout = getattr(base, "pinout", None)
        if not am_block or pinout is None:
            continue

        for pin in pinout:
            domain = getattr(pin, "power_domain", None)
            if not domain:
                continue
            net = _connected_net(ctx, ref, getattr(pin, "numbers", []))
            if net is None:
                continue
            rail_v = rail_voltages.get(net)
            if rail_v is None:
                continue

            synonyms = _candidate_synonyms(domain, VDD_SYNONYMS)
            specs = _resolve_key(am_block, synonyms)
            if not has_data(specs):
                continue
            sv = best(specs, min_confidence="medium")
            if sv is None or sv.max is None:
                continue
            absolute_max_v = sv.max

            # Per-pin override: tighten the rail-level limit if pin publishes
            # a stricter per-pin absolute_max.
            pin_specs = getattr(pin, "absolute_max", None)
            if has_data(pin_specs):
                pin_sv = best(pin_specs, min_confidence="medium")
                if pin_sv is not None and pin_sv.max is not None and pin_sv.max < absolute_max_v:
                    absolute_max_v = pin_sv.max

            if rail_v <= absolute_max_v:
                continue

            pin_number = pin.numbers[0] if pin.numbers else "?"
            findings.append(make_finding(
                detector="detect_absolute_max_violations",
                rule_id="AM-001",
                category="electrical_safety",
                summary=(f"{ref} pin {pin_number} ({pin.name}) on {net} at "
                          f"{rail_v}V exceeds absolute_max {absolute_max_v}V"),
                description=(f"Pin {pin_number} of {ref} ({mpn}) connects to "
                              f"net {net} at an estimated {rail_v}V, exceeding "
                              f"the datasheet absolute_max of {absolute_max_v}V "
                              f"for power domain {domain}. Exceeding absolute_max "
                              f"can permanently damage the part."),
                severity="error",
                confidence="datasheet-backed",
                evidence_source="datasheet",
                components=[ref],
                nets=[net],
                pins=[{"ref": ref, "pin": pin_number, "name": pin.name}],
                recommendation=(f"Reduce {net} voltage below {absolute_max_v}V "
                                 f"or replace {ref} with a part rated to handle "
                                 f"{rail_v}V on the {domain} domain."),
                report_section="Electrical Safety",
                impact="Risk of permanent device damage or destruction.",
                source=ctx.source,
                design_context=design_context,
                schema_era="v1.4",
                rail_voltage=rail_v,
                absolute_max_v=absolute_max_v,
                domain=domain,
            ))
    return findings


# ---------------------------------------------------------------------------
# OV-001 — VCC outside recommended operating range
# ---------------------------------------------------------------------------

def detect_vcc_outside_recommended(ctx, rail_voltages: dict) -> list[dict]:
    """OV-001: For each IC pin with a power_domain, verify the connected
    rail voltage is within base.recommended_operating[domain] range
    (with synonym resolution).

    Severity: warning (escalates via severity_tuning matrix in
    automotive/medical environments through Layer 2).
    """
    findings: list[dict] = []
    cache_dir = getattr(ctx, "cache_dir", None)
    design_context = getattr(ctx, "design_context", None)

    for component in ctx.components:
        ref = component.get("reference") or component.get("ref")
        mpn = _component_mpn(component)
        if not ref or not mpn:
            continue
        facts = get_facts(mpn, cache_dir=cache_dir)
        if facts is None:
            continue
        base = getattr(facts, "base", None)
        if base is None:
            continue
        rec_block = getattr(base, "recommended_operating", None)
        pinout = getattr(base, "pinout", None)
        if not rec_block or pinout is None:
            continue

        for pin in pinout:
            domain = getattr(pin, "power_domain", None)
            if not domain:
                continue
            net = _connected_net(ctx, ref, getattr(pin, "numbers", []))
            if net is None:
                continue
            rail_v = rail_voltages.get(net)
            if rail_v is None:
                continue

            synonyms = _candidate_synonyms(domain, VDD_SYNONYMS)
            specs = _resolve_key(rec_block, synonyms)
            if not has_data(specs):
                continue
            sv = best(specs, min_confidence="medium")
            if sv is None:
                continue
            v_min = sv.min
            v_max = sv.max

            pin_number = pin.numbers[0] if pin.numbers else "?"

            if v_min is not None and rail_v < v_min:
                findings.append(make_finding(
                    detector="detect_vcc_outside_recommended",
                    rule_id="OV-001",
                    category="electrical_safety",
                    summary=(f"{ref} pin {pin_number} ({pin.name}) on {net} at "
                              f"{rail_v}V below recommended min {v_min}V"),
                    description=(f"Pin {pin_number} of {ref} ({mpn}) connects to "
                                  f"net {net} at {rail_v}V, below the recommended "
                                  f"operating minimum of {v_min}V for domain {domain}. "
                                  f"Operation outside the recommended range may "
                                  f"compromise specified electrical characteristics."),
                    severity="warning",
                    confidence="datasheet-backed",
                    evidence_source="datasheet",
                    components=[ref],
                    nets=[net],
                    pins=[{"ref": ref, "pin": pin_number, "name": pin.name}],
                    recommendation=(f"Raise {net} to at least {v_min}V or use a "
                                     f"part rated for lower-voltage operation."),
                    report_section="Electrical Safety",
                    impact="Specified electrical characteristics may not be met.",
                    source=ctx.source,
                    design_context=design_context,
                    schema_era="v1.4",
                    rail_voltage=rail_v,
                    recommended_min=v_min,
                    domain=domain,
                ))
            elif v_max is not None and rail_v > v_max:
                findings.append(make_finding(
                    detector="detect_vcc_outside_recommended",
                    rule_id="OV-001",
                    category="electrical_safety",
                    summary=(f"{ref} pin {pin_number} ({pin.name}) on {net} at "
                              f"{rail_v}V above recommended max {v_max}V"),
                    description=(f"Pin {pin_number} of {ref} ({mpn}) connects to "
                                  f"net {net} at {rail_v}V, above the recommended "
                                  f"operating maximum of {v_max}V for domain {domain}. "
                                  f"Still within absolute_max but specified "
                                  f"performance is not guaranteed."),
                    severity="warning",
                    confidence="datasheet-backed",
                    evidence_source="datasheet",
                    components=[ref],
                    nets=[net],
                    pins=[{"ref": ref, "pin": pin_number, "name": pin.name}],
                    recommendation=(f"Reduce {net} below {v_max}V or use a part "
                                     f"rated for higher-voltage operation."),
                    report_section="Electrical Safety",
                    impact="Specified electrical characteristics may not be met.",
                    source=ctx.source,
                    design_context=design_context,
                    schema_era="v1.4",
                    rail_voltage=rail_v,
                    recommended_max=v_max,
                    domain=domain,
                ))
    return findings


# ---------------------------------------------------------------------------
# TJ-001 — junction temperature exceeds TJmax (thermal)
# ---------------------------------------------------------------------------

def detect_tj_exceeds_max(assessments, *, source, cache_dir,
                            design_context=None) -> list[dict]:
    """TJ-001: Recompute junction temperature using v1.4 facts.base.thermal
    [theta_ja] and compare to facts.base.absolute_max[TJ_SYNONYMS].

    Severity: error.

    Each assessment must carry: ref, value (or mpn), ambient_c, pdiss_w.
    Existing v1.3 thermal pipeline (analyze_thermal._compute_junction_temps)
    populates these fields; TJ-001 is an additive rule on top.
    """
    findings: list[dict] = []
    for a in assessments:
        ref = a.get("ref")
        mpn = a.get("mpn") or a.get("value")
        if not ref or not mpn:
            continue
        facts = get_facts(mpn, cache_dir=cache_dir)
        if facts is None:
            continue
        base = getattr(facts, "base", None)
        if base is None:
            continue

        thermal_block = getattr(base, "thermal", None)
        theta_specs = _resolve_key(thermal_block, THETA_JA_SYNONYMS)
        if not has_data(theta_specs):
            continue
        theta_sv = best(theta_specs, min_confidence="medium")
        if theta_sv is None:
            continue
        # Prefer typ; fall back to max (worst-case) when typ is absent.
        theta = theta_sv.typ if theta_sv.typ is not None else theta_sv.max
        if theta is None:
            continue

        am_block = getattr(base, "absolute_max", None)
        tj_specs = _resolve_key(am_block, TJ_SYNONYMS)
        if not has_data(tj_specs):
            continue
        tj_sv = best(tj_specs, min_confidence="medium")
        if tj_sv is None or tj_sv.max is None:
            continue
        tj_max = tj_sv.max

        ambient = a.get("ambient_c", 25.0)
        pdiss = a.get("pdiss_w", 0.0)
        tj_v14 = ambient + theta * pdiss

        if tj_v14 <= tj_max:
            continue

        findings.append(make_finding(
            detector="detect_tj_exceeds_max",
            rule_id="TJ-001",
            category="thermal",
            summary=(f"{ref} ({mpn}) estimated TJ {tj_v14:.1f}°C exceeds "
                      f"datasheet TJmax {tj_max}°C"),
            description=(f"Component {ref} ({mpn}): TJ = ambient ({ambient}°C) + "
                          f"θJA ({theta}°C/W) × P_diss ({pdiss}W) = {tj_v14:.1f}°C, "
                          f"exceeding datasheet TJmax of {tj_max}°C. "
                          f"Operation may cause thermal shutdown, accelerated "
                          f"aging, or permanent damage."),
            severity="error",
            confidence="datasheet-backed",
            evidence_source="datasheet",
            components=[ref],
            recommendation=(f"Reduce P_diss below "
                             f"{(tj_max - ambient) / theta:.2f}W, improve PCB "
                             f"thermal path (more copper, vias, or heat-sinking), "
                             f"or select a part with a higher TJmax / lower θJA."),
            report_section="Thermal",
            impact="Risk of thermal shutdown or accelerated device aging.",
            source=source,
            design_context=design_context,
            schema_era="v1.4",
            tj_estimated_c=round(tj_v14, 1),
            tj_max_c=tj_max,
            theta_ja=theta,
            pdiss_w=pdiss,
            ambient_c=ambient,
        ))
    return findings
