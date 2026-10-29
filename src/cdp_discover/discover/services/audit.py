#!/usr/bin/env python3
"""Audit archiving discovery module (account-level)."""

from cdp_discover.discover.utils import log, save_to_file
from cdp_discover.discover.exporters.csv_exporter import CSVExporter


class AuditDiscovery:
    """Discover audit archiving configuration and status."""

    def __init__(self, cdp_client, config):
        self.client = cdp_client
        self.config = config
        self.exporter = CSVExporter()

    def discover(self):
        log("📋 Starting Audit discovery...")
        results = {"success": False}
        audit_dir = self.config.get_service_dir("audit")
        ts = self.config.timestamp
        any_data = False

        config_json, config_err = self.client.get_audit_archiving_config()
        if config_json:
            any_data = True
            save_to_file(config_json, audit_dir / f"audit_archiving_config_{ts}.json")
            self.exporter.save_flattened_json_to_csv(
                config_json, audit_dir / f"audit_archiving_config_{ts}.csv"
            )
            results["archiving_config"] = config_json
        elif self.config.debug:
            log(f"DEBUG: audit archiving config: {config_err}")

        # get-archiving-status requires a --task-id that only the (mutating)
        # archive-audit-events call returns, so it is not part of read-only discovery.

        runs_json, runs_err = self.client.list_audit_recent_archive_runs()
        if runs_json:
            any_data = True
            save_to_file(runs_json, audit_dir / f"audit_recent_runs_{ts}.json")
            runs = runs_json.get("archiveRuns") or runs_json.get("runs") or []
            if runs:
                log(f"Found {len(runs)} recent audit archive run(s)")
                self.exporter.save_instance_groups_to_csv(
                    audit_dir / f"audit_recent_runs_{ts}.csv", runs
                )
            results["recent_runs"] = runs_json
        elif self.config.debug:
            log(f"DEBUG: audit recent runs: {runs_err}")

        batches_json, batches_err = self.client.list_audit_outstanding_archive_batches()
        if batches_json:
            any_data = True
            save_to_file(batches_json, audit_dir / f"audit_outstanding_batches_{ts}.json")
            batches = batches_json.get("batches") or batches_json.get("archiveBatches") or []
            if batches:
                log(f"Found {len(batches)} outstanding audit archive batch(es)")
                self.exporter.save_instance_groups_to_csv(
                    audit_dir / f"audit_outstanding_batches_{ts}.csv", batches
                )
            results["outstanding_batches"] = batches_json
        elif self.config.debug:
            log(f"DEBUG: audit outstanding batches: {batches_err}")

        results["success"] = any_data
        if not any_data:
            log("ℹ️ No Audit data collected (service may be unavailable)")
        return results
