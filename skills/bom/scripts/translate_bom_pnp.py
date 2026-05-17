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


def translate_bom(input_path: str, output_path: str) -> dict:
    """Translate a BOM file to JLCPCB format. Returns stats dict.

    Placeholder — implemented in Task 2.
    """
    raise NotImplementedError("translate_bom — implemented in Task 2")


def translate_pnp(
    input_path: str, output_path: str, *, bom_filter_path: str | None = None
) -> dict:
    """Translate a CPL file to JLCPCB format. Returns stats dict.

    Placeholder — implemented in Task 3 (and --bom filter in Task 4).
    """
    raise NotImplementedError("translate_pnp — implemented in Task 3")


def _self_test() -> int:
    """End-to-end smoke test. Returns 0 on success, 1 on failure."""
    print("self-test: no tests implemented yet (Task 1 skeleton)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
