"""``cdp-discover cde-report``: build the executive Excel workbook from cde-inventory output."""

from __future__ import annotations

import argparse
from pathlib import Path

from cdp_discover.discover.utils import log

INSTALL_HINT = 'pip install "cdp-discover[report]"'


def openpyxl_available() -> bool:
    try:
        import openpyxl  # noqa: F401
    except ImportError:
        return False
    return True


def generate(inventory_dirs, output=None) -> Path:
    """Build the workbook; ``output`` defaults to the first inventory dir."""
    from cdp_discover.cde_inventory.excel_report import build_workbook, default_output, load_inventory

    bundle = load_inventory(inventory_dirs)
    target = Path(output) if output else default_output(bundle, Path(inventory_dirs[0]))
    return build_workbook(bundle, target)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="cdp-discover cde-report",
        description="Build the CDE upgrade-impact executive Excel workbook from one or more "
                    "`cdp-discover cde-inventory` output directories.",
        epilog="example:\n  cdp-discover cde-report --inventory-dir /tmp/cde_inventory_dev-<ts> "
               "--inventory-dir /tmp/cde_inventory_prod-<ts> --output CDE_UpgradeImpact_all.xlsx",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--inventory-dir", "-d", action="append", required=True, type=Path,
                        help="cde-inventory output dir (repeatable to merge environments)")
    parser.add_argument("--output", "-o", type=Path,
                        help="Output .xlsx (default: <first dir>/CDE_UpgradeImpact_<env>.xlsx)")
    args = parser.parse_args(argv)

    if not openpyxl_available():
        log(f"❌ openpyxl is required for the Excel report: {INSTALL_HINT}")
        return 2
    try:
        path = generate(args.inventory_dir, args.output)
    except FileNotFoundError as exc:
        log(f"❌ {exc}")
        return 2
    log(f"✅ excel_report: {path}")
    return 0
