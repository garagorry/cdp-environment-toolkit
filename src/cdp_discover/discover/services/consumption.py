#!/usr/bin/env python3
"""Consumption / billing discovery module (Tier 4 / full)."""

from cdp_discover.discover.utils import log, save_to_file
from cdp_discover.discover.exporters.csv_exporter import CSVExporter


class ConsumptionDiscovery:
    """Discover compute usage records (account-level)."""

    def __init__(self, cdp_client, config):
        self.client = cdp_client
        self.config = config
        self.exporter = CSVExporter()

    def discover(self):
        log("💰 Starting Consumption discovery...")
        results = {"usage_records": [], "success": False}
        cons_dir = self.config.get_service_dir("consumption")
        ts = self.config.timestamp

        usage_json, usage_err = self.client.list_compute_usage_records()
        if not usage_json:
            if self.config.debug:
                log(f"DEBUG: consumption usage records: {usage_err}")
            log("ℹ️ No Consumption data collected (service may be unavailable)")
            return results

        records = usage_json.get("computeUsageRecords") or usage_json.get("records") or []
        env_name = self.config.environment_name
        filtered = [
            r for r in records
            if env_name in str(r.get("environmentCrn", ""))
            or env_name in str(r.get("environmentName", ""))
            or env_name in str(r.get("resourceCrn", ""))
        ]
        if not filtered:
            filtered = records

        save_to_file(usage_json, cons_dir / f"consumption_usage_{ts}.json")
        if filtered:
            log(f"Found {len(filtered)} compute usage record(s)")
            self.exporter.save_instance_groups_to_csv(
                cons_dir / f"consumption_usage_{ts}.csv", filtered
            )

        results["usage_records"] = filtered
        results["success"] = True
        return results
