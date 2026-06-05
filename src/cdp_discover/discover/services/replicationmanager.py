#!/usr/bin/env python3
"""Replication Manager discovery module."""

from cdp_discover.discover.utils import log, save_to_file
from cdp_discover.discover.exporters.csv_exporter import CSVExporter
from cdp_discover.discover.diagnostics import save_diagnostic_collect


class ReplicationManagerDiscovery:
    """Discover Replication Manager policies and registered clusters."""

    def __init__(self, cdp_client, config):
        self.client = cdp_client
        self.config = config
        self.exporter = CSVExporter()

    def discover(self):
        log("🔄 Starting Replication Manager discovery...")
        results = {
            "policies": [],
            "clusters": [],
            "paired_hbase_clusters": [],
            "success": False,
        }
        rm_dir = self.config.get_service_dir("replicationmanager")
        ts = self.config.timestamp
        env_crn = self._environment_crn()
        any_data = False

        policies_json, policies_err = self.client.list_rm_policies()
        if policies_json:
            any_data = True
            policies = policies_json.get("policies") or []
            policies = self._filter_by_environment(policies, env_crn)
            save_to_file(
                {"policies": policies, "unreachableClusters": policies_json.get("unreachableClusters")},
                rm_dir / f"rm_policies_{ts}.json",
            )
            if policies:
                log(f"Found {len(policies)} Replication Manager polic(ies)")
                self.exporter.save_instance_groups_to_csv(
                    rm_dir / f"rm_policies_{ts}.csv", policies
                )
            results["policies"] = policies
        elif self.config.debug:
            log(f"DEBUG: RM policies: {policies_err}")

        clusters_json, clusters_err = self.client.list_rm_clusters()
        if clusters_json:
            any_data = True
            clusters = clusters_json.get("clusters") or []
            clusters = self._filter_clusters(clusters, env_crn)
            save_to_file(
                {
                    "clusters": clusters,
                    "unreachableClusters": clusters_json.get("unreachableClusters"),
                },
                rm_dir / f"rm_clusters_{ts}.json",
            )
            if clusters:
                log(f"Found {len(clusters)} Replication Manager cluster(s)")
                self.exporter.save_instance_groups_to_csv(
                    rm_dir / f"rm_clusters_{ts}.csv", clusters
                )
            self._discover_cluster_configs(clusters, rm_dir, ts)
            results["clusters"] = clusters
        elif self.config.debug:
            log(f"DEBUG: RM clusters: {clusters_err}")

        paired_json, paired_err = self.client.list_rm_paired_hbase_clusters()
        if paired_json:
            any_data = True
            paired = paired_json.get("pairedClusters") or paired_json.get("clusters") or []
            save_to_file(paired_json, rm_dir / f"rm_paired_hbase_clusters_{ts}.json")
            if paired:
                log(f"Found {len(paired)} paired HBase cluster(s)")
                self.exporter.save_instance_groups_to_csv(
                    rm_dir / f"rm_paired_hbase_clusters_{ts}.csv", paired
                )
            results["paired_hbase_clusters"] = paired
        elif self.config.debug:
            log(f"DEBUG: RM paired HBase clusters: {paired_err}")

        if self.config.exhaustive:
            self._discover_exhaustive_extras(rm_dir, ts, results.get("clusters") or [])

        results["success"] = any_data
        if not any_data:
            log("ℹ️ No Replication Manager data collected (service may be unavailable)")
        return results

    def _discover_cluster_configs(self, clusters, rm_dir, ts):
        clusters_dir = rm_dir / "clusters"
        clusters_dir.mkdir(parents=True, exist_ok=True)
        for cluster in clusters:
            crn = cluster.get("crn")
            name = cluster.get("name") or crn or "unknown"
            if not crn:
                continue
            config_json, config_err = self.client.get_rm_cluster_config(crn)
            if not config_json:
                if self.config.debug:
                    log(f"DEBUG: RM cluster config for {name}: {config_err}")
                continue
            safe_name = name.replace("/", "_")
            subdir = clusters_dir / safe_name
            subdir.mkdir(parents=True, exist_ok=True)
            save_to_file(config_json, subdir / f"cluster_config_{ts}.json")
            self.exporter.save_flattened_json_to_csv(
                config_json, subdir / f"cluster_config_{ts}.csv"
            )

    def _discover_exhaustive_extras(self, rm_dir, ts, clusters):
        """Tier 5 Replication Manager diagnostic collection per cluster."""
        for cluster in clusters:
            crn = cluster.get("crn")
            name = cluster.get("name") or crn or "unknown"
            if not crn:
                continue
            collect_json, collect_err = self.client.collect_rm_diagnostics(crn)
            if not collect_json:
                if self.config.debug:
                    log(f"DEBUG: collect RM diagnostics for {name}: {collect_err}")
                continue
            safe_name = name.replace("/", "_")
            subdir = rm_dir / "clusters" / safe_name
            subdir.mkdir(parents=True, exist_ok=True)
            save_diagnostic_collect(
                self.config,
                subdir,
                f"RM_{safe_name}",
                "Diagnostics",
                collect_json,
                self.exporter,
            )

    def _environment_crn(self):
        env_json, _ = self.client.describe_environment(self.config.environment_name)
        if not env_json:
            return None
        env = env_json.get("environment") or env_json
        return env.get("crn")

    def _filter_clusters(self, clusters, env_crn):
        if not clusters:
            return []
        if not env_crn:
            return [
                c for c in clusters
                if self.config.environment_name in (c.get("environmentCrn") or "")
                or self.config.environment_name in (c.get("name") or "")
            ]
        return [c for c in clusters if c.get("environmentCrn") == env_crn]

    def _filter_by_environment(self, items, env_crn):
        if not items:
            return []
        filtered = []
        for item in items:
            if env_crn and item.get("environmentCrn") == env_crn:
                filtered.append(item)
                continue
            haystack = " ".join(
                str(item.get(k, "")) for k in ("environmentCrn", "sourceClusterCrn", "targetClusterCrn", "name")
            )
            if self.config.environment_name in haystack:
                filtered.append(item)
        return filtered if filtered else items
