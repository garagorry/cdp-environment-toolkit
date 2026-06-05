"""Unified CLI: ``cdp-discover discover`` and ``cdp-discover generate``."""

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

    args, remainder = parser.parse_known_args(argv)

    if getattr(args, "_run_discover", False):
        from .discover.orchestrator import main as discover_main
        return discover_main(remainder)

    if getattr(args, "_run_generate", False):
        from .generate.cli import main as generate_main
        return generate_main(remainder)

    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
