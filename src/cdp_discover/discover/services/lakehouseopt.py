#!/usr/bin/env python3
"""Lakehouse Optimizer discovery module."""

from cdp_discover.discover.utils import log, save_to_file
from cdp_discover.discover.exporters.csv_exporter import CSVExporter


class LakehouseOptimizerDiscovery:
    """Discover Lakehouse Optimizer policies and health per Data Hub."""

    def __init__(self, cdp_client, config):
        self.client = cdp_client
        self.config = config
        self.exporter = CSVExporter()

    def discover(self):
        log("📊 Starting Lakehouse Optimizer discovery...")
        results = {"datahubs": [], "success": False}
        lho_dir = self.config.get_service_dir("lakehouseopt")
        ts = self.config.timestamp
        any_data = False

        envs_json, envs_err = self.client.list_lho_environments()
        if envs_json:
            any_data = True
            save_to_file(envs_json, lho_dir / f"lho_environments_{ts}.json")
            self.exporter.save_flattened_json_to_csv(
                envs_json, lho_dir / f"lho_environments_{ts}.csv"
            )
            results["environments"] = envs_json
        elif self.config.debug:
            log(f"DEBUG: LHO environments: {envs_err}")

        datahubs = self._list_environment_datahubs()
        if not datahubs:
            log(f"ℹ️ No DataHub clusters found for Lakehouse Optimizer in {self.config.environment_name}")
            results["success"] = any_data
            return results

        for dh in datahubs:
            dh_name = dh.get("clusterName")
            dh_crn = dh.get("crn")
            if not dh_crn or not dh_name:
                continue
            dh_info = self._discover_datahub_lho(dh_name, dh_crn, lho_dir, ts)
            if dh_info:
                any_data = True
                results["datahubs"].append(dh_info)

        results["success"] = any_data
        if not any_data:
            log("ℹ️ No Lakehouse Optimizer data collected (service may be unavailable)")
        return results

    def _list_environment_datahubs(self):
        list_output, _ = self.client.list_datahub_clusters(self.config.environment_name)
        if not list_output:
            return []
        return list_output.get("clusters") or []

    def _discover_datahub_lho(self, dh_name, dh_crn, lho_dir, ts):
        dh_dir = lho_dir / dh_name
        dh_dir.mkdir(parents=True, exist_ok=True)
        info = {"name": dh_name, "crn": dh_crn, "policies": [], "health": None}

        health_json, health_err = self.client.get_lho_health(dh_crn)
        if health_json:
            save_to_file(health_json, dh_dir / f"lho_health_{ts}.json")
            self.exporter.save_flattened_json_to_csv(
                health_json, dh_dir / f"lho_health_{ts}.csv"
            )
            info["health"] = health_json
        elif self.config.debug:
            log(f"DEBUG: LHO health for {dh_name}: {health_err}")

        policies_json, policies_err = self.client.list_lho_policies(dh_crn)
        if not policies_json:
            if self.config.debug:
                log(f"DEBUG: LHO policies for {dh_name}: {policies_err}")
            return info if info["health"] else None

        policies = policies_json.get("policies") or []
        save_to_file(policies_json, dh_dir / f"lho_policies_{ts}.json")
        if policies:
            log(f"Found {len(policies)} LHO polic(ies) for {dh_name}")
            self.exporter.save_instance_groups_to_csv(
                dh_dir / f"lho_policies_{ts}.csv", policies
            )
        info["policies"] = policies

        policies_dir = dh_dir / "policies"
        policies_dir.mkdir(parents=True, exist_ok=True)
        for policy in policies:
            policy_name = policy.get("policyName")
            if not policy_name:
                continue
            policy_json, policy_err = self.client.get_lho_policy(dh_crn, policy_name)
            if not policy_json:
                if self.config.debug:
                    log(f"DEBUG: LHO policy {policy_name}: {policy_err}")
                continue
            safe_name = policy_name.replace("/", "_")
            subdir = policies_dir / safe_name
            subdir.mkdir(parents=True, exist_ok=True)
            save_to_file(policy_json, subdir / f"policy_{ts}.json")
            self.exporter.save_flattened_json_to_csv(
                policy_json, subdir / f"policy_{ts}.csv"
            )

        return info
