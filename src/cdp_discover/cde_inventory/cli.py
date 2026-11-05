"""``cdp-discover cde-inventory``: discover CDE VCs and inventory their jobs for upgrade impact."""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from cdp_discover import __version__
from cdp_discover.cde_inventory import auth, report
from cdp_discover.cde_inventory._http import HttpError, build_ssl_context
from cdp_discover.cde_inventory.api import CdeJobsApi
from cdp_discover.cde_inventory.targets import (
    VCTarget,
    filter_targets,
    targets_from_cli,
    targets_from_discovery_dir,
)
from cdp_discover.discover.utils import log

EPILOG = """\
examples:
  # One environment, live discovery (read-only cdp de calls), prompts for the workload password
  cdp-discover cde-inventory --environment-name my-env

  # Several environments, or every environment in the account
  cdp-discover cde-inventory --environment-name dev-env --environment-name prod-env
  cdp-discover cde-inventory --all-environments

  # Reuse an existing `cdp-discover discover` output (no cdp CLI calls)
  cdp-discover cde-inventory --discovery-dir /tmp/discovery_env_my-env-20261105120000 \\
      --workload-user srv_cde_audit

  # Show what would be audited and the token URLs, without calling any CDE API
  cdp-discover cde-inventory --environment-name my-env --dry-run

environment:
  CDE_WORKLOAD_PASSWORD   workload password (otherwise prompted, never echoed)
  CDE_WORKLOAD_USER       workload user (otherwise --workload-user, else `cdp iam get-user`)
"""


def parse_arguments(argv=None):
    parser = argparse.ArgumentParser(
        prog="cdp-discover cde-inventory",
        description="Inventory CDE jobs across every virtual cluster of one or more environments "
                    "and assess Runtime 7.3.2 / CDE 1.26+ upgrade impact.",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--environment-name", action="append", metavar="ENV",
                        help="CDP environment to audit (repeatable)")
    source.add_argument("--all-environments", action="store_true",
                        help="Audit every environment in the account")
    source.add_argument("--discovery-dir", type=Path,
                        help="Read CDE services/VCs from a `cdp-discover discover` output dir")
    parser.add_argument("--profile", default="default", help="CDP CLI profile (default: default)")
    parser.add_argument("--workload-user", default=os.environ.get(auth.USER_ENV),
                        help="CDP workload user for the CDE API (default: caller's workloadUsername)")
    parser.add_argument("--vc", action="append", metavar="GLOB", help="Only VCs whose name matches (repeatable)")
    parser.add_argument("--exclude-vc", action="append", metavar="GLOB", help="Skip VCs whose name matches (repeatable)")
    parser.add_argument("--ca-bundle", help="PEM CA bundle for TLS verification (private/custom CAs)")
    parser.add_argument("--insecure", action="store_true", help="Disable TLS verification (not recommended)")
    parser.add_argument("--timeout", type=float, default=60, help="HTTP timeout in seconds (default: 60)")
    parser.add_argument("--output-dir", type=Path,
                        help="Report directory (default: /tmp/cde_inventory_<scope>-<timestamp>)")
    parser.add_argument("--no-excel", action="store_true",
                        help="Skip the executive Excel workbook (needs the [report] extra / openpyxl)")
    parser.add_argument("--dry-run", action="store_true",
                        help="List target VCs and token URLs; make no CDE API calls")
    parser.add_argument("--debug", action="store_true", help="Enable debug output")
    return parser.parse_args(argv)


def _cdp_client(args):
    # Imported lazily so --discovery-dir works without CDP CLI credentials
    from cdp_discover.discover.client import CDPClient

    return CDPClient(profile=args.profile, debug=args.debug)


def _resolve_targets(args, client) -> List[VCTarget]:
    if args.discovery_dir:
        if not args.discovery_dir.is_dir():
            raise SystemExit(f"--discovery-dir {args.discovery_dir} is not a directory")
        return targets_from_discovery_dir(args.discovery_dir)

    if args.all_environments:
        envs_json, err = client.list_environments()
        if not envs_json:
            raise SystemExit(f"Could not list CDP environments: {err}")
        names = sorted({e.get("environmentName") for e in envs_json.get("environments") or []} - {None})
    else:
        names = args.environment_name
    log(f"🔍 Discovering CDE virtual clusters in: {', '.join(names) or '(none)'}")
    return targets_from_cli(client, names)


def _resolve_workload_user(args, client) -> str:
    if args.workload_user:
        return args.workload_user
    if client is None:
        try:
            client = _cdp_client(args)
        except (FileNotFoundError, ValueError) as exc:
            raise SystemExit(f"Pass --workload-user (or set {auth.USER_ENV}); {exc}")
    user_json, err = client.get_current_user()
    user = ((user_json or {}).get("user") or {}).get("workloadUsername")
    if not user:
        raise SystemExit(f"Could not determine the workload user ({err}); pass --workload-user")
    return user


def _scope_label(args) -> str:
    if args.discovery_dir:
        return "offline"
    if args.all_environments:
        return "account"
    return "-".join(args.environment_name)


def _print_targets(targets: List[VCTarget]) -> None:
    print(f"\n{'ENVIRONMENT/SERVICE/VC':50} {'SPARK':12} {'OS':18} STATUS")
    for t in targets:
        status = f"SKIP ({t.skip_reason})" if t.skip_reason else (t.vc_status or "")
        print(f"{t.label:50} {t.spark_version or '-':12} {t.spark_os or '-':18} {status}")
        print(f"    jobs API : {t.vc_api_url or '-'}")
        print(f"    token URL: {auth.token_url(t) or '-'}")


