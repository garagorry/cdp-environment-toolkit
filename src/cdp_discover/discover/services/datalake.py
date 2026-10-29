#!/usr/bin/env python3
"""DataLake discovery module."""

from pathlib import Path


from cdp_discover.discover.utils import (
    check_expected_fields,
    log,
    save_recipe_script,
    save_to_file,
)
from cdp_discover.discover.exporters.csv_exporter import CSVExporter
from cdp_discover.discover.diagnostics import save_diagnostic_collect



class DatalakeDiscovery:
    """Discover DataLake details."""
    
    def __init__(self, cdp_client, config):
        """
        Initialize datalake discovery.
        
        Args:
            cdp_client: CDPClient instance
            config: DiscoveryConfig instance
        """
        self.client = cdp_client
        self.config = config
        self.exporter = CSVExporter()
    
    def discover(self):
        """
        Discover all datalakes in the environment.
        
        Returns:
            dict: Discovery results with datalake details
        """
        log("🛢️ Starting DataLake discovery...")
        
        results = {
            'datalakes': [],
            'success': False
        }
        
        # List datalakes
        datalake_list_json, datalake_list_err = self.client.list_datalakes(
            self.config.environment_name
        )
        
        datalakes = datalake_list_json.get("datalakes", []) if datalake_list_json else []
        
        if not datalakes:
            log("ℹ️ No datalakes found in this environment")
            if self.config.debug:
                log(f"DEBUG: datalake_list_json: {datalake_list_json}")
                log(f"DEBUG: datalake_list_err: {datalake_list_err}")
            return results
        
        log(f"Found {len(datalakes)} datalake(s):")
        for dl in datalakes:
            log(f"  - {dl.get('datalakeName')}")
        
        all_datalake_instance_rows = []
        datalake_recipes_set = set()
        
        # Discover each datalake
        for datalake in datalakes:
            datalake_info = self._discover_single_datalake(
                datalake, 
                all_datalake_instance_rows
            )
            if datalake_info:
                results['datalakes'].append(datalake_info)
        
        # Save aggregated instance groups
        if all_datalake_instance_rows:
            csv_path = self.config.output_dir / f"ALL_{self.config.environment_name}_datalake_instance_groups.csv"
            self.exporter.save_instance_groups_to_csv(csv_path, all_datalake_instance_rows)
        
        self._discover_datalake_runtimes()
        
        results['success'] = True
        return results
    
    def _discover_datalake_runtimes(self):
        """Fetch account-level datalake runtimes once per discovery run."""
        runtimes_json, runtimes_err = self.client.list_datalake_runtimes()
        if not runtimes_json:
            if self.config.debug:
                log(f"DEBUG: datalake runtimes: {runtimes_err}")
            return
        
        dl_root = self.config.get_service_dir("datalake")
        dl_root.mkdir(parents=True, exist_ok=True)
        path = dl_root / f"datalake_runtimes_{self.config.timestamp}.json"
        save_to_file(runtimes_json, path)
        csv_path = dl_root / f"datalake_runtimes_{self.config.timestamp}.csv"
        self.exporter.save_flattened_json_to_csv(runtimes_json, csv_path)
    
    def _discover_single_datalake(self, datalake, all_instance_rows):
        """
        Discover details for a single datalake.
        
        Args:
            datalake: Datalake summary object
            all_instance_rows: List to collect instance group rows
            
        Returns:
            dict: Datalake details or None if failed
        """
        datalake_crn = datalake.get("crn")
        datalake_name = datalake.get("datalakeName")
        
        if not datalake_crn or not datalake_name:
            log(f"⚠️ Skipping datalake with missing CRN or name")
            return None
        
        dl_dir = self.config.get_service_dir("datalake") / datalake_name
        dl_dir.mkdir(parents=True, exist_ok=True)
        
        output_prefix = self.config.get_output_prefix("DL", datalake_name)
        
        # 1. Describe the datalake
        describe_dl_json, describe_dl_err = self.client.describe_datalake(datalake_crn)
        
        if not describe_dl_json:
            log(f"⚠️ Could not describe datalake {datalake_name}")
            if self.config.debug:
                log(f"DEBUG: describe_dl_err: {describe_dl_err}")
            return None
        
        dl_obj = describe_dl_json.get("datalake", describe_dl_json.get("datalakeDetails", describe_dl_json))
        missing = check_expected_fields(dl_obj, ["clouderaManager.version"], f"Data Lake {datalake_name}")
        self.client.note_missing_fields("datalake", datalake_name, missing)

        # Save JSON
        json_path = dl_dir / f"{output_prefix}_{self.config.timestamp}.json"
        save_to_file(describe_dl_json, json_path)
        
        # Save flattened CSV
        csv_path = dl_dir / f"{output_prefix}_{self.config.timestamp}.csv"
        self.exporter.save_flattened_json_to_csv(dl_obj, csv_path)
        
        # 2. Instance groups
        dl_instance_groups_rows = self._flatten_datalake_instance_groups(datalake_name, dl_obj)
        if dl_instance_groups_rows:
            ig_csv_path = dl_dir / f"{output_prefix}_InstanceGroups_{self.config.timestamp}.csv"
            self.exporter.save_instance_groups_to_csv(ig_csv_path, dl_instance_groups_rows)
            all_instance_rows.extend(dl_instance_groups_rows)
        
        # 3. Collect and describe recipes for THIS datalake
        datalake_recipes_set = set()
        self._collect_recipes(dl_obj, datalake_recipes_set)
        if datalake_recipes_set:
            recipe_dir = dl_dir / "recipes"
            self._describe_recipes_for_datalake(recipe_dir, datalake_recipes_set)
        
        # 4. Database server
        describe_db_json, describe_db_err = self.client.describe_datalake_database_server(datalake_crn)
        if describe_db_json:
            db_path = dl_dir / f"{output_prefix}_DB_{self.config.timestamp}.json"
            save_to_file(describe_db_json, db_path)
            db_csv_path = dl_dir / f"{output_prefix}_DB_{self.config.timestamp}.csv"
            self.exporter.save_flattened_json_to_csv(describe_db_json, db_csv_path)
        
        # 5. Cluster service status
        status_json, status_err = self.client.get_datalake_cluster_service_status(datalake_crn)
        if status_json:
            status_path = dl_dir / f"{output_prefix}_ServiceStatus_{self.config.timestamp}.json"
            save_to_file(status_json, status_path)
            status_csv_path = dl_dir / f"{output_prefix}_ServiceStatus_{self.config.timestamp}.csv"
            self.exporter.save_flattened_json_to_csv(status_json, status_csv_path)
        elif self.config.debug:
            log(f"DEBUG: datalake service status for {datalake_name}: {status_err}")
        
        # 6. Cluster host status
        host_json, host_err = self.client.get_datalake_cluster_host_status(datalake_crn)
        if host_json:
            host_path = dl_dir / f"{output_prefix}_HostStatus_{self.config.timestamp}.json"
            save_to_file(host_json, host_path)
            host_csv_path = dl_dir / f"{output_prefix}_HostStatus_{self.config.timestamp}.csv"
            self.exporter.save_flattened_json_to_csv(host_json, host_csv_path)
        elif self.config.debug:
            log(f"DEBUG: datalake host status for {datalake_name}: {host_err}")
        
        # 7. Upgrade images
        self._check_upgrade_images(datalake_crn, datalake_name, dl_dir, output_prefix)
        
        if self.config.deep:
            self._discover_deep_extras(datalake_crn, datalake_name, dl_dir, output_prefix)
        if self.config.exhaustive:
            self._discover_exhaustive_extras(datalake_crn, datalake_name, dl_dir, output_prefix)
        
        return {
            'name': datalake_name,
            'crn': datalake_crn,
            'details': dl_obj
        }
    
    def _flatten_datalake_instance_groups(self, datalake_name, datalake_obj):
        """Flatten datalake instance groups for CSV export."""
        rows = []
        
        # Try top-level instanceGroups first
        instance_groups = datalake_obj.get("instanceGroups", [])
        
        if instance_groups:
            rows.extend(self._process_instance_groups(datalake_name, instance_groups))
        else:
            # Try cloud provider configuration
            for config_key in ["awsConfiguration", "azureConfiguration", "gcpConfiguration"]:
                config = datalake_obj.get(config_key, {})
                if isinstance(config, dict):
                    instance_groups = config.get("instanceGroups", [])
                    rows.extend(self._process_instance_groups(datalake_name, instance_groups))
        
        return rows
    
    def _process_instance_groups(self, datalake_name, instance_groups):
        """Process instance groups and return flattened rows."""
        rows = []
        
        for ig in instance_groups:
            ig_name = ig.get("name")
            azs = ",".join(filter(None, ig.get("availabilityZones", [])))
            recipes = ",".join(filter(None, ig.get("recipes", [])))
            
            for inst in ig.get("instances", []):
                base = {
                    "environment": self.config.environment_name,
                    "datalakeName": datalake_name,
                    "instanceGroupName": ig_name,
                    "availabilityZones": azs,
                    "recipes": recipes,
                    "nodeGroupRole": inst.get("instanceGroup"),
                    "instanceId": inst.get("id"),
                    "state": inst.get("state"),
                    "discoveryFQDN": inst.get("discoveryFQDN"),
                    "instanceStatus": inst.get("instanceStatus"),
                    "statusReason": inst.get("statusReason"),
                    "privateIp": inst.get("privateIp"),
                    "publicIp": inst.get("publicIp"),
                    "sshPort": inst.get("sshPort"),
                    "clouderaManagerServer": inst.get("clouderaManagerServer"),
                    "instanceTypeVal": inst.get("instanceTypeVal"),
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
    
    def _collect_recipes(self, dl_obj, recipes_set):
        """Collect all recipe names from datalake object."""
        # Top-level recipes
        for recipe in dl_obj.get("recipes", []):
            if recipe:  # Only add non-None recipes
                recipes_set.add(recipe)
        
        # Recipes under configuration
        for config_key in ["awsConfiguration", "azureConfiguration", "gcpConfiguration"]:
            config = dl_obj.get(config_key, {})
            if isinstance(config, dict):
                for recipe in config.get("recipes", []):
                    if recipe:  # Only add non-None recipes
                        recipes_set.add(recipe)
                for ig in config.get("instanceGroups", []):
                    for recipe in ig.get("recipes", []):
                        if recipe:  # Only add non-None recipes
                            recipes_set.add(recipe)
        
        # Recipes under top-level instanceGroups
        for ig in dl_obj.get("instanceGroups", []):
            for recipe in ig.get("recipes", []):
                if recipe:  # Only add non-None recipes
                    recipes_set.add(recipe)
    
    def _describe_recipes_for_datalake(self, recipe_dir, recipes_set):
        """
        Describe all unique recipes for a specific datalake.
        
        Note: All recipes (FreeIPA, DataLake, DataHub, COD) use the same CDP CLI command:
        'cdp datahub describe-recipe'
        
        Args:
            recipe_dir: Directory to save recipes for this datalake
            recipes_set: Set of unique recipe names for this datalake
        """
        if not recipes_set:
            return
        
        recipe_dir.mkdir(parents=True, exist_ok=True)
        
        for recipe_name in sorted(recipes_set):
            # Note: All recipes use 'cdp datahub describe-recipe' regardless of service type
            describe, err = self.client.execute(
                "datahub",
                "describe-recipe",
                task_name=f"Describing datalake recipe {recipe_name}",
                recipe_name=recipe_name,
            )
            
            if describe:
                json_path = recipe_dir / f"recipe_{recipe_name}.json"
                save_to_file(describe, json_path)
                
                recipe_content = describe.get("recipe", {}).get("recipeContent")
                if recipe_content:
                    script_path = recipe_dir / f"recipe_{recipe_name}.sh"
                    save_recipe_script(recipe_content, script_path)
            else:
                log(f"⚠️ Failed to describe datalake recipe: {recipe_name}")
    
    def _check_upgrade_images(self, datalake_crn, datalake_name, dl_dir, output_prefix):
        """Check available upgrade images for datalake (--show-* flags only list, never upgrade)."""
        upgrades = [
            ("AvailableImages", "Checking available upgrade images", "show_available_images"),
            ("RunTimeAvailableImages", "Checking latest runtime image", "show_latest_available_image_per_runtime")
        ]

        for suffix, label, upgrade_flag in upgrades:
            upgrade_json, upgrade_err = self.client.execute(
                "datalake",
                "upgrade-datalake",
                task_name=f"{label} for datalake {datalake_name}",
                datalake_name=datalake_crn,
                **{upgrade_flag: True},
            )
            
            if upgrade_json:
                upgrade_path = dl_dir / f"{output_prefix}_{suffix}_{self.config.timestamp}.json"
                save_to_file(upgrade_json, upgrade_path)
                upgrade_csv_path = dl_dir / f"{output_prefix}_{suffix}_{self.config.timestamp}.csv"
                self.exporter.save_flattened_json_to_csv(upgrade_json, upgrade_csv_path)
    
    def _discover_deep_extras(self, datalake_crn, datalake_name, dl_dir, output_prefix):
        """Tier 3 datalake diagnostics metadata and backups (no bundle download)."""
        diag_json, diag_err = self.client.list_datalake_diagnostics(datalake_crn)
        if diag_json:
            path = dl_dir / f"{output_prefix}_DiagnosticsList_{self.config.timestamp}.json"
            save_to_file(diag_json, path)
            self.exporter.save_flattened_json_to_csv(
                diag_json, dl_dir / f"{output_prefix}_DiagnosticsList_{self.config.timestamp}.csv"
            )
        elif self.config.debug:
            log(f"DEBUG: datalake diagnostics list for {datalake_name}: {diag_err}")

        # list-datalake-backups resolves --datalake-name by name only (a CRN returns NOT_FOUND)
        backups_json, backups_err = self.client.list_datalake_backups(datalake_name)
        if backups_json:
            path = dl_dir / f"{output_prefix}_Backups_{self.config.timestamp}.json"
            save_to_file(backups_json, path)
            backups = backups_json.get("backups") or []
            if backups:
                self.exporter.save_instance_groups_to_csv(
                    dl_dir / f"{output_prefix}_Backups_{self.config.timestamp}.csv", backups
                )
        elif self.config.debug:
            log(f"DEBUG: datalake backups for {datalake_name}: {backups_err}")

    def _discover_exhaustive_extras(self, datalake_crn, datalake_name, dl_dir, output_prefix):
        """Tier 5 datalake diagnostic bundle collection."""
        for label, method, poll_fn in (
            ("Datalake", self.client.collect_datalake_diagnostics, self.client.get_datalake_operation),
            ("Cm", self.client.collect_datalake_cm_diagnostics, self.client.get_datalake_operation),
        ):
            collect_json, collect_err = method(datalake_crn)
            if collect_json:
                save_diagnostic_collect(
                    self.config,
                    dl_dir,
                    output_prefix,
                    label,
                    collect_json,
                    self.exporter,
                    poll_fn=poll_fn,
                )
            elif self.config.debug:
                log(f"DEBUG: collect datalake {label} diagnostics for {datalake_name}: {collect_err}")

