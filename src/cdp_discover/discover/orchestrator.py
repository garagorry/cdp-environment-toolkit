#!/usr/bin/env python3
"""Orchestrate CDP environment discovery across all services."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from .api_manifest import APIManifestRecorder, write_api_manifest
from .client import CDPClient
from .config import DiscoveryConfig
from .manifest import build_manifest, write_manifest
from .services import (
    AuditDiscovery,
    CAIDiscovery,
    CDEDiscovery,
    CDFDiscovery,
    CDWDiscovery,
    CODDiscovery,
    ComputeDiscovery,
    ConsumptionDiscovery,
    DataCatalogDiscovery,
    DatahubDiscovery,
    DatalakeDiscovery,
    DFWorkloadDiscovery,
    EnvironmentDiscovery,
    IAMDiscovery,
    LakehouseOptimizerDiscovery,
    ReplicationManagerDiscovery,
)
from .utils import create_archive, log


class EnvironmentDiscoveryOrchestrator:
    """Orchestrates the discovery of all CDP environment resources."""

    def __init__(self, config: DiscoveryConfig):
        self.config = config
        self.api_recorder = APIManifestRecorder()
        self.client = CDPClient(
            profile=config.profile,
            debug=config.debug,
            api_recorder=self.api_recorder,
        )
        self.modules = {
            "environment": EnvironmentDiscovery(self.client, self.config),
            "datalake": DatalakeDiscovery(self.client, self.config),
            "datahub": DatahubDiscovery(self.client, self.config),
            "cde": CDEDiscovery(self.client, self.config),
            "cai": CAIDiscovery(self.client, self.config),
            "cdw": CDWDiscovery(self.client, self.config),
            "cdf": CDFDiscovery(self.client, self.config),
            "cod": CODDiscovery(self.client, self.config),
            "iam": IAMDiscovery(self.client, self.config),
            "audit": AuditDiscovery(self.client, self.config),
            "replicationmanager": ReplicationManagerDiscovery(self.client, self.config),
            "lakehouseopt": LakehouseOptimizerDiscovery(self.client, self.config),
            "datacatalog": DataCatalogDiscovery(self.client, self.config),
            "dfworkload": DFWorkloadDiscovery(self.client, self.config),
            "consumption": ConsumptionDiscovery(self.client, self.config),
            "compute": ComputeDiscovery(self.client, self.config),
        }
        self.results = {}

    def discover_all(self):
        log(f"🚀 Starting full environment discovery for: {self.config.environment_name}")
        log(f"📂 Output directory: {self.config.output_dir}")
        log(f"🔧 CDP Profile: {self.config.profile}")
        log(f"📊 Discovery tier: {self.config.discovery_tier}")
        if self.config.download_diagnostics:
            log("ℹ️ --download-diagnostics: job metadata is collected; bundle file download is not yet automated")
        log("")

        for service_name, module in self.modules.items():
            if not self.config.should_discover(service_name):
                log(f"⏭️ Skipping {service_name} (excluded from discovery)")
                continue
            try:
                self.results[service_name] = module.discover()
            except Exception as e:
                log(f"❌ Error discovering {service_name}: {e}")
                if self.config.debug:
                    import traceback
                    log(f"DEBUG: {traceback.format_exc()}")
                self.results[service_name] = {"success": False, "error": str(e)}

        return self.results

    def generate_summary(self):
        summary = {
            "environment": self.config.environment_name,
            "output_dir": str(self.config.output_dir),
            "services_discovered": {},
            "total_resources": 0,
        }

        for service_name, result in self.results.items():
            if not result.get("success"):
                summary["services_discovered"][service_name] = {
                    "status": "failed",
                    "count": 0,
                }
                continue

            count = 0
            if service_name == "environment":
                count = 1 if result.get("environment") else 0
            elif service_name in ("datalake", "datahub"):
                key = "datalakes" if service_name == "datalake" else "datahubs"
                count = len(result.get(key, []))
            elif service_name == "cde":
                count = len(result.get("services", []))
            elif service_name == "cai":
                count = len(result.get("workspaces", []))
            elif service_name == "cdw":
                count = len(result.get("clusters", []))
            elif service_name == "cdf":
                count = len(result.get("services", []))
            elif service_name == "cod":
                count = len(result.get("databases", []))
            elif service_name == "iam":
                count = sum(
                    len((result.get(key) or {}).get(list_key) or [])
                    for key, list_key in (
                        ("users", "users"),
                        ("groups", "groups"),
                        ("roles", "roles"),
                        ("resource_roles", "resourceRoles"),
                        ("machine_users", "machineUsers"),
                    )
                    if isinstance(result.get(key), dict)
                )
                if result.get("account"):
                    count = max(count, 1)
            elif service_name == "audit":
                count = sum(
                    1 for key in ("archiving_config", "archiving_status", "recent_runs", "outstanding_batches")
                    if result.get(key)
                )
            elif service_name == "replicationmanager":
                count = len(result.get("policies", [])) + len(result.get("clusters", []))
            elif service_name == "lakehouseopt":
                count = len(result.get("datahubs", []))
            elif service_name == "datacatalog":
                count = len(result.get("data_shares", [])) + len(result.get("external_users", []))
            elif service_name == "dfworkload":
                count = len(result.get("deployments", []))
            elif service_name == "consumption":
                count = len(result.get("usage_records", []))
            elif service_name == "compute":
                count = len(result.get("clusters", [])) + len(result.get("deployments", []))

            summary["services_discovered"][service_name] = {
                "status": "success",
                "count": count,
            }
            summary["total_resources"] += count

        return summary

    def print_summary(self):
        summary = self.generate_summary()
        log("\n" + "=" * 60)
        log("📊 DISCOVERY SUMMARY")
        log("=" * 60)
        log(f"Environment: {summary['environment']}")
        log(f"Output Directory: {summary['output_dir']}")
        log(f"Total Resources: {summary['total_resources']}")
        log("")
        log("Services:")
        for service, info in summary["services_discovered"].items():
            status_icon = "✅" if info["status"] == "success" else "❌"
            log(f"  {status_icon} {service.upper()}: {info['count']} resource(s)")
        log("=" * 60)

    def write_manifest_file(self) -> None:
        summary = self.generate_summary()
        manifest = build_manifest(
            environment_name=self.config.environment_name,
            timestamp=self.config.timestamp,
            output_dir=self.config.output_dir,
            results=self.results,
            services_discovered=summary["services_discovered"],
            discovery_tier=self.config.discovery_tier,
        )
        path = self.config.output_dir / "manifest.json"
        write_manifest(path, manifest)
        log(f"📄 Wrote manifest: {path}")

    def write_api_manifest_file(self) -> None:
        api_manifest = self.api_recorder.build(
            environment_name=self.config.environment_name,
            discovery_tier=self.config.discovery_tier,
            profile=self.config.profile,
        )
        path = self.config.output_dir / "api_manifest.json"
        write_api_manifest(path, api_manifest)
        log(f"📄 Wrote API manifest: {path} ({api_manifest['totalCalls']} calls)")


def parse_arguments(argv=None):
    parser = argparse.ArgumentParser(
        description="Discover CDP environment resources (single environment or entire account)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  cdp-discover discover --environment-name my-env
  cdp-discover discover --profile prod
  cdp-discover discover --environment-name my-env --profile prod
  cdp-discover discover --environment-name my-env --output-dir /tmp/my-discovery
  cdp-discover discover --environment-name my-env --include-services datalake datahub
  cdp-discover discover --environment-name my-env --no-archive
  cdp-discover discover --environment-name my-env --deep
  cdp-discover discover --environment-name my-env --full
  cdp-discover discover --environment-name my-env --exhaustive
        """,
    )
    parser.add_argument(
        "--environment-name",
        help="CDP environment name (omit to discover all environments in the account)",
    )
    parser.add_argument("--output-dir", help="Output directory (default: /tmp/discovery_env_<name>-<ts>)")
    parser.add_argument("--profile", default="default", help="CDP CLI profile (default: default)")
    parser.add_argument(
        "--deep",
        action="store_true",
        help="Enable Tier 3 deep discovery (datacatalog, dfworkload, diagnostics metadata)",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Enable Tier 4 full discovery (implies --deep; consumption, compute, platform APIs)",
    )
    parser.add_argument(
        "--exhaustive",
        action="store_true",
        help="Enable Tier 5 exhaustive discovery (implies --full; diagnostic bundle jobs)",
    )
    parser.add_argument(
        "--download-diagnostics",
        action="store_true",
        help="With --exhaustive, also download completed diagnostic bundles (large output)",
    )
    tier4_choices = ["consumption", "compute"]
    parser.add_argument(
        "--include-services",
        nargs="+",
        choices=["environment", "freeipa", "datalake", "datahub", "cde", "cai", "cdw", "cdf", "cod", "iam", "audit", "replicationmanager", "lakehouseopt", "datacatalog", "dfworkload"] + tier4_choices,
        help="Services to include",
    )
    parser.add_argument(
        "--exclude-services",
        nargs="+",
        choices=["environment", "freeipa", "datalake", "datahub", "cde", "cai", "cdw", "cdf", "cod", "iam", "audit", "replicationmanager", "lakehouseopt", "datacatalog", "dfworkload"] + tier4_choices,
        help="Services to exclude",
    )
    parser.add_argument("--debug", action="store_true", help="Enable debug output")
    parser.add_argument("--no-archive", action="store_true", help="Skip tar.gz archive")
    return parser.parse_args(argv)


