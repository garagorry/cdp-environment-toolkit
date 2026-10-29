#!/usr/bin/env python3
"""Compare CDP SDK read APIs against cdp_discover client.py coverage."""

from __future__ import annotations

import argparse
import re
import sys
import urllib.error
import urllib.request
from collections import defaultdict
from pathlib import Path

SDK_BASE = (
    "https://raw.githubusercontent.com/cloudera/cdp-sdk-java/master/"
    "src/main/java/com/cloudera/cdp/cdp/{service}/api/{client}.java"
)

SDK_CLIENTS = {
    "environments": "EnvironmentsClient",
    "datalake": "DatalakeClient",
    "datahub": "DatahubClient",
    "de": "DeClient",
    "ml": "MlClient",
    "dw": "DwClient",
    "df": "DfClient",
    "opdb": "OpdbClient",
    "iam": "IamClient",
    "audit": "AuditClient",
    "datacatalog": "DatacatalogClient",
    "replicationmanager": "ReplicationmanagerClient",
    "lakehouseopt": "LakehouseoptClient",
    "consumption": "ConsumptionClient",
    "compute": "ComputeClient",
    "dfworkload": "DfworkloadClient",
}

READ_PREFIXES = ("describe", "list", "get", "collect", "download", "search", "find", "show")


def kebab_to_camel(operation: str) -> str:
    parts = operation.split("-")
    return parts[0] + "".join(p.capitalize() for p in parts[1:])


def parse_client_operations(client_path: Path) -> dict[str, set[str]]:
    text = client_path.read_text(encoding="utf-8")
    pattern = re.compile(r'self\.execute\(\s*"([^"]+)"\s*,\s*"([^"]+)"', re.MULTILINE)
    covered: dict[str, set[str]] = defaultdict(set)
    for service, operation in pattern.findall(text):
        covered[service].add(kebab_to_camel(operation))
    return covered


def fetch_sdk_methods(service: str, client_class: str) -> set[str]:
    url = SDK_BASE.format(service=service, client=client_class)
    try:
        with urllib.request.urlopen(url, timeout=20) as response:
            text = response.read().decode("utf-8")
    except (urllib.error.URLError, TimeoutError) as exc:
        print(f"WARN: could not fetch {url}: {exc}", file=sys.stderr)
        return set()
    methods = re.findall(r"public\s+\w+Response\s+(\w+)\s*\(", text)
    return {
        name for name in methods
        if name.lower().startswith(READ_PREFIXES)
    }


def render_report(covered: dict[str, set[str]], include_sdk: bool) -> str:
    lines = ["# SDK coverage report", ""]
    lines.append("Operations discovered via `client.py` `execute()` calls.")
    lines.append("")

    total_covered = sum(len(ops) for ops in covered.values())
    lines.append(f"**Total wrapped operations:** {total_covered}")
    lines.append("")

    for service in sorted(covered):
        ops = sorted(covered[service])
        lines.append(f"## {service} ({len(ops)})")
        lines.append("")
        lines.append(", ".join(ops))
        lines.append("")

        if not include_sdk:
            continue

        client_class = SDK_CLIENTS.get(service)
        if not client_class:
            continue

        sdk_read = fetch_sdk_methods(service, client_class)
        if not sdk_read:
            continue

        missing = sorted(sdk_read - set(ops))
        lines.append(f"SDK read APIs not wrapped: **{len(missing)}**")
        if missing:
            lines.append("")
            lines.append(", ".join(missing[:40]))
            if len(missing) > 40:
                lines.append(f"... +{len(missing) - 40} more")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def check_local_model(client_path: Path) -> int:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from cdp_discover.discover.cli_model import get_cli_version, load_cli_model
    from cdp_discover.discover.contract import check_client_contract

    model = load_cli_model()
    if not model:
        print("Could not read the CDP CLI model (is `cdp` on PATH?)", file=sys.stderr)
        return 1
    issues = check_client_contract(model, client_path.read_text(encoding="utf-8"))
    print(f"CDP CLI {get_cli_version()}: {len(issues)} contract issue(s)")
    for issue in issues:
        print(f"  {issue}")
    return 1 if issues else 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--client",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "src/cdp_discover/discover/client.py",
        help="Path to client.py",
    )
    parser.add_argument(
        "--compare-sdk",
        action="store_true",
        help="Fetch CDP SDK Java clients and list unwrapped read APIs",
    )
    parser.add_argument(
        "--local-model",
        action="store_true",
        help="Validate client.py calls (operations, flags, required args) against the "
             "installed CDP CLI's bundled API model; exits 1 on violations",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Write markdown report to this file (default: stdout)",
    )
    args = parser.parse_args(argv)

    if not args.client.is_file():
        print(f"client.py not found: {args.client}", file=sys.stderr)
        return 1

    if args.local_model:
        return check_local_model(args.client)

    covered = parse_client_operations(args.client)
    report = render_report(covered, include_sdk=args.compare_sdk)

    if args.output:
        args.output.write_text(report, encoding="utf-8")
        print(f"Wrote {args.output}")
    else:
        print(report, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
