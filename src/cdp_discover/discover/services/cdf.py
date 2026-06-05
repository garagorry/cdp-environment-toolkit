#!/usr/bin/env python3
"""CDF (Cloudera DataFlow) discovery module."""

from pathlib import Path


from cdp_discover.discover.utils import log, save_to_file
from cdp_discover.discover.exporters.csv_exporter import CSVExporter



class CDFDiscovery:
    """Discover CDF (DataFlow) service details."""
    
    # Cloud provider availability
    SUPPORTED_CLOUDS = ['aws', 'azure']
    
    def __init__(self, cdp_client, config):
        """
        Initialize CDF discovery.
        
        Args:
            cdp_client: CDPClient instance
            config: DiscoveryConfig instance
        """
        self.client = cdp_client
        self.config = config
        self.exporter = CSVExporter()
        self.environment_crn = None

    @staticmethod
    def _service_crn_from_item(item):
        service = item.get("service") or {}
        return service.get("crn")

    @staticmethod
    def _filter_by_service_crn(items, service_crn):
        if not service_crn:
            return items
        return [item for item in items if CDFDiscovery._service_crn_from_item(item) == service_crn]

    @staticmethod
    def _flow_definitions_from_response(flows_json):
        if not flows_json:
            return []
        return flows_json.get("flows") or flows_json.get("flowDefinitions") or []
    
    def discover(self, environment_crn=None):
        """
        Discover all CDF services.
        
        Args:
            environment_crn: Optional environment CRN for filtering
            
        Returns:
            dict: Discovery results with CDF service details
        """
        log("🌊 Starting CDF (DataFlow) discovery...")
        
        results = {
            'services': [],
            'success': False
        }
        
        services_json, services_err = self.client.list_cdf_services(environment_crn)
        
        if not services_json:
            log("ℹ️ No CDF services found or CDF not available")
            if services_err and "command not found" in str(services_err):
                log("⚠️  CDP CLI not found in PATH - did you activate your virtual environment?")
            elif self.config.debug:
                log(f"DEBUG: services_err: {services_err}")
            return results
        
        all_services = services_json.get("services", [])
        
        services = []
        for s in all_services:
            if s.get("name") == self.config.environment_name:
                services.append(s)
                continue
            env_crn = s.get("environmentCrn", "")
            if env_crn and self.config.environment_name in env_crn:
                services.append(s)
                continue
        
        if self.config.debug and not services:
            log(f"DEBUG: No services matched environment '{self.config.environment_name}'")
            log(f"DEBUG: Available services:")
            for s in all_services:
                log(f"  - Name: {s.get('name')}, EnvCRN: {s.get('environmentCrn', 'N/A')[:80]}...")
        
        if not services:
            log(f"ℹ️ No CDF services found in environment {self.config.environment_name}")
            return results
        
        log(f"Found {len(services)} CDF service(s):")
        for s in services:
            log(f"  - {s.get('name', s.get('crn'))}")
        
        all_flows = []
        all_projects = []
        for service in services:
            service_info = self._discover_single_service(service)
            if service_info:
                results['services'].append(service_info)
                all_flows.extend(service_info.get('flow_definitions', []))
                all_projects.extend(service_info.get('projects', []))

        results['flow_definitions'] = all_flows
        results['projects'] = all_projects
        results['readyflows'] = self._discover_readyflows()

        results['success'] = True
        return results
    
    def _discover_single_service(self, service_summary):
        """
        Discover details for a single CDF service and all its resources.
        
        Args:
            service_summary: Service summary object
            
        Returns:
            dict: Service details or None if failed
        """
        service_crn = service_summary.get("crn")
        service_name = service_summary.get("name", "unknown")
        cluster_id = service_summary.get("clusterId")
        workload_version = service_summary.get("workloadVersion")
        deployment_count = service_summary.get("deploymentCount", 0)
        
        if not service_crn:
            log(f"⚠️ Skipping CDF service with missing CRN")
            return None
        
        cdf_dir = self.config.get_service_dir("cdf") / service_name
        cdf_dir.mkdir(parents=True, exist_ok=True)
        
        output_prefix = self.config.get_output_prefix("CDF", service_name)
        
        log(f"📊 CDF Service: {service_name}")
        if workload_version:
            log(f"  Workload version: {workload_version}")
        if cluster_id:
            log(f"  Cluster ID: {cluster_id}")
        log(f"  Deployment count: {deployment_count}")
        
        describe, describe_err = self.client.describe_cdf_service(service_crn)
        
        if not describe:
            log(f"⚠️ Could not describe CDF service {service_name}")
            if self.config.debug:
                log(f"DEBUG: describe_err: {describe_err}")
            return None
        
        service_obj = describe.get("service", describe)
        
        json_path = cdf_dir / f"{output_prefix}_{self.config.timestamp}.json"
        save_to_file(describe, json_path)
        
        csv_path = cdf_dir / f"{output_prefix}_{self.config.timestamp}.csv"
        self.exporter.save_flattened_json_to_csv(service_obj, csv_path)
        
        deployments = self._discover_deployments(service_crn, service_name, cdf_dir)
        flow_definitions = self._discover_flow_definitions(service_crn, service_name, cdf_dir)
        projects = self._discover_projects(service_crn, service_name, cdf_dir)

        return {
            'name': service_name,
            'crn': service_crn,
            'cluster_id': cluster_id,
            'workload_version': workload_version,
            'deployment_count': deployment_count,
            'details': service_obj,
            'deployments': deployments,
            'flow_definitions': flow_definitions,
            'projects': projects,
        }
    
    def _discover_deployments(self, service_crn, service_name, cdf_dir):
        """
        Discover deployments for a CDF service.
        
        Args:
            service_crn: CDF service CRN
            service_name: CDF service name
            cdf_dir: Output directory for CDF service
            
        Returns:
            list: List of deployment details
        """
        log(f"🌊 Discovering deployments for {service_name}...")
        
        deployments_json, deployments_err = self.client.list_cdf_deployments(service_crn)
        
        if not deployments_json:
            log(f"⚠️ Could not list deployments for {service_name}")
            if self.config.debug:
                log(f"DEBUG: deployments_err: {deployments_err}")
            return []
        
        deployments = self._filter_by_service_crn(
            deployments_json.get("deployments", []),
            service_crn,
        )
        
        if not deployments:
            log(f"ℹ️ No deployments found in {service_name}")
            return []
        
        log(f"Found {len(deployments)} deployment(s)")
        
        deployments_dir = cdf_dir / "deployments"
        deployments_dir.mkdir(parents=True, exist_ok=True)
        
        deployments_list_path = deployments_dir / f"deployments_list_{self.config.timestamp}.json"
        save_to_file(deployments_json, deployments_list_path)
        
        if deployments:
            deployments_csv_path = deployments_dir / f"deployments_list_{self.config.timestamp}.csv"
            self.exporter.save_instance_groups_to_csv(deployments_csv_path, deployments)
        
        deployment_details = []
        for deployment in deployments:
            deployment_detail = self._discover_single_deployment(deployment, deployments_dir)
            if deployment_detail:
                deployment_details.append(deployment_detail)
        
        return deployment_details
    
    def _discover_single_deployment(self, deployment_summary, deployments_dir):
        """
        Discover details for a single CDF deployment.
        
        Args:
            deployment_summary: Deployment summary object
            deployments_dir: Output directory for deployments
            
        Returns:
            dict: Deployment details or None if failed
        """
        deployment_crn = deployment_summary.get("crn")
        deployment_name = deployment_summary.get("name", "unknown")
        
        if not deployment_crn:
            log(f"⚠️ Skipping deployment with missing CRN")
            return None
        
        deployment_describe, deployment_err = self.client.describe_cdf_deployment(deployment_crn)
        
        if not deployment_describe:
            log(f"⚠️ Could not describe deployment {deployment_name}")
            if self.config.debug:
                log(f"DEBUG: deployment_err: {deployment_err}")
            return None
        
        deployment_obj = deployment_describe.get("deployment", deployment_describe)
        
        deployment_subdir = deployments_dir / deployment_name
        deployment_subdir.mkdir(parents=True, exist_ok=True)
        
        deployment_json_path = deployment_subdir / f"deployment_{deployment_name}_{self.config.timestamp}.json"
        save_to_file(deployment_describe, deployment_json_path)
        
        deployment_csv_path = deployment_subdir / f"deployment_{deployment_name}_{self.config.timestamp}.csv"
        self.exporter.save_flattened_json_to_csv(deployment_obj, deployment_csv_path)
        
        nifi_version = deployment_obj.get("nifiVersion")
        status = deployment_obj.get("status", {}).get("state")
        if nifi_version:
            log(f"  Deployment {deployment_name} - NiFi version: {nifi_version}")
        if status:
            log(f"  Deployment {deployment_name} - Status: {status}")
        
        self._discover_deployment_extras(deployment_crn, deployment_name, deployment_subdir)
        
        return {
            'crn': deployment_crn,
            'name': deployment_name,
            'details': deployment_obj
        }
    
    def _discover_deployment_extras(self, deployment_crn, deployment_name, deployment_subdir):
        """Fetch deployment events and active alerts."""
        events_json, events_err = self.client.list_cdf_deployment_events(deployment_crn)
        if events_json:
            events_path = deployment_subdir / f"deployment_{deployment_name}_DeploymentEvents_{self.config.timestamp}.json"
            save_to_file(events_json, events_path)
            events_csv = deployment_subdir / f"deployment_{deployment_name}_DeploymentEvents_{self.config.timestamp}.csv"
            self.exporter.save_flattened_json_to_csv(events_json, events_csv)
        elif self.config.debug:
            log(f"DEBUG: CDF deployment events for {deployment_name}: {events_err}")
        
        alerts_json, alerts_err = self.client.list_cdf_deployment_active_alerts(deployment_crn)
        if alerts_json:
            alerts_path = deployment_subdir / f"deployment_{deployment_name}_DeploymentAlerts_{self.config.timestamp}.json"
            save_to_file(alerts_json, alerts_path)
            alerts_csv = deployment_subdir / f"deployment_{deployment_name}_DeploymentAlerts_{self.config.timestamp}.csv"
            self.exporter.save_flattened_json_to_csv(alerts_json, alerts_csv)
        elif self.config.debug:
            log(f"DEBUG: CDF deployment alerts for {deployment_name}: {alerts_err}")
    
    def _discover_flow_definitions(self, service_crn, service_name, cdf_dir):
        """List and describe flow definitions scoped to a CDF service."""
        log(f"📐 Discovering flow definitions for {service_name}...")

        flows_json, flows_err = self.client.list_cdf_flow_definitions(service_crn)
        if not flows_json:
            if self.config.debug:
                log(f"DEBUG: Could not list flow definitions: {flows_err}")
            return []

        flows = self._flow_definitions_from_response(flows_json)
        if not flows:
            log(f"ℹ️ No flow definitions found for {service_name}")
            return []

        log(f"Found {len(flows)} flow definition(s) for {service_name}")
        flows_dir = cdf_dir / "flow_definitions"
        flows_dir.mkdir(parents=True, exist_ok=True)

        list_path = flows_dir / f"flows_list_{self.config.timestamp}.json"
        save_to_file(flows_json, list_path)
        self.exporter.save_instance_groups_to_csv(
            flows_dir / f"flows_list_{self.config.timestamp}.csv", flows
        )

        described = []
        for flow in flows:
            detail = self._describe_cdf_resource(
                flow,
                crn_key="crn",
                name_key="name",
                describe_fn=self.client.describe_cdf_flow,
                parent_dir=flows_dir,
                file_prefix="flow",
                resource_label="flow",
            )
            if detail:
                described.append(detail)
        return described

    def _discover_projects(self, service_crn, service_name, cdf_dir):
        """List and describe DataFlow projects scoped to a CDF service."""
        log(f"📁 Discovering projects for {service_name}...")

        projects_json, projects_err = self.client.list_cdf_projects(service_crn)
        if not projects_json:
            if self.config.debug:
                log(f"DEBUG: Could not list projects: {projects_err}")
            return []

        projects = self._filter_by_service_crn(
            projects_json.get("projects", []),
            service_crn,
        )
        if not projects:
            log(f"ℹ️ No projects found for {service_name}")
            return []

        log(f"Found {len(projects)} project(s) for {service_name}")
        projects_dir = cdf_dir / "projects"
        projects_dir.mkdir(parents=True, exist_ok=True)

        list_path = projects_dir / f"projects_list_{self.config.timestamp}.json"
        save_to_file(projects_json, list_path)
        self.exporter.save_instance_groups_to_csv(
            projects_dir / f"projects_list_{self.config.timestamp}.csv", projects
        )

        described = []
        for project in projects:
            detail = self._describe_cdf_resource(
                project,
                crn_key="crn",
                name_key="name",
                describe_fn=self.client.describe_cdf_project,
                parent_dir=projects_dir,
                file_prefix="project",
                resource_label="project",
            )
            if detail:
                described.append(detail)
        return described

    def _discover_readyflows(self):
        """List and describe ReadyFlows (account-level templates)."""
        log("🎁 Discovering ReadyFlows (pre-built flows)...")

        readyflows_json, readyflows_err = self.client.list_cdf_readyflows()
        if not readyflows_json:
            if self.config.debug:
                log(f"DEBUG: Could not list ReadyFlows: {readyflows_err}")
            return []

        readyflows = readyflows_json.get("readyflows", [])
        if not readyflows:
            log("ℹ️ No ReadyFlows found")
            return []

        log(f"Found {len(readyflows)} ReadyFlow(s)")
        cdf_main_dir = self.config.get_service_dir("cdf")
        readyflows_dir = cdf_main_dir / "readyflows"
        readyflows_dir.mkdir(parents=True, exist_ok=True)

        list_path = readyflows_dir / f"readyflows_list_{self.config.timestamp}.json"
        save_to_file(readyflows_json, list_path)
        self.exporter.save_instance_groups_to_csv(
            readyflows_dir / f"readyflows_list_{self.config.timestamp}.csv", readyflows
        )

        described = []
        for rf in readyflows:
            detail = self._describe_cdf_resource(
                rf,
                crn_key="crn",
                name_key="name",
                describe_fn=self.client.describe_cdf_readyflow,
                parent_dir=readyflows_dir,
                file_prefix="readyflow",
                resource_label="readyflow",
            )
            if detail:
                described.append(detail)
        return described

    def _describe_cdf_resource(
        self,
        summary,
        *,
        crn_key,
        name_key,
        describe_fn,
        parent_dir,
        file_prefix,
        resource_label,
    ):
        """Describe one CDF resource and persist JSON/CSV under ``parent_dir``."""
        crn = summary.get(crn_key) or summary.get("readyflowCrn") or summary.get("crn")
        name = summary.get(name_key, "unknown")
        if not crn:
            log(f"⚠️ Skipping {resource_label} with missing CRN")
            return None

        describe, err = describe_fn(crn)
        if not describe:
            log(f"⚠️ Could not describe {resource_label} {name}")
            if self.config.debug:
                log(f"DEBUG: {err}")
            return None

        obj = None
        for key in (resource_label, file_prefix, f"{file_prefix}Definition", "flowDefinition"):
            candidate = describe.get(key)
            if isinstance(candidate, dict):
                obj = candidate
                break
        if obj is None:
            obj = describe if isinstance(describe, dict) else {}
        subdir = parent_dir / name
        subdir.mkdir(parents=True, exist_ok=True)
        json_path = subdir / f"{file_prefix}_{name}_{self.config.timestamp}.json"
        save_to_file(describe, json_path)
        if isinstance(obj, dict):
            csv_path = subdir / f"{file_prefix}_{name}_{self.config.timestamp}.csv"
            self.exporter.save_flattened_json_to_csv(obj, csv_path)

        return {"crn": crn, "name": name, "details": obj if isinstance(obj, dict) else describe}