def collect(targets, token_provider, ssl_context, timeout, urlopen=None):
    """Query each VC. Returns (rows, outcomes). Aborts on rejected credentials."""
    http = {"urlopen": urlopen} if urlopen else {}
    rows, outcomes = [], []
    for index, target in enumerate(targets):
        outcome = {"label": target.label, **target.to_dict()}
        outcomes.append(outcome)
        if target.skip_reason:
            outcome.update(status="skipped", error=target.skip_reason)
            log(f"⏭️  {target.label}: skipped ({target.skip_reason})")
            continue
        log(f"⚙️ Auditing {target.label}")
        api = CdeJobsApi(target, token_provider, ssl_context, timeout=timeout, **http)
        try:
            jobs = api.jobs()
        except auth.AuthError as exc:
            outcome.update(status="failed", error=str(exc))
            if exc.status == 401:
                # Same password for every service: stop before repeated failures lock the account
                log(f"❌ {exc}. Workload user/password rejected; aborting remaining VCs.")
                for rest in targets[index + 1:]:
                    outcomes.append({"label": rest.label, **rest.to_dict(), "status": "not_attempted",
                                     "error": "aborted after authentication failure"})
                break
            log(f"❌ {target.label}: {exc}")
            continue
        except HttpError as exc:
            outcome.update(status="failed", error=str(exc))
            log(f"❌ {target.label}: {exc}")
            continue

        resources = {}
        try:
            resources = {r.get("name"): r for r in api.resources() if r.get("name")}
        except (HttpError, auth.AuthError) as exc:
            # Rules still run; python-env / runtime-image checks just lose detail
            outcome["resources_error"] = str(exc)
            log(f"⚠️ {target.label}: could not list resources ({exc})")

        for job in jobs:
            rows.append(report.build_row(job, target, resources))
        outcome.update(status="ok", jobs=len(jobs), resources=len(resources))
        log(f"   {len(jobs)} job(s), {len(resources)} resource(s)")
    return rows, outcomes


def _write_excel(output_dir: Path) -> Optional[Path]:
    """Best effort: the CSV/JSON reports are the source of truth, the workbook is a view."""
    from cdp_discover.cde_inventory import report_cli

    if not report_cli.openpyxl_available():
        log(f"ℹ️ Excel report skipped: {report_cli.INSTALL_HINT}, then "
            f"`cdp-discover cde-report --inventory-dir {output_dir}`")
        return None
    try:
        return report_cli.generate([output_dir])
    except Exception as exc:  # noqa: BLE001 - never fail a finished collection over the view
        log(f"⚠️ Excel report failed ({exc}); retry with `cdp-discover cde-report --inventory-dir {output_dir}`")
        return None


def main(argv=None) -> int:
    args = parse_arguments(argv)
    started = datetime.now(timezone.utc)

    client = None
    try:
        if not args.discovery_dir:
            client = _cdp_client(args)
            client.warn_if_cli_outdated()
        targets = _resolve_targets(args, client)
    except (FileNotFoundError, ValueError) as exc:
        log(f"❌ {exc}")
        return 1

    targets = filter_targets(targets, args.vc, args.exclude_vc)
    if not targets:
        log("ℹ️ No CDE virtual clusters found for the given scope/filters")
        return 0
    log(f"Found {len(targets)} virtual cluster(s)")

    if args.dry_run:
        _print_targets(targets)
        return 0

    if args.insecure:
        log("⚠️ TLS verification disabled (--insecure)")
    ssl_context = build_ssl_context(args.ca_bundle, args.insecure)
    user = _resolve_workload_user(args, client)
    password = auth.password_from_env_or_prompt(user)
    try:
        password()  # ask once, up front, so a missing password fails fast
    except auth.AuthError as exc:
        log(f"❌ {exc}")
        return 1
    provider = auth.KnoxTokenProvider(user, password, ssl_context, timeout=min(args.timeout, 30))

    rows, outcomes = collect(targets, provider, ssl_context, args.timeout)

    output_dir = args.output_dir or Path(
        f"/tmp/cde_inventory_{_scope_label(args)}-{started.strftime('%Y%m%d%H%M%S')}"
    )
    manifest = {
        "tool": "cdp-discover cde-inventory",
        "toolVersion": __version__,
        "startedAt": started.isoformat(),
        "finishedAt": datetime.now(timezone.utc).isoformat(),
        "source": "discovery-dir" if args.discovery_dir else "cdp-cli",
        "profile": None if args.discovery_dir else args.profile,
        "cdpCliVersion": getattr(client, "cli_version", None),
        "workloadUser": user,
        "tlsVerify": not args.insecure,
        "jobCount": len(rows),
    }
    paths = report.write_reports(output_dir, rows, outcomes, manifest)
    if not args.no_excel:
        excel = _write_excel(output_dir)
        if excel:
            paths["excel_report"] = excel

    failed = [o for o in outcomes if o["status"] in ("failed", "not_attempted")]
    print()
    for row in report.summarize(rows, outcomes):
        counts = " ".join(f"{s}={row[s.lower()]}" for s in report.SEVERITIES if row[s.lower()])
        print(f"  {row['virtual_cluster']:50} {row['status']:13} jobs={row['jobs']} {counts}")
    print()
    for name, path in paths.items():
        log(f"✅ {name}: {path}")
    if failed:
        log(f"⚠️ {len(failed)} virtual cluster(s) not collected; see inventory_manifest.json")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
