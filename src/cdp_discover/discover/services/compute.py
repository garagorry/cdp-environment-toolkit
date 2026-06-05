#!/usr/bin/env python3
"""Compute (Open Lakehouse) discovery module (Tier 4 / full)."""

from cdp_discover.discover.utils import log, save_to_file
from cdp_discover.discover.exporters.csv_exporter import CSVExporter


class ComputeDiscovery:
    """Discover compute clusters and deployments for an environment."""

    def __init__(self, cdp_client, config):
        self.client = cdp_client
        self.config = config
        self.exporter = CSVExporter()

    def discover(self):
        log("🖥️ Starting Compute discovery...")
        results = {"clusters": [], "deployments": [], "success": False}
        compute_dir = self.config.get_service_dir("compute")
        ts = self.config.timestamp
        env_key = self._environment_key()

        clusters_json, clusters_err = self.client.list_compute_clusters(env_key)
        if not clusters_json:
            if self.config.debug:
                log(f"DEBUG: compute clusters: {clusters_err}")
            log("ℹ️ No Compute data collected (service may be unavailable)")
            return results

        clusters = clusters_json.get("clusters") or []
        save_to_file(clusters_json, compute_dir / f"compute_clusters_{ts}.json")
        if clusters:
            log(f"Found {len(clusters)} compute cluster(s)")
            self.exporter.save_instance_groups_to_csv(
                compute_dir / f"compute_clusters_{ts}.csv", clusters
            )

        clusters_dir = compute_dir / "clusters"
        clusters_dir.mkdir(parents=True, exist_ok=True)
        all_deployments = []

        for cluster in clusters:
            crn = cluster.get("crn")
            name = cluster.get("name") or crn or "unknown"
            if not crn:
                continue

            describe, err = self.client.describe_compute_cluster(crn)
            if describe:
                safe_name = name.replace("/", "_")
                subdir = clusters_dir / safe_name
                subdir.mkdir(parents=True, exist_ok=True)
                save_to_file(describe, subdir / f"cluster_describe_{ts}.json")
                self.exporter.save_flattened_json_to_csv(
                    describe, subdir / f"cluster_describe_{ts}.csv"
                )

            dep_json, dep_err = self.client.list_compute_deployments(crn)
            if not dep_json:
                if self.config.debug:
                    log(f"DEBUG: compute deployments for {name}: {dep_err}")
                continue

            deployments = dep_json.get("deployments") or []
            save_to_file(dep_json, clusters_dir / f"{name}_deployments_list_{ts}.json")
            dep_dir = clusters_dir / name / "deployments"
            dep_dir.mkdir(parents=True, exist_ok=True)

            for deployment in deployments:
                dep_name = deployment.get("name")
                namespace = deployment.get("namespace")
                if not dep_name:
                    continue
                dep_desc, dep_desc_err = self.client.describe_compute_deployment(
                    crn, dep_name, namespace=namespace
                )
                if dep_desc:
                    save_to_file(
                        dep_desc,
                        dep_dir / f"deployment_{dep_name}_{ts}.json",
                    )
                    all_deployments.append({
                        "clusterName": name,
                        "clusterCrn": crn,
                        "deployment": dep_desc.get("deployment", dep_desc),
                    })
                elif self.config.debug:
                    log(f"DEBUG: compute deployment {dep_name}: {dep_desc_err}")

        results["clusters"] = clusters
        results["deployments"] = all_deployments
        results["success"] = bool(clusters)
        return results

    def _environment_key(self):
        env_json, _ = self.client.describe_environment(self.config.environment_name)
        if env_json:
            env = env_json.get("environment") or env_json
            return env.get("crn") or self.config.environment_name
        return self.config.environment_name
