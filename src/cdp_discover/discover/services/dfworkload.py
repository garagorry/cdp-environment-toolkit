#!/usr/bin/env python3
"""DataFlow Workload (CFM) discovery module (Tier 3 / deep)."""

from cdp_discover.discover.utils import log, save_to_file
from cdp_discover.discover.exporters.csv_exporter import CSVExporter


class DFWorkloadDiscovery:
    """Discover NiFi deployment runtime configuration via dfworkload APIs."""

    def __init__(self, cdp_client, config):
        self.client = cdp_client
        self.config = config
        self.exporter = CSVExporter()

    def discover(self):
        log("⚙️ Starting DataFlow Workload (CFM) discovery...")
        results = {"deployments": [], "success": False}
        dfw_dir = self.config.get_service_dir("dfworkload")
        ts = self.config.timestamp

        env_crn = self._environment_crn()
        if not env_crn:
            log("⚠️ Could not resolve environment CRN for dfworkload")
            return results

        any_data = self._discover_environment_scoped(dfw_dir, ts, env_crn)
        deployment_configs = self._discover_deployment_configs(dfw_dir, ts, env_crn)
        if deployment_configs:
            any_data = True
            results["deployments"] = deployment_configs
        if self.config.exhaustive:
            any_data = self._discover_exhaustive_extras(dfw_dir, ts, env_crn) or any_data

        results["success"] = any_data
        if not any_data:
            log("ℹ️ No dfworkload data collected (service may be unavailable)")
        return results

    def _discover_environment_scoped(self, dfw_dir, ts, env_crn):
        any_data = False
        calls = [
            ("flow_drafts", self.client.list_dfw_flow_drafts, "flowDrafts"),
            ("inbound_endpoints", self.client.list_dfw_inbound_connection_endpoints, "inboundConnectionEndpoints"),
            ("deployment_archives", self.client.list_dfw_deployment_archives, "deploymentArchives"),
            ("parameter_groups", self.client.list_dfw_parameter_groups, "parameterGroups"),
            ("nifi_versions", self.client.list_dfw_nifi_versions, "nifiVersions"),
        ]
        for suffix, method, list_key in calls:
            data, err = method(env_crn)
            if not data:
                if self.config.debug:
                    log(f"DEBUG: dfworkload {suffix}: {err}")
                continue
            any_data = True
            save_to_file(data, dfw_dir / f"dfw_{suffix}_{ts}.json")
            items = data.get(list_key)
            if isinstance(items, list) and items:
                self.exporter.save_instance_groups_to_csv(
                    dfw_dir / f"dfw_{suffix}_{ts}.csv", items
                )
            else:
                self.exporter.save_flattened_json_to_csv(
                    data, dfw_dir / f"dfw_{suffix}_{ts}.csv"
                )
        return any_data

    def _discover_deployment_configs(self, dfw_dir, ts, env_crn):
        deployments_dir = dfw_dir / "deployments"
        deployments_dir.mkdir(parents=True, exist_ok=True)
        configured = []

        services_json, _ = self.client.list_cdf_services()
        if not services_json:
            return configured

        for service in services_json.get("services") or []:
            if not self._service_matches_environment(service):
                continue
            service_crn = service.get("crn")
            if not service_crn:
                continue
            dep_json, _ = self.client.list_cdf_deployments(service_crn)
            deployments = (dep_json or {}).get("deployments") or []
            deployments = [
                d for d in deployments
                if (d.get("service") or {}).get("crn") == service_crn
            ]
            for deployment in deployments:
                deployment_crn = deployment.get("crn")
                deployment_name = deployment.get("name") or deployment_crn
                if not deployment_crn:
                    continue
                config_json, err = self.client.get_dfw_deployment_configuration(
                    deployment_crn, env_crn
                )
                if not config_json:
                    if self.config.debug:
                        log(f"DEBUG: dfw deployment config {deployment_name}: {err}")
                    continue
                subdir = deployments_dir / deployment_name
                subdir.mkdir(parents=True, exist_ok=True)
                save_to_file(config_json, subdir / f"deployment_config_{ts}.json")
                self.exporter.save_flattened_json_to_csv(
                    config_json, subdir / f"deployment_config_{ts}.csv"
                )
                configured.append(
                    {"name": deployment_name, "crn": deployment_crn, "config": config_json}
                )
        if configured:
            log(f"Collected dfworkload config for {len(configured)} deployment(s)")
        return configured

    def _discover_exhaustive_extras(self, dfw_dir, ts, env_crn):
        """Tier 5 dfworkload reporting tasks."""
        data, err = self.client.list_dfw_reporting_tasks(env_crn)
        if not data:
            if self.config.debug:
                log(f"DEBUG: dfworkload reporting tasks: {err}")
            return False
        save_to_file(data, dfw_dir / f"dfw_reporting_tasks_{ts}.json")
        items = data.get("reportingTasks") or data.get("tasks") or []
        if items:
            self.exporter.save_instance_groups_to_csv(
                dfw_dir / f"dfw_reporting_tasks_{ts}.csv", items
            )
        else:
            self.exporter.save_flattened_json_to_csv(
                data, dfw_dir / f"dfw_reporting_tasks_{ts}.csv"
            )
        return True

    def _service_matches_environment(self, service):
        if service.get("name") == self.config.environment_name:
            return True
        env_crn = service.get("environmentCrn") or ""
        return self.config.environment_name in env_crn

    def _environment_crn(self):
        env_json, _ = self.client.describe_environment(self.config.environment_name)
        if not env_json:
            return None
        env = env_json.get("environment") or env_json
        return env.get("crn")
