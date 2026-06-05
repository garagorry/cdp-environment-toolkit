"""CLI for ``cdp-discover generate``."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import List, Optional

from .builders import BUILDERS
from .common import at
from .excel_writer import write_workbook
from .loader import find_assets, summarize


SUPPORTED_CLOUDS = ("aws", "azure", "gcp")
MANIFEST_FILE = "manifest.json"


def _prompt_cloud() -> str:
    print("Which cloud provider was the discovery taken from?")
    for i, c in enumerate(SUPPORTED_CLOUDS, start=1):
        print(f"  {i}) {c}")
    while True:
        raw = input("Select [1-3] (default: 1=aws): ").strip()
        if not raw:
            return "aws"
        if raw.isdigit() and 1 <= int(raw) <= len(SUPPORTED_CLOUDS):
            return SUPPORTED_CLOUDS[int(raw) - 1]
        if raw.lower() in SUPPORTED_CLOUDS:
            return raw.lower()
        print(f"  Invalid choice {raw!r}. Please try again.")


def _prompt_path(label: str, default: str) -> str:
    raw = input(f"{label} [{default}]: ").strip()
    return raw or default


def _load_columns(cloud: str):
    if cloud == "aws":
        from .columns import aws as mod
        return mod.SHEETS
    if cloud == "azure":
        try:
            from .columns import azure as mod  # type: ignore
            return mod.SHEETS
        except Exception:
            print("Azure column specs not yet defined; falling back to AWS specs.")
            from .columns import aws as mod
            return mod.SHEETS
    if cloud == "gcp":
        try:
            from .columns import gcp as mod  # type: ignore
            return mod.SHEETS
        except Exception:
            print("GCP column specs not yet defined; falling back to AWS specs.")
            from .columns import aws as mod
            return mod.SHEETS
    raise ValueError(f"Unknown cloud {cloud!r}")


def _read_manifest(discovery_dir: str) -> Optional[dict]:
    path = Path(discovery_dir) / MANIFEST_FILE
    if not path.is_file():
        return None
    try:
        with open(path, encoding="utf-8") as fp:
            return json.load(fp)
    except (OSError, json.JSONDecodeError):
        return None


def _validate_cloud(bundle, expected: str, manifest: Optional[dict]) -> str:
    warnings = []
    if manifest:
        m_cloud = (manifest.get("cloudPlatform") or "").lower()
        if m_cloud and m_cloud != expected:
            warnings.append(
                f"WARNING: manifest reports cloudPlatform={manifest.get('cloudPlatform')!r} "
                f"but you selected {expected!r}."
            )
    actual = at("environment.cloudPlatform")(bundle.environment) if bundle.environment else None
    if actual and actual.lower() != expected:
        warnings.append(
            f"WARNING: discovery files report cloudPlatform={actual!r} but you "
            f"selected {expected!r}. Continuing with {expected!r} column specs."
        )
    return "\n".join(warnings)


def _default_output(discovery_dir: str, env_name: str) -> str:
    base = env_name or os.path.basename(os.path.abspath(discovery_dir))
    samples = os.path.join(discovery_dir, "Samples")
    if os.path.isdir(samples):
        return os.path.join(samples, f"UpgradePlanning_{base}.xlsx")
    return os.path.join(discovery_dir, f"UpgradePlanning_{base}.xlsx")


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="cdp-discover generate",
        description="Build an Excel upgrade-planning report from cdp-discover discovery output.",
    )
    parser.add_argument(
        "--discovery-dir", "-d",
        help="Path to discovery output directory (contains manifest.json and service folders).",
    )
    parser.add_argument(
        "--cloud", "-c",
        choices=SUPPORTED_CLOUDS,
        help="Cloud provider (aws/azure/gcp). Full column support is AWS.",
    )
    parser.add_argument("--output", "-o", help="Output .xlsx path.")
    parser.add_argument(
        "--no-prompt",
        action="store_true",
        help="Fail instead of prompting when arguments are missing.",
    )
    args = parser.parse_args(argv)

    cloud = args.cloud
    if not cloud:
        if args.no_prompt:
            parser.error("--cloud is required when --no-prompt is set")
        cloud = _prompt_cloud()

    discovery_dir = args.discovery_dir
    if not discovery_dir:
        default = os.getcwd()
        discovery_dir = default if args.no_prompt else _prompt_path(
            "Path to discovery directory", default,
        )
    discovery_dir = os.path.abspath(discovery_dir)
    if not os.path.isdir(discovery_dir):
        print(f"ERROR: discovery directory does not exist: {discovery_dir}", file=sys.stderr)
        return 2

    manifest = _read_manifest(discovery_dir)
    if manifest:
        print(f"Using manifest.json (schema {manifest.get('schemaVersion', '?')})")
    else:
        print("Note: manifest.json not found; scanning directory layout only.")

    print(f"\nScanning {discovery_dir} ...")
    bundle = find_assets(discovery_dir)
    print(summarize(bundle))

    warning = _validate_cloud(bundle, cloud, manifest)
    if warning:
        print(warning)

    env_name = at("environment.environmentName")(bundle.environment) if bundle.environment else ""
    if not env_name and manifest:
        env_name = manifest.get("environmentName", "")

    output = args.output or _default_output(discovery_dir, env_name or "")
    output = os.path.abspath(output)

    sheet_specs = _load_columns(cloud)
    sheets_for_writer = []
    for name, columns in sheet_specs:
        builder = BUILDERS.get(name)
        if not builder:
            sheets_for_writer.append((name, columns, []))
            continue
        rows = builder(bundle)
        sheets_for_writer.append((name, columns, rows))

    print(f"\nWriting workbook -> {output}")
    write_workbook(output, sheets_for_writer)
    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