def _discovery_config_from_args(args, *, environment_name, output_dir=None, timestamp=None, append_timestamp=True):
    return DiscoveryConfig(
        environment_name=environment_name,
        output_dir=output_dir,
        profile=args.profile,
        debug=args.debug,
        include_services=args.include_services,
        exclude_services=args.exclude_services,
        deep=args.deep,
        full=args.full,
        exhaustive=args.exhaustive,
        download_diagnostics=args.download_diagnostics,
        timestamp=timestamp,
        append_timestamp=append_timestamp,
    )


def _environment_names_from_list_response(envs_json):
    environments = envs_json.get("environments") or []
    names = []
    for env in environments:
        name = env.get("environmentName") or env.get("name")
        if name:
            names.append(name)
    return sorted(set(names))


def _account_output_dir(args, timestamp):
    if args.output_dir:
        base = args.output_dir.rstrip("/")
        if base.endswith(timestamp):
            return Path(base)
        return Path(f"{base}-{timestamp}")
    return Path(f"/tmp/discovery_account-{timestamp}")


def _write_account_manifest(path, *, timestamp, output_dir, discovery_tier, profile, environments):
    manifest = {
        "schemaVersion": "1",
        "scope": "account",
        "timestamp": timestamp,
        "discoveryTier": discovery_tier,
        "profile": profile,
        "outputDir": str(output_dir),
        "environmentCount": len(environments),
        "environments": environments,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fp:
        json.dump(manifest, fp, indent=2, ensure_ascii=False)
        fp.write("\n")


def discover_single_environment(args, environment_name, *, output_dir=None, timestamp=None, append_timestamp=True):
    config = _discovery_config_from_args(
        args,
        environment_name=environment_name,
        output_dir=output_dir,
        timestamp=timestamp,
        append_timestamp=append_timestamp,
    )
    orchestrator = EnvironmentDiscoveryOrchestrator(config)
    orchestrator.discover_all()
    orchestrator.print_summary()
    orchestrator.write_manifest_file()
    orchestrator.write_api_manifest_file()
    return orchestrator


def discover_account(args):
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    account_dir = _account_output_dir(args, timestamp)
    account_dir.mkdir(parents=True, exist_ok=True)

    list_client = CDPClient(profile=args.profile, debug=args.debug)
    envs_json, envs_err = list_client.list_environments()
    if not envs_json:
        log(f"❌ Could not list CDP environments: {envs_err}")
        return 1

    env_names = _environment_names_from_list_response(envs_json)
    if not env_names:
        log("ℹ️ No CDP environments found in account")
        return 0

    if args.exhaustive:
        discovery_tier = "exhaustive"
    elif args.full:
        discovery_tier = "full"
    elif args.deep:
        discovery_tier = "deep"
    else:
        discovery_tier = "standard"
    log(f"🚀 Starting account-wide discovery for {len(env_names)} environment(s)")
    log(f"📂 Output directory: {account_dir}")
    log(f"🔧 CDP Profile: {args.profile}")
    log(f"📊 Discovery tier: {discovery_tier}")
    if args.download_diagnostics:
        log("ℹ️ --download-diagnostics: job metadata is collected; bundle file download is not yet automated")
    log("")

    account_entries = []
    for index, env_name in enumerate(env_names, start=1):
        log("\n" + "=" * 60)
        log(f"🌍 Environment {index}/{len(env_names)}: {env_name}")
        log("=" * 60)
        try:
            orchestrator = discover_single_environment(
                args,
                env_name,
                output_dir=str(account_dir / env_name),
                timestamp=timestamp,
                append_timestamp=False,
            )
            summary = orchestrator.generate_summary()
            account_entries.append(
                {
                    "name": env_name,
                    "status": "success",
                    "outputDir": str(orchestrator.config.output_dir),
                    "totalResources": summary["total_resources"],
                    "servicesDiscovered": summary["services_discovered"],
                }
            )
        except KeyboardInterrupt:
            raise
        except Exception as e:
            log(f"❌ Error discovering environment {env_name}: {e}")
            if args.debug:
                import traceback
                log(f"DEBUG: {traceback.format_exc()}")
            account_entries.append(
                {
                    "name": env_name,
                    "status": "failed",
                    "error": str(e),
                }
            )

    succeeded = sum(1 for entry in account_entries if entry.get("status") == "success")
    failed = len(account_entries) - succeeded
    total_resources = sum(entry.get("totalResources", 0) for entry in account_entries)

    log("\n" + "=" * 60)
    log("📊 ACCOUNT DISCOVERY SUMMARY")
    log("=" * 60)
    log(f"Environments: {len(account_entries)} total, {succeeded} succeeded, {failed} failed")
    log(f"Output Directory: {account_dir}")
    log(f"Total Resources: {total_resources}")
    log("=" * 60)

    manifest_path = account_dir / "account_manifest.json"
    _write_account_manifest(
        manifest_path,
        timestamp=timestamp,
        output_dir=account_dir,
        discovery_tier=discovery_tier,
        profile=args.profile,
        environments=account_entries,
    )
    log(f"📄 Wrote account manifest: {manifest_path}")

    if not args.no_archive:
        create_archive(account_dir)
    log(f"\n🏁 Account discovery complete! Output saved in: {account_dir}")
    return 0 if failed == 0 else 1


def main(argv=None) -> int:
    args = None
    try:
        args = parse_arguments(argv)
        if args.environment_name:
            orchestrator = discover_single_environment(args, args.environment_name)
            if not args.no_archive:
                create_archive(orchestrator.config.output_dir)
            log(f"\n🏁 Discovery complete! Output saved in: {orchestrator.config.output_dir}")
            return 0
        return discover_account(args)
    except KeyboardInterrupt:
        log("\n⚠️ Discovery interrupted by user")
        return 130
    except Exception as e:
        log(f"\n❌ Error: {e}")
        if args and args.debug:
            import traceback
            log(f"DEBUG: {traceback.format_exc()}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
