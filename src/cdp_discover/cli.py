"""Unified CLI: ``cdp-discover discover``, ``generate`` and ``cde-inventory``."""

from __future__ import annotations

import argparse
import sys


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="cdp-discover",
        description="CDP environment toolkit: discover resources and generate Excel reports.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    discover_p = sub.add_parser(
        "discover",
        help="Discover CDP environment resources (JSON/CSV via CDP CLI)",
        add_help=False,
    )
    discover_p.set_defaults(_run_discover=True)

    generate_p = sub.add_parser(
        "generate",
        help="Build upgrade-planning XLSX from discovery output",
        add_help=False,
    )
    generate_p.set_defaults(_run_generate=True)

    inventory_p = sub.add_parser(
        "cde-inventory",
        help="Inventory CDE jobs across virtual clusters and assess upgrade impact",
        add_help=False,
    )
    inventory_p.set_defaults(_run_cde_inventory=True)

    report_p = sub.add_parser(
        "cde-report",
        help="Build the CDE upgrade-impact executive XLSX from cde-inventory output",
        add_help=False,
    )
    report_p.set_defaults(_run_cde_report=True)

    args, remainder = parser.parse_known_args(argv)

    if getattr(args, "_run_discover", False):
        from .discover.orchestrator import main as discover_main
        return discover_main(remainder)

    if getattr(args, "_run_generate", False):
        from .generate.cli import main as generate_main
        return generate_main(remainder)

    if getattr(args, "_run_cde_inventory", False):
        from .cde_inventory.cli import main as cde_inventory_main
        return cde_inventory_main(remainder)

    if getattr(args, "_run_cde_report", False):
        from .cde_inventory.report_cli import main as cde_report_main
        return cde_report_main(remainder)

    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
