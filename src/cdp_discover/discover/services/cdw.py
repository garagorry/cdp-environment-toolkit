#!/usr/bin/env python3
"""CDW (Cloudera Data Warehouse) discovery module."""

from pathlib import Path


from cdp_discover.discover.utils import check_expected_fields, log, save_to_file
from cdp_discover.discover.exporters.csv_exporter import CSVExporter
from cdp_discover.discover.diagnostics import save_diagnostic_collect, save_diagnostic_job_describes



class CDWDiscovery:
    """Discover CDW cluster details."""
    
    # Cloud provider availability
    SUPPORTED_CLOUDS = ['aws', 'azure']
    
    def __init__(self, cdp_client, config):
        """
        Initialize CDW discovery.
        
        Args:
            cdp_client: CDPClient instance
            config: DiscoveryConfig instance
        """
        self.client = cdp_client
        self.config = config
        self.exporter = CSVExporter()
    
    def discover(self):
        """
        Discover all CDW clusters and their resources.
        
        Returns:
            dict: Discovery results with CDW cluster details
        """
        log("🏢 Starting CDW (Data Warehouse) discovery...")
        
        results = {
            'clusters': [],
            'success': False
        }
        
        # List CDW clusters
        clusters_json, clusters_err = self.client.list_cdw_clusters()
        
        if not clusters_json:
            log("ℹ️ No CDW clusters found or CDW not available")
            if self.config.debug:
                log(f"DEBUG: clusters_err: {clusters_err}")
            return results
        
        all_clusters = clusters_json.get("clusters", [])
        
        # Filter clusters by environment CRN (match environment name in CRN)
        clusters = []
        for c in all_clusters:
            env_crn = c.get("environmentCrn", "")
            cluster_name = c.get("name", "")
            # Match by environment name in CRN or cluster name contains env name
            if (env_crn and self.config.environment_name in env_crn) or \
               (cluster_name and self.config.environment_name in cluster_name):
                clusters.append(c)
        
        if not clusters:
            log(f"ℹ️ No CDW clusters found in environment {self.config.environment_name}")
            if self.config.debug:
                log(f"DEBUG: Available clusters: {[c.get('id') + ' (' + c.get('name', 'N/A') + ')' for c in all_clusters]}")
            return results
        
        log(f"Found {len(clusters)} CDW cluster(s):")
        for c in clusters:
            log(f"  - {c.get('name')} (ID: {c.get('id')})")
        
        # Discover each cluster
        for cluster in clusters:
            cluster_info = self._discover_single_cluster(cluster)
            if cluster_info:
                results['clusters'].append(cluster_info)
        
        self._discover_cdw_backups()
        
        results['success'] = True
        return results
    
    def _discover_single_cluster(self, cluster_summary):
        """
        Discover details for a single CDW cluster and all its resources.
        
        Args:
            cluster_summary: Cluster summary object
            
        Returns:
            dict: Cluster details or None if failed
        """
        cluster_id = cluster_summary.get("id")
        cluster_name = cluster_summary.get("name", cluster_id)
        
        if not cluster_id:
            log(f"⚠️ Skipping CDW cluster with missing ID")
            return None
        
        cdw_dir = self.config.get_service_dir("cdw") / cluster_name
        cdw_dir.mkdir(parents=True, exist_ok=True)
        
        output_prefix = self.config.get_output_prefix("CDW", cluster_name)
        
        # 1. Describe the CDW cluster
        describe, describe_err = self.client.describe_cdw_cluster(cluster_id)
        
        if not describe:
            log(f"⚠️ Could not describe CDW cluster {cluster_name}")
            if self.config.debug:
                log(f"DEBUG: describe_err: {describe_err}")
            return None
        
        cluster_obj = describe.get("cluster", describe)
        missing = check_expected_fields(cluster_obj, ["version"], f"CDW cluster {cluster_name}")
        self.client.note_missing_fields("cdw", cluster_name, missing)

        # Save JSON
        json_path = cdw_dir / f"{output_prefix}_{self.config.timestamp}.json"
        save_to_file(describe, json_path)
        
        # Save flattened CSV
        csv_path = cdw_dir / f"{output_prefix}_{self.config.timestamp}.csv"
        self.exporter.save_flattened_json_to_csv(cluster_obj, csv_path)
        
        # 2. Discover Database Catalogs (DBCs)
        dbcs = self._discover_database_catalogs(cluster_id, cluster_name, cdw_dir)
        
        # 3. Discover Virtual Warehouses (VWs)
        vws = self._discover_virtual_warehouses(cluster_id, cluster_name, cdw_dir)
        
        # 4. Discover Data Visualizations
        data_vizs = self._discover_data_visualizations(cluster_id, cluster_name, cdw_dir)

        # Hue endpoints are reported per VW (vw.endpoints.hue); the dw API has no list-hues

        if self.config.deep:
            self._discover_deep_extras(cluster_id, cluster_name, cdw_dir)
        if self.config.full:
            self._discover_full_extras(cluster_id, cluster_name, cdw_dir, dbcs, vws)
        if self.config.exhaustive:
            self._discover_exhaustive_extras(cluster_id, cluster_name, cdw_dir, dbcs, vws)
        
        return {
            'id': cluster_id,
            'name': cluster_name,
            'details': cluster_obj,
            'dbcs': dbcs,
            'virtual_warehouses': vws,
            'data_visualizations': data_vizs,
        }
    
    def _discover_database_catalogs(self, cluster_id, cluster_name, cdw_dir):
        """
        Discover Database Catalogs (DBCs) for a CDW cluster.
        
        Args:
            cluster_id: CDW cluster ID
            cluster_name: CDW cluster name
            cdw_dir: Output directory for CDW cluster
            
        Returns:
            list: List of DBC details
        """
        log(f"📚 Discovering Database Catalogs for {cluster_name}...")
        
        # List DBCs
        dbcs_json, dbcs_err = self.client.list_cdw_dbcs(cluster_id)
        
        if not dbcs_json:
            log(f"⚠️ Could not list DBCs for {cluster_name}")
            if self.config.debug:
                log(f"DEBUG: dbcs_err: {dbcs_err}")
            return []
        
        dbcs = dbcs_json.get("dbcs", [])
        
        if not dbcs:
            log(f"ℹ️ No Database Catalogs found in {cluster_name}")
            return []
        
        log(f"Found {len(dbcs)} Database Catalog(s)")
        
        # Create subdirectory for DBCs
        dbcs_dir = cdw_dir / "database_catalogs"
        dbcs_dir.mkdir(parents=True, exist_ok=True)
        
        # Save DBCs list
        dbcs_list_path = dbcs_dir / f"dbcs_list_{self.config.timestamp}.json"
        save_to_file(dbcs_json, dbcs_list_path)
        
        if dbcs:
            dbcs_csv_path = dbcs_dir / f"dbcs_list_{self.config.timestamp}.csv"
            self.exporter.save_instance_groups_to_csv(dbcs_csv_path, dbcs)
        
        # Discover each DBC in detail
        dbc_details = []
        for dbc in dbcs:
            dbc_detail = self._discover_single_dbc(cluster_id, dbc, dbcs_dir)
            if dbc_detail:
                dbc_details.append(dbc_detail)
        
        return dbc_details
    
    def _discover_single_dbc(self, cluster_id, dbc_summary, dbcs_dir):
        """Discover details for a single Database Catalog."""
        dbc_id = dbc_summary.get("id")
        dbc_name = dbc_summary.get("name", dbc_id)
        
        if not dbc_id:
            return None
        
        # Describe DBC
        dbc_describe, dbc_err = self.client.describe_cdw_dbc(cluster_id, dbc_id)
        
        if not dbc_describe:
            log(f"⚠️ Could not describe DBC {dbc_name}")
            return None
        
        dbc_obj = dbc_describe.get("dbc", dbc_describe)
        
        # Create subdirectory for this DBC
        dbc_subdir = dbcs_dir / dbc_name
        dbc_subdir.mkdir(parents=True, exist_ok=True)
        
        # Save DBC details
        dbc_json_path = dbc_subdir / f"dbc_{dbc_name}_{self.config.timestamp}.json"
        save_to_file(dbc_describe, dbc_json_path)
        
        dbc_csv_path = dbc_subdir / f"dbc_{dbc_name}_{self.config.timestamp}.csv"
        self.exporter.save_flattened_json_to_csv(dbc_obj, dbc_csv_path)
        
        # Get upgrade versions
        upgrade_json, upgrade_err = self.client.get_upgrade_dbc_versions(cluster_id, dbc_id)
        if upgrade_json:
            upgrade_path = dbc_subdir / f"dbc_{dbc_name}_UpgradeVersions_{self.config.timestamp}.json"
            save_to_file(upgrade_json, upgrade_path)
            
            # Log version info
            upgrade_versions = upgrade_json.get("upgradeVersions", {})
            current = upgrade_versions.get("currentVersion")
            latest = upgrade_versions.get("latestVersion")
            if current:
                log(f"  DBC {dbc_name} - Current version: {current}")
            if latest and latest != current:
                log(f"  DBC {dbc_name} - Upgrade available: {latest}")
        
        return {
            'id': dbc_id,
            'name': dbc_name,
            'details': dbc_obj
        }
    
    def _discover_virtual_warehouses(self, cluster_id, cluster_name, cdw_dir):
        """
        Discover Virtual Warehouses (VWs) for a CDW cluster.
        
        Args:
            cluster_id: CDW cluster ID
            cluster_name: CDW cluster name
            cdw_dir: Output directory for CDW cluster
            
        Returns:
            list: List of VW details
        """
        log(f"🏭 Discovering Virtual Warehouses for {cluster_name}...")
        
        # List VWs
        vws_json, vws_err = self.client.list_cdw_vws(cluster_id)
        
        if not vws_json:
            log(f"⚠️ Could not list VWs for {cluster_name}")
            if self.config.debug:
                log(f"DEBUG: vws_err: {vws_err}")
            return []
        
        vws = vws_json.get("vws", [])
        
        if not vws:
            log(f"ℹ️ No Virtual Warehouses found in {cluster_name}")
            return []
        
        log(f"Found {len(vws)} Virtual Warehouse(s)")
        
        # Create subdirectory for VWs
        vws_dir = cdw_dir / "virtual_warehouses"
        vws_dir.mkdir(parents=True, exist_ok=True)
        
        # Save VWs list
        vws_list_path = vws_dir / f"vws_list_{self.config.timestamp}.json"
        save_to_file(vws_json, vws_list_path)
        
        if vws:
            vws_csv_path = vws_dir / f"vws_list_{self.config.timestamp}.csv"
            self.exporter.save_instance_groups_to_csv(vws_csv_path, vws)
        
        # Discover each VW in detail
        vw_details = []
        for vw in vws:
            vw_detail = self._discover_single_vw(cluster_id, vw, vws_dir)
            if vw_detail:
                vw_details.append(vw_detail)
        
        return vw_details
    
    def _discover_single_vw(self, cluster_id, vw_summary, vws_dir):
        """Discover details for a single Virtual Warehouse."""
        vw_id = vw_summary.get("id")
        vw_name = vw_summary.get("name", vw_id)
        
        if not vw_id:
            return None
        
        # Describe VW
        vw_describe, vw_err = self.client.describe_cdw_vw(cluster_id, vw_id)
        
        if not vw_describe:
            log(f"⚠️ Could not describe VW {vw_name}")
            return None
        
        vw_obj = vw_describe.get("vw", vw_describe)
        missing = check_expected_fields(vw_obj, ["cdhVersion"], f"CDW VW {vw_name}")
        self.client.note_missing_fields("cdw", vw_name, missing)

        # Create subdirectory for this VW
        vw_subdir = vws_dir / vw_name
        vw_subdir.mkdir(parents=True, exist_ok=True)
        
        # Save VW details
        vw_json_path = vw_subdir / f"vw_{vw_name}_{self.config.timestamp}.json"
        save_to_file(vw_describe, vw_json_path)
        
        vw_csv_path = vw_subdir / f"vw_{vw_name}_{self.config.timestamp}.csv"
        self.exporter.save_flattened_json_to_csv(vw_obj, vw_csv_path)
        
        # Get upgrade versions
        upgrade_json, upgrade_err = self.client.get_upgrade_vw_versions(cluster_id, vw_id)
        if upgrade_json:
            upgrade_path = vw_subdir / f"vw_{vw_name}_UpgradeVersions_{self.config.timestamp}.json"
            save_to_file(upgrade_json, upgrade_path)
            
            # Log version info
            upgrade_versions = upgrade_json.get("upgradeVersions", {})
            current = upgrade_versions.get("currentVersion")
            latest = upgrade_versions.get("latestVersion")
            if current:
                log(f"  VW {vw_name} - Current version: {current}")
            if latest and latest != current:
                log(f"  VW {vw_name} - Upgrade available: {latest}")
        
        return {
            'id': vw_id,
            'name': vw_name,
            'details': vw_obj
        }
    
    def _discover_data_visualizations(self, cluster_id, cluster_name, cdw_dir):
        """Discover Data Visualizations for a CDW cluster."""
        log(f"📊 Discovering Data Visualizations for {cluster_name}...")
        
        dvizs_json, dvizs_err = self.client.list_cdw_data_visualizations(cluster_id)
        
        if not dvizs_json:
            if self.config.debug:
                log(f"DEBUG: Could not list Data Visualizations: {dvizs_err}")
            return []
        
        dvizs = dvizs_json.get("dataVisualizations", [])
        
        if not dvizs:
            log(f"ℹ️ No Data Visualizations found in {cluster_name}")
            return []
        
        log(f"Found {len(dvizs)} Data Visualization(s)")

        dviz_root = cdw_dir / "data_visualizations"
        dviz_root.mkdir(parents=True, exist_ok=True)

        list_path = dviz_root / f"data_visualizations_list_{self.config.timestamp}.json"
        save_to_file(dvizs_json, list_path)
        self.exporter.save_instance_groups_to_csv(
            dviz_root / f"data_visualizations_list_{self.config.timestamp}.csv", dvizs
        )

        described = []
        for dviz in dvizs:
            dviz_id = dviz.get("id")
            dviz_name = dviz.get("name", dviz_id or "unknown")
            if not dviz_id:
                log(f"⚠️ Skipping Data Visualization with missing id")
                continue

            detail, err = self.client.describe_cdw_data_visualization(cluster_id, dviz_id)
            if not detail:
                log(f"⚠️ Could not describe Data Visualization {dviz_name}")
                if self.config.debug:
                    log(f"DEBUG: {err}")
                continue

            dviz_obj = detail.get("dataVisualization", detail)
            subdir = dviz_root / str(dviz_name)
            subdir.mkdir(parents=True, exist_ok=True)
            json_path = subdir / f"dviz_{dviz_name}_{self.config.timestamp}.json"
            save_to_file(detail, json_path)
            if isinstance(dviz_obj, dict):
                self.exporter.save_flattened_json_to_csv(
                    dviz_obj,
                    subdir / f"dviz_{dviz_name}_{self.config.timestamp}.csv",
                )
            described.append({"id": dviz_id, "name": dviz_name, "details": dviz_obj})

        return described
    
    def _discover_cdw_backups(self):
        """Discover CDW backup entities, backups, and restore jobs (account-level)."""
        cdw_root = self.config.get_service_dir("cdw")
        cdw_root.mkdir(parents=True, exist_ok=True)
        
        entities_json, entities_err = self.client.list_cdw_backup_entities()
        if entities_json:
            entities_path = cdw_root / f"cdw_backup_entities_{self.config.timestamp}.json"
            save_to_file(entities_json, entities_path)
            entities_csv = cdw_root / f"cdw_backup_entities_{self.config.timestamp}.csv"
            self.exporter.save_flattened_json_to_csv(entities_json, entities_csv)
        elif self.config.debug:
            log(f"DEBUG: CDW backup entities: {entities_err}")
        
        backups_json, backups_err = self.client.list_cdw_backups()
        if not backups_json:
            if self.config.debug:
                log(f"DEBUG: CDW backups: {backups_err}")
            return
        
        backups = backups_json.get("backups") or []
        backups_path = cdw_root / f"cdw_backups_{self.config.timestamp}.json"
        save_to_file(backups_json, backups_path)
        if backups:
            backups_csv = cdw_root / f"cdw_backups_{self.config.timestamp}.csv"
            self.exporter.save_instance_groups_to_csv(backups_csv, backups)
            log(f"Found {len(backups)} CDW backup(s)")
        
        backups_dir = cdw_root / "backups"
        backups_dir.mkdir(parents=True, exist_ok=True)
        
        for backup in backups:
            backup_crn = backup.get("backupCrn")
            backup_name = backup.get("backupName") or backup_crn or "unknown"
            if not backup_crn:
                continue
            
            backup_subdir = backups_dir / backup_name.replace("/", "_")
            backup_subdir.mkdir(parents=True, exist_ok=True)
            
            describe, describe_err = self.client.describe_cdw_backup(backup_crn)
            if describe:
                describe_path = backup_subdir / f"backup_describe_{self.config.timestamp}.json"
                save_to_file(describe, describe_path)
                self.exporter.save_flattened_json_to_csv(
                    describe,
                    backup_subdir / f"backup_describe_{self.config.timestamp}.csv",
                )
            elif self.config.debug:
                log(f"DEBUG: CDW backup describe {backup_name}: {describe_err}")
            
            restores_json, restores_err = self.client.list_cdw_restores(backup_crn)
            if not restores_json:
                if self.config.debug:
                    log(f"DEBUG: CDW restores for {backup_name}: {restores_err}")
                continue
            
            restores = restores_json.get("restores") or []
            restores_path = backup_subdir / f"restores_list_{self.config.timestamp}.json"
            save_to_file(restores_json, restores_path)
            if restores:
                self.exporter.save_instance_groups_to_csv(
                    backup_subdir / f"restores_list_{self.config.timestamp}.csv",
                    restores,
                )
            
            for restore in restores:
                restore_crn = restore.get("restoreCrn")
                if not restore_crn:
                    continue
                restore_desc, restore_err = self.client.describe_cdw_restore(restore_crn)
                if restore_desc:
                    safe_crn = restore_crn.split(":")[-1][:32]
                    restore_path = backup_subdir / f"restore_describe_{safe_crn}_{self.config.timestamp}.json"
                    save_to_file(restore_desc, restore_path)
                elif self.config.debug:
                    log(f"DEBUG: CDW restore describe: {restore_err}")

    def _discover_deep_extras(self, cluster_id, cluster_name, cdw_dir):
        """Tier 3 CDW diagnostic job metadata (no bundle collection)."""
        jobs_json, jobs_err = self.client.list_cdw_cluster_diagnostic_data_jobs(cluster_id)
        if jobs_json:
            path = cdw_dir / f"cdw_diagnostic_jobs_{self.config.timestamp}.json"
            save_to_file(jobs_json, path)
            jobs = jobs_json.get("jobs") or jobs_json.get("diagnosticDataJobs") or []
            if jobs:
                self.exporter.save_instance_groups_to_csv(
                    cdw_dir / f"cdw_diagnostic_jobs_{self.config.timestamp}.csv", jobs
                )
            else:
                self.exporter.save_flattened_json_to_csv(
                    jobs_json, cdw_dir / f"cdw_diagnostic_jobs_{self.config.timestamp}.csv"
                )
        elif self.config.debug:
            log(f"DEBUG: CDW diagnostic jobs for {cluster_name}: {jobs_err}")

    def _discover_full_extras(self, cluster_id, cluster_name, cdw_dir, dbcs, vws):
        """Tier 4 CDW events and configuration details."""
        ts = self.config.timestamp

        events_json, events_err = self.client.list_cdw_events(cluster_id)
        if events_json:
            path = cdw_dir / f"cdw_cluster_events_{ts}.json"
            save_to_file(events_json, path)
            events = events_json.get("events") or []
            if events:
                self.exporter.save_instance_groups_to_csv(
                    cdw_dir / f"cdw_cluster_events_{ts}.csv", events
                )
        elif self.config.debug:
            log(f"DEBUG: CDW cluster events for {cluster_name}: {events_err}")

        configs_json, configs_err = self.client.list_cdw_configs(cluster_id)
        if configs_json:
            path = cdw_dir / f"cdw_configs_list_{ts}.json"
            save_to_file(configs_json, path)
            configs = configs_json.get("configs") or configs_json.get("configurations") or []
            if configs:
                self.exporter.save_instance_groups_to_csv(
                    cdw_dir / f"cdw_configs_list_{ts}.csv", configs
                )
            for config in configs:
                config_id = config.get("id") or config.get("configId")
                if not config_id:
                    continue
                config_desc, config_desc_err = self.client.describe_cdw_config(cluster_id, config_id)
                if config_desc:
                    save_to_file(
                        config_desc,
                        cdw_dir / f"cdw_config_describe_{config_id}_{ts}.json",
                    )
                elif self.config.debug:
                    log(f"DEBUG: CDW config {config_id}: {config_desc_err}")
        elif self.config.debug:
            log(f"DEBUG: CDW configs for {cluster_name}: {configs_err}")

        for dbc in dbcs:
            dbc_id = dbc.get("id")
            if not dbc_id:
                continue
            dbc_events, dbc_events_err = self.client.list_cdw_dbc_events(cluster_id, dbc_id)
            if dbc_events:
                path = cdw_dir / f"cdw_dbc_events_{dbc_id}_{ts}.json"
                save_to_file(dbc_events, path)
            elif self.config.debug:
                log(f"DEBUG: CDW DBC events for {dbc_id}: {dbc_events_err}")

        for vw in vws:
            vw_id = vw.get("id")
            if not vw_id:
                continue
            vw_events, vw_events_err = self.client.list_cdw_vw_events(cluster_id, vw_id)
            if vw_events:
                path = cdw_dir / f"cdw_vw_events_{vw_id}_{ts}.json"
                save_to_file(vw_events, path)
            elif self.config.debug:
                log(f"DEBUG: CDW VW events for {vw_id}: {vw_events_err}")

    def _discover_exhaustive_extras(self, cluster_id, cluster_name, cdw_dir, dbcs, vws):
        """Tier 5 CDW diagnostic job describe + DBC/VW job lists."""
        ts = self.config.timestamp
        prefix = self.config.get_output_prefix("CDW", cluster_name)

        jobs_json, jobs_err = self.client.list_cdw_cluster_diagnostic_data_jobs(cluster_id)
        if jobs_json:
            jobs = jobs_json.get("jobs") or jobs_json.get("diagnosticDataJobs") or []
            save_diagnostic_job_describes(
                self.config,
                cdw_dir,
                prefix,
                "Cluster",
                jobs,
                lambda job_id: self.client.describe_cdw_cluster_diagnostic_job(cluster_id, job_id),
                self.exporter,
            )
        elif self.config.debug:
            log(f"DEBUG: CDW cluster diagnostic jobs for {cluster_name}: {jobs_err}")

        for dbc in dbcs:
            dbc_id = dbc.get("id")
            if not dbc_id:
                continue
            dbc_jobs_json, dbc_jobs_err = self.client.list_cdw_dbc_diagnostic_jobs(cluster_id, dbc_id)
            if not dbc_jobs_json:
                if self.config.debug:
                    log(f"DEBUG: CDW DBC diagnostic jobs for {dbc_id}: {dbc_jobs_err}")
                continue
            jobs = dbc_jobs_json.get("jobs") or dbc_jobs_json.get("diagnosticDataJobs") or []
            save_to_file(dbc_jobs_json, cdw_dir / f"cdw_dbc_diagnostic_jobs_{dbc_id}_{ts}.json")
            save_diagnostic_job_describes(
                self.config,
                cdw_dir,
                prefix,
                f"Dbc_{dbc_id}",
                jobs,
                lambda job_id, cid=cluster_id, did=dbc_id: self.client.describe_cdw_dbc_diagnostic_job(
                    cid, did, job_id
                ),
                self.exporter,
            )

        for vw in vws:
            vw_id = vw.get("id")
            if not vw_id:
                continue
            vw_jobs_json, vw_jobs_err = self.client.list_cdw_vw_diagnostic_jobs(cluster_id, vw_id)
            if not vw_jobs_json:
                if self.config.debug:
                    log(f"DEBUG: CDW VW diagnostic jobs for {vw_id}: {vw_jobs_err}")
                continue
            jobs = vw_jobs_json.get("jobs") or vw_jobs_json.get("diagnosticDataJobs") or []
            save_to_file(vw_jobs_json, cdw_dir / f"cdw_vw_diagnostic_jobs_{vw_id}_{ts}.json")
            save_diagnostic_job_describes(
                self.config,
                cdw_dir,
                prefix,
                f"Vw_{vw_id}",
                jobs,
                lambda job_id, cid=cluster_id, vid=vw_id: self.client.describe_cdw_vw_diagnostic_job(
                    cid, vid, job_id
                ),
                self.exporter,
            )

