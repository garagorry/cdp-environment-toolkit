#!/usr/bin/env python3
"""CDP CLI client wrapper for service discovery."""

import os
from pathlib import Path
from cdp_discover.discover.cli_model import (
    MIN_CDP_CLI_VERSION,
    get_cli_version,
    get_form_factor,
    is_outdated,
    kebab_to_camel,
    load_cli_model,
)
from cdp_discover.discover.utils import log, run_command_json


class CDPClient:
    """Wrapper for CDP CLI commands."""
    
    def __init__(self, profile="default", debug=False, api_recorder=None):
        """
        Initialize CDP client.
        
        Args:
            profile: CDP CLI profile name
            debug: Enable debug output
            api_recorder: Optional APIManifestRecorder instance
        """
        self.profile = profile
        self.debug = debug
        self.api_recorder = api_recorder
        self._validate_credentials()
        self.cli_version = get_cli_version()
        self.cli_outdated = is_outdated(self.cli_version)
        self.form_factor = get_form_factor(profile)
        # None when the CLI model cannot be inspected; supports() then allows every call
        self._cli_model = load_cli_model()
        if self.api_recorder is not None:
            self.api_recorder.set_cli_info(
                version=self.cli_version,
                minimum=MIN_CDP_CLI_VERSION,
                outdated=self.cli_outdated,
                form_factor=self.form_factor,
            )
    
    def warn_if_cli_outdated(self):
        """Log a warning when the installed CDP CLI may drop newer API fields."""
        if self.cli_outdated:
            log(
                f"⚠️ CDP CLI {self.cli_version} is older than {MIN_CDP_CLI_VERSION}. "
                "The CLI drops response fields its bundled model does not know "
                "(e.g. CDE service version), so this snapshot will be incomplete. "
                "Upgrade with: pip install -U cdpcli"
            )
        elif self.cli_outdated is None:
            log(f"⚠️ Could not determine CDP CLI version (minimum recommended: {MIN_CDP_CLI_VERSION})")
    
    def supports(self, service, operation):
        """
        Return (supported, reason). An operation is unsupported when the installed
        CLI does not ship it, or it is not available on this profile's form factor.
        """
        if self._cli_model is None:
            return True, None
        ops = self._cli_model.get(service)
        if ops is None:
            return False, "unsupported-by-cli"
        op = ops.get(kebab_to_camel(operation))
        if op is None:
            return False, "unsupported-by-cli"
        if self.form_factor not in op.get("formFactors", [self.form_factor]):
            return False, f"not-available-on-{self.form_factor}"
        return True, None
    
    def note_missing_fields(self, service, resource, fields):
        """Record expected snapshot fields absent from a response."""
        if fields and self.api_recorder is not None:
            self.api_recorder.record_missing_fields(service, resource, fields)
    
    def _validate_credentials(self):
        """Validate that CDP credentials are configured."""
        cred_path = os.path.expanduser("~/.cdp/credentials")
        if not os.path.exists(cred_path):
            raise FileNotFoundError(
                "CDP credentials not found at ~/.cdp/credentials. "
                "Please configure the CDP CLI first."
            )
        
        profiles = self.get_profiles()
        if self.profile not in profiles:
            raise ValueError(
                f"Profile '{self.profile}' not found in ~/.cdp/credentials. "
                f"Available profiles: {profiles}"
            )
    
    @staticmethod
    def get_profiles():
        """
        Get list of available CDP profiles.
        
        Returns:
            list: List of profile names
        """
        cred_path = os.path.expanduser("~/.cdp/credentials")
        profiles = []
        
        if not os.path.exists(cred_path):
            return profiles
        
        with open(cred_path, "r") as f:
            for line in f:
                line = line.strip()
                if line.startswith("[") and line.endswith("]"):
                    prof = line[1:-1].strip()
                    if prof and not prof.startswith("#"):
                        profiles.append(prof)
        
        return profiles
    
    def _build_command(self, service, operation, **kwargs):
        """
        Build CDP CLI command.
        
        Args:
            service: CDP service name (e.g., 'environments', 'datahub')
            operation: Operation name (e.g., 'describe-environment')
            **kwargs: Additional command arguments
            
        Returns:
            str: Complete command string
        """
        cmd_parts = [f"cdp {service} {operation}"]
        cmd_parts.append(f"--profile {self.profile}")
        
        for key, value in kwargs.items():
            # Skip None values - don't add them to the command
            if value is None:
                continue
            
            flag = key.replace("_", "-")
            if isinstance(value, bool):
                if value:
                    cmd_parts.append(f"--{flag}")
            else:
                cmd_parts.append(f"--{flag} {value}")
        
        return " ".join(cmd_parts)
    
    def execute(self, service, operation, task_name=None, **kwargs):
        """
        Execute a CDP CLI command.
        
        Args:
            service: CDP service name
            operation: Operation name
            task_name: Optional task description for spinner
            **kwargs: Additional command arguments
            
        Returns:
            tuple: (result_json, error)
        """
        command = self._build_command(service, operation, **kwargs)
        supported, reason = self.supports(service, operation)
        if not supported:
            if self.debug:
                log(f"DEBUG: Skipping cdp {service} {operation}: {reason}")
            if self.api_recorder is not None:
                self.api_recorder.record(service, operation, command, success=False, skipped=reason)
            return None, f"skipped: {reason}"
        result, error = run_command_json(command, task_name=task_name, debug=self.debug)
        if error and error.lstrip().startswith("usage:"):
            # argparse dumps the whole usage text; keep the actual complaint
            lines = [ln.strip() for ln in error.splitlines() if ln.strip()]
            error = lines[-1] if lines else error
        if self.api_recorder is not None:
            self.api_recorder.record(
                service,
                operation,
                command,
                success=result is not None,
                error=error,
            )
        return result, error
    
    # Environment operations
    def list_environments(self):
        """List all CDP environments in the account."""
        return self.execute(
            "environments",
            "list-environments",
            task_name="Listing CDP environments",
            no_paginate=True,
        )

    def describe_environment(self, environment_name):
        """Describe a CDP environment."""
        return self.execute(
            "environments",
            "describe-environment",
            task_name=f"Describing environment {environment_name}",
            environment_name=environment_name
        )
    
    def get_freeipa_upgrade_options(self, environment_name):
        """Get FreeIPA upgrade options for an environment."""
        return self.execute(
            "environments",
            "get-freeipa-upgrade-options",
            task_name=f"Getting FreeIPA upgrade options for {environment_name}",
            environment=environment_name
        )
    
    # DataLake operations
    def list_datalakes(self, environment_name):
        """List datalakes in an environment."""
        return self.execute(
            "datalake",
            "list-datalakes",
            task_name=f"Listing datalakes for {environment_name}",
            environment_name=environment_name
        )
    
    def describe_datalake(self, datalake_crn):
        """Describe a datalake."""
        return self.execute(
            "datalake",
            "describe-datalake",
            task_name=f"Describing datalake",
            datalake_name=datalake_crn
        )
    
    def describe_datalake_database_server(self, cluster_crn):
        """Describe database server for a datalake."""
        return self.execute(
            "datalake",
            "describe-database-server",
            task_name=f"Describing datalake database server",
            cluster_crn=cluster_crn
        )
    
    def get_datalake_cluster_service_status(self, cluster_name):
        """Get service health status for a datalake cluster."""
        return self.execute(
            "datalake",
            "get-cluster-service-status",
            task_name="Getting datalake cluster service status",
            cluster_name=cluster_name,
        )
    
    def get_datalake_cluster_host_status(self, cluster_name):
        """Get host health status for a datalake cluster."""
        return self.execute(
            "datalake",
            "get-cluster-host-status",
            task_name="Getting datalake cluster host status",
            cluster_name=cluster_name,
        )
    
    def list_datalake_runtimes(self):
        """List available datalake runtimes (account-level)."""
        return self.execute(
            "datalake",
            "list-runtimes",
            task_name="Listing datalake runtimes",
        )
    
    # DataHub operations
    def list_datahub_clusters(self, environment_name):
        """List DataHub clusters in an environment."""
        return self.execute(
            "datahub",
            "list-clusters",
            task_name=f"Listing DataHub clusters for {environment_name}",
            environment_name=environment_name
        )
    
    def describe_datahub_cluster(self, cluster_crn):
        """Describe a DataHub cluster."""
        return self.execute(
            "datahub",
            "describe-cluster",
            task_name=f"Describing DataHub cluster",
            cluster_name=cluster_crn
        )
    
    def get_datahub_cluster_service_status(self, cluster_name):
        """Get service health status for a DataHub cluster."""
        return self.execute(
            "datahub",
            "get-cluster-service-status",
            task_name="Getting DataHub cluster service status",
            cluster_name=cluster_name,
        )
    
    def list_datahub_cluster_lifecycle_events(self, cluster_name):
        """List lifecycle events for a DataHub cluster."""
        return self.execute(
            "datahub",
            "list-cluster-lifecycle-events",
            task_name="Listing DataHub cluster lifecycle events",
            cluster=cluster_name,
            no_paginate=True,
        )
    
    def get_datahub_cluster_host_status(self, cluster_name):
        """Get host health status for a DataHub cluster."""
        return self.execute(
            "datahub",
            "get-cluster-host-status",
            task_name=f"Getting DataHub host status for {cluster_name}",
            cluster_name=cluster_name,
        )
    
    def describe_datahub_auto_scale_rules(self, cluster_name):
        """Describe autoscale rules for a DataHub cluster."""
        return self.execute(
            "datahub",
            "describe-auto-scale-rules",
            task_name=f"Describing autoscale rules for {cluster_name}",
            cluster_name=cluster_name,
        )
    
    def list_datahub_auto_scale_history(self, cluster_name, count=200):
        """List autoscale history for a DataHub cluster."""
        return self.execute(
            "datahub",
            "list-auto-scale-history",
            task_name=f"Listing autoscale history for {cluster_name}",
            cluster_name=cluster_name,
            count=count,
        )
    
    # CDE operations
    def list_cde_services(self):
        """List CDE services (account-wide; deleted services filtered out)."""
        return self.execute(
            "de",
            "list-services",
            task_name="Listing CDE services",
            remove_deleted=True,
        )
    
    def describe_cde_service(self, cluster_id):
        """Describe a CDE service."""
        return self.execute(
            "de",
            "describe-service",
            task_name=f"Describing CDE service {cluster_id}",
            cluster_id=cluster_id
        )
    
    def list_cde_virtual_clusters(self, cluster_id):
        """List virtual clusters for a CDE service."""
        return self.execute(
            "de",
            "list-vcs",
            task_name=f"Listing CDE virtual clusters for {cluster_id}",
            cluster_id=cluster_id
        )
    
    def describe_cde_virtual_cluster(self, cluster_id, vc_id):
        """Describe a CDE virtual cluster."""
        return self.execute(
            "de",
            "describe-vc",
            task_name=f"Describing CDE virtual cluster {vc_id}",
            cluster_id=cluster_id,
            vc_id=vc_id
        )
    
    def get_cde_upgrade_status(self, cluster_id):
        """Get CDE multi-step upgrade status (message, next step, completion)."""
        return self.execute(
            "de",
            "get-upgrade-status",
            task_name=f"Getting upgrade status for {cluster_id}",
            cluster_id=cluster_id
        )
    
    def get_cde_kubeconfig(self, cluster_id):
        """Get Kubeconfig for the CDE service."""
        return self.execute(
            "de",
            "get-kubeconfig",
            task_name=f"Getting Kubeconfig for {cluster_id}",
            cluster_id=cluster_id
        )
    
    def get_cde_service_init_logs(self, cluster_id):
        """Retrieve CDE service initialization logs."""
        return self.execute(
            "de",
            "get-service-init-logs",
            task_name=f"Getting init logs for {cluster_id}",
            service_id=cluster_id,
        )
    
    def list_cde_backups(self):
        """List CDE service backups (account-wide; filter by clusterId client-side)."""
        return self.execute(
            "de",
            "list-backups",
            task_name="Listing CDE backups",
        )
    
    def describe_cde_backup(self, backup_id):
        """Describe a CDE service backup."""
        return self.execute(
            "de",
            "describe-backup",
            task_name=f"Describing CDE backup {backup_id}",
            backup_id=backup_id,
        )
    
    def get_cde_backup_logs(self, backup_id):
        """Retrieve logs for a CDE service backup."""
        return self.execute(
            "de",
            "get-backup-logs",
            task_name=f"Getting CDE backup logs for {backup_id}",
            backup_id=backup_id,
            no_paginate=True,
        )
    
    # CAI/ML operations
    def list_ml_workspaces(self, environment_name=None):
        """List ML workspaces."""
        kwargs = {}
        if environment_name:
            kwargs['environment_name'] = environment_name
        return self.execute(
            "ml",
            "list-workspaces",
            task_name="Listing ML workspaces",
            **kwargs
        )
    
    def describe_ml_workspace(self, environment_name, workspace_name):
        """Describe an ML workspace."""
        return self.execute(
            "ml",
            "describe-workspace",
            task_name=f"Describing ML workspace {workspace_name}",
            environment_name=environment_name,
            workspace_name=workspace_name
        )
    
    def get_latest_workspace_version(self):
        """Get the latest CAI workspace version available (account-wide, no arguments)."""
        return self.execute(
            "ml",
            "get-latest-workspace-version",
            task_name="Getting latest workspace version",
        )
    
    def list_workspace_backups(self, workspace_name, environment_name):
        """List backups for an ML workspace."""
        return self.execute(
            "ml",
            "list-workspace-backups",
            task_name=f"Listing workspace backups for {workspace_name}",
            workspace_name=workspace_name,
            environment_name=environment_name
        )
    
    def list_workspace_access(self, workspace_name, environment_name):
        """List access grants for an ML workspace."""
        return self.execute(
            "ml",
            "list-workspace-access",
            task_name=f"Listing workspace access for {workspace_name}",
            workspace_name=workspace_name,
            environment_name=environment_name
        )
    
    def list_ml_serving_apps(self):
        """List ML Serving Apps (Inference Service instances)."""
        return self.execute(
            "ml",
            "list-ml-serving-apps",
            task_name="Listing ML Serving Apps"
        )
    
    def describe_ml_serving_app(self, app_crn):
        """Describe an ML Serving App."""
        return self.execute(
            "ml",
            "describe-ml-serving-app",
            task_name="Describing ML Serving App",
            app_crn=app_crn,
        )
    
    def list_model_registries(self):
        """List Model Registries."""
        return self.execute(
            "ml",
            "list-model-registries",
            task_name="Listing Model Registries"
        )
    
    def describe_model_registry(self, model_registry_crn):
        """Describe a Model Registry."""
        return self.execute(
            "ml",
            "describe-model-registry",
            task_name="Describing Model Registry",
            model_registry_crn=model_registry_crn,
        )

    def get_latest_model_registry_version(self):
        """Get the latest Model Registry version available (account-wide, no arguments)."""
        return self.execute(
            "ml",
            "get-latest-model-registry-version",
            task_name="Getting latest model registry version",
        )
    
    def list_ml_serving_app_access(self, resource_crn):
        """List access grants for an ML Serving App."""
        return self.execute(
            "ml",
            "list-ml-serving-app-access",
            task_name="Listing ML Serving App access",
            resource_crn=resource_crn,
        )
    
    def list_model_registry_access(self, resource_crn):
        """List access grants for a Model Registry."""
        return self.execute(
            "ml",
            "list-model-registry-access",
            task_name="Listing Model Registry access",
            resource_crn=resource_crn,
        )
    
    # CDW operations
    def list_cdw_clusters(self):
        """List CDW clusters."""
        return self.execute(
            "dw",
            "list-clusters",
            task_name="Listing CDW clusters",
            no_paginate=True,
        )
    
    def describe_cdw_cluster(self, cluster_id):
        """Describe a CDW cluster."""
        return self.execute(
            "dw",
            "describe-cluster",
            task_name=f"Describing CDW cluster {cluster_id}",
            cluster_id=cluster_id
        )
    
    def list_cdw_dbcs(self, cluster_id):
        """List Database Catalogs in a CDW cluster."""
        return self.execute(
            "dw",
            "list-dbcs",
            task_name=f"Listing DBCs for cluster {cluster_id}",
            cluster_id=cluster_id,
            no_paginate=True,
        )
    
    def describe_cdw_dbc(self, cluster_id, dbc_id):
        """Describe a Database Catalog."""
        return self.execute(
            "dw",
            "describe-dbc",
            task_name=f"Describing DBC {dbc_id}",
            cluster_id=cluster_id,
            dbc_id=dbc_id
        )
    
    def list_cdw_vws(self, cluster_id):
        """List Virtual Warehouses in a CDW cluster."""
        return self.execute(
            "dw",
            "list-vws",
            task_name=f"Listing VWs for cluster {cluster_id}",
            cluster_id=cluster_id,
            no_paginate=True,
        )
    
    def describe_cdw_vw(self, cluster_id, vw_id):
        """Describe a Virtual Warehouse."""
        return self.execute(
            "dw",
            "describe-vw",
            task_name=f"Describing VW {vw_id}",
            cluster_id=cluster_id,
            vw_id=vw_id
        )
    
    def get_upgrade_dbc_versions(self, cluster_id, dbc_id):
        """Get upgrade versions for a Database Catalog."""
        return self.execute(
            "dw",
            "get-upgrade-dbc-versions",
            task_name=f"Getting upgrade versions for DBC {dbc_id}",
            cluster_id=cluster_id,
            dbc_id=dbc_id
        )
    
    def get_upgrade_vw_versions(self, cluster_id, vw_id):
        """Get upgrade versions for a Virtual Warehouse."""
        return self.execute(
            "dw",
            "get-upgrade-vw-versions",
            task_name=f"Getting upgrade versions for VW {vw_id}",
            cluster_id=cluster_id,
            vw_id=vw_id
        )
    
    def list_cdw_data_visualizations(self, cluster_id):
        """List Data Visualizations in a CDW cluster."""
        return self.execute(
            "dw",
            "list-data-visualizations",
            task_name=f"Listing Data Visualizations for cluster {cluster_id}",
            cluster_id=cluster_id,
            no_paginate=True,
        )
    
    def describe_cdw_data_visualization(self, cluster_id, data_visualization_id):
        """Describe a Data Visualization."""
        return self.execute(
            "dw",
            "describe-data-visualization",
            task_name=f"Describing Data Visualization {data_visualization_id}",
            cluster_id=cluster_id,
            data_visualization_id=data_visualization_id
        )
    
    def list_cdw_backup_entities(self):
        """List backup-eligible CDW entities (account-level)."""
        return self.execute(
            "dw",
            "list-backup-entities",
            task_name="Listing CDW backup entities",
        )
    
    def list_cdw_backups(self):
        """List CDW backups (account-level)."""
        return self.execute(
            "dw",
            "list-backups",
            task_name="Listing CDW backups",
        )
    
    def describe_cdw_backup(self, backup_crn):
        """Describe a CDW backup."""
        return self.execute(
            "dw",
            "describe-backup",
            task_name="Describing CDW backup",
            backup_crn=backup_crn,
        )
    
    def list_cdw_restores(self, backup_crn):
        """List restore jobs for a CDW backup."""
        return self.execute(
            "dw",
            "list-restores",
            task_name="Listing CDW restores",
            backup_crn=backup_crn,
        )
    
    def describe_cdw_restore(self, restore_crn):
        """Describe a CDW restore job."""
        return self.execute(
            "dw",
            "describe-restore",
            task_name="Describing CDW restore",
            restore_crn=restore_crn,
        )
    
    # CDF operations
    def list_cdf_services(self, environment_crn=None):
        """List CDF (DataFlow) services."""
        kwargs = {}
        if environment_crn:
            kwargs['environment_crn'] = environment_crn
        return self.execute(
            "df",
            "list-services",
            task_name="Listing CDF services",
            **kwargs
        )
    
    def describe_cdf_service(self, service_crn):
        """Describe a CDF service."""
        return self.execute(
            "df",
            "describe-service",
            task_name=f"Describing CDF service",
            service_crn=service_crn
        )
    
    def list_cdf_deployments(self, service_crn=None):
        """List DataFlow deployments (account-wide; filter by service in caller)."""
        return self.execute(
            "df",
            "list-deployments",
            task_name="Listing CDF deployments",
            no_paginate=True,
        )
    
    def describe_cdf_deployment(self, deployment_crn):
        """Describe a DataFlow deployment."""
        return self.execute(
            "df",
            "describe-deployment",
            task_name=f"Describing CDF deployment",
            deployment_crn=deployment_crn
        )
    
    def list_cdf_deployment_events(self, deployment_crn):
        """List event history for a CDF deployment."""
        return self.execute(
            "df",
            "list-deployment-events",
            task_name="Listing CDF deployment events",
            deployment_crn=deployment_crn,
            no_paginate=True,
        )
    
    def list_cdf_deployment_active_alerts(self, deployment_crn):
        """List active alerts for a CDF deployment."""
        return self.execute(
            "df",
            "list-deployment-active-alerts",
            task_name="Listing CDF deployment alerts",
            deployment_crn=deployment_crn,
        )
    
    def list_cdf_flow_definitions(self, service_crn=None):
        """List flow definitions (account-wide catalog in beta CLI)."""
        return self.execute(
            "df",
            "list-flow-definitions",
            task_name="Listing CDF flow definitions",
            no_paginate=True,
        )
    
    def describe_cdf_flow(self, flow_crn):
        """Describe a flow definition."""
        return self.execute(
            "df",
            "describe-flow",
            task_name=f"Describing CDF flow",
            flow_crn=flow_crn
        )
    
    def list_cdf_projects(self, service_crn=None):
        """List DataFlow projects (account-wide; filter by service in caller)."""
        return self.execute(
            "df",
            "list-projects",
            task_name="Listing CDF projects",
            no_paginate=True,
        )
    
    def describe_cdf_project(self, project_crn):
        """Describe a DataFlow project."""
        return self.execute(
            "df",
            "describe-project",
            task_name=f"Describing CDF project",
            project_crn=project_crn
        )
    
    def list_cdf_readyflows(self):
        """List ReadyFlows (pre-built flows)."""
        return self.execute(
            "df",
            "list-readyflows",
            task_name="Listing CDF ReadyFlows",
            no_paginate=True,
        )
    
    def describe_cdf_readyflow(self, readyflow_crn):
        """Describe a ReadyFlow."""
        return self.execute(
            "df",
            "describe-readyflow",
            task_name=f"Describing ReadyFlow",
            readyflow_crn=readyflow_crn
        )
    
    # COD operations
    def list_cod_databases(self, environment_name):
        """List Operational Databases."""
        return self.execute(
            "opdb",
            "list-databases",
            task_name=f"Listing COD databases for {environment_name}",
            environment_name=environment_name
        )
    
    def describe_cod_database(self, database_name, environment_name):
        """Describe an Operational Database."""
        return self.execute(
            "opdb",
            "describe-database",
            task_name=f"Describing COD database {database_name}",
            database_name=database_name,
            environment_name=environment_name
        )
    
    def describe_cod_upgrade_database(self, environment_name, database_name):
        """Describe upgrade availability for a COD database."""
        return self.execute(
            "opdb",
            "describe-upgrade-database",
            task_name=f"Describing COD upgrade options for {database_name}",
            environment=environment_name,
            database=database_name,
        )
    
    def describe_cod_client_connectivity(self, environment_name, database_name):
        """Describe client connectivity connectors for a COD database."""
        return self.execute(
            "opdb",
            "describe-client-connectivity",
            task_name=f"Describing COD client connectivity for {database_name}",
            environment_name=environment_name,
            database_name=database_name,
        )
    
    def list_cod_snapshots(self, environment_name, database_name):
        """List snapshots for a COD database."""
        return self.execute(
            "opdb",
            "list-snapshots",
            task_name=f"Listing COD snapshots for {database_name}",
            environment_name=environment_name,
            database_name=database_name,
        )
    
    def list_cod_restore_snapshots(self, environment_name, database_name):
        """List restore snapshots for a COD database."""
        return self.execute(
            "opdb",
            "list-restore-snapshots",
            task_name=f"Listing COD restore snapshots for {database_name}",
            environment_name=environment_name,
            database_name=database_name,
        )
    
    def list_cod_diagnostics(self, environment_name, database_name):
        """List diagnostics for a COD database."""
        return self.execute(
            "opdb",
            "list-diagnostics",
            task_name=f"Listing COD diagnostics for {database_name}",
            environment_name=environment_name,
            database_name=database_name,
        )
    
    # IAM operations
    def get_iam_account(self):
        """Get CDP account metadata."""
        return self.execute(
            "iam",
            "get-account",
            task_name="Getting IAM account",
        )
    
    def list_iam_users(self):
        """List IAM users."""
        return self.execute(
            "iam",
            "list-users",
            task_name="Listing IAM users",
            no_paginate=True,
        )
    
    def list_iam_groups(self):
        """List IAM groups."""
        return self.execute(
            "iam",
            "list-groups",
            task_name="Listing IAM groups",
            no_paginate=True,
        )
    
    def list_iam_roles(self):
        """List IAM roles."""
        return self.execute(
            "iam",
            "list-roles",
            task_name="Listing IAM roles",
            no_paginate=True,
        )
    
    def list_iam_resource_roles(self):
        """List IAM resource roles."""
        return self.execute(
            "iam",
            "list-resource-roles",
            task_name="Listing IAM resource roles",
            no_paginate=True,
        )
    
    def list_iam_machine_users(self):
        """List IAM machine users."""
        return self.execute(
            "iam",
            "list-machine-users",
            task_name="Listing IAM machine users",
            no_paginate=True,
        )
    
    def list_iam_resource_assignees(self, resource_crn):
        """List IAM assignees for a resource CRN (e.g. environment)."""
        return self.execute(
            "iam",
            "list-resource-assignees",
            task_name="Listing IAM resource assignees",
            resource_crn=resource_crn,
            no_paginate=True,
        )
    
    # Audit operations
    def get_audit_archiving_config(self):
        """Get audit archiving configuration."""
        return self.execute(
            "audit",
            "get-archiving-config",
            task_name="Getting audit archiving config",
        )
    
    def get_audit_archiving_status(self, task_id):
        """Get status of an audit archiving task (task id comes from archive-audit-events)."""
        return self.execute(
            "audit",
            "get-archiving-status",
            task_name="Getting audit archiving status",
            task_id=task_id,
        )
    
    def list_audit_recent_archive_runs(self, limit=50):
        """List recent audit archive runs."""
        return self.execute(
            "audit",
            "list-recent-archive-runs",
            task_name="Listing recent audit archive runs",
            limit=limit,
        )
    
    def list_audit_outstanding_archive_batches(self):
        """List outstanding audit archive batches."""
        return self.execute(
            "audit",
            "list-outstanding-archive-batches",
            task_name="Listing outstanding audit archive batches",
            no_paginate=True,
        )
    
    # Replication Manager operations
    def list_rm_policies(self):
        """List Replication Manager policies."""
        return self.execute(
            "replicationmanager",
            "list-policies",
            task_name="Listing Replication Manager policies",
        )
    
    def list_rm_clusters(self):
        """List Replication Manager registered clusters."""
        return self.execute(
            "replicationmanager",
            "list-clusters",
            task_name="Listing Replication Manager clusters",
        )
    
    def list_rm_paired_hbase_clusters(self):
        """List paired HBase clusters for replication."""
        return self.execute(
            "replicationmanager",
            "list-paired-hbase-clusters",
            task_name="Listing paired HBase clusters",
        )
    
    def get_rm_cluster_config(self, cluster_crn):
        """Get Replication Manager cluster configuration."""
        return self.execute(
            "replicationmanager",
            "get-cluster-config",
            task_name="Getting Replication Manager cluster config",
            cluster_crn=cluster_crn,
        )
    
    # Lakehouse Optimizer operations
    def list_lho_environments(self):
        """List Lakehouse Optimizer environments."""
        return self.execute(
            "lakehouseopt",
            "list-environments",
            task_name="Listing Lakehouse Optimizer environments",
            no_paginate=True,
        )
    
    def list_lho_policies(self, datahub_crn, namespace=None):
        """List Lakehouse Optimizer policies for a Data Hub."""
        kwargs = {"datahub_crn": datahub_crn}
        if namespace:
            kwargs["namespace"] = namespace
        return self.execute(
            "lakehouseopt",
            "list-policies",
            task_name="Listing Lakehouse Optimizer policies",
            **kwargs,
        )
    
    def get_lho_policy(self, datahub_crn, policy_name):
        """Get a Lakehouse Optimizer policy."""
        return self.execute(
            "lakehouseopt",
            "get-policy",
            task_name=f"Getting Lakehouse Optimizer policy {policy_name}",
            datahub_crn=datahub_crn,
            policy_name=policy_name,
        )
    
    def get_lho_health(self, datahub_crn, scope=None):
        """Get Lakehouse Optimizer health for a Data Hub."""
        kwargs = {"datahub_crn": datahub_crn}
        if scope:
            kwargs["scope"] = scope
        return self.execute(
            "lakehouseopt",
            "get-health",
            task_name="Getting Lakehouse Optimizer health",
            **kwargs,
        )
    
    # Environment deep-read operations
    def get_freeipa_status(self, environment_name):
        """Get FreeIPA status for an environment."""
        return self.execute(
            "environments",
            "get-freeipa-status",
            task_name=f"Getting FreeIPA status for {environment_name}",
            environment_name=environment_name,
        )
    
    def get_id_broker_mappings(self, environment_name):
        """Get ID broker mappings for an environment."""
        return self.execute(
            "environments",
            "get-id-broker-mappings",
            task_name=f"Getting ID broker mappings for {environment_name}",
            environment_name=environment_name,
        )
    
    def list_connected_data_services(self, environment_name):
        """List connected data services for an environment."""
        return self.execute(
            "environments",
            "list-connected-data-services",
            task_name=f"Listing connected data services for {environment_name}",
            environment=environment_name,
        )
    
    def list_freeipa_diagnostics(self, environment_name):
        """List available FreeIPA diagnostics (metadata only)."""
        return self.execute(
            "environments",
            "list-freeipa-diagnostics",
            task_name=f"Listing FreeIPA diagnostics for {environment_name}",
            environment_name=environment_name,
        )
    
    # DataLake deep-read operations
    def list_datalake_diagnostics(self, datalake_crn):
        """List datalake diagnostics bundles (metadata only)."""
        return self.execute(
            "datalake",
            "list-datalake-diagnostics",
            task_name="Listing datalake diagnostics",
            crn=datalake_crn,
        )
    
    def list_datalake_backups(self, datalake_name):
        """List datalake backups."""
        return self.execute(
            "datalake",
            "list-datalake-backups",
            task_name=f"Listing datalake backups for {datalake_name}",
            datalake_name=datalake_name,
        )
    
    # DataHub deep-read operations
    def list_datahub_diagnostics(self, cluster_crn):
        """List DataHub diagnostics bundles (metadata only)."""
        return self.execute(
            "datahub",
            "list-datahub-diagnostics",
            task_name="Listing DataHub diagnostics",
            crn=cluster_crn,
        )
    
    def list_datahub_scaling_activities(self, cluster_name):
        """List DataHub scaling activities."""
        return self.execute(
            "datahub",
            "list-scaling-activities",
            task_name=f"Listing scaling activities for {cluster_name}",
            cluster=cluster_name,
            no_paginate=True,
        )
    
    # CDE deep-read operations
    def get_cde_suspend_resume_status(self, cluster_id, vc_id=None):
        """Get CDE service or VC suspend/resume status."""
        kwargs = {"cluster_id": cluster_id}
        if vc_id:
            kwargs["vc_id"] = vc_id
        return self.execute(
            "de",
            "get-suspend-resume-status",
            task_name="Getting CDE suspend/resume status",
            **kwargs,
        )
    
    # CAI deep-read operations
    def describe_workspace_backup(self, backup_crn):
        """Describe an ML workspace backup."""
        return self.execute(
            "ml",
            "describe-workspace-backup",
            task_name="Describing workspace backup",
            backup_crn=backup_crn,
        )
    
    def list_ml_instance_type_configuration(self, environment_name):
        """List ML instance type configuration for an environment."""
        return self.execute(
            "ml",
            "list-instance-type-configuration",
            task_name=f"Listing ML instance types for {environment_name}",
            environment_name=environment_name,
        )
    
    # CDW deep-read operations
    def list_cdw_cluster_diagnostic_data_jobs(self, cluster_id):
        """List CDW cluster diagnostic data jobs (metadata only)."""
        return self.execute(
            "dw",
            "list-cluster-diagnostic-data-jobs",
            task_name="Listing CDW cluster diagnostic jobs",
            cluster_id=cluster_id,
            no_paginate=True,
        )
    
    # Data Catalog operations
    def list_datacatalog_data_shares(self, environment_crn, datalake_crn=None):
        """List data shares for an environment."""
        kwargs = {"environment_crn": environment_crn}
        if datalake_crn:
            kwargs["datalake_crn"] = datalake_crn
        return self.execute(
            "datacatalog",
            "list-data-shares",
            task_name="Listing data catalog shares",
            no_paginate=True,
            **kwargs,
        )
    
    def get_datacatalog_data_share(self, data_share_id, environment_crn, datalake_crn=None):
        """Get a data share by ID."""
        kwargs = {
            "data_share_id": data_share_id,
            "environment_crn": environment_crn,
        }
        if datalake_crn:
            kwargs["datalake_crn"] = datalake_crn
        return self.execute(
            "datacatalog",
            "get-data-share",
            task_name=f"Getting data share {data_share_id}",
            **kwargs,
        )
    
    def list_datacatalog_external_users(self, environment_crn, datalake_crn=None):
        """List external users for data catalog."""
        kwargs = {"environment_crn": environment_crn}
        if datalake_crn:
            kwargs["datalake_crn"] = datalake_crn
        return self.execute(
            "datacatalog",
            "list-external-users",
            task_name="Listing data catalog external users",
            no_paginate=True,
            **kwargs,
        )
    
    # DataFlow Workload (CFM) operations
    def get_dfw_deployment_configuration(self, deployment_crn, environment_crn):
        """Get NiFi deployment configuration."""
        return self.execute(
            "dfworkload",
            "get-deployment-configuration",
            task_name="Getting deployment configuration",
            deployment_crn=deployment_crn,
            environment_crn=environment_crn,
        )
    
    def list_dfw_flow_drafts(self, environment_crn):
        """List flow drafts for an environment."""
        return self.execute(
            "dfworkload",
            "list-flow-drafts",
            task_name="Listing flow drafts",
            environment_crn=environment_crn,
        )
    
    def list_dfw_inbound_connection_endpoints(self, environment_crn):
        """List inbound connection endpoints."""
        return self.execute(
            "dfworkload",
            "list-inbound-connection-endpoints",
            task_name="Listing inbound connection endpoints",
            environment_crn=environment_crn,
        )
    
    def list_dfw_deployment_archives(self, environment_crn):
        """List deployment archives."""
        return self.execute(
            "dfworkload",
            "list-deployment-archives",
            task_name="Listing deployment archives",
            environment_crn=environment_crn,
        )
    
    def list_dfw_parameter_groups(self, environment_crn):
        """List parameter groups."""
        return self.execute(
            "dfworkload",
            "list-parameter-groups",
            task_name="Listing parameter groups",
            environment_crn=environment_crn,
        )
    
    def list_dfw_nifi_versions(self, environment_crn):
        """List supported NiFi versions."""
        return self.execute(
            "dfworkload",
            "list-nifi-versions",
            task_name="Listing NiFi versions",
            environment_crn=environment_crn,
        )
    
    # Tier 4 — Consumption operations
    def list_compute_usage_records(self):
        """List compute usage records (account-level)."""
        return self.execute(
            "consumption",
            "list-compute-usage-records",
            task_name="Listing compute usage records",
            no_paginate=True,
        )
    
    # Tier 4 — Compute (Open Lakehouse) operations
    def list_compute_clusters(self, env_name_or_crn):
        """List compute clusters for an environment."""
        return self.execute(
            "compute",
            "list-clusters",
            task_name=f"Listing compute clusters for {env_name_or_crn}",
            env_name_or_crn=env_name_or_crn,
            no_paginate=True,
        )
    
    def describe_compute_cluster(self, cluster_crn):
        """Describe a compute cluster."""
        return self.execute(
            "compute",
            "describe-cluster",
            task_name="Describing compute cluster",
            cluster_crn=cluster_crn,
        )
    
    def list_compute_deployments(self, cluster_crn):
        """List deployments in a compute cluster."""
        return self.execute(
            "compute",
            "list-deployments",
            task_name="Listing compute deployments",
            cluster_crn=cluster_crn,
        )
    
    def describe_compute_deployment(self, cluster_crn, name, namespace=None):
        """Describe a compute deployment."""
        kwargs = {"cluster_crn": cluster_crn, "name": name}
        if namespace:
            kwargs["namespace"] = namespace
        return self.execute(
            "compute",
            "describe-deployment",
            task_name=f"Describing compute deployment {name}",
            **kwargs,
        )
    
    # Tier 4 — Environment platform operations
    def list_environment_credentials(self, credential_name=None):
        """List environment credentials (metadata only)."""
        kwargs = {}
        if credential_name:
            kwargs["credential_name"] = credential_name
        return self.execute(
            "environments",
            "list-credentials",
            task_name="Listing environment credentials",
            **kwargs,
        )
    
    def get_account_telemetry(self):
        """Get account telemetry settings."""
        return self.execute(
            "environments",
            "get-account-telemetry",
            task_name="Getting account telemetry",
        )
    
    def list_proxy_configs(self, proxy_config_name=None):
        """List proxy configurations."""
        kwargs = {}
        if proxy_config_name:
            kwargs["proxy_config_name"] = proxy_config_name
        return self.execute(
            "environments",
            "list-proxy-configs",
            task_name="Listing proxy configs",
            **kwargs,
        )
    
    # Tier 4 — CDW platform operations
    def list_cdw_configs(self, cluster_id):
        """List CDW cluster configurations."""
        return self.execute(
            "dw",
            "list-configs",
            task_name="Listing CDW configs",
            cluster_id=cluster_id,
        )

    def describe_cdw_config(self, cluster_id, config_id):
        """Describe a CDW cluster configuration."""
        return self.execute(
            "dw",
            "describe-config",
            task_name="Describing CDW config",
            cluster_id=cluster_id,
            config_id=config_id,
        )
    
    def list_cdw_events(self, cluster_id, limit=100):
        """List CDW cluster events."""
        return self.execute(
            "dw",
            "list-events",
            task_name="Listing CDW cluster events",
            service_id=cluster_id,
            limit=limit,
        )
    
    def list_cdw_dbc_events(self, cluster_id, dbc_id, limit=100):
        """List events for a Database Catalog."""
        return self.execute(
            "dw",
            "list-dbc-events",
            task_name=f"Listing DBC events for {dbc_id}",
            cluster_id=cluster_id,
            dbc_id=dbc_id,
            limit=limit,
        )
    
    def list_cdw_vw_events(self, cluster_id, vw_id, limit=100):
        """List events for a Virtual Warehouse."""
        return self.execute(
            "dw",
            "list-vw-events",
            task_name=f"Listing VW events for {vw_id}",
            cluster_id=cluster_id,
            vw_id=vw_id,
            limit=limit,
        )
    
    # Tier 4 — DataHub platform operations
    def list_datahub_cluster_definitions(self):
        """List DataHub cluster definitions (account catalog)."""
        return self.execute(
            "datahub",
            "list-cluster-definitions",
            task_name="Listing DataHub cluster definitions",
        )
    
    def describe_datahub_scaling_activity(self, cluster_name, operation_id):
        """Describe a DataHub scaling activity."""
        return self.execute(
            "datahub",
            "describe-scaling-activity",
            task_name=f"Describing scaling activity {operation_id}",
            cluster=cluster_name,
            operation_id=operation_id,
        )

    # Tier 5 — Diagnostic bundle collection
    def collect_freeipa_diagnostics(self, environment_name):
        """Start FreeIPA diagnostic bundle collection."""
        return self.execute(
            "environments",
            "collect-freeipa-diagnostics",
            task_name=f"Collecting FreeIPA diagnostics for {environment_name}",
            environment_name=environment_name,
        )

    def get_environment_operation(self, operation_id):
        """Poll an environments async operation."""
        return self.execute(
            "environments",
            "get-operation",
            task_name="Getting environment operation status",
            operation_id=operation_id,
        )

    def collect_datalake_diagnostics(self, datalake_crn):
        """Start datalake diagnostic bundle collection."""
        return self.execute(
            "datalake",
            "collect-datalake-diagnostics",
            task_name="Collecting datalake diagnostics",
            crn=datalake_crn,
        )

    def collect_datalake_cm_diagnostics(self, datalake_crn):
        """Start Cloudera Manager diagnostics collection for a datalake."""
        return self.execute(
            "datalake",
            "collect-cm-diagnostics",
            task_name="Collecting datalake CM diagnostics",
            crn=datalake_crn,
        )

    def get_datalake_operation(self, operation_id):
        """Poll a datalake async operation."""
        return self.execute(
            "datalake",
            "get-operation",
            task_name="Getting datalake operation status",
            operation_id=operation_id,
        )

    def collect_datahub_diagnostics(self, cluster_crn):
        """Start DataHub diagnostic bundle collection."""
        return self.execute(
            "datahub",
            "collect-datahub-diagnostics",
            task_name="Collecting DataHub diagnostics",
            crn=cluster_crn,
        )

    def collect_datahub_cm_diagnostics(self, cluster_crn):
        """Start Cloudera Manager diagnostics collection for a DataHub cluster."""
        return self.execute(
            "datahub",
            "collect-cm-diagnostics",
            task_name="Collecting DataHub CM diagnostics",
            crn=cluster_crn,
        )

    def get_datahub_operation(self, operation_id):
        """Poll a DataHub async operation."""
        return self.execute(
            "datahub",
            "get-operation",
            task_name="Getting DataHub operation status",
            operation_id=operation_id,
        )

    def describe_cdw_cluster_diagnostic_job(self, cluster_id, job_id):
        """Describe a CDW cluster diagnostic data job."""
        return self.execute(
            "dw",
            "describe-cluster-diagnostic-data-job",
            task_name="Describing CDW cluster diagnostic job",
            cluster_id=cluster_id,
            job_id=job_id,
        )

    def list_cdw_dbc_diagnostic_jobs(self, cluster_id, dbc_id):
        """List DBC diagnostic data jobs."""
        return self.execute(
            "dw",
            "list-dbc-diagnostic-data-jobs",
            task_name="Listing CDW DBC diagnostic jobs",
            cluster_id=cluster_id,
            dbc_id=dbc_id,
            no_paginate=True,
        )

    def describe_cdw_dbc_diagnostic_job(self, cluster_id, dbc_id, job_id):
        """Describe a DBC diagnostic data job."""
        return self.execute(
            "dw",
            "describe-dbc-diagnostic-data-job",
            task_name="Describing CDW DBC diagnostic job",
            cluster_id=cluster_id,
            dbc_id=dbc_id,
            job_id=job_id,
        )

    def list_cdw_vw_diagnostic_jobs(self, cluster_id, vw_id):
        """List VW diagnostic data jobs."""
        return self.execute(
            "dw",
            "list-vw-diagnostic-data-jobs",
            task_name="Listing CDW VW diagnostic jobs",
            cluster_id=cluster_id,
            vw_id=vw_id,
            no_paginate=True,
        )

    def describe_cdw_vw_diagnostic_job(self, cluster_id, vw_id, job_id):
        """Describe a VW diagnostic data job."""
        return self.execute(
            "dw",
            "describe-vw-diagnostic-data-job",
            task_name="Describing CDW VW diagnostic job",
            cluster_id=cluster_id,
            vw_id=vw_id,
            job_id=job_id,
        )

    def collect_cod_diagnostics(self, environment_name, database_name):
        """Start COD diagnostic bundle collection."""
        return self.execute(
            "opdb",
            "collect-diagnostics",
            task_name=f"Collecting COD diagnostics for {database_name}",
            environment_name=environment_name,
            database_name=database_name,
        )

    def get_cod_command_status(self, command_id):
        """Poll a COD async command."""
        return self.execute(
            "opdb",
            "get-command-status",
            task_name="Getting COD command status",
            command_id=command_id,
        )

    def collect_rm_diagnostics(self, cluster_crn):
        """Start Replication Manager diagnostic collection."""
        return self.execute(
            "replicationmanager",
            "collect-diagnostics",
            task_name="Collecting Replication Manager diagnostics",
            cluster_crn=cluster_crn,
        )

    def list_dfw_reporting_tasks(self, environment_crn):
        """List NiFi reporting tasks (dfworkload exhaustive read)."""
        return self.execute(
            "dfworkload",
            "list-reporting-tasks",
            task_name="Listing dfworkload reporting tasks",
            environment_crn=environment_crn,
        )

