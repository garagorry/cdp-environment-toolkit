#!/usr/bin/env python3
"""COD (Operational Database) discovery module.

Note: COD is NOT a Kubernetes-based data service. It is a specialized
DataHub cluster that uses virtual machines, optimized for operational
database workloads (HBase/Phoenix).
"""

from pathlib import Path


from cdp_discover.discover.utils import (
    check_expected_fields,
    log,
    save_recipe_script,
    save_to_file,
)
from cdp_discover.discover.exporters.csv_exporter import CSVExporter
from cdp_discover.discover.diagnostics import save_diagnostic_collect



class CODDiscovery:
    """Discover COD (Operational Database) details.
    
    COD databases are specialized DataHub clusters running on VMs,
    not Kubernetes-based services like CDE, CAI, CDW, or CDF.
    """
    
    # Cloud provider availability
    SUPPORTED_CLOUDS = ['aws', 'azure']
    
    def __init__(self, cdp_client, config):
        """
        Initialize COD discovery.
        
        Args:
            cdp_client: CDPClient instance
            config: DiscoveryConfig instance
        """
        self.client = cdp_client
        self.config = config
        self.exporter = CSVExporter()
    
    def discover(self):
        """
        Discover all COD databases in the environment.
        
        Returns:
            dict: Discovery results with COD database details
        """
        log("💾 Starting COD (Operational Database) discovery...")
        
        results = {
            'databases': [],
            'success': False
        }
        
        # List COD databases
        databases_json, databases_err = self.client.list_cod_databases(
            self.config.environment_name
        )
        
        if not databases_json:
            log("ℹ️ No COD databases found or COD not available")
            if self.config.debug:
                log(f"DEBUG: databases_err: {databases_err}")
            return results
        
        databases = databases_json.get("databases", [])
        
        if not databases:
            log(f"ℹ️ No COD databases found in environment {self.config.environment_name}")
            return results
        
        log(f"Found {len(databases)} COD database(s):")
        for db in databases:
            log(f"  - {db.get('databaseName')} (Internal: {db.get('internalName')})")
        
        datahub_index = self._build_datahub_name_index()
        
        # Discover each database
        for database in databases:
            database_info = self._discover_single_database(database, datahub_index)
            if database_info:
                results['databases'].append(database_info)
        
        results['success'] = True
        return results
    
    def _build_datahub_name_index(self):
        """Map DataHub clusterName -> CRN for COD internalName lookups."""
        list_output, _ = self.client.list_datahub_clusters(self.config.environment_name)
        if not list_output:
            return {}
        return {
            c.get("clusterName"): c.get("crn")
            for c in list_output.get("clusters", [])
            if c.get("clusterName") and c.get("crn")
        }
    
    def _discover_single_database(self, database_summary, datahub_index):
        """
        Discover details for a single COD database.
        
        Args:
            database_summary: Database summary object
            datahub_index: clusterName -> CRN map for backing DataHub cluster
            
        Returns:
            dict: Database details or None if failed
        """
        database_name = database_summary.get("databaseName")
        internal_name = database_summary.get("internalName")
        
        if not database_name:
            log(f"⚠️ Skipping COD database with missing name")
            return None
        
        cod_dir = self.config.get_service_dir("cod") / database_name
        cod_dir.mkdir(parents=True, exist_ok=True)
        
        output_prefix = self.config.get_output_prefix("COD", database_name)
        
        # Describe the COD database
        describe, describe_err = self.client.describe_cod_database(
            database_name,
            self.config.environment_name
        )
        
        if not describe:
            log(f"⚠️ Could not describe COD database {database_name}")
            if self.config.debug:
                log(f"DEBUG: describe_err: {describe_err}")
            return None
        
        database_obj = describe.get("databaseDetails", describe)
        missing = check_expected_fields(database_obj, ["dbVersion"], f"COD database {database_name}")
        self.client.note_missing_fields("cod", database_name, missing)

        # Save JSON
        json_path = cod_dir / f"{output_prefix}_{self.config.timestamp}.json"
        save_to_file(describe, json_path)
        
        # Save flattened CSV
        csv_path = cod_dir / f"{output_prefix}_{self.config.timestamp}.csv"
        self.exporter.save_flattened_json_to_csv(database_obj, csv_path)
        
        # Collect and describe recipes for THIS COD database
        database_recipes_set = set()
        self._collect_cod_recipes(database_obj, database_recipes_set)
        
        if database_recipes_set:
            recipe_dir = cod_dir / "recipes"
            self._describe_recipes_for_database(recipe_dir, database_recipes_set)
        
        self._discover_opdb_extras(
            cod_dir,
            output_prefix,
            database_name,
        )
        
        if internal_name:
            self._discover_backing_datahub(
                cod_dir,
                output_prefix,
                internal_name,
                datahub_index,
            )
        if self.config.exhaustive:
            self._discover_exhaustive_extras(cod_dir, output_prefix, database_name)
        
        return {
            'database_name': database_name,
            'internal_name': internal_name,
            'details': database_obj
        }
    
    def _discover_opdb_extras(self, cod_dir, output_prefix, database_name):
        """OPDB upgrade, connectivity, and snapshot APIs."""
        env = self.config.environment_name
        extras = [
            (
                "Upgrade",
                self.client.describe_cod_upgrade_database,
            ),
            (
                "ClientConnectivity",
                self.client.describe_cod_client_connectivity,
            ),
            (
                "Snapshots",
                self.client.list_cod_snapshots,
            ),
            (
                "RestoreSnapshots",
                self.client.list_cod_restore_snapshots,
            ),
            (
                "Diagnostics",
                self.client.list_cod_diagnostics,
            ),
        ]
        for suffix, method in extras:
            data, err = method(env, database_name)
            if data:
                path = cod_dir / f"{output_prefix}_{suffix}_{self.config.timestamp}.json"
                save_to_file(data, path)
                csv_path = cod_dir / f"{output_prefix}_{suffix}_{self.config.timestamp}.csv"
                self.exporter.save_flattened_json_to_csv(data, csv_path)
            elif self.config.debug:
                log(f"DEBUG: COD {suffix} for {database_name}: {err}")

    def _discover_exhaustive_extras(self, cod_dir, output_prefix, database_name):
        """Tier 5 COD diagnostic bundle collection."""
        env = self.config.environment_name
        collect_json, collect_err = self.client.collect_cod_diagnostics(env, database_name)
        if collect_json:
            save_diagnostic_collect(
                self.config,
                cod_dir,
                output_prefix,
                "Cod",
                collect_json,
                self.exporter,
                poll_fn=self.client.get_cod_command_status,
            )
        elif self.config.debug:
            log(f"DEBUG: collect COD diagnostics for {database_name}: {collect_err}")
    
    def _discover_backing_datahub(self, cod_dir, output_prefix, internal_name, datahub_index):
        """
        COD runs on a DataHub cluster; instance groups come from describe-cluster.
        """
        cluster_crn = datahub_index.get(internal_name)
        if not cluster_crn:
            log(f"ℹ️ No DataHub cluster named '{internal_name}' for COD backing cluster lookup")
            return
        
        describe, err = self.client.describe_datahub_cluster(cluster_crn)
        if not describe:
            log(f"⚠️ Could not describe backing DataHub cluster {internal_name}")
            if self.config.debug:
                log(f"DEBUG: {err}")
            return
        
        json_path = cod_dir / f"{output_prefix}_DataHub_{self.config.timestamp}.json"
        save_to_file(describe, json_path)
        
        cluster_obj = describe.get("cluster", {})
        instance_groups = cluster_obj.get("instanceGroups", [])
        rows = self._flatten_datahub_instance_groups(internal_name, instance_groups)
        if rows:
            ig_csv_path = cod_dir / f"{output_prefix}_DataHub_InstanceGroups_{self.config.timestamp}.csv"
            self.exporter.save_instance_groups_to_csv(ig_csv_path, rows)
    
    def _flatten_datahub_instance_groups(self, cluster_name, instance_groups):
        """Flatten backing DataHub instance groups for COD export."""
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
                }
                volumes = inst.get("attachedVolumes", [])
                if volumes:
                    for vol in volumes:
                        row = base.copy()
                        row.update({
                            "volumeCount": vol.get("count"),
                            "volumeType": vol.get("volumeType"),
                            "volumeSize": vol.get("size"),
                        })
                        rows.append(row)
                else:
                    rows.append(base)
        return rows
    
    def _collect_cod_recipes(self, database_obj, recipes_set):
        """
        Collect recipe names from COD database object.
        
        Since COD is a specialized DataHub, it may have recipes attached.
        
        Args:
            database_obj: COD database details object
            recipes_set: Set to collect unique recipe names
        """
        # Check for recipes in various possible locations
        # Top-level recipes
        for recipe in database_obj.get("recipes", []):
            if recipe:  # Only add non-None recipes
                recipes_set.add(recipe)
        
        # Instance groups (if present)
        instance_groups = database_obj.get("instanceGroups", [])
        for ig in instance_groups:
            for recipe in ig.get("recipes", []):
                if recipe:  # Only add non-None recipes
                    recipes_set.add(recipe)
        
        # Check under infrastructure details (varies by cloud provider)
        for config_key in ["infrastructure", "nodeGroups", "computeResources"]:
            config = database_obj.get(config_key, {})
            if isinstance(config, dict):
                for recipe in config.get("recipes", []):
                    if recipe:  # Only add non-None recipes
                        recipes_set.add(recipe)
                # Check instance groups within config
                for ig in config.get("instanceGroups", []):
                    for recipe in ig.get("recipes", []):
                        if recipe:  # Only add non-None recipes
                            recipes_set.add(recipe)
    
    def _describe_recipes_for_database(self, recipe_dir, recipes_set):
        """
        Describe all unique recipes for a specific COD database.
        
        Note: All recipes (FreeIPA, DataLake, DataHub, COD) use the same CDP CLI command:
        'cdp datahub describe-recipe'
        
        Args:
            recipe_dir: Directory to save recipes for this database
            recipes_set: Set of unique recipe names for this database
        """
        if not recipes_set:
            return
        
        recipe_dir.mkdir(parents=True, exist_ok=True)
        
        
        for recipe_name in sorted(recipes_set):
            # Note: All recipes use 'cdp datahub describe-recipe' regardless of service type
            describe, err = self.client.execute(
                "datahub",
                "describe-recipe",
                task_name=f"Describing COD recipe {recipe_name}",
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
                log(f"⚠️ Failed to describe COD recipe: {recipe_name}")
                if self.config.debug:
                    log(f"DEBUG: Error: {err}")

