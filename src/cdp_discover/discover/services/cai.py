#!/usr/bin/env python3
"""CAI (Cloudera AI / ML Workspaces) discovery module."""

from pathlib import Path


from cdp_discover.discover.utils import check_expected_fields, log, save_to_file
from cdp_discover.discover.exporters.csv_exporter import CSVExporter



class CAIDiscovery:
    """Discover CAI/ML workspace details."""
    
    # Cloud provider availability
    SUPPORTED_CLOUDS = ['aws', 'azure']
    
    def __init__(self, cdp_client, config):
        """
        Initialize CAI discovery.
        
        Args:
            cdp_client: CDPClient instance
            config: DiscoveryConfig instance
        """
        self.client = cdp_client
        self.config = config
        self.exporter = CSVExporter()
        self._latest_version_json = None

    def discover(self):
        """
        Discover all ML workspaces in the environment.
        
        Returns:
            dict: Discovery results with workspace details
        """
        log("🤖 Starting CAI (ML Workspaces) discovery...")
        
        results = {
            'workspaces': [],
            'success': False
        }
        
        # List ML workspaces
        workspaces_json, workspaces_err = self.client.list_ml_workspaces()
        
        if not workspaces_json:
            log("ℹ️ No ML workspaces found or CAI not available")
            if self.config.debug:
                log(f"DEBUG: workspaces_err: {workspaces_err}")
            return results
        
        all_workspaces = workspaces_json.get("workspaces", [])
        
        # Filter workspaces by environment
        workspaces = [
            w for w in all_workspaces
            if w.get("environmentName") == self.config.environment_name
        ]
        
        if not workspaces:
            log(f"ℹ️ No ML workspaces found in environment {self.config.environment_name}")
            return results
        
        log(f"Found {len(workspaces)} ML workspace(s):")
        for w in workspaces:
            log(f"  - {w.get('instanceName')}")
        
        # Discover each workspace
        for workspace in workspaces:
            workspace_info = self._discover_single_workspace(workspace)
            if workspace_info:
                results['workspaces'].append(workspace_info)
        
        # Discover ML Serving Apps (Inference Service)
        serving_apps = self._discover_ml_serving_apps()
        results['ml_serving_apps'] = serving_apps
        
        # Discover Model Registries
        model_registries = self._discover_model_registries()
        results['model_registries'] = model_registries
        
        results['success'] = True
        return results
    
    def _discover_single_workspace(self, workspace_summary):
        """
        Discover details for a single ML workspace.
        
        Args:
            workspace_summary: Workspace summary object
            
        Returns:
            dict: Workspace details or None if failed
        """
        workspace_name = workspace_summary.get("instanceName")
        
        if not workspace_name:
            log(f"⚠️ Skipping ML workspace with missing name")
            return None
        
        cai_dir = self.config.get_service_dir("cai") / workspace_name
        cai_dir.mkdir(parents=True, exist_ok=True)
        
        output_prefix = self.config.get_output_prefix("CAI", workspace_name)
        
        # Describe the ML workspace
        describe, describe_err = self.client.describe_ml_workspace(
            self.config.environment_name,
            workspace_name
        )
        
        if not describe:
            log(f"⚠️ Could not describe ML workspace {workspace_name}")
            if self.config.debug:
                log(f"DEBUG: describe_err: {describe_err}")
            return None
        
        workspace_obj = describe.get("workspace", describe)

        # Save JSON
        json_path = cai_dir / f"{output_prefix}_{self.config.timestamp}.json"
        save_to_file(describe, json_path)
        
        # Save workspace summary CSV
        summary_csv = cai_dir / f"{output_prefix}_Summary_{self.config.timestamp}.csv"
        workspace_flat = {k: v for k, v in workspace_obj.items() if not isinstance(v, (list, dict))}
        self.exporter.save_flattened_json_to_csv([workspace_flat], summary_csv)
        
        # Extract detailed components
        self._extract_instance_groups(workspace_obj, workspace_name, cai_dir, output_prefix)
        self._extract_tags(workspace_obj, cai_dir, output_prefix)
        self._extract_health_info(workspace_obj, cai_dir, output_prefix)
        self._extract_network_info(workspace_obj, cai_dir, output_prefix)
        self._extract_quota_info(workspace_obj, cai_dir, output_prefix)
        
        # Get version and upgrade information
        missing = check_expected_fields(workspace_obj, ["version"], f"CAI workspace {workspace_name}")
        self.client.note_missing_fields("cai", workspace_name, missing)
        self._get_workspace_version_info(workspace_obj, workspace_name, cai_dir, output_prefix)
        
        # Get workspace backups
        self._get_workspace_backups(workspace_name, cai_dir, output_prefix)
        
        # Get workspace access
        self._get_workspace_access(workspace_name, cai_dir, output_prefix)
        
        if self.config.deep:
            self._discover_deep_extras(workspace_name, cai_dir, output_prefix)
        
        return {
            'name': workspace_name,
            'details': workspace_obj
        }
    
    def _extract_instance_groups(self, workspace_obj, workspace_name, cai_dir, output_prefix):
        """Extract and save ML workspace instance groups."""
        instance_groups = workspace_obj.get("instanceGroups", [])
        
        if not instance_groups:
            return
        
        # Flatten instance groups
        ig_flat = []
        ig_instances = []
        ig_tags = []
        
        for ig in instance_groups:
            base = {k: v for k, v in ig.items() if k not in ["instances", "tags"]}
            base['workspaceName'] = workspace_name
            ig_flat.append(base)
            
            # Extract instances
            for inst in ig.get("instances", []):
                inst_row = {"workspaceName": workspace_name, "group": ig.get("instanceGroupName"), **inst}
                ig_instances.append(inst_row)
            
            # Extract tags
            for tag in ig.get("tags", []):
                tag_row = {
                    "workspaceName": workspace_name,
                    "group": ig.get("instanceGroupName"),
                    "key": tag.get("key"),
                    "value": tag.get("value")
                }
                ig_tags.append(tag_row)
        
        # Save CSVs
        if ig_flat:
            csv_path = cai_dir / f"{output_prefix}_InstanceGroups_{self.config.timestamp}.csv"
            self.exporter.save_instance_groups_to_csv(csv_path, ig_flat)
        
        if ig_instances:
            csv_path = cai_dir / f"{output_prefix}_Instances_{self.config.timestamp}.csv"
            self.exporter.save_instance_groups_to_csv(csv_path, ig_instances)
        
        if ig_tags:
            csv_path = cai_dir / f"{output_prefix}_InstanceGroupTags_{self.config.timestamp}.csv"
            self.exporter.save_instance_groups_to_csv(csv_path, ig_tags)
    
    def _extract_tags(self, workspace_obj, cai_dir, output_prefix):
        """Extract and save workspace tags."""
        tags = workspace_obj.get("tags", [])
        
        if tags:
            csv_path = cai_dir / f"{output_prefix}_Tags_{self.config.timestamp}.csv"
            self.exporter.save_instance_groups_to_csv(csv_path, tags)
    
    def _extract_health_info(self, workspace_obj, cai_dir, output_prefix):
        """Extract and save workspace health information."""
        health_info = workspace_obj.get("healthInfoLists", [])
        
        if health_info:
            csv_path = cai_dir / f"{output_prefix}_HealthInfo_{self.config.timestamp}.csv"
            self.exporter.save_instance_groups_to_csv(csv_path, health_info)
    
    def _extract_network_info(self, workspace_obj, cai_dir, output_prefix):
        """Extract and save network configuration."""
        # Subnets
        subnets = workspace_obj.get("subnets", [])
        if subnets:
            subnets_data = [{"subnet": s} for s in subnets]
            csv_path = cai_dir / f"{output_prefix}_Subnets_{self.config.timestamp}.csv"
            self.exporter.save_instance_groups_to_csv(csv_path, subnets_data)
        
        # Load balancer subnets
        lb_subnets = workspace_obj.get("subnetsForLoadBalancers", [])
        if lb_subnets:
            lb_data = [{"lb_subnet": s} for s in lb_subnets]
            csv_path = cai_dir / f"{output_prefix}_LBSubnets_{self.config.timestamp}.csv"
            self.exporter.save_instance_groups_to_csv(csv_path, lb_data)
        
        # Authorized IP ranges
        ip_ranges = workspace_obj.get("authorizedIPRanges", [])
        if ip_ranges:
            ip_data = [{"cidr": s} for s in ip_ranges]
            csv_path = cai_dir / f"{output_prefix}_AuthorizedIPRanges_{self.config.timestamp}.csv"
            self.exporter.save_instance_groups_to_csv(csv_path, ip_data)
    
    def _extract_quota_info(self, workspace_obj, cai_dir, output_prefix):
        """Extract and save quota information."""
        for key in ["upgradeState", "backupMetadata", "quota", "availableQuota"]:
            if isinstance(workspace_obj.get(key), dict):
                csv_path = cai_dir / f"{output_prefix}_{key}_{self.config.timestamp}.csv"
                self.exporter.save_flattened_json_to_csv([workspace_obj[key]], csv_path)
    
    def _get_latest_available_version(self):
        """Latest CAI workspace version (account-wide API; fetched once per run)."""
        if self._latest_version_json is None:
            version_json, version_err = self.client.get_latest_workspace_version()
            self._latest_version_json = version_json or {}
            if not version_json and self.config.debug:
                log(f"DEBUG: Could not get latest version: {version_err}")
        return self._latest_version_json

    def _get_workspace_version_info(self, workspace_obj, workspace_name, cai_dir, output_prefix):
        """Save current vs. latest available workspace version."""
        log(f"📊 Getting version information for {workspace_name}...")

        current_version = workspace_obj.get("version")
        latest_version = self._get_latest_available_version().get("version")
        if not current_version and not latest_version:
            return

        version_info = {
            "workspaceName": workspace_name,
            "currentVersion": current_version,
            "latestAvailableVersion": latest_version,
        }
        version_path = cai_dir / f"{output_prefix}_LatestVersion_{self.config.timestamp}.json"
        save_to_file(version_info, version_path)

        version_csv_path = cai_dir / f"{output_prefix}_LatestVersion_{self.config.timestamp}.csv"
        self.exporter.save_flattened_json_to_csv(version_info, version_csv_path)

        log(f"  CAI workspace version: {current_version} (latest available: {latest_version})")
    
    def _get_workspace_backups(self, workspace_name, cai_dir, output_prefix):
        """Get workspace backups."""
        log(f"💾 Getting backups for {workspace_name}...")
        
        backups_json, backups_err = self.client.list_workspace_backups(
            workspace_name,
            self.config.environment_name
        )
        
        if backups_json:
            backups = backups_json.get("backups", [])
            if backups:
                log(f"  Found {len(backups)} backup(s)")
                backup_path = cai_dir / f"{output_prefix}_Backups_{self.config.timestamp}.json"
                save_to_file(backups_json, backup_path)
                
                backup_csv_path = cai_dir / f"{output_prefix}_Backups_{self.config.timestamp}.csv"
                self.exporter.save_instance_groups_to_csv(backup_csv_path, backups)
        else:
            if self.config.debug:
                log(f"DEBUG: Could not list backups: {backups_err}")
    
    def _discover_deep_extras(self, workspace_name, cai_dir, output_prefix):
        """Tier 3 CAI instance types and workspace backup details."""
        types_json, types_err = self.client.list_ml_instance_type_configuration(
            self.config.environment_name
        )
        if types_json:
            path = cai_dir / f"{output_prefix}_InstanceTypes_{self.config.timestamp}.json"
            save_to_file(types_json, path)
            self.exporter.save_flattened_json_to_csv(
                types_json, cai_dir / f"{output_prefix}_InstanceTypes_{self.config.timestamp}.csv"
            )
        elif self.config.debug:
            log(f"DEBUG: ML instance types: {types_err}")

        backups_json, _ = self.client.list_workspace_backups(
            workspace_name, self.config.environment_name
        )
        backups = (backups_json or {}).get("backups") or []
        if not backups:
            return
        backups_dir = cai_dir / "backups"
        backups_dir.mkdir(parents=True, exist_ok=True)
        for backup in backups:
            backup_crn = backup.get("backupCrn") or backup.get("crn")
            if not backup_crn:
                continue
            detail, err = self.client.describe_workspace_backup(backup_crn)
            if not detail:
                if self.config.debug:
                    log(f"DEBUG: workspace backup {backup_crn}: {err}")
                continue
            safe = backup_crn.split(":")[-1][:32]
            subdir = backups_dir / safe
            subdir.mkdir(parents=True, exist_ok=True)
            save_to_file(detail, subdir / f"workspace_backup_{self.config.timestamp}.json")
            self.exporter.save_flattened_json_to_csv(
                detail, subdir / f"workspace_backup_{self.config.timestamp}.csv"
            )
    
    def _get_workspace_access(self, workspace_name, cai_dir, output_prefix):
        """Get workspace access control."""
        log(f"🔐 Getting access control for {workspace_name}...")
        
        access_json, access_err = self.client.list_workspace_access(
            workspace_name,
            self.config.environment_name
        )
        
        if access_json:
            access_list = access_json.get("access", [])
            if access_list:
                log(f"  Found {len(access_list)} access grant(s)")
                access_path = cai_dir / f"{output_prefix}_Access_{self.config.timestamp}.json"
                save_to_file(access_json, access_path)
                
                access_csv_path = cai_dir / f"{output_prefix}_Access_{self.config.timestamp}.csv"
                self.exporter.save_instance_groups_to_csv(access_csv_path, access_list)
        else:
            if self.config.debug:
                log(f"DEBUG: Could not list access: {access_err}")
    
    def _discover_ml_serving_apps(self):
        """Discover ML Serving Apps (Inference Service instances)."""
        log(f"🤖 Discovering ML Serving Apps (Inference Service)...")
        
        apps_json, apps_err = self.client.list_ml_serving_apps()
        
        if not apps_json:
            if self.config.debug:
                log(f"DEBUG: Could not list ML Serving Apps: {apps_err}")
            return []
        
        apps = apps_json.get("mlServingApps", [])
        
        # Filter by environment
        env_apps = [
            app for app in apps
            if app.get("environmentName") == self.config.environment_name or
            (app.get("environmentCrn") and self.config.environment_name in app.get("environmentCrn", ""))
        ]
        
        if not env_apps:
            log(f"ℹ️ No ML Serving Apps found in environment")
            return []
        
        log(f"Found {len(env_apps)} ML Serving App(s)")

        cai_main_dir = self.config.get_service_dir("cai")
        apps_dir = cai_main_dir / "ml_serving_apps"
        apps_dir.mkdir(parents=True, exist_ok=True)

        apps_path = apps_dir / f"ml_serving_apps_list_{self.config.timestamp}.json"
        save_to_file(apps_json, apps_path)
        self.exporter.save_instance_groups_to_csv(
            apps_dir / f"ml_serving_apps_list_{self.config.timestamp}.csv", env_apps
        )

        described = []
        for app in env_apps:
            detail = self._describe_single_serving_app(app, apps_dir)
            if detail:
                described.append(detail)
        return described
    
    def _discover_model_registries(self):
        """Discover Model Registries."""
        log(f"📚 Discovering Model Registries...")
        
        registries_json, registries_err = self.client.list_model_registries()
        
        if not registries_json:
            if self.config.debug:
                log(f"DEBUG: Could not list Model Registries: {registries_err}")
            return []
        
        registries = registries_json.get("modelRegistries", [])
        
        # Filter by environment
        env_registries = [
            reg for reg in registries
            if reg.get("environmentName") == self.config.environment_name or
            (reg.get("environmentCrn") and self.config.environment_name in reg.get("environmentCrn", ""))
        ]
        
        if not env_registries:
            log(f"ℹ️ No Model Registries found in environment")
            return []
        
        log(f"Found {len(env_registries)} Model Registr(y/ies)")

        cai_main_dir = self.config.get_service_dir("cai")
        reg_dir = cai_main_dir / "model_registries"
        reg_dir.mkdir(parents=True, exist_ok=True)

        reg_path = reg_dir / f"model_registries_list_{self.config.timestamp}.json"
        save_to_file(registries_json, reg_path)
        self.exporter.save_instance_groups_to_csv(
            reg_dir / f"model_registries_list_{self.config.timestamp}.csv", env_registries
        )

        described = []
        for reg in env_registries:
            detail = self._describe_single_model_registry(reg, reg_dir)
            if detail:
                described.append(detail)
        return described

    def _describe_single_serving_app(self, app_summary, apps_dir):
        """Describe one ML Serving App."""
        app_crn = app_summary.get("crn") or app_summary.get("appCrn")
        app_name = (
            app_summary.get("appName")
            or app_summary.get("name")
            or app_summary.get("instanceName")
            or "unknown"
        )

        if not app_crn:
            log(f"⚠️ Skipping ML Serving App {app_name} (missing crn)")
            return None

        describe, err = self.client.describe_ml_serving_app(app_crn)
        if not describe:
            log(f"⚠️ Could not describe ML Serving App {app_name}")
            if self.config.debug:
                log(f"DEBUG: {err}")
            return None

        app_obj = describe.get("mlServingApp", describe.get("app", describe))
        subdir = apps_dir / app_name
        subdir.mkdir(parents=True, exist_ok=True)
        json_path = subdir / f"serving_app_{app_name}_{self.config.timestamp}.json"
        save_to_file(describe, json_path)
        if isinstance(app_obj, dict):
            self.exporter.save_flattened_json_to_csv(
                app_obj,
                subdir / f"serving_app_{app_name}_{self.config.timestamp}.csv",
            )
        
        access_json, access_err = self.client.list_ml_serving_app_access(app_crn)
        if access_json:
            access_path = subdir / f"serving_app_{app_name}_Access_{self.config.timestamp}.json"
            save_to_file(access_json, access_path)
            access_list = access_json.get("access") or []
            if access_list:
                self.exporter.save_instance_groups_to_csv(
                    subdir / f"serving_app_{app_name}_Access_{self.config.timestamp}.csv",
                    access_list,
                )
        elif self.config.debug:
            log(f"DEBUG: ML Serving App access for {app_name}: {access_err}")
        
        return {"name": app_name, "crn": app_crn, "details": app_obj}

    def _describe_single_model_registry(self, reg_summary, reg_dir):
        """Describe one Model Registry and fetch latest version info."""
        registry_name = (
            reg_summary.get("modelRegistryName")
            or reg_summary.get("registryName")
            or reg_summary.get("name")
        )
        registry_crn = reg_summary.get("crn") or reg_summary.get("modelRegistryCrn")

        if not registry_name or not registry_crn:
            log("⚠️ Skipping Model Registry with missing name or crn")
            return None

        describe, err = self.client.describe_model_registry(registry_crn)
        if not describe:
            log(f"⚠️ Could not describe Model Registry {registry_name}")
            if self.config.debug:
                log(f"DEBUG: {err}")
            return None

        reg_obj = describe.get("modelRegistry", describe)
        subdir = reg_dir / registry_name
        subdir.mkdir(parents=True, exist_ok=True)
        json_path = subdir / f"model_registry_{registry_name}_{self.config.timestamp}.json"
        save_to_file(describe, json_path)
        if isinstance(reg_obj, dict):
            self.exporter.save_flattened_json_to_csv(
                reg_obj,
                subdir / f"model_registry_{registry_name}_{self.config.timestamp}.csv",
            )

        version_json, version_err = self.client.get_latest_model_registry_version()
        if version_json:
            version_path = subdir / f"model_registry_{registry_name}_LatestVersion_{self.config.timestamp}.json"
            save_to_file(version_json, version_path)
            self.exporter.save_flattened_json_to_csv(
                version_json,
                subdir / f"model_registry_{registry_name}_LatestVersion_{self.config.timestamp}.csv",
            )
        elif self.config.debug:
            log(f"DEBUG: Could not get latest registry version: {version_err}")
        
        if registry_crn:
            access_json, access_err = self.client.list_model_registry_access(registry_crn)
            if access_json:
                access_path = subdir / f"model_registry_{registry_name}_Access_{self.config.timestamp}.json"
                save_to_file(access_json, access_path)
                access_list = access_json.get("access") or []
                if access_list:
                    self.exporter.save_instance_groups_to_csv(
                        subdir / f"model_registry_{registry_name}_Access_{self.config.timestamp}.csv",
                        access_list,
                    )
            elif self.config.debug:
                log(f"DEBUG: Model Registry access for {registry_name}: {access_err}")

        return {"name": registry_name, "crn": registry_crn, "details": reg_obj}

