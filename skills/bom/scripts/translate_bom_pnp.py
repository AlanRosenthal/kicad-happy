#!/usr/bin/env python3
"""Translate BOM and Pick-and-Place (CPL) files into JLCPCB upload format.

Two subcommands:
    bom  — read Altium xlsx or KiCad CSV BOM, write JLCPCB BOM CSV
    pnp  — read CPL CSV, write JLCPCB Pick-and-Place CSV
           (with optional --bom filter to drop CPL rows whose designators
            don't appear in the BOM — avoids JLCPCB upload rejection)

Stdlib-only except optional ``openpyxl`` for Altium xlsx input.

Inspired by MattStarfield/kicad-happy fork commits fe440c8 + 8d8d06c.
Clean reimplementation under the kicad-happy MIT license.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Iterator


# --- Header field synonyms (loose-match dictionaries) -----------------------

BOM_DES_FIELDS = ("designator", "reference", "references", "refdes", "ref")
BOM_VAL_FIELDS = ("comment", "value", "val")
BOM_FOOT_FIELDS = ("footprint", "package", "pattern")
BOM_MPN_FIELDS = ("mpn", "manufacturer part number", "manufacturer pn", "mfg pn")
BOM_MFG_FIELDS = ("manufacturer", "mfg", "mfr", "vendor")
BOM_QTY_FIELDS = ("quantity", "qty")

PNP_REF_FIELDS = ("designator", "reference", "refdes", "ref")
PNP_X_FIELDS = ("mid x", "midx", "x", "center-x", "centerx", "ref x", "refx")
PNP_Y_FIELDS = ("mid y", "midy", "y", "center-y", "centery", "ref y", "refy")
PNP_LAYER_FIELDS = ("layer", "side")
PNP_ROT_FIELDS = ("rotation", "rot", "angle")

# --- Markers that indicate a row should be skipped --------------------------

DNP_MARKERS = ("no stuff", "dnp", "do not populate", "dni", "noload", "no load")
PCB_MARKERS = ("pcb,", "bare pcb", "pcb-")

# Header-row detection: scan first N rows, pick the one with the most matches.
HEADER_SCAN_LIMIT = 20


def _loose_match(cell: str, candidates: tuple[str, ...]) -> bool:
    """Case-insensitive substring match against any candidate.

    >>> _loose_match("Designator", ("designator", "reference"))
    True
    >>> _loose_match("Ref Des", ("refdes",))
    True
    >>> _loose_match("Quantity", ("designator",))
    False
    >>> _loose_match("", ("designator",))
    False
    """
    if not cell:
        return False
    cell_lc = cell.strip().lower()
    cell_no_space = cell_lc.replace(" ", "")
    return any(c in cell_lc or c in cell_no_space for c in candidates)


def _find_col(header: list[str], candidates: tuple[str, ...]) -> int | None:
    """Return index of first header cell matching any candidate, else None.

    Exact match first, then loose substring (via _loose_match for
    space-tolerance like "Ref Des" → "refdes").

    >>> _find_col(["Designator", "Comment"], ("comment",))
    1
    >>> _find_col(["Ref Des", "Value"], ("refdes",))
    0
    >>> _find_col(["A", "B"], ("c",)) is None
    True
    """
    lower = [(c or "").strip().lower() for c in header]
    for i, cell in enumerate(lower):
        if cell in candidates:
            return i
    for i, cell in enumerate(header):
        if _loose_match(cell, candidates):
            return i
    return None


def _is_dnp(value: str) -> bool:
    """Return True if value matches any DNP marker.

    >>> _is_dnp("No Stuff")
    True
    >>> _is_dnp("DNP")
    True
    >>> _is_dnp("100nF")
    False
    """
    if not value:
        return False
    v = value.strip().lower()
    return any(m in v for m in DNP_MARKERS)


def _is_pcb_marker(value: str) -> bool:
    """Return True if value matches any PCB-marker (bare-PCB sentinel row).

    >>> _is_pcb_marker("Bare PCB")
    True
    >>> _is_pcb_marker("PCB-001")
    True
    >>> _is_pcb_marker("PCB,REV2")
    True
    >>> _is_pcb_marker("100nF")
    False
    """
    if not value:
        return False
    v = value.strip().lower()
    return any(m in v for m in PCB_MARKERS)


def _detect_header_row(rows: list[list[str]]) -> int:
    """Return index of best-match header row in the first HEADER_SCAN_LIMIT rows.

    Score = count of (BOM_DES, BOM_VAL, BOM_FOOT, BOM_MPN) field matches.
    Requires at least 2 matches to count as a header. Returns 0 if no row qualifies.

    >>> _detect_header_row([["a", "b"], ["Designator", "Value", "Footprint"]])
    1
    >>> _detect_header_row([["Designator", "Value"]])
    0
    """
    best_idx, best_score = 0, 0
    for i, row in enumerate(rows[:HEADER_SCAN_LIMIT]):
        if not row:
            continue
        cells_lc = [(c or "").strip().lower() for c in row]
        score = sum(
            1
            for group in (BOM_DES_FIELDS, BOM_VAL_FIELDS, BOM_FOOT_FIELDS, BOM_MPN_FIELDS)
            if any(any(c in cell for c in group) for cell in cells_lc)
        )
        if score > best_score and score >= 2:
            best_idx, best_score = i, score
    return best_idx


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="translate_bom_pnp",
        description="Translate BOM/CPL into JLCPCB upload format.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_bom = sub.add_parser("bom", help="Translate a BOM file to JLCPCB format.")
    p_bom.add_argument("input", help="Input BOM file (.csv or .xlsx).")
    p_bom.add_argument("-o", "--output", required=True, help="Output CSV path.")

    p_pnp = sub.add_parser("pnp", help="Translate a CPL file to JLCPCB format.")
    p_pnp.add_argument("input", help="Input CPL file (.csv).")
    p_pnp.add_argument("-o", "--output", required=True, help="Output CSV path.")
    p_pnp.add_argument(
        "--bom",
        help="BOM CSV path. If supplied, CPL rows whose designators are not in "
             "the BOM are dropped (avoids JLCPCB upload rejection on orphans).",
    )

    sub.add_parser("self-test", help="Run embedded end-to-end tests and exit.")

    args = parser.parse_args(argv)

    if args.cmd == "self-test":
        return _self_test()
    if args.cmd == "bom":
        stats = translate_bom(args.input, args.output)
    elif args.cmd == "pnp":
        stats = translate_pnp(args.input, args.output, bom_filter_path=args.bom)
    else:
        parser.error(f"Unknown command: {args.cmd}")

    print(json.dumps(stats, indent=2))
    return 0


def _read_csv_rows(path: str) -> list[list[str]]:
    """Read a CSV file into a list of rows (each row a list of strings)."""
    with open(path, newline="", encoding="utf-8-sig") as f:
        return [list(row) for row in csv.reader(f)]


def translate_bom(input_path: str, output_path: str) -> dict:
    """Translate a BOM file to JLCPCB upload format.

    Supports KiCad CSV and Altium-exported CSV. Altium xlsx input is
    deferred to a follow-up (requires optional ``openpyxl``); raise
    a clear error for now.
    """
    in_path = Path(input_path)
    if in_path.suffix.lower() in (".xlsx", ".xls"):
        raise NotImplementedError(
            f"xlsx input not yet supported (input: {input_path}). "
            "Convert to CSV in Altium/Excel and rerun."
        )

    rows = _read_csv_rows(input_path)
    if not rows:
        raise ValueError(f"BOM is empty: {input_path}")

    header_idx = _detect_header_row(rows)
    header = rows[header_idx]
    data_rows = rows[header_idx + 1 :]

    col_des = _find_col(header, BOM_DES_FIELDS)
    col_val = _find_col(header, BOM_VAL_FIELDS)
    col_foot = _find_col(header, BOM_FOOT_FIELDS)
    col_mpn = _find_col(header, BOM_MPN_FIELDS)
    col_mfg = _find_col(header, BOM_MFG_FIELDS)
    col_qty = _find_col(header, BOM_QTY_FIELDS)

    if col_des is None or col_val is None:
        raise ValueError(
            f"BOM missing required columns (Designator/Reference and Value/Comment). "
            f"Header at row {header_idx}: {header}"
        )

    stats = {
        "input": input_path,
        "output": output_path,
        "header_row": header_idx,
        "rows_in": 0,
        "rows_out": 0,
        "skipped_dnp": 0,
        "skipped_pcb_marker": 0,
        "continuation_rows_merged": 0,
    }

    output_rows: list[dict] = []
    current: dict | None = None

    def _cell(row: list[str], idx: int | None) -> str:
        if idx is None or idx >= len(row):
            return ""
        return (row[idx] or "").strip()

    for raw in data_rows:
        stats["rows_in"] += 1
        if not any((c or "").strip() for c in raw):
            continue

        des = _cell(raw, col_des)
        val = _cell(raw, col_val)
        mpn = _cell(raw, col_mpn)
        mfg = _cell(raw, col_mfg)

        # Continuation row: no designator, but MPN/Mfg present — alt-part for prior row.
        if not des and (mpn or mfg) and current is not None:
            if mpn:
                current["alt_mpns"].append(mpn)
            if mfg:
                current["alt_mfgs"].append(mfg)
            stats["continuation_rows_merged"] += 1
            continue

        if not des:
            continue

        if _is_pcb_marker(val) or _is_pcb_marker(des):
            stats["skipped_pcb_marker"] += 1
            current = None
            continue
        if _is_dnp(val):
            stats["skipped_dnp"] += 1
            current = None
            continue

        current = {
            "designator": des,
            "value": val,
            "footprint": _cell(raw, col_foot),
            "mpn": mpn,
            "manufacturer": mfg,
            "quantity": _cell(raw, col_qty),
            "alt_mpns": [],
            "alt_mfgs": [],
        }
        output_rows.append(current)

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "Comment",
                "Designator",
                "Footprint",
                "LCSC Part #",
                "MPN",
                "Manufacturer",
                "Quantity",
                "Notes",
            ]
        )
        for r in output_rows:
            notes = ""
            if r["alt_mpns"]:
                notes = "alt MPN: " + ", ".join(r["alt_mpns"])
            writer.writerow(
                [
                    r["value"],
                    r["designator"],
                    r["footprint"],
                    "",  # LCSC Part # — user populates separately
                    r["mpn"],
                    r["manufacturer"],
                    r["quantity"],
                    notes,
                ]
            )
            stats["rows_out"] += 1

    return stats


def translate_pnp(
    input_path: str, output_path: str, *, bom_filter_path: str | None = None
) -> dict:
    """Translate a CPL file to JLCPCB format. Returns stats dict.

    Placeholder — implemented in Task 3 (and --bom filter in Task 4).
    """
    raise NotImplementedError("translate_pnp — implemented in Task 3")


def _self_test() -> int:
    """End-to-end smoke test. Returns 0 on success, 1 on failure."""
    import tempfile

    failures: list[str] = []

    # --- BOM translation: KiCad-style CSV with DNP, PCB marker, continuation row ---
    bom_csv = (
        "Project: demo\n"
        "Generated: 2026-05-16\n"
        "Reference,Value,Footprint,Manufacturer,Manufacturer Part Number\n"
        "C1,100nF,Capacitor_SMD:C_0402_1005Metric,Yageo,CC0402KRX7R9BB104\n"
        ",,,Murata,GRM155R71C104KA88\n"  # continuation row — alt MPN
        "R1,10k,Resistor_SMD:R_0402_1005Metric,Yageo,RC0402FR-0710KL\n"
        "DNP1,DO NOT POPULATE,Capacitor_SMD:C_0402_1005Metric,,\n"
        "PCB1,Bare PCB,,,\n"
        "U1,STM32G030F6P6,Package_SO:TSSOP-20,STMicro,STM32G030F6P6\n"
    )

    with tempfile.TemporaryDirectory() as tmp:
        in_path = Path(tmp) / "bom_in.csv"
        out_path = Path(tmp) / "bom_out.csv"
        in_path.write_text(bom_csv)

        stats = translate_bom(str(in_path), str(out_path))

        if stats["rows_out"] != 3:
            failures.append(
                f"BOM rows_out: expected 3 (C1, R1, U1), got {stats['rows_out']}"
            )
        if stats["skipped_dnp"] != 1:
            failures.append(f"BOM skipped_dnp: expected 1, got {stats['skipped_dnp']}")
        if stats["skipped_pcb_marker"] != 1:
            failures.append(
                f"BOM skipped_pcb_marker: expected 1, got {stats['skipped_pcb_marker']}"
            )
        if stats["continuation_rows_merged"] != 1:
            failures.append(
                f"BOM continuation_rows_merged: expected 1, got "
                f"{stats['continuation_rows_merged']}"
            )

        out_text = out_path.read_text()
        if "alt MPN: GRM155R71C104KA88" not in out_text:
            failures.append("BOM output missing alt-MPN notes column")
        if "DO NOT POPULATE" in out_text:
            failures.append("BOM output unexpectedly contains DNP row")
        if "Bare PCB" in out_text:
            failures.append("BOM output unexpectedly contains PCB-marker row")

    if failures:
        print("self-test: FAIL")
        for f in failures:
            print(f"  - {f}")
        return 1

    print("self-test: PASS (BOM translation)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
