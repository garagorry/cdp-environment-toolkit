#!/usr/bin/env python3
"""DataHub discovery module."""

from pathlib import Path
import json


from cdp_discover.discover.utils import log, save_to_file, run_command_json, save_recipe_script
from cdp_discover.discover.exporters.csv_exporter import CSVExporter
from cdp_discover.discover.diagnostics import save_diagnostic_collect, save_diagnostic_job_describes



class DatahubDiscovery:
    """Discover DataHub cluster details."""
    
    def __init__(self, cdp_client, config):
        """
        Initialize datahub discovery.
        
        Args:
            cdp_client: CDPClient instance
            config: DiscoveryConfig instance
        """
        self.client = cdp_client
        self.config = config
        self.exporter = CSVExporter()
    
    def discover(self, specific_datahub=None):
        """
        Discover all DataHub clusters in the environment.
        
        Args:
            specific_datahub: Optional specific DataHub name to discover
            
        Returns:
            dict: Discovery results with datahub details
        """
        log("🧩 Starting DataHub discovery...")
        
        results = {
            'datahubs': [],
            'success': False
        }
        
        # List DataHub clusters
        list_output, list_err = self.client.list_datahub_clusters(self.config.environment_name)
        
        if not list_output:
            log("⚠️ Could not list DataHub clusters")
            if self.config.debug:
                log(f"DEBUG: list_err: {list_err}")
            return results
        
        all_clusters = list_output.get("clusters", [])
        
        # Filter to specific cluster if requested
        if specific_datahub:
            clusters = [c for c in all_clusters if c.get('clusterName') == specific_datahub]
            if not clusters:
                log(f"⚠️ No DataHub cluster found with name '{specific_datahub}'")
                if all_clusters:
                    log("Available clusters in this environment:")
                    for c in all_clusters:
                        log(f"  - {c.get('clusterName')}")
                return results
            log(f"Found specific cluster: {specific_datahub}")
        else:
            clusters = all_clusters
        
        if not clusters:
            log("ℹ️ No DataHub clusters found")
            return results
        
        log(f"Found {len(clusters)} DataHub cluster(s):")
        for c in clusters:
            log(f"  - {c.get('clusterName')}")
        
        all_instance_rows = []
        
        # Discover each cluster
        for cluster in clusters:
            cluster_info = self._discover_single_cluster(
                cluster,
                all_instance_rows
            )
            if cluster_info:
                results['datahubs'].append(cluster_info)
        
        if all_instance_rows:
            if specific_datahub:
                csv_name = f"{self.config.environment_name}_{specific_datahub}_datahub_instance_groups.csv"
            else:
                csv_name = f"ALL_{self.config.environment_name}_datahub_instance_groups.csv"
            csv_path = self.config.output_dir / csv_name
            self.exporter.save_instance_groups_to_csv(csv_path, all_instance_rows)

        if self.config.full:
            self._discover_full_account_extras()
        
        results['success'] = True
        return results
    
    def _discover_single_cluster(self, cluster, all_instance_rows):
        """
        Discover details for a single DataHub cluster.
        
        Args:
            cluster: Cluster summary object
            all_instance_rows: List to collect instance group rows
            
        Returns:
            dict: Cluster details or None if failed
        """
        name = cluster.get("clusterName")
        crn = cluster.get("crn")
        
        if not name or not crn:
            log(f"⚠️ Skipping cluster with missing name or CRN")
            return None
        
        cluster_dir = self.config.get_service_dir("datahub") / name
        cluster_dir.mkdir(parents=True, exist_ok=True)
        
        output_prefix = self.config.get_output_prefix("DH", name)
        
        # 1. Describe the cluster
        describe, describe_err = self.client.describe_datahub_cluster(crn)
        
        if not describe:
            log(f"⚠️ Could not describe cluster {name}")
            if self.config.debug:
                log(f"DEBUG: describe_err: {describe_err}")
            return None
        
        # Save JSON
        json_path = cluster_dir / f"{output_prefix}_{self.config.timestamp}.json"
        save_to_file(describe, json_path)
        
        cluster_obj = describe.get("cluster", {})
        
        # 2. Instance groups
        instance_groups = cluster_obj.get("instanceGroups", [])
        rows = self._flatten_instance_groups(name, instance_groups)
        
        if rows:
            ig_csv_path = cluster_dir / f"{output_prefix}_InstanceGroups_{self.config.timestamp}.csv"
            self.exporter.save_instance_groups_to_csv(ig_csv_path, rows)
            all_instance_rows.extend(rows)
        
        # 3. Collect and describe recipes for THIS cluster
        cluster_recipes_set = set()
        for ig in instance_groups:
            for recipe in ig.get("recipes", []):
                if recipe:  # Only add non-None recipes
                    cluster_recipes_set.add(recipe)
        
        if cluster_recipes_set:
            recipe_dir = cluster_dir / "recipes"
            self._describe_recipes_for_cluster(recipe_dir, cluster_recipes_set)
        
        # 4. Describe cluster template
        self._describe_cluster_template(cluster_obj, name, cluster_dir, output_prefix)
        
        # 5. Check upgrade images
        self._check_upgrade_images(crn, name, cluster_dir, output_prefix)
        
        # 6. Database server
        db_server, db_err = self.client.describe_datahub_database_server(crn)
        if db_server:
            db_path = cluster_dir / f"{output_prefix}_DB_{self.config.timestamp}.json"
            save_to_file(db_server, db_path)
        else:
            if self.config.debug:
                log(f"DEBUG: Could not describe DB server for {name}: {db_err}")
        
        # 7. Cluster service status
        status_json, status_err = self.client.get_datahub_cluster_service_status(crn)
        if status_json:
            status_path = cluster_dir / f"{output_prefix}_ServiceStatus_{self.config.timestamp}.json"
            save_to_file(status_json, status_path)
            status_csv_path = cluster_dir / f"{output_prefix}_ServiceStatus_{self.config.timestamp}.csv"
            self.exporter.save_flattened_json_to_csv(status_json, status_csv_path)
        elif self.config.debug:
            log(f"DEBUG: DataHub service status for {name}: {status_err}")
        
        # 8. Lifecycle events
        lifecycle_json, lifecycle_err = self.client.list_datahub_cluster_lifecycle_events(crn)
        if lifecycle_json:
            lifecycle_path = cluster_dir / f"{output_prefix}_LifecycleEvents_{self.config.timestamp}.json"
            save_to_file(lifecycle_json, lifecycle_path)
            lifecycle_csv_path = cluster_dir / f"{output_prefix}_LifecycleEvents_{self.config.timestamp}.csv"
            self.exporter.save_flattened_json_to_csv(lifecycle_json, lifecycle_csv_path)
        elif self.config.debug:
            log(f"DEBUG: DataHub lifecycle events for {name}: {lifecycle_err}")
        
        # 9. Cluster host status
        host_json, host_err = self.client.get_datahub_cluster_host_status(crn)
        if host_json:
            host_path = cluster_dir / f"{output_prefix}_HostStatus_{self.config.timestamp}.json"
            save_to_file(host_json, host_path)
            host_csv_path = cluster_dir / f"{output_prefix}_HostStatus_{self.config.timestamp}.csv"
            self.exporter.save_flattened_json_to_csv(host_json, host_csv_path)
        elif self.config.debug:
            log(f"DEBUG: DataHub host status for {name}: {host_err}")
        
        # 10. Autoscale rules and history
        rules_json, rules_err = self.client.describe_datahub_auto_scale_rules(crn)
        if rules_json:
            rules_path = cluster_dir / f"{output_prefix}_AutoScaleRules_{self.config.timestamp}.json"
            save_to_file(rules_json, rules_path)
            rules_csv_path = cluster_dir / f"{output_prefix}_AutoScaleRules_{self.config.timestamp}.csv"
            self.exporter.save_flattened_json_to_csv(rules_json, rules_csv_path)
        elif self.config.debug:
            log(f"DEBUG: DataHub autoscale rules for {name}: {rules_err}")
        
        history_json, history_err = self.client.list_datahub_auto_scale_history(crn)
        if history_json:
            history_path = cluster_dir / f"{output_prefix}_AutoScaleHistory_{self.config.timestamp}.json"
            save_to_file(history_json, history_path)
            history_csv_path = cluster_dir / f"{output_prefix}_AutoScaleHistory_{self.config.timestamp}.csv"
            self.exporter.save_flattened_json_to_csv(history_json, history_csv_path)
        elif self.config.debug:
            log(f"DEBUG: DataHub autoscale history for {name}: {history_err}")
        
        if self.config.deep:
            self._discover_deep_extras(crn, name, cluster_dir, output_prefix)
        if self.config.full:
            self._discover_full_extras(crn, name, cluster_dir, output_prefix)
        if self.config.exhaustive:
            self._discover_exhaustive_extras(crn, name, cluster_dir, output_prefix)
        
        return {
            'name': name,
            'crn': crn,
            'details': cluster_obj
        }
    
    def _flatten_instance_groups(self, cluster_name, instance_groups):
        """Flatten instance groups for CSV export."""
        rows = []
        
        for ig in instance_groups:
            ig_name = ig.get("name")
            azs = ",".join(filter(None, ig.get("availabilityZones", [])))
            subnets = ",".join(filter(None, ig.get("subnetIds", [])))
            recipes = ",".join(filter(None, ig.get("recipes", [])))
            
            for inst in ig.get("instances", []):
                base = {
                    "environment": self.config.environment_name,
                    "clusterName": cluster_name,
                    "instanceGroupName": ig_name,
                    "availabilityZones": azs,
                    "subnetIds": subnets,
                    "recipes": recipes,
                    "nodeGroupRole": inst.get("instanceGroup"),
                    "instanceId": inst.get("id"),
                    "state": inst.get("state"),
                    "instanceType": inst.get("instanceType"),
                    "privateIp": inst.get("privateIp"),
                    "publicIp": inst.get("publicIp"),
                    "fqdn": inst.get("fqdn"),
                    "status": inst.get("status"),
                    "statusReason": inst.get("statusReason"),
                    "sshPort": inst.get("sshPort"),
                    "clouderaManagerServer": inst.get("clouderaManagerServer"),
                    "availabilityZone": inst.get("availabilityZone"),
                    "instanceVmType": inst.get("instanceVmType"),
                    "rackId": inst.get("rackId"),
                    "subnetId": inst.get("subnetId")
                }
                
                volumes = inst.get("attachedVolumes", [])
                if volumes:
                    for vol in volumes:
                        row = base.copy()
                        row.update({
                            "volumeCount": vol.get("count"),
                            "volumeType": vol.get("volumeType"),
                            "volumeSize": vol.get("size")
                        })
                        rows.append(row)
                else:
                    base.update({
                        "volumeCount": None,
                        "volumeType": None,
                        "volumeSize": None
                    })
                    rows.append(base)
        
        return rows
    
    def _describe_cluster_template(self, cluster_obj, name, cluster_dir, output_prefix):
        """Describe and save cluster template."""
        template_crn = cluster_obj.get("clusterTemplateCrn")
        
        if not template_crn:
            log(f"⚠️ No clusterTemplateCrn found for {name}")
            return
        
        cmd = f"cdp datahub describe-cluster-template --profile {self.client.profile} --cluster-template-name {template_crn}"
        template, template_err = run_command_json(
            cmd,
            task_name=f"Describing template for {name}",
            debug=self.config.debug
        )
        
        if not template:
            log(f"⚠️ Could not describe template for {name}")
            return
        
        cluster_template = template.get("clusterTemplate", {})
        status = cluster_template.get("status")
        template_name = cluster_template.get("clusterTemplateName", "").strip()
        content = cluster_template.get("clusterTemplateContent")
        
        # Save template JSON
        template_path = cluster_dir / f"{output_prefix}_Template_{self.config.timestamp}.json"
        save_to_file({"clusterTemplate": cluster_template}, template_path)
        
        # Save template content if available
        if status in ("USER_MANAGED", "DEFAULT") and content:
            safe_template_name = template_name.replace(" ", "_").replace("/", "_").replace("\\", "_")
            content_path = cluster_dir / f"{safe_template_name}_content.json"
            try:
                parsed_content = json.loads(content)
                with open(content_path, "w", encoding="utf-8") as f:
                    json.dump(parsed_content, f, indent=4)
                log(f"✅ Pretty-printed template content saved to {content_path}")
            except json.JSONDecodeError:
                log(f"⚠️ Failed to parse JSON content from template {template_name}, saving raw.")
                with open(content_path, "w", encoding="utf-8") as f:
                    f.write(content)
        elif status == "SERVICE_MANAGED":
            log(f"ℹ️ Skipping content extraction for {name} (SERVICE_MANAGED template)")
    
    def _check_upgrade_images(self, crn, name, cluster_dir, output_prefix):
        """Check available upgrade images for cluster."""
        upgrades = [
            ("AvailableImages", "Checking available upgrade images", "--show-available-images"),
            ("RunTimeAvailableImages", "Checking latest runtime image", "--show-latest-available-image-per-runtime")
        ]
        
        for suffix, label, flag in upgrades:
            cmd = f"cdp datahub upgrade-cluster --profile {self.client.profile} {flag} --cluster-name {crn}"
            data, err = run_command_json(
                cmd,
                task_name=f"{label} for {name}",
                debug=self.config.debug
            )
            
            if data:
                upgrade_path = cluster_dir / f"{output_prefix}_{suffix}_{self.config.timestamp}.json"
                save_to_file(data, upgrade_path)
    
    def _describe_recipes_for_cluster(self, recipe_dir, recipes_set):
        """
        Describe all unique recipes for a specific cluster.
        
        Note: All recipes (FreeIPA, DataLake, DataHub, COD) use the same CDP CLI command:
        'cdp datahub describe-recipe'
        
        Args:
            recipe_dir: Directory to save recipes for this cluster
            recipes_set: Set of unique recipe names for this cluster
        """
        if not recipes_set:
            return
        
        recipe_dir.mkdir(parents=True, exist_ok=True)
        
        
        for recipe_name in sorted(recipes_set):
            cmd = f"cdp datahub describe-recipe --profile {self.client.profile} --recipe-name {recipe_name}"
            describe, err = run_command_json(
                cmd,
                task_name=f"Describing recipe {recipe_name}",
                debug=self.config.debug
            )
            
            if describe:
                json_path = recipe_dir / f"recipe_{recipe_name}.json"
                save_to_file(describe, json_path)
                
                recipe_content = describe.get("recipe", {}).get("recipeContent")
                if recipe_content:
                    script_path = recipe_dir / f"recipe_{recipe_name}.sh"
                    save_recipe_script(recipe_content, script_path)
            else:
                log(f"⚠️ Failed to describe recipe: {recipe_name}")

    def _discover_deep_extras(self, crn, name, cluster_dir, output_prefix):
        """Tier 3 DataHub diagnostics metadata and scaling activities."""
        diag_json, diag_err = self.client.list_datahub_diagnostics(crn)
        if diag_json:
            path = cluster_dir / f"{output_prefix}_DiagnosticsList_{self.config.timestamp}.json"
            save_to_file(diag_json, path)
            self.exporter.save_flattened_json_to_csv(
                diag_json, cluster_dir / f"{output_prefix}_DiagnosticsList_{self.config.timestamp}.csv"
            )
        elif self.config.debug:
            log(f"DEBUG: DataHub diagnostics list for {name}: {diag_err}")

        scaling_json, scaling_err = self.client.list_datahub_scaling_activities(crn)
        if scaling_json:
            path = cluster_dir / f"{output_prefix}_ScalingActivities_{self.config.timestamp}.json"
            save_to_file(scaling_json, path)
            self.exporter.save_flattened_json_to_csv(
                scaling_json, cluster_dir / f"{output_prefix}_ScalingActivities_{self.config.timestamp}.csv"
            )
        elif self.config.debug:
            log(f"DEBUG: DataHub scaling activities for {name}: {scaling_err}")

    def _discover_full_account_extras(self):
        """Tier 4 account-level DataHub cluster definition catalog."""
        dh_dir = self.config.get_service_dir("datahub")
        ts = self.config.timestamp
        prefix = f"ENV_{self.config.environment_name}"
        defs_json, defs_err = self.client.list_datahub_cluster_definitions()
        if defs_json:
            path = dh_dir / f"{prefix}_ClusterDefinitions_{ts}.json"
            save_to_file(defs_json, path)
            definitions = defs_json.get("clusterDefinitions") or defs_json.get("definitions") or []
            if definitions:
                self.exporter.save_instance_groups_to_csv(
                    dh_dir / f"{prefix}_ClusterDefinitions_{ts}.csv", definitions
                )
        elif self.config.debug:
            log(f"DEBUG: DataHub cluster definitions: {defs_err}")

    def _discover_full_extras(self, crn, name, cluster_dir, output_prefix):
        """Tier 4 DataHub scaling activity detail."""
        scaling_json, scaling_err = self.client.list_datahub_scaling_activities(crn)
        if not scaling_json:
            if self.config.debug:
                log(f"DEBUG: DataHub scaling activities for {name}: {scaling_err}")
            return

        activities = scaling_json.get("scalingActivities") or scaling_json.get("activities") or []
        details = []
        for activity in activities:
            operation_id = activity.get("operationId") or activity.get("id") or activity.get("activityId")
            if not operation_id:
                continue
            detail_json, detail_err = self.client.describe_datahub_scaling_activity(name, operation_id)
            if detail_json:
                details.append(detail_json)
            elif self.config.debug:
                log(f"DEBUG: scaling activity {operation_id} for {name}: {detail_err}")

        if details:
            path = cluster_dir / f"{output_prefix}_ScalingActivityDetails_{self.config.timestamp}.json"
            save_to_file({"scalingActivityDetails": details}, path)
            self.exporter.save_instance_groups_to_csv(
                cluster_dir / f"{output_prefix}_ScalingActivityDetails_{self.config.timestamp}.csv",
                details,
            )

    def _discover_exhaustive_extras(self, crn, name, cluster_dir, output_prefix):
        """Tier 5 DataHub diagnostic bundle collection."""
        for label, method in (
            ("DataHub", self.client.collect_datahub_diagnostics),
            ("Cm", self.client.collect_datahub_cm_diagnostics),
        ):
            collect_json, collect_err = method(crn)
            if collect_json:
                save_diagnostic_collect(
                    self.config,
                    cluster_dir,
                    output_prefix,
                    label,
                    collect_json,
                    self.exporter,
                    poll_fn=self.client.get_datahub_operation,
                )
            elif self.config.debug:
                log(f"DEBUG: collect DataHub {label} diagnostics for {name}: {collect_err}")

